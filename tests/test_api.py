from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_and_month_listing(tmp_path: Path):
    month = tmp_path / "2025_10"
    (month / "pdf_origen").mkdir(parents=True)
    (month / "pdf_modificado").mkdir()
    client = TestClient(create_app(Settings(data_root=tmp_path)))
    assert client.get("/health").json()["status"] == "ok"
    response = client.get("/months")
    assert response.status_code == 200
    assert response.json()["months"][0]["month"] == "2025_10"


def test_invalid_month_is_rejected(tmp_path: Path):
    client = TestClient(create_app(Settings(data_root=tmp_path)))
    assert client.get("/months/2025-10/results").status_code == 422


def test_request_rejects_unknown_fields(tmp_path: Path):
    client = TestClient(create_app(Settings(data_root=tmp_path)))
    assert client.post("/months/2025_10/run", json={"use_ollama": False, "unexpected": 1}).status_code == 422
