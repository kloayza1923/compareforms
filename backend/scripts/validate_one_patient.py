"""Opt-in local acceptance: one real pair, PostgreSQL, HTTP contract and worker.

No remote service is contacted. Originals are copied into private ingestion storage.
The temporary QA account is disabled in finally; evidence is retained for review.
"""
from pathlib import Path
import argparse
import io
import json
import secrets
import shutil
import zipfile
from collections import Counter
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from app.config import Settings, ROOT
from app.cli import create_admin
from app.main import create_app
from app.worker import run_once
from app import db as m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists(): raise SystemExit("Output exists; choose a new filename.")
    cfg = Settings()
    if "127.0.0.1:54327/compareforms" not in cfg.database_url:
        raise SystemExit("Acceptance is restricted to the isolated local database.")
    original = ROOT / "dataset/2026_06/pdf_origen/ALARCON CARPIO DIGNA ASUNCION_origen.pdf"
    modified = ROOT / "dataset/2026_06/pdf_modificado/1 - ALARCON CARPIO DIGNA ASUNCION_modificado.pdf"
    if not original.is_file() or not modified.is_file(): raise SystemExit("Missing selected pair.")
    token = secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    username = "qa_acceptance_" + token
    user = create_admin(cfg, username, password, "Aceptación local V1 " + token)
    app = create_app(cfg)
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/health").json()["status"] == "ready"
            response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
            response.raise_for_status()
            headers = {"X-CSRF-Token": response.json()["csrf_token"]}
            response = client.post("/api/v1/batches", headers=headers, json={"name": "Validación V1 · un expediente", "period": "2026_06", "source_mode": "manual", "source_system": "manual_otro"})
            response.raise_for_status()
            batch_id = response.json()["id"]
            for side, path in (("original", original), ("modified", modified)):
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z: z.write(path, path.name)
                response = client.post(f"/api/v1/batches/{batch_id}/uploads", params={"side": side}, headers=headers, files={"file": ("one.zip", archive.getvalue(), "application/zip")})
                response.raise_for_status()
            inventory = client.get(f"/api/v1/batches/{batch_id}/inventory").json()
            assert len(inventory["pairs"]) == 1, "Pair suggestion failed"
            pair = inventory["pairs"][0]
            response = client.post(f"/api/v1/batches/{batch_id}/pairs", headers=headers, json={k: pair[k] for k in ("original_id", "modified_id", "patient_name")})
            response.raise_for_status()
            headers["Idempotency-Key"] = token
            response = client.post(f"/api/v1/batches/{batch_id}/runs", headers=headers, json={"allow_partial": False})
            response.raise_for_status()
            run_id = response.json()["id"]
            # A second PostgreSQL connection cannot acquire the global worker lock.
            with app.state.engine.connect() as lock:
                assert lock.scalar(text("SELECT pg_try_advisory_lock(1870025201)"))
                try: assert run_once(cfg, app.state.SessionLocal) is False
                finally: lock.execute(text("SELECT pg_advisory_unlock(1870025201)"))
            print(json.dumps({"event": "comparing", "patients": 1, "run_id": run_id}), flush=True)
            assert run_once(cfg, app.state.SessionLocal)
            data = client.get(f"/api/v1/runs/{run_id}").json()
            assert data["total"] == data["completed"] == 1, data
            assert data["report_available"], data
            response = client.get(f"/api/v1/runs/{run_id}/report")
            response.raise_for_status()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as file: file.write(response.content)
            comp = data["cases"][0]["comparison"]
            result = {"event": "report_created", "run_id": run_id, "status": data["status"], "patients": 1, "pages_original": comp["pages_original"], "pages_modified": comp["pages_modified"], "findings": len(comp["findings"]), "types": dict(Counter(f["change_type"] for f in comp["findings"])), "page_mapping": dict(Counter(p["status"] for p in comp["page_map"])), "output": str(args.output)}
            with args.output.with_suffix(".validation.json").open("x", encoding="utf-8") as file: json.dump(result, file, ensure_ascii=False, indent=2)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        with app.state.SessionLocal.begin() as db:
            db.get(m.User, user.id).active = False
            db.execute(delete(m.Session).where(m.Session.user_id == user.id))
        app.state.engine.dispose()


if __name__ == "__main__": main()
