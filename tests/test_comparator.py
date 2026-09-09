from pathlib import Path

import pytest

from app.comparator import discover, monetary_line_changes, name_key, scores


def test_discover_pairs_by_numeric_prefix(tmp_path: Path):
    (tmp_path / "2 - DOS.pdf").write_bytes(b"x")
    (tmp_path / "1 - UNO.pdf").write_bytes(b"x")
    (tmp_path / "scan.pdf").write_bytes(b"x")
    found, ignored = discover(tmp_path)
    assert list(found) == [1, 2]
    assert ignored == ["scan.pdf"]


def test_discover_rejects_duplicate_index(tmp_path: Path):
    (tmp_path / "1 - A.pdf").write_bytes(b"x")
    (tmp_path / "1 - B.pdf").write_bytes(b"x")
    with pytest.raises(ValueError, match="duplicado"):
        discover(tmp_path)


def test_name_key_ignores_diacritics():
    assert name_key("VICUÑA PEÑA") == name_key("VICUNA PENA")


def test_score_floors_for_pages_and_sensitive_changes():
    page = {"width_pt": 1, "height_pt": 1, "rotation": 0}
    before = {"sha256": "a", "page_count": 1, "pages": [page]}
    after = {"sha256": "b", "page_count": 2, "pages": [page, page]}
    text = {"change_percent": 1, "tokens_before": 100, "tokens_after": 100}
    sensitive = {"dates": {"added_count": 1, "removed_count": 0}}
    result = scores(before, after, text, sensitive, False)
    assert result["severity"] >= 80
    assert result["level"] in {"muy alto", "crítico"}


def test_monetary_lines_match_by_context_and_report_changed_lists():
    before = ["2025-10-30 Pinza de Biopsia Estandar 1 $95,00 $104,50 $9,50 $15,6750 $120,18\nTOTAL LIQUIDACION $841,74"]
    after = ["2025-10-30 Pinza de Biopsia Estandar 1 $95,00 $95,00 $9,50 $14,2500 $118,75\nTOTAL LIQUIDACION $839,87"]
    changes = monetary_line_changes(before, after)
    pinza = next(item for item in changes if "Pinza" in item["description"])
    total = next(item for item in changes if "TOTAL LIQUIDACION" in item["description"])
    assert pinza["page_before"] == pinza["page_after"] == 1
    assert pinza["amounts_before"] == ["$95,00", "$104,50", "$9,50", "$15,6750", "$120,18"]
    assert pinza["amounts_after"] == ["$95,00", "$95,00", "$9,50", "$14,2500", "$118,75"]
    assert total["amounts_before"] == ["$841,74"]
    assert total["amounts_after"] == ["$839,87"]
    assert {item["evidence_id"] for item in changes} == {"E_MONEY_LINE_1", "E_MONEY_LINE_2"}
