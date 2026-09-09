"""Deterministic document comparison (option A), with explicit abstention.

Patient/encounter pairing is confirmed upstream. This module never discovers or
pairs patients, calls a language model, authenticates signatures or edits PDFs.
Thresholds are versioned engineering defaults, not clinically calibrated scores.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from functools import cached_property
from hashlib import sha256
from pathlib import Path
import math
import re
import unicodedata

import numpy as np
from pypdf import PdfReader
from scipy.optimize import linear_sum_assignment

ENGINE_VERSION = "deterministic-a/1.1.0"
MAX_PAGES = 500
MAX_TEXT_CHARS_PER_PAGE = 200_000
MAX_RENDER_PIXELS = 20_000_000
MAX_RENDER_SIDE = 16_000
MATCH_THRESHOLD = 0.56
AMBIGUITY_MARGIN = 0.035
UNMATCHED_COST = (1 - MATCH_THRESHOLD) / 2
OCR_MIN_CONFIDENCE = 0.78
MONEY_RE = re.compile(r"(?<!\w)(?:US\$|USD|\$)\s*(-?\d(?:[\d.,]*\d)?)(?!\w)", re.I)
WORD_RE = re.compile(r"[\w]+(?:[.,]\d+)?", re.UNICODE)
DOCUMENT_TYPES = (
    ("Consentimiento informado", ("consentimiento informado", "autorizacion para procedimiento")),
    ("Acta de entrega y recepción", ("acta entrega recepcion", "acta de entrega recepcion", "acuse entrega del servicio")),
    ("Liquidación de prestaciones", ("planilla de cargos", "total liquidacion")),
    ("Anatomía patológica", ("histopatolog", "anatomia patolog")),
    ("Protocolo quirúrgico", ("protocolo quirurgico",)),
    ("Registro anestésico", ("registro de anestesia", "registro anestesico",)),
    ("Epicrisis", ("epicrisis",)),
    ("Evolución y prescripciones", ("evolucion y prescripciones", "evolucion y prescripcion")),
    ("Referencia o derivación", ("referencia / derivacion", "referencia y derivacion",)),
    ("Interconsulta", ("interconsulta",)),
    ("Consulta de cobertura", ("consulta de cobertura", "cobertura de salud")),
    ("Informe técnico-médico", ("informe tecnico",)),
    ("Factura de soporte", ("factura", "autorizacion sri")),
)


def _normal(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return re.sub(r"\s+", " ", "".join(c for c in decomposed if unicodedata.category(c) != "Mn")).strip()


def _clean(value: str) -> str:
    return "\n".join(re.sub(r"[ \t]+", " ", x).strip() for x in unicodedata.normalize("NFKC", value).splitlines() if x.strip())


def _readable(text: str) -> bool:
    words = re.findall(r"[A-Za-zÀ-ÿ]{2,}", text)
    if len(words) < 4:
        return False
    # A text layer can contain hundreds of characters while being corrupted
    # OCR. Symbol flooding and fragmented one/two-letter tokens trigger a new
    # OCR attempt; this is a conservative quality gate, not a clinical score.
    alphabetic_tokens = re.findall(r"[A-Za-zÀ-ÿ]+", text)
    compact = "".join(text.split())
    symbol_noise = sum(not c.isalnum() and c not in ".,:;/%$()-" for c in compact) / max(len(compact), 1)
    substantial_words = sum(len(word) >= 3 for word in alphabetic_tokens) / max(len(alphabetic_tokens), 1)
    if symbol_noise > 0.06 or substantial_words < 0.35:
        return False
    vowel_words = sum(bool(re.search(r"[aeiouáéíóúüy]", w, re.I)) for w in words)
    controls = sum(unicodedata.category(c).startswith("C") and c not in "\n\r\t" for c in text)
    replacements = text.count("�") + text.count("□")
    return vowel_words / len(words) >= 0.55 and (controls + replacements) / max(len(text), 1) < 0.02


def _document_type(text: str) -> str:
    key = _normal(text[:3500])
    # A form heading takes precedence over diagnoses/references in its body.
    if re.search(r"informe tecnico[\s-]*medico", key[:1200]):
        return "Informe técnico-médico"
    for title, terms in DOCUMENT_TYPES:
        if any(term in key for term in terms):
            return title
    return "Documento clínico o administrativo"


@dataclass
class Page:
    number: int
    text: str
    source: str = "embedded"
    confidence: float = 0.99
    readable: bool = True
    visual_hash: str | None = None
    thumbnail: np.ndarray | None = field(default=None, repr=False)
    issues: list[str] = field(default_factory=list)
    title: str = "Documento clínico o administrativo"

    @cached_property
    def tokens(self) -> list[str]:
        return WORD_RE.findall(_normal(self.text))

    @cached_property
    def text_key(self) -> str:
        return _normal(self.text)


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ocr(image) -> tuple[str, float]:
    import pytesseract

    available = set(pytesseract.get_languages(config=""))
    languages = "+".join(x for x in ("spa", "eng") if x in available)
    if not languages:
        raise RuntimeError("No están instalados los idiomas OCR spa o eng")
    data = pytesseract.image_to_data(image, lang=languages, config="--psm 3", output_type=pytesseract.Output.DICT, timeout=90)
    groups: dict[tuple, list[str]] = defaultdict(list)
    scores = []
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        groups[(data["block_num"][i], data["par_num"][i], data["line_num"][i])].append(text)
        score = float(data["conf"][i])
        if score >= 0:
            scores.append(score)
    confidence = sum(scores) / (100 * len(scores)) if scores else 0
    return _clean("\n".join(" ".join(words) for words in groups.values())), confidence


def _extract(path: Path, reader: PdfReader, *, ocr_enabled: bool) -> list[Page]:
    renderer = None
    renderer_error = None
    try:
        import pypdfium2
        renderer = pypdfium2.PdfDocument(str(path))
    except Exception as exc:
        renderer_error = type(exc).__name__
    pages = []
    try:
        for number, native in enumerate(reader.pages, 1):
            issues = []
            try:
                text = _clean(native.extract_text() or "")
            except Exception as exc:
                text = ""
                issues.append(f"Extracción de texto fallida ({type(exc).__name__}).")
            if len(text) > MAX_TEXT_CHARS_PER_PAGE:
                # Never compare a silently truncated prefix.
                pages.append(Page(number, "", readable=False, confidence=0, issues=["Límite de texto excedido; página no evaluada." ]))
                continue
            page = Page(number, text, readable=_readable(text), issues=issues, title=_document_type(text))
            render_page = bitmap = image = None
            try:
                if renderer is None:
                    raise RuntimeError(renderer_error or "render unavailable")
                render_page = renderer[number - 1]
                # 144 dpi. Exact rendered equality is independent of PDF metadata.
                width, height = render_page.get_size()
                if not all(math.isfinite(v) and 0 < v <= MAX_RENDER_SIDE / 2 for v in (width, height)):
                    raise ValueError("Dimensiones de página fuera del límite seguro")
                if math.ceil(width * 2) * math.ceil(height * 2) > MAX_RENDER_PIXELS:
                    raise ValueError("Página excede el presupuesto de píxeles")
                bitmap = render_page.render(scale=2)
                image = bitmap.to_pil().convert("L")
                page.visual_hash = sha256(str(image.size).encode() + image.tobytes()).hexdigest()
                page.thumbnail = np.asarray(image.resize((192, 256)), dtype=np.float32) / 255
                if not page.readable and ocr_enabled:
                    try:
                        ocr_text, confidence = _ocr(image)
                        page.text, page.source, page.confidence = ocr_text, "ocr", confidence
                        page.readable = _readable(ocr_text) and confidence >= OCR_MIN_CONFIDENCE
                        page.title = _document_type(ocr_text) if page.readable else "Documento pendiente de lectura"
                    except Exception as exc:
                        page.issues.append(f"OCR no disponible o fallido ({type(exc).__name__}).")
            except Exception as exc:
                page.issues.append(f"Comparación gráfica no disponible ({type(exc).__name__}).")
            finally:
                if image is not None:
                    image.close()
                if bitmap is not None:
                    bitmap.close()
                if render_page is not None:
                    render_page.close()
            if not page.readable:
                page.confidence = min(page.confidence, 0.5)
                page.issues.append("Lectura insuficiente; no se confirman cambios de texto ni importes de esta página.")
            pages.append(page)
    finally:
        if renderer is not None:
            renderer.close()
    return pages


def _similarity(a: Page, b: Page, weights: dict[str, float]) -> float:
    if a.visual_hash and a.visual_hash == b.visual_hash:
        return 1.0
    if not a.readable or not b.readable:
        return 0.0
    if a.text_key == b.text_key and a.text:
        return 1.0
    ta, tb = a.tokens, b.tokens
    sa, sb = set(ta), set(tb)
    weighted = sum(weights.get(x, 1) for x in sa & sb) / max(1, sum(weights.get(x, 1) for x in sa | sb))
    biga, bigb = set(zip(ta, ta[1:])), set(zip(tb, tb[1:]))
    bigram = len(biga & bigb) / max(1, len(biga | bigb))
    # SequenceMatcher over long token sequences can grow quadratically. The
    # weighted set and bigram components use all tokens, with no data omission.
    sequence = SequenceMatcher(None, ta, tb, autojunk=True).ratio() if len(ta) + len(tb) < 12000 else weighted
    score = 0.50 * weighted + 0.25 * bigram + 0.25 * sequence
    generic = "Documento clínico o administrativo"
    if a.title != b.title and a.title != generic and b.title != generic:
        score *= 0.65
    return score


def _form_key(page: Page) -> tuple[str, str] | None:
    if not page.readable:
        return None
    match = re.search(r"codigo de validacion que autorizo prestacion\s*:+\s*([a-z0-9]+(?:\s*-\s*[a-z0-9]+){2,})", _normal(page.text))
    if not match:
        return None
    return _document_type(page.text), re.sub(r"\s+", "", match.group(1))


def _align_pages(original: list[Page], modified: list[Page]) -> list[dict]:
    """Global one-to-one cost minimization with independent unmatched nodes."""
    n, m = len(original), len(modified)
    frequency = Counter(token for p in original + modified for token in set(p.tokens))
    weights = {word: 1 + math.log((n + m + 1) / (count + 1)) for word, count in frequency.items()}
    scores = np.array([[_similarity(a, b, weights) for b in modified] for a in original])
    keys_a, keys_b = [_form_key(p) for p in original], [_form_key(p) for p in modified]
    count_a, count_b = Counter(keys_a), Counter(keys_b)
    anchored = set()
    for i, key in enumerate(keys_a):
        for j, other in enumerate(keys_b):
            if key and other and key[0] == other[0] and key[1] != other[1]:
                scores[i, j] = 0  # Similar templates with different authorizations are not equivalent.
            elif key and key == other and count_a[key] == count_b[key] == 1:
                scores[i, j] = max(scores[i, j], 0.98)
                anchored.add((i, j))
    # Real->own dummy = removal; own dummy->real = addition; dummy->dummy=0.
    costs = np.full((n + m, n + m), 1e6)
    costs[:n, :m] = np.where(scores >= MATCH_THRESHOLD, 1 - scores, 1e6)
    for i in range(n):
        costs[i, m + i] = UNMATCHED_COST
    for j in range(m):
        costs[n + j, j] = UNMATCHED_COST
    costs[n:, m:] = 0
    rows, cols = linear_sum_assignment(costs)
    matched = {int(i): int(j) for i, j in zip(rows, cols) if i < n and j < m}
    result = []
    for i, a in enumerate(original):
        if i not in matched:
            closest = float(scores[i].max()) if m else 0.0
            result.append({"page_original": a.number, "page_modified": None, "status": "removed", "similarity": round(closest, 4), "review_required": True})
            continue
        j = matched[i]
        b, score = modified[j], float(scores[i, j])
        # Identical duplicate renderings are interchangeable; nonidentical near
        # alternatives are explicitly tentative instead of silently forced.
        alternatives = [(original[ii], b, float(scores[ii, j])) for ii in range(n) if ii != i]
        alternatives += [(a, modified[jj], float(scores[i, jj])) for jj in range(m) if jj != j]
        ambiguous = (i, j) not in anchored and (score < 0.75 or any(s >= MATCH_THRESHOLD and abs(s - score) < AMBIGUITY_MARGIN and not (
            p.visual_hash and q.visual_hash and a.visual_hash and b.visual_hash
            and p.visual_hash == q.visual_hash == a.visual_hash == b.visual_hash
        ) for p, q, s in alternatives))
        result.append({"page_original": a.number, "page_modified": b.number, "status": "review" if ambiguous else "matched", "similarity": round(score, 4), "review_required": ambiguous, "match_basis": "validation_code_and_form" if (i, j) in anchored else "content"})
    used = set(matched.values())
    for j, b in enumerate(modified):
        if j not in used:
            closest = float(scores[:, j].max()) if n else 0.0
            result.append({"page_original": None, "page_modified": b.number, "status": "added", "similarity": round(closest, 4), "review_required": True})
    # A physical page shift caused only by an insertion is not a reordering.
    pairs = [x for x in result if x["page_original"] and x["page_modified"]]
    for row in pairs:
        row["relocated"] = any((row["page_original"] - other["page_original"]) * (row["page_modified"] - other["page_modified"]) < 0 for other in pairs)
        if row["relocated"] and row["status"] != "review":
            row["status"] = "relocated"
    return result


def _money_value(raw: str) -> Decimal | None:
    """Decimal parsing refuses ambiguous one-separator thousands (e.g. 1,234)."""
    if not re.fullmatch(r"-?\d[\d.,]*", raw) or sum(c.isdigit() for c in raw) > 15:
        return None
    if "," in raw and "." in raw:
        sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if sep == "," else ","
        integer, decimals = raw.rsplit(sep, 1)
        if not re.fullmatch(r"-?\d{1,3}(?:" + re.escape(thousands) + r"\d{3})+", integer) or len(decimals) not in (2, 4):
            return None
        canonical = integer.replace(thousands, "") + "." + decimals
    elif "," in raw or "." in raw:
        sep = "," if "," in raw else "."
        if raw.count(sep) != 1:
            return None
        integer, decimals = raw.split(sep)
        if len(decimals) not in (2, 4):
            return None
        canonical = integer + "." + decimals
    else:
        canonical = raw
    try:
        return Decimal(canonical)
    except InvalidOperation:
        return None


def _finding(kind: str, category: str, description: str, before: str, after: str, po: int | None, pm: int | None, confidence: float, review: bool = False, **extra) -> dict:
    fingerprint = f"{kind}|{category}|{po}|{pm}|{before}|{after}|{description}"
    return {"id": "F_" + sha256(fingerprint.encode()).hexdigest()[:20], "change_type": kind, "category": category,
            "description": description, "before": before, "after": after, "page_original": po, "page_modified": pm,
            "confidence": round(confidence, 4), "review_required": review, **extra}


def _sequence_line_changes(a: Page, b: Page) -> list[dict]:
    old, new = a.text.splitlines(), b.text.splitlines()
    # Ignore whitespace wrapping alone but preserve numbers, accents and case.
    if re.sub(r"\s+", " ", a.text) == re.sub(r"\s+", " ", b.text):
        return []
    findings = []
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    edits = []
    for op, i, ii, j, jj in matcher.get_opcodes():
        # Preserve row-level evidence for adjacent monetary changes only when
        # every row retains the same surrounding concept. Otherwise preserve
        # the complete block, without inventing a table/column association.
        if op == "replace" and ii - i == jj - j and ii - i > 1 and all(
            _normal(MONEY_RE.sub("<importe>", left)) == _normal(MONEY_RE.sub("<importe>", right))
            for left, right in zip(old[i:ii], new[j:jj])
        ):
            edits.extend((op, i + k, i + k + 1, j + k, j + k + 1) for k in range(ii - i))
        else:
            edits.append((op, i, ii, j, jj))
    for op, i, ii, j, jj in edits:
        if op == "equal":
            continue
        before, after = "\n".join(old[i:ii]), "\n".join(new[j:jj])
        kind = {"replace": "modified", "delete": "removed", "insert": "added"}[op]
        # Line/block edits retain both physical pages: absence of a line is not
        # absence of its containing page.
        category = "Contenido documental"
        description = {"replace": "Se modificó contenido dentro de páginas correspondientes.", "delete": "Se eliminó contenido del original dentro de la página correspondiente del PDF modificado.", "insert": "Se añadió contenido dentro de páginas correspondientes."}[op]
        monetary_changes = []
        if op == "replace" and len(old[i:ii]) == len(new[j:jj]) == 1:
            old_money, new_money = list(MONEY_RE.finditer(before)), list(MONEY_RE.finditer(after))
            same_context = _normal(MONEY_RE.sub("<importe>", before)) == _normal(MONEY_RE.sub("<importe>", after))
            context_text = MONEY_RE.sub(" ", before)
            legible_context = _readable(context_text) or bool(re.search(r"\b(?:total|subtotal|liquidacion|liquidación|tarifa|honorarios)\b", context_text, re.I))
            if same_context and legible_context and old_money and len(old_money) == len(new_money) and a.source == b.source == "embedded":
                for k, (x, y) in enumerate(zip(old_money, new_money), 1):
                    av, bv = _money_value(x.group(1)), _money_value(y.group(1))
                    if av is not None and bv is not None and av != bv:
                        monetary_changes.append({"position": k, "before": str(av), "after": str(bv), "delta": str(bv - av), "relative_change": str((bv - av) / av) if av else None, "currency": "USD", "source_before": x.group(), "source_after": y.group()})
                if monetary_changes:
                    category = "Importe documental"
                    description = "Cambió un importe en la misma línea documental. Verificar su concepto y efecto en la liquidación; no se presume cuál valor es correcto."
        review = a.source == "ocr" or b.source == "ocr"
        if review:
            description += " Texto obtenido mediante OCR: requiere cotejo con el PDF."
        findings.append(_finding(kind, category, description, before, after, a.number, b.number, min(a.confidence, b.confidence), review, monetary_changes=monetary_changes,
                                 line_original_start=i + 1 if i < ii else None, line_modified_start=j + 1 if j < jj else None))
    return findings


def _line_changes(a: Page, b: Page) -> list[dict]:
    def fields(text):
        grouped = defaultdict(list)
        for index, line in enumerate(text.splitlines()):
            label, sep, value = line.partition(":")
            key = _normal(label)
            if sep and len(key) >= 12 and len(key.split()) >= 2:
                grouped[key].append((index, line, value.strip()))
        return grouped
    old_fields, new_fields = fields(a.text), fields(b.text)
    old_used, new_used, findings = set(), set(), []
    for key in old_fields:
        if key not in new_fields:
            continue
        if len(old_fields[key]) != 1 or len(new_fields[key]) != 1:
            continue  # Repeated labels must not be paired arbitrarily.
        i, before, before_value = old_fields[key][0]
        j, after, after_value = new_fields[key][0]
        old_used.add(i); new_used.add(j)
        if before == after:
            continue
        changes = _sequence_line_changes(
            Page(a.number, before, source=a.source, confidence=a.confidence),
            Page(b.number, after, source=b.source, confidence=b.confidence))
        for finding in changes:
            finding.update(line_original_start=i + 1, line_modified_start=j + 1)
            if 'diagnostic' in key or 'diganostic' in key:
                finding['category'] = 'Diagnóstico documental'
                finding['description'] = 'Cambió el diagnóstico en el mismo campo del formulario.'
            findings.append(finding)
    remaining_a = "\n".join(line for i, line in enumerate(a.text.splitlines()) if i not in old_used)
    remaining_b = "\n".join(line for i, line in enumerate(b.text.splitlines()) if i not in new_used)
    findings.extend(_sequence_line_changes(
        Page(a.number, remaining_a, source=a.source, confidence=a.confidence),
        Page(b.number, remaining_b, source=b.source, confidence=b.confidence)))
    return findings


def compare_documents(original: Path, modified: Path, *, ocr_enabled: bool = True) -> dict:
    """Compare one already-confirmed patient pair; return JSON-serializable evidence."""
    original, modified = Path(original), Path(modified)
    readers = [PdfReader(str(p), strict=False) for p in (original, modified)]
    if any(r.is_encrypted for r in readers):
        raise ValueError("No se comparan documentos PDF cifrados.")
    n, m = (len(r.pages) for r in readers)
    if not n or not m:
        raise ValueError("Ambos PDF deben contener al menos una página.")
    hashes = [_file_hash(p) for p in (original, modified)]
    result = {"status": "inconclusive", "pages_original": n, "pages_modified": m, "pages_added": 0, "pages_removed": 0,
              "pages_relocated": 0, "findings": [], "page_map": [], "limitations": [], "engine_version": ENGINE_VERSION,
              "hash_original": hashes[0], "hash_modified": hashes[1], "text_change_ratio": None, "priority": None,
              "priority_reason": "Rúbrica de prioridad pendiente de calibración y aprobación por auditoría.",
              "pages_evaluated_original": 0, "pages_evaluated_modified": 0, "page_counts_reconciled": False}
    if n > MAX_PAGES or m > MAX_PAGES:
        result["limitations"].append(f"Límite de {MAX_PAGES} páginas por PDF excedido. No se evaluó el expediente; los conteos de cambios no están determinados.")
        return result
    if hashes[0] == hashes[1]:
        result.update(status="no_differences_detected", priority=0, priority_reason="Archivos binariamente idénticos.", text_change_ratio=0, page_counts_reconciled=True, pages_evaluated_original=n, pages_evaluated_modified=m)
        result["page_map"] = [{"page_original": k, "page_modified": k, "status": "identical", "similarity": 1.0, "review_required": False} for k in range(1, n + 1)]
        return result
    pages_a = _extract(original, readers[0], ocr_enabled=ocr_enabled)
    pages_b = _extract(modified, readers[1], ocr_enabled=ocr_enabled)
    mapping = _align_pages(pages_a, pages_b)
    result["page_map"] = mapping
    findings = result["findings"]
    limitations = result["limitations"]
    inconclusive = False
    changed_tokens = all_tokens = 0
    for row in mapping:
        po, pm = row["page_original"], row["page_modified"]
        a, b = pages_a[po - 1] if po else None, pages_b[pm - 1] if pm else None
        for side, page in (("original", a), ("modificado", b)):
            if page:
                row[f"document_type_{side}"] = page.title
                row[f"extraction_{side}"] = page.source
                row[f"confidence_{side}"] = page.confidence
        exact_visual = bool(a and b and a.visual_hash and a.visual_hash == b.visual_hash)
        for side, page in (("original", a), ("modificado", b)):
            if page and not exact_visual:
                limitations.extend(f"PDF {side}, página {page.number}: {issue}" for issue in page.issues)
                if page.issues or not page.readable:
                    inconclusive = True
        if a and not b or b and not a:
            page = a or b
            kind = "removed" if a else "added"
            counter = "pages_removed" if a else "pages_added"
            result[counter] += 1
            # A dummy node proves only that the assignment left a page without
            # a counterpart. It does not prove the auditor added/deleted it:
            # OCR failure, rotation, cropping and split pages can also cause it.
            review = True
            inconclusive = True
            if page.readable:
                description = ("Página del original sin correspondencia automática en el PDF modificado." if a else "Página del PDF modificado sin correspondencia automática en el original.") + f" Tipo identificado: {page.title}."
            else:
                description = "Página sin correspondencia automática y lectura insuficiente. Revisar visualmente antes de confirmar incorporación o eliminación."
            if review and page.readable:
                description += " Asociación incierta: podría ser una sustitución o cambio de maquetación; requiere revisión."
            if review:
                limitations.append(f"Página {'original' if a else 'modificada'} {page.number}: incorporación/eliminación pendiente de confirmar por falta de correspondencia segura.")
            findings.append(_finding("review", "Correspondencia de páginas", description, page.text if a and page.readable else "", page.text if b and page.readable else "", po, pm, page.confidence, review, proposed_change_type=kind))
            continue
        if row["review_required"]:
            inconclusive = True
            limitations.append(f"Asociación tentativa original {po} / modificado {pm}: similitud insuficiente o candidatos cercanos.")
            findings.append(_finding("review", "Correspondencia de páginas", "La correspondencia tiene similitud insuficiente o más de un candidato posible. Confirmar estas páginas antes de interpretar sus diferencias.", "", "", po, pm, row["similarity"], True))
            continue
        if row.get("relocated"):
            result["pages_relocated"] += 1
            findings.append(_finding("relocated", "Orden documental", "La página cambió de posición relativa respecto de otras páginas correspondientes; no es una incorporación.", a.title, b.title, po, pm, row["similarity"]))
        if exact_visual:
            result["pages_evaluated_original"] += 1
            result["pages_evaluated_modified"] += 1
            row["visual_equal"] = True
            if a.readable and b.readable:
                all_tokens += max(len(a.tokens), len(b.tokens))
            continue
        if not a.readable or not b.readable:
            inconclusive = True
            findings.append(_finding("review", "Lectura documental", "No se puede establecer el cambio de contenido por lectura insuficiente. Cotejar ambas páginas en el visor.", "", "", po, pm, min(a.confidence, b.confidence), True))
            continue
        result["pages_evaluated_original"] += 1
        result["pages_evaluated_modified"] += 1
        lines = _line_changes(a, b)
        for finding in lines:
            finding["page_relocated"] = bool(row.get("relocated"))
        findings.extend(lines)
        ta, tb = a.tokens, b.tokens
        seq = SequenceMatcher(None, ta, tb, autojunk=True)
        all_tokens += max(len(ta), len(tb))
        changed_tokens += sum(max(ii - i, jj - j) for op, i, ii, j, jj in seq.get_opcodes() if op != "equal")
        if a.visual_hash and b.visual_hash and a.visual_hash != b.visual_hash:
            # A render difference can be layout/compression/stamp/signature or
            # text. Do not authenticate signatures or name an unlocalized mark.
            graphic_description = "Cambió la representación visual de la página. Puede corresponder a maquetación, imágenes, sellos, firmas o al texto; cotejar en el visor. No determina autenticidad ni ausencia de firma."
            findings.append(_finding("review", "Representación gráfica", graphic_description,
                                     "Página original; revisar soporte gráfico" if lines else "Texto sin variación detectada",
                                     "Representación visual diferente", po, pm, 0.5, True))
            inconclusive = True
            limitations.append(f"Original {po} / modificado {pm}: cambio gráfico pendiente de revisión visual; no se identificó automáticamente la región que lo explica.")
            row["visual_equal"] = False
    result["page_counts_reconciled"] = m - n == result["pages_added"] - result["pages_removed"]
    result["text_change_ratio"] = round(changed_tokens / all_tokens, 6) if all_tokens else None
    result["limitations"] = list(dict.fromkeys(limitations))
    result["status"] = "inconclusive" if inconclusive else ("with_differences" if findings else "no_differences_detected")
    if result["status"] == "no_differences_detected":
        result["priority"] = 0
        result["priority_reason"] = "Comparación evaluada sin diferencias detectadas a la resolución de análisis."
    return result
