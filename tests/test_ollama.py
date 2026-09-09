import json

from app.ollama import evidence_payload, validate_summary


def sample_comparison():
    sensitive = {key: {"added_count": 1, "removed_count": 0, "added": ["SECRET"]} for key in ("amounts", "dates", "identifiers", "diagnostic_codes", "signature_terms")}
    return {
        "index": 1, "name_before": "PRIVATE NAME", "page_delta": 2,
        "text_diff": {"change_percent": 30, "snippets": [{"added": "CLINICAL SECRET"}]},
        "scores": {"technical_change_percent": 40, "severity": 80},
        "before": {"pages_requiring_ocr": [1]}, "after": {"pages_requiring_ocr": []},
        "metadata_changes": {"author": {"before": "PRIVATE", "after": "SECRET"}},
        "sensitive_changes": sensitive,
        "monetary_line_changes": [{"evidence_id": "E_MONEY_LINE_1", "status": "different_amounts", "page_before": 1, "page_after": 1, "description": "PRIVATE SUPPLY", "amounts_before": ["$10,00"], "amounts_after": ["$9,00"]}],
    }


def test_evidence_payload_excludes_phi_and_raw_values():
    serialized = json.dumps(evidence_payload(sample_comparison()))
    assert "PRIVATE" not in serialized
    assert "SECRET" not in serialized
    assert "CLINICAL" not in serialized
    assert "PRIVATE SUPPLY" not in serialized
    assert "E_MONEY_LINE_1" in serialized
    assert "$10,00" in serialized


def test_dynamic_money_evidence_id_is_valid():
    value = {"summary": {"text": "x", "evidence_ids": ["E_MONEY_LINE_1"]}, "main_changes": [], "alerts": [], "limitations": []}
    assert validate_summary(value, {"E_MONEY_LINE_1"}) == value


def test_summary_rejects_unknown_evidence_id():
    value = {"summary": "x", "main_changes": [{"text": "x", "evidence_ids": ["UNKNOWN"]}], "alerts": [], "limitations": []}
    try:
        validate_summary(value, {"E_PAGE_DELTA"})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown evidence id accepted")
