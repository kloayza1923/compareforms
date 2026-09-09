from __future__ import annotations

from typing import Any
import json
import re

import httpx


SYSTEM_PROMPT = """Redacta únicamente hechos literales desde evidencias numéricas anonimizadas.
Devuelve JSON válido con: summary, main_changes, alerts, limitations. Summary, cada elemento de
main_changes y cada alerta deben ser {"text": string, "evidence_ids": [string]}. Cada afirmación
debe citar evidence_ids recibidos. No uses calificativos como significativo, sustancial o grave;
no digas gestión, alteración o modificación. Para importes/fechas/IDs indica solo apariciones
agregadas o eliminadas y aclara que no confirma un cambio campo a campo. No infieras causas,
fraude, manipulación, intención, autoría, identidad, diagnóstico ni corrección clínica/legal.
No inventes valores. No solicites ni menciones datos personales."""

EVIDENCE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
    "required": ["text", "evidence_ids"],
    "additionalProperties": False,
}
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": EVIDENCE_ITEM_SCHEMA,
        "main_changes": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
        "alerts": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "main_changes", "alerts", "limitations"],
    "additionalProperties": False,
}


class OllamaUnavailable(RuntimeError):
    pass


def preflight(base_url: str, model: str, timeout: int) -> None:
    """Verify Ollama and the model; never pull or install anything."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=min(timeout, 20))
        response.raise_for_status()
        names = {item.get("name", "") for item in response.json().get("models", [])}
    except Exception as exc:
        raise OllamaUnavailable(f"Ollama no disponible: {type(exc).__name__}") from exc
    if model not in names:
        raise OllamaUnavailable(f"Modelo configurado no disponible: {model}")


def evidence_payload(comparison: dict[str, Any]) -> dict[str, Any]:
    """Allow-listed aggregates only: no names, IDs, clinical text, or snippets."""
    sensitive = comparison["sensitive_changes"]
    evidence = [
        {"id": "E_PAGE_DELTA", "metric": "page_delta", "value": comparison["page_delta"]},
        {"id": "E_TEXT_CHANGE", "metric": "text_change_percent", "value": comparison["text_diff"]["change_percent"]},
        {"id": "E_TECHNICAL", "metric": "technical_change_percent", "value": comparison["scores"]["technical_change_percent"]},
        {"id": "E_SEVERITY", "metric": "severity", "value": comparison["scores"]["severity"]},
        {"id": "E_OCR", "metric": "pages_requiring_ocr", "before": len(comparison["before"]["pages_requiring_ocr"]), "after": len(comparison["after"]["pages_requiring_ocr"])},
        {"id": "E_METADATA", "metric": "metadata_fields_changed", "value": len(comparison["metadata_changes"])},
    ]
    for key in ("amounts", "dates", "identifiers", "diagnostic_codes", "signature_terms"):
        evidence.append({"id": f"E_{key.upper()}", "metric": f"{key}_changes", "added_count": sensitive[key]["added_count"], "removed_count": sensitive[key]["removed_count"]})
    for change in comparison.get("monetary_line_changes", []):
        evidence.append({
            "id": change["evidence_id"], "metric": "monetary_line_difference",
            "status": change["status"], "page_before": change["page_before"], "page_after": change["page_after"],
            "amounts_before": change["amounts_before"], "amounts_after": change["amounts_after"],
            "count_before": len(change["amounts_before"]), "count_after": len(change["amounts_after"]),
        })
    return {"document_index": comparison["index"], "evidence": evidence}


def validate_summary(value: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("summary"), dict): raise ValueError("invalid summary")
    evidence_items = [value["summary"]]
    for key in ("main_changes", "alerts"):
        if not isinstance(value.get(key), list): raise ValueError(f"invalid {key}")
        for item in value[key]:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("evidence_ids"), list): raise ValueError(f"invalid evidence item in {key}")
            evidence_items.append(item)
    forbidden = re.compile(r"\b(?:significativ\w*|sustancial\w*|gesti[oó]n|alteraci[oó]n|modificaci[oó]n|fraude|manipulaci[oó]n|autor[ií]a|culpable)\b", re.I)
    for item in evidence_items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("evidence_ids"), list): raise ValueError("invalid cited statement")
        ids = set(item["evidence_ids"])
        if not ids or not ids <= allowed: raise ValueError("unknown/missing evidence id")
        if forbidden.search(item["text"]): raise ValueError("unsupported wording")
    if not isinstance(value.get("limitations"), list) or not all(isinstance(x, str) for x in value["limitations"]): raise ValueError("invalid limitations")
    return value


def deterministic_fallback(comparison: dict[str, Any], reason: str) -> dict[str, Any]:
    money_items = [
        {"text": "Se detectó una diferencia de importe en línea documental.", "evidence_ids": [change["evidence_id"]]}
        for change in comparison.get("monetary_line_changes", [])
    ]
    return {
        "status": "fallback", "model": None, "reason": reason,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "summary": {
            "summary": {"text": f"Cambio técnico {comparison['scores']['technical_change_percent']:.2f}% y prioridad {comparison['scores']['severity']:.2f}/100.", "evidence_ids": ["E_TECHNICAL", "E_SEVERITY"]},
            "main_changes": [{"text": f"Diferencia de páginas: {comparison['page_delta']:+d}.", "evidence_ids": ["E_PAGE_DELTA"]}] + money_items,
            "alerts": [{"text": "Existen páginas que requieren OCR.", "evidence_ids": ["E_OCR"]}] if comparison["before"]["pages_requiring_ocr"] or comparison["after"]["pages_requiring_ocr"] else [],
            "limitations": ["Resumen automático basado solo en métricas; requiere revisión humana."],
        },
    }


def normalize_wording(summary: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    """Replace ambiguous model prose with literal statements tied to deterministic metrics."""
    summary["summary"] = {
        "text": (
            f"Se detectó una diferencia neta de {comparison['page_delta']:+d} páginas, "
            f"un cambio de texto de {comparison['text_diff']['change_percent']:.3f}%, "
            f"un cambio técnico de {comparison['scores']['technical_change_percent']:.2f}% "
            f"y una prioridad de revisión de {comparison['scores']['severity']:.2f}/100."
        ),
        "evidence_ids": ["E_PAGE_DELTA", "E_TEXT_CHANGE", "E_TECHNICAL", "E_SEVERITY"],
    }
    metadata_count = len(comparison["metadata_changes"])
    sensitive_labels = {
        "E_AMOUNTS": ("amounts", "importes"),
        "E_DATES": ("dates", "fechas"),
        "E_IDENTIFIERS": ("identifiers", "identificadores"),
        "E_DIAGNOSTIC_CODES": ("diagnostic_codes", "códigos diagnósticos"),
        "E_SIGNATURE_TERMS": ("signature_terms", "términos asociados a firma"),
    }
    money_by_id = {change["evidence_id"]: change for change in comparison.get("monetary_line_changes", [])}
    for key in ("main_changes", "alerts"):
        for item in summary[key]:
            if "E_METADATA" in item["evidence_ids"]:
                item["text"] = f"Se detectaron diferencias en {metadata_count} campos de metadatos."
            for evidence_id, (metric_key, label) in sensitive_labels.items():
                if evidence_id in item["evidence_ids"]:
                    metric = comparison["sensitive_changes"][metric_key]
                    item["text"] = (
                        f"Se detectaron {metric['added_count']} apariciones agregadas y "
                        f"{metric['removed_count']} eliminadas de {label}; "
                        "no confirma correspondencia ni cambio campo a campo."
                    )
            if "E_SEVERITY" in item["evidence_ids"]:
                item["text"] = f"La prioridad de revisión automática es {comparison['scores']['severity']:.2f}/100."
            money_ids = [evidence_id for evidence_id in item["evidence_ids"] if evidence_id in money_by_id]
            if money_ids:
                pages = sorted({money_by_id[evidence_id]["page_after"] or money_by_id[evidence_id]["page_before"] for evidence_id in money_ids})
                item["text"] = f"Se detectó una diferencia de importe en línea documental en la página {', '.join(map(str, pages))}."
    return summary


def summarize(comparison: dict[str, Any], base_url: str, model: str, timeout: int) -> dict[str, Any]:
    payload = evidence_payload(comparison)
    allowed = {item["id"] for item in payload["evidence"]}
    request = {"model": model, "stream": False, "format": SUMMARY_SCHEMA, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=True)}], "options": {"temperature": 0, "seed": 42}}
    error = "respuesta inválida"
    for _attempt in range(2):
        try:
            response = httpx.post(f"{base_url.rstrip('/')}/api/chat", json=request, timeout=timeout)
            response.raise_for_status()
            response_data = response.json()
            parsed = json.loads(response_data["message"]["content"])
            prompt_tokens = int(response_data.get("prompt_eval_count", 0) or 0)
            completion_tokens = int(response_data.get("eval_count", 0) or 0)
            validated = validate_summary(parsed, allowed)
            return {
                "status": "ok",
                "model": model,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                "summary": normalize_wording(validated, comparison),
            }
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    return deterministic_fallback(comparison, error[:240])
