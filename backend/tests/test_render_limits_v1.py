from pypdf import PdfWriter, PdfReader
from app.comparison import _extract


def test_huge_page_is_not_rasterized(tmp_path, monkeypatch):
    import pypdfium2
    path = tmp_path / "huge.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100000, height=100000)
    writer.write(path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Render must not allocate an oversized page")
    monkeypatch.setattr(pypdfium2.PdfPage, "render", forbidden)
    pages = _extract(path, PdfReader(path), ocr_enabled=False)
    assert len(pages) == 1
    assert pages[0].visual_hash is None
    assert any("ValueError" in issue for issue in pages[0].issues)
