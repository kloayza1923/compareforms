from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path
from typing import Any
import re
import shutil
import subprocess
import tempfile
import unicodedata

from PIL import Image
from pypdf import PdfReader
import pytesseract


INDEX_RE = re.compile(r"^\s*(\d+)\s*-\s*(.*?)\s*\.pdf$", re.IGNORECASE)
WORD_RE = re.compile(r"[\wÀ-ÿ]+(?:['’-][\wÀ-ÿ]+)*|[^\w\s]", re.UNICODE)
PATTERNS = {
    "amounts": re.compile(r"(?<!\w)(?:US\$|USD|\$)\s*\d[\d.,]*|(?<!\w)\d{1,3}(?:[.,]\d{3})*[.,]\d{2}(?!\w)", re.I),
    "dates": re.compile(r"(?<!\d)(?:[0-3]?\d[/-][01]?\d[/-](?:19|20)?\d{2}|(?:19|20)\d{2}-[01]\d-[0-3]\d)(?!\d)"),
    "identifiers": re.compile(r"(?<!\d)\d{10}(?!\d)"),
    "diagnostic_codes": re.compile(r"(?<![A-Z0-9])[A-Z][0-9]{2}(?:\.[0-9A-Z]{1,2})?(?![A-Z0-9])", re.I),
    "signature_terms": re.compile(r"\b(?:firma(?:do|da|s)?|suscri(?:to|ta)|rúbrica|rubrica)\b", re.I),
}
MONEY_RE = re.compile(r"(?<!\w)(?:US\$|USD|\$)\s*((?:\d{1,3}(?:[.\s]\d{3})+|\d+)(?:[,.]\d{2,4})?)(?!\d)", re.I)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "").replace("\u00ad", "")).strip()


def name_key(value: str) -> str:
    value = unicodedata.normalize("NFD", normalize_text(value)).casefold()
    return "".join(char for char in value if unicodedata.category(char) != "Mn")


def normalize_money(value: str) -> tuple[str, str]:
    compact = re.sub(r"\s+", "", value)
    if "," in compact:
        integer, decimals = compact.rsplit(",", 1)
        integer = integer.replace(".", "")
    elif compact.count(".") == 1 and len(compact.rsplit(".", 1)[1]) in {2, 3, 4}:
        integer, decimals = compact.rsplit(".", 1)
    else:
        integer, decimals = compact.replace(".", ""), ""
    canonical = f"${integer},{decimals}" if decimals else f"${integer}"
    numeric = f"{integer}.{decimals}" if decimals else integer
    return canonical, numeric


def money_context(line: str) -> str:
    without_money = MONEY_RE.sub(" ", line)
    without_money = re.sub(r"^\s*\d{4}-\d{2}-\d{2}\s+", "", without_money)
    return normalize_text(without_money)[:300]


def money_context_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value).casefold()
    ascii_value = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def extract_money_lines(raw_pages: list[str]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for page_number, raw_text in enumerate(raw_pages, 1):
        for line_number, raw_line in enumerate(raw_text.splitlines(), 1):
            matches = list(MONEY_RE.finditer(raw_line))
            if not matches:
                continue
            normalized = [normalize_money(match.group(1)) for match in matches]
            context = money_context(raw_line)
            lines.append({
                "page": page_number, "line": line_number, "context": context,
                "context_key": money_context_key(context),
                "amounts": [item[0] for item in normalized],
                "amount_values": [item[1] for item in normalized],
            })
    return lines


def monetary_line_changes(before_pages: list[str], after_pages: list[str], threshold: float = 0.78) -> list[dict[str, Any]]:
    before_lines = extract_money_lines(before_pages)
    after_lines = extract_money_lines(after_pages)
    candidates: list[tuple[float, int, int]] = []
    for before_index, before in enumerate(before_lines):
        for after_index, after in enumerate(after_lines):
            if not before["context_key"] or not after["context_key"]:
                continue
            similarity = SequenceMatcher(None, before["context_key"], after["context_key"], autojunk=False).ratio()
            adjusted = similarity - min(0.15, 0.02 * abs(before["page"] - after["page"]))
            if adjusted >= threshold:
                candidates.append((adjusted, before_index, after_index))
    used_before: set[int] = set()
    used_after: set[int] = set()
    matched: list[tuple[int, int, float]] = []
    for similarity, before_index, after_index in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        if before_index in used_before or after_index in used_after:
            continue
        used_before.add(before_index); used_after.add(after_index)
        matched.append((before_index, after_index, similarity))
    raw_changes: list[dict[str, Any]] = []
    for before_index, after_index, similarity in sorted(matched):
        before, after = before_lines[before_index], after_lines[after_index]
        if before["amount_values"] == after["amount_values"]:
            continue
        raw_changes.append({
            "status": "different_amounts", "page_before": before["page"], "page_after": after["page"],
            "context_before": before["context"], "context_after": after["context"],
            "description": after["context"] or before["context"],
            "amounts_before": before["amounts"], "amounts_after": after["amounts"],
            "amount_values_before": before["amount_values"], "amount_values_after": after["amount_values"],
            "context_similarity_percent": round(similarity * 100, 2),
            "review_note": "Diferencia de importe en línea documental; requiere revisión contra los documentos fuente.",
        })
    for index, line in enumerate(before_lines):
        if index not in used_before:
            raw_changes.append({
                "status": "line_removed", "page_before": line["page"], "page_after": None,
                "context_before": line["context"], "context_after": "", "description": line["context"],
                "amounts_before": line["amounts"], "amounts_after": [], "amount_values_before": line["amount_values"], "amount_values_after": [],
                "context_similarity_percent": None, "review_note": "Línea documental con importes no emparejada; requiere revisión contra los documentos fuente.",
            })
    for index, line in enumerate(after_lines):
        if index not in used_after:
            raw_changes.append({
                "status": "line_added", "page_before": None, "page_after": line["page"],
                "context_before": "", "context_after": line["context"], "description": line["context"],
                "amounts_before": [], "amounts_after": line["amounts"], "amount_values_before": [], "amount_values_after": line["amount_values"],
                "context_similarity_percent": None, "review_note": "Línea documental con importes no emparejada; requiere revisión contra los documentos fuente.",
            })
    raw_changes.sort(key=lambda item: (item["page_before"] or item["page_after"] or 0, item["description"], item["status"]))
    for number, change in enumerate(raw_changes, 1):
        change["evidence_id"] = f"E_MONEY_LINE_{number}"
    return raw_changes


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def discover(directory: Path) -> tuple[dict[int, Path], list[str]]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Directorio no encontrado: {directory}")
    indexed: dict[int, Path] = {}
    ignored: list[str] = []
    for path in sorted(directory.glob("*.pdf"), key=lambda p: p.name.casefold()):
        match = INDEX_RE.match(path.name)
        if not match:
            ignored.append(path.name)
            continue
        index = int(match.group(1))
        if index in indexed:
            raise ValueError(f"Índice duplicado {index} en {directory}")
        indexed[index] = path
    return dict(sorted(indexed.items())), ignored


def ocr_page(path: Path, page_number: int, language: str, dpi: int) -> str:
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        raise RuntimeError("pdftoppm/tesseract no disponible")
    pytesseract.pytesseract.tesseract_cmd = tesseract
    with tempfile.TemporaryDirectory(prefix="compareforms_ocr_") as temp_dir:
        prefix = Path(temp_dir) / "page"
        subprocess.run([pdftoppm, "-f", str(page_number), "-l", str(page_number), "-singlefile", "-gray", "-r", str(dpi), "-png", str(path), str(prefix)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
        with Image.open(prefix.with_suffix(".png")) as image:
            return pytesseract.image_to_string(image, lang=language, config="--psm 6")


def extract(path: Path, ocr_enabled: bool = False, ocr_lang: str = "spa", ocr_dpi: int = 200, ocr_min_chars: int = 30) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    metadata = reader.metadata or {}
    pages: list[dict[str, Any]] = []
    page_texts: list[str] = []
    raw_pages: list[str] = []
    warnings: list[str] = []
    for number, page in enumerate(reader.pages, 1):
        try:
            raw_text = page.extract_text() or ""
            text = normalize_text(raw_text)
        except Exception as exc:
            raw_text = ""; text = ""
            warnings.append(f"página {number}: {type(exc).__name__}: {exc}")
        raw_pages.append(raw_text)
        page_texts.append(text)
        pages.append({
            "number": number,
            "width_pt": round(float(page.mediabox.width), 2),
            "height_pt": round(float(page.mediabox.height), 2),
            "rotation": int(page.get("/Rotate", 0) or 0) % 360,
            "text_chars": len(text),
            "text_sha256": sha256(text.encode()).hexdigest(),
            "text_source": "embedded",
            "ocr_confidence": None,
            "ocr_required": len(text) < ocr_min_chars,
        })
    ocr_applied: list[int] = []
    if ocr_enabled:
        for page in pages:
            if not page["ocr_required"]:
                continue
            number = page["number"]
            try:
                recognized_raw = ocr_page(path, number, ocr_lang, ocr_dpi)
                recognized = normalize_text(recognized_raw)
            except Exception as exc:
                warnings.append(f"OCR página {number}: {type(exc).__name__}: {exc}")
                continue
            if len(recognized) > len(page_texts[number - 1]):
                page_texts[number - 1] = recognized
                raw_pages[number - 1] = recognized_raw
                page["text_chars"] = len(recognized)
                page["text_sha256"] = sha256(recognized.encode()).hexdigest()
                page["text_source"] = "tesseract"
                page["ocr_confidence"] = "media" if len(recognized) >= 80 else "baja"
                page["ocr_required"] = len(recognized) < ocr_min_chars
                ocr_applied.append(number)
    fields = reader.get_fields() or {}
    return {
        "filename": path.name,
        "sha256": file_hash(path),
        "size_bytes": path.stat().st_size,
        "page_count": len(pages),
        "pages": pages,
        "page_texts": page_texts,
        "raw_pages": raw_pages,
        "text": "\n\f\n".join(page_texts),
        "text_chars": sum(map(len, page_texts)),
        "pages_requiring_ocr": [p["number"] for p in pages if p["ocr_required"]],
        "pages_ocr_applied": ocr_applied,
        "ocr_language": ocr_lang if ocr_enabled else None,
        "metadata": {key.lstrip("/").lower(): str(value) for key, value in metadata.items() if value is not None},
        "signature_field_count": sum(1 for value in fields.values() if str(value.get("/FT", "")) == "/Sig"),
        "warnings": warnings,
    }


def token_diff(before: str, after: str, limit: int) -> dict[str, Any]:
    left = WORD_RE.findall(before)
    right = WORD_RE.findall(after)
    matcher = SequenceMatcher(None, [x.casefold() for x in left], [x.casefold() for x in right], autojunk=False)
    added = deleted = unchanged = 0
    snippets: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
            continue
        deleted += i2 - i1
        added += j2 - j1
        if len(snippets) < limit:
            snippets.append({
                "operation": tag,
                "deleted": " ".join(left[i1:i2])[:500],
                "added": " ".join(right[j1:j2])[:500],
            })
    denominator = max(len(left) + len(right), 1)
    return {
        "tokens_before": len(left), "tokens_after": len(right),
        "tokens_added": added, "tokens_deleted": deleted, "tokens_unchanged": unchanged,
        "similarity_percent": round(100 * matcher.ratio(), 3),
        "change_percent": round(100 * (added + deleted) / denominator, 3),
        "snippets": snippets,
    }


def page_diff(before: list[str], after: list[str], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number in range(max(len(before), len(after))):
        left = before[number] if number < len(before) else ""
        right = after[number] if number < len(after) else ""
        diff = token_diff(left, right, min(limit, 5))
        rows.append({
            "page_before": number + 1 if number < len(before) else None,
            "page_after": number + 1 if number < len(after) else None,
            "status": "added" if number >= len(before) else "removed" if number >= len(after) else "matched_by_position",
            "change_percent": diff["change_percent"],
            "tokens_added": diff["tokens_added"], "tokens_deleted": diff["tokens_deleted"],
            "snippets": diff["snippets"],
        })
    return rows


def sensitive_changes(before: str, after: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, pattern in PATTERNS.items():
        left = Counter(normalize_text(x).casefold() for x in pattern.findall(before))
        right = Counter(normalize_text(x).casefold() for x in pattern.findall(after))
        added = list((right - left).elements())
        removed = list((left - right).elements())
        output[name] = {"added": added[:100], "removed": removed[:100], "added_count": len(added), "removed_count": len(removed)}
    return output


def scores(before: dict[str, Any], after: dict[str, Any], text: dict[str, Any], sensitive: dict[str, Any], metadata_changed: bool) -> dict[str, Any]:
    if before["sha256"] == after["sha256"]:
        return {"components": {k: 0.0 for k in "PTVFM"}, "technical_change_percent": 0.0, "severity": 0.0, "level": "idéntico"}
    p = min(100.0, 100 * abs(after["page_count"] - before["page_count"]) / max(before["page_count"], 1))
    t = text["change_percent"] if text["tokens_before"] + text["tokens_after"] >= 20 else 0.0
    # Server-safe deterministic fallback: V measures changes in page geometry and rotation.
    common = min(before["page_count"], after["page_count"])
    geometry_changes = sum(
        (before["pages"][i]["width_pt"], before["pages"][i]["height_pt"], before["pages"][i]["rotation"])
        != (after["pages"][i]["width_pt"], after["pages"][i]["height_pt"], after["pages"][i]["rotation"])
        for i in range(common)
    )
    v = 100 * geometry_changes / max(common, 1)
    sensitive_total = sum(vv["added_count"] + vv["removed_count"] for vv in sensitive.values())
    f = 100.0 if sensitive_total else 0.0
    m = 100.0 if metadata_changed else 0.0
    components = {"P": round(p, 3), "T": round(t, 3), "V": round(v, 3), "F": f, "M": m}
    technical = 0.20 * p + 0.40 * t + 0.30 * v + 0.08 * f + 0.02 * m
    severity = 0.30 * p + 0.35 * t + 0.25 * v + 0.07 * f + 0.03 * m
    if before["page_count"] != after["page_count"]:
        severity = max(severity, 60)
    if sensitive_total:
        severity = max(severity, 80)
    severity = round(min(100.0, severity), 2)
    level = "mínimo" if severity <= 10 else "bajo" if severity <= 25 else "moderado" if severity <= 45 else "alto" if severity <= 65 else "muy alto" if severity <= 85 else "crítico"
    return {"components": components, "technical_change_percent": round(technical, 2), "severity": severity, "level": level}


def compare_pair(index: int, before_path: Path, after_path: Path, max_snippets: int = 30, ocr_enabled: bool = False, ocr_lang: str = "spa", ocr_dpi: int = 200, ocr_min_chars: int = 30) -> dict[str, Any]:
    before = extract(before_path, ocr_enabled, ocr_lang, ocr_dpi, ocr_min_chars)
    after = extract(after_path, ocr_enabled, ocr_lang, ocr_dpi, ocr_min_chars)
    text = token_diff(before["text"], after["text"], max_snippets)
    sensitive = sensitive_changes(before["text"], after["text"])
    metadata_delta = {key: {"before": before["metadata"].get(key), "after": after["metadata"].get(key)} for key in sorted(set(before["metadata"]) | set(after["metadata"])) if before["metadata"].get(key) != after["metadata"].get(key)}
    money_changes = monetary_line_changes(before["raw_pages"], after["raw_pages"])
    matched_before = INDEX_RE.match(before_path.name)
    matched_after = INDEX_RE.match(after_path.name)
    return {
        "index": index,
        "name_before": matched_before.group(2) if matched_before else before_path.stem,
        "name_after": matched_after.group(2) if matched_after else after_path.stem,
        "name_matches": name_key(matched_before.group(2)) == name_key(matched_after.group(2)) if matched_before and matched_after else False,
        "identical": before["sha256"] == after["sha256"],
        "before": {k: v for k, v in before.items() if k not in {"text", "page_texts", "raw_pages"}},
        "after": {k: v for k, v in after.items() if k not in {"text", "page_texts", "raw_pages"}},
        "page_delta": after["page_count"] - before["page_count"],
        "size_delta_bytes": after["size_bytes"] - before["size_bytes"],
        "text_diff": text,
        "page_details": page_diff(before["page_texts"], after["page_texts"], max_snippets),
        "sensitive_changes": sensitive,
        "monetary_line_changes": money_changes,
        "metadata_changes": metadata_delta,
        "scores": scores(before, after, text, sensitive, bool(metadata_delta)),
    }
