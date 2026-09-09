"""Independent V1 portal contract checks (design.md §§5, 7, 9, 15).

Only temporary SQLite databases and synthetic PDFs are used. These tests never
contact Roboti/Ollama, start a worker, or read a real patient document.
"""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import select

from app.cli import create_admin, deactivate_user
from app.config import Settings
from app.db import Base
from app import db as models
from app.main import create_app


API = "/api/v1"
PASSWORD = "Synthetic-test-passphrase!42"


def pdf_bytes(label: str = "Synthetic fixture") -> bytes:
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": label})
    writer.write(stream)
    return stream.getvalue()


def zip_bytes(entries: list[tuple[str | zipfile.ZipInfo, bytes]]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return stream.getvalue()


@pytest.fixture()
def portal(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'portal.sqlite').as_posix()}",
        documents_root=tmp_path / "private_documents",
        testing=True,
        session_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    create_admin(settings, "admin_test", PASSWORD, "Organizacion de prueba A")
    create_admin(settings, "other_test", PASSWORD, "Organizacion de prueba B")
    yield app
    app.state.engine.dispose()


@pytest.fixture()
def client(portal):
    with TestClient(portal) as value:
        yield value


def login(client: TestClient, username: str = "admin_test") -> dict[str, str]:
    response = client.post(
        f"{API}/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user"]["username"] == username
    assert data["csrf_token"]
    return {"X-CSRF-Token": data["csrf_token"]}


def test_maintenance_deactivation_preserves_user_and_revokes_sessions(portal, client):
    login(client)
    deactivate_user(portal.state.settings, "admin_test")
    assert client.get(f"{API}/auth/me").status_code == 401
    with portal.state.SessionLocal() as db:
        user = db.scalar(select(models.User).where(models.User.username == "admin_test"))
        assert user is not None and user.active is False
        assert list(db.scalars(select(models.Session).where(models.Session.user_id == user.id))) == []
        event = db.scalar(select(models.AuditEvent).where(models.AuditEvent.action == "maintenance_deactivate_user"))
        assert event.user_id is None and event.target_id == user.id


def create_batch(client, headers, *, source_mode="manual", source_system="dalia"):
    response = client.post(
        f"{API}/batches",
        json={
            "name": "Auditoria sintetica junio",
            "period": "2026_06",
            "source_mode": source_mode,
            "source_system": source_system,
        },
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def upload(client, headers, batch_id, side, entries):
    return client.post(
        f"{API}/batches/{batch_id}/uploads",
        params={"side": side},
        files={"file": ("expedientes.zip", zip_bytes(entries), "application/zip")},
        headers=headers,
    )


def inventory(client, batch_id):
    response = client.get(f"{API}/batches/{batch_id}/inventory")
    assert response.status_code == 200, response.text
    return response.json()


def confirmed_pair(client, headers, batch_id):
    # Original deliberately lacks a numeric index: the legacy zero-pair bug.
    for side, filename in (
        ("original", "PACIENTE SINTETICO UNO.pdf"),
        ("modified", "1 - PACIENTE SINTETICO UNO.pdf"),
    ):
        response = upload(client, headers, batch_id, side, [(filename, pdf_bytes())])
        assert response.status_code in (200, 201), response.text
    before = inventory(client, batch_id)
    assert len(before["documents"]) == 2
    assert not before["can_run"], "Suggestions cannot authorize case association"
    original = next(d for d in before["documents"] if d["side"] == "original")
    modified = next(d for d in before["documents"] if d["side"] == "modified")
    response = client.post(
        f"{API}/batches/{batch_id}/pairs",
        json={
            "original_id": original["id"],
            "modified_id": modified["id"],
            "patient_name": "PACIENTE SINTETICO UNO",
        },
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text
    return original, modified


def enqueue(client, headers, batch_id, *, key="synthetic-idempotency-001", partial=False):
    return client.post(
        f"{API}/batches/{batch_id}/runs",
        json={"allow_partial": partial},
        headers={**headers, "Idempotency-Key": key},
    )


def completed_fixture(portal, client, headers):
    """Seed deterministic output only, to exercise review routes without OCR."""
    batch_id = create_batch(client, headers)
    confirmed_pair(client, headers, batch_id)
    response = enqueue(client, headers, batch_id)
    assert response.status_code == 202
    run_id = response.json()["id"]
    finding = {
        "id": "F-SYNTHETIC-1", "change_type": "modified", "category": "Documento",
        "description": "Cambio sintetico para probar revision", "before": "Texto anterior",
        "after": "Texto nuevo", "page_original": 1, "page_modified": 1,
        "confidence": 0.99, "review_required": True,
    }
    with portal.state.SessionLocal() as session:
        run = session.get(models.Run, run_id)
        run.status = "completed"
        run.completed = 1
        case = session.scalar(select(models.RunCase).where(models.RunCase.run_id == run_id))
        case.status = "with_differences"
        case.comparison = {
            "status": "with_differences", "pages_original": 1, "pages_modified": 1,
            "pages_added": 0, "pages_removed": 0, "pages_relocated": 0,
            "findings": [finding], "page_map": [], "limitations": [],
            "engine_version": "synthetic-fixture-only",
        }
        case_id = case.id
        session.commit()
    return run_id, case_id, finding


def test_session_requires_login_and_revokes_after_logout(client):
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/batches").status_code == 401
    wrong = client.post(
        f"{API}/auth/login", json={"username": "admin_test", "password": "wrong"}
    )
    assert wrong.status_code == 401
    headers = login(client)
    response = client.get(f"{API}/auth/me")
    assert response.json()["csrf_token"] == headers["X-CSRF-Token"]
    assert response.json()["user"]["role"] == "admin"
    assert client.post(f"{API}/auth/logout", headers=headers).status_code in (200, 204)
    assert client.get(f"{API}/auth/me").status_code == 401


def test_session_cookie_is_httponly_and_samesite(client):
    response = client.post(
        f"{API}/auth/login", json={"username": "admin_test", "password": PASSWORD}
    )
    cookies = ";".join(response.headers.get_list("set-cookie")).lower()
    assert "httponly" in cookies
    assert "samesite=" in cookies


@pytest.mark.parametrize("csrf", [None, "incorrect-token"])
def test_mutation_rejects_missing_or_invalid_csrf(client, csrf):
    login(client)
    headers = {} if csrf is None else {"X-CSRF-Token": csrf}
    response = client.post(
        f"{API}/batches",
        json={"name": "No crear", "period": "2026_06", "source_mode": "manual", "source_system": "dalia"},
        headers=headers,
    )
    assert response.status_code == 403
    assert client.get(f"{API}/batches").json() == []


def test_zero_pairs_never_produces_success_or_report(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    assert inventory(client, batch_id)["can_run"] is False
    response = enqueue(client, headers, batch_id)
    assert response.status_code == 422, response.text
    assert client.get(f"{API}/runs").json() == []


def test_original_without_index_is_visible_and_explicitly_confirmable(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    original, modified = confirmed_pair(client, headers, batch_id)
    result = inventory(client, batch_id)
    assert result["can_run"] is True
    confirmed = [p for p in result["pairs"] if p["confirmed"]]
    assert len(confirmed) == 1
    assert confirmed[0]["original_id"] == original["id"]
    assert confirmed[0]["modified_id"] == modified["id"]
    assert result["unpaired"] == []
    response = enqueue(client, headers, batch_id)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    detail = client.get(f"{API}/runs/{response.json()['id']}").json()
    assert detail["total"] == 1
    assert not detail["report_available"]
    assert detail["cases"][0]["patient_name"] == "PACIENTE SINTETICO UNO"


def test_run_idempotency_prevents_double_click_and_rejects_changed_payload(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    confirmed_pair(client, headers, batch_id)
    first = enqueue(client, headers, batch_id)
    second = enqueue(client, headers, batch_id)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get(f"{API}/runs").json()) == 1
    changed = enqueue(client, headers, batch_id, partial=True)
    assert changed.status_code == 409, changed.text


def test_incomplete_batch_requires_explicit_partial_scope(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    confirmed_pair(client, headers, batch_id)
    response = upload(client, headers, batch_id, "modified", [("PACIENTE SINTETICO DOS.pdf", pdf_bytes("Synthetic case two"))])
    assert response.status_code in (200, 201), response.text
    assert len(inventory(client, batch_id)["unpaired"]) == 1
    assert enqueue(client, headers, batch_id).status_code == 422
    response = enqueue(client, headers, batch_id, key="allow-partial-002", partial=True)
    assert response.status_code == 202, response.text


def test_run_snapshot_survives_later_inventory_changes(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    confirmed_pair(client, headers, batch_id)
    response = enqueue(client, headers, batch_id)
    assert response.status_code == 202
    run_id = response.json()["id"]
    pair_id = next(p["id"] for p in inventory(client, batch_id)["pairs"] if p["confirmed"])
    response = client.delete(f"{API}/batches/{batch_id}/pairs/{pair_id}", headers=headers)
    # Either lock the batch while queued, or preserve the immutable run snapshot.
    assert response.status_code in (200, 204, 409)
    detail = client.get(f"{API}/runs/{run_id}").json()
    assert detail["total"] == 1
    assert len(detail["cases"]) == 1
    assert detail["cases"][0]["original_id"]
    assert detail["cases"][0]["modified_id"]


@pytest.mark.parametrize("filename", ["../../escape.pdf", "/escape.pdf", "C:/escape.pdf", "..\\escape.pdf"])
def test_zip_traversal_is_rejected_and_never_imported(client, filename):
    headers = login(client)
    batch_id = create_batch(client, headers)
    response = upload(client, headers, batch_id, "original", [(filename, pdf_bytes())])
    # Implementations can reject the archive or record a per-member rejection.
    assert response.status_code in (200, 201, 400, 422), response.text
    result = inventory(client, batch_id)
    assert result["documents"] == []
    if response.status_code in (200, 201):
        assert result["rejections"]


def test_zip_symlink_and_false_pdf_cannot_become_documents(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    link = zipfile.ZipInfo("link.pdf")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    response = upload(client, headers, batch_id, "modified", [(link, b"/etc/passwd"), ("fake.pdf", b"not a PDF")])
    assert response.status_code in (200, 201, 400, 422), response.text
    assert inventory(client, batch_id)["documents"] == []


def test_corrupt_zip_is_rejected_without_server_error(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    response = client.post(
        f"{API}/batches/{batch_id}/uploads?side=original",
        files={"file": ("broken.zip", b"this is not a ZIP", "application/zip")},
        headers=headers,
    )
    assert response.status_code in (400, 422), response.text
    assert inventory(client, batch_id)["documents"] == []


def test_duplicate_normalized_zip_members_are_not_silently_selected(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    response = upload(
        client, headers, batch_id, "original",
        [("PACIENTE.pdf", pdf_bytes("first")), ("paciente.pdf", pdf_bytes("second"))],
    )
    assert response.status_code in (200, 201, 400, 422), response.text
    result = inventory(client, batch_id)
    assert result["documents"] == []
    if response.status_code in (200, 201):
        assert len(result["rejections"]) == 2


def test_encrypted_pdf_is_rejected_with_inventory_reason(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("synthetic-document-password")
    writer.write(stream)
    response = upload(client, headers, batch_id, "original", [("PACIENTE.pdf", stream.getvalue())])
    assert response.status_code in (200, 201, 400, 422), response.text
    result = inventory(client, batch_id)
    assert result["documents"] == []
    if response.status_code in (200, 201):
        assert result["rejections"]


def test_upload_rejects_unknown_document_side(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    response = upload(client, headers, batch_id, "arbitrary-path", [("PACIENTE.pdf", pdf_bytes())])
    assert response.status_code in (400, 422), response.text
    assert inventory(client, batch_id)["documents"] == []


def test_support_spreadsheet_is_inventoried_not_silently_a_pdf(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    response = upload(
        client, headers, batch_id, "original",
        [("patient/PACIENTE SINTETICO UNO.pdf", pdf_bytes()), ("patient/documentos_faltantes.csv", b"documento,motivo\nreceta,no disponible\n")],
    )
    assert response.status_code in (200, 201), response.text
    result = inventory(client, batch_id)
    assert len(result["documents"]) == 1
    assert result["rejections"], "Non-PDF input must remain visible in the inventory"


def test_known_non_pdf_annex_does_not_make_all_confirmed_pdfs_partial(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    confirmed_pair(client, headers, batch_id)
    response = upload(client, headers, batch_id, "original", [("documentos_faltantes.csv", b"documento,motivo\n")])
    assert response.status_code in (200, 201)
    result = inventory(client, batch_id)
    assert result["rejections"][0]["blocking"] is False
    response = enqueue(client, headers, batch_id)
    assert response.status_code == 202, response.text
    detail = client.get(f"{API}/runs/{response.json()['id']}").json()
    assert detail["partial_scope"] is False


def test_reconfirming_same_pair_is_idempotent(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    original, modified = confirmed_pair(client, headers, batch_id)
    response = client.post(
        f"{API}/batches/{batch_id}/pairs", headers=headers,
        json={"original_id": original["id"], "modified_id": modified["id"], "patient_name": "PACIENTE SINTETICO UNO"},
    )
    assert response.status_code in (200, 201), response.text
    confirmed = [p for p in inventory(client, batch_id)["pairs"] if p["confirmed"]]
    assert len(confirmed) == 1
    assert response.json()["id"] == confirmed[0]["id"]


def test_cross_organization_data_and_downloads_are_isolated(portal):
    with TestClient(portal) as owner, TestClient(portal) as outsider:
        owner_headers = login(owner)
        outsider_headers = login(outsider, "other_test")
        batch_id = create_batch(owner, owner_headers)
        original, modified = confirmed_pair(owner, owner_headers, batch_id)
        run = enqueue(owner, owner_headers, batch_id)
        assert run.status_code == 202
        run_id = run.json()["id"]
        assert outsider.get(f"{API}/batches").json() == []
        assert outsider.get(f"{API}/runs").json() == []
        for path in (
            f"/batches/{batch_id}/inventory",
            f"/documents/{original['id']}/content",
            f"/documents/{modified['id']}/content",
            f"/runs/{run_id}",
            f"/runs/{run_id}/report",
        ):
            response = outsider.get(API + path)
            assert response.status_code in (403, 404), (path, response.text)
        response = enqueue(outsider, outsider_headers, batch_id, key="cross-org-attempt")
        assert response.status_code in (403, 404)
        foreign_batch = create_batch(outsider, outsider_headers)
        response = outsider.post(
            f"{API}/batches/{foreign_batch}/pairs",
            json={"original_id": original["id"], "modified_id": modified["id"], "patient_name": "Unauthorized"},
            headers=outsider_headers,
        )
        assert response.status_code in (403, 404, 422)


def test_auditor_cannot_create_users(client):
    headers = login(client)
    response = client.post(
        f"{API}/users",
        json={"username": "auditor_test", "password": PASSWORD, "role": "auditor"},
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text
    client.post(f"{API}/auth/logout", headers=headers)
    headers = login(client, "auditor_test")
    assert client.get(f"{API}/users").status_code == 403
    response = client.post(
        f"{API}/users",
        json={"username": "not_allowed", "password": PASSWORD, "role": "admin"},
        headers=headers,
    )
    assert response.status_code == 403


def test_roboti_and_ml_are_explicitly_disabled_in_v1(client):
    login(client)
    response = client.get(f"{API}/capabilities")
    assert response.status_code == 200
    capabilities = response.json()
    assert capabilities["roboti"]["enabled"] is False
    assert capabilities["roboti"]["reason"]
    assert capabilities["ml"]["enabled"] is False
    assert capabilities["ml"]["architecture"] == "encoder_decoder"
    assert capabilities["ml"]["threshold"] == 1000
    assert capabilities["ml"]["eligible_for_evaluation"] is False
    assert capabilities["ml"]["reason"]


def test_document_download_requires_session_and_returns_original_pdf(client):
    headers = login(client)
    batch_id = create_batch(client, headers)
    original, _ = confirmed_pair(client, headers, batch_id)
    path = f"{API}/documents/{original['id']}/content"
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content == pdf_bytes()
    client.post(f"{API}/auth/logout", headers=headers)
    assert client.get(path).status_code == 401


def test_human_reviews_are_append_only_and_reference_real_findings(portal, client):
    headers = login(client)
    run_id, case_id, finding = completed_fixture(portal, client, headers)
    path = f"{API}/runs/{run_id}/cases/{case_id}/reviews"
    missing = client.post(path, headers=headers, json={"finding_id": "not-in-this-case", "decision": "confirmed", "comment": "No"})
    assert missing.status_code == 404
    for decision in ("confirmed", "needs_review"):
        response = client.post(path, headers=headers, json={"finding_id": finding["id"], "decision": decision, "comment": "Observacion sintetica"})
        assert response.status_code == 201, response.text
    detail = client.get(f"{API}/runs/{run_id}").json()["cases"][0]
    assert len(detail["reviews"]) == 2
    assert detail["comparison"]["findings"] == [finding], "Human feedback must not overwrite machine evidence"


def test_manual_finding_requires_a_real_page_and_remains_separate(portal, client):
    headers = login(client)
    run_id, case_id, finding = completed_fixture(portal, client, headers)
    path = f"{API}/runs/{run_id}/cases/{case_id}/findings"
    payload = {"description": "Documento adicional sintetico", "before": "", "after": "Texto agregado", "change_type": "added"}
    assert client.post(path, headers=headers, json=payload).status_code == 422
    assert client.post(path, headers=headers, json={**payload, "page_modified": 2}).status_code == 422
    response = client.post(path, headers=headers, json={**payload, "page_modified": 1})
    assert response.status_code == 201, response.text
    detail = client.get(f"{API}/runs/{run_id}").json()["cases"][0]
    assert len(detail["manual_findings"]) == 1
    assert detail["manual_findings"][0]["id"] == response.json()["id"]
    assert detail["comparison"]["findings"] == [finding]


def test_dalia_improvement_keeps_provenance_and_cannot_apply_to_roboti(portal, client):
    headers = login(client)
    run_id, case_id, finding = completed_fixture(portal, client, headers)
    response = client.post(
        f"{API}/improvements", headers=headers,
        json={"run_id": run_id, "case_id": case_id, "finding_id": finding["id"],
              "description": "Revisar seleccion documental", "expected_benefit": "Reducir revisiones manuales"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["applied_to_roboti"] is False
    assert response.json()["status"] == "proposed"
    proposals = client.get(f"{API}/improvements").json()
    assert len(proposals) == 1
    assert proposals[0]["source_system"] == "dalia"
    assert proposals[0]["status"] == "proposed"


def test_worker_expired_lease_reclaims_without_authorizing_old_owner(portal, client):
    from app.worker import claim, owns

    headers = login(client)
    batch_id = create_batch(client, headers)
    confirmed_pair(client, headers, batch_id)
    response = enqueue(client, headers, batch_id)
    run_id = response.json()["id"]
    cfg = portal.state.settings
    first = claim(portal.state.SessionLocal, cfg)
    assert first[0] == run_id
    with portal.state.SessionLocal.begin() as session:
        session.get(models.Run, run_id).lease_until = models.now() - 5
    second = claim(portal.state.SessionLocal, cfg)
    assert second[0] == run_id
    assert second[1] != first[1]
    with portal.state.SessionLocal() as session:
        run = session.get(models.Run, run_id)
        assert not owns(run, first[1])
        assert owns(run, second[1])
        assert run.attempts == 2


def test_worker_exhausted_expired_job_is_failed_not_completed(portal, client):
    from app.worker import claim

    headers = login(client)
    batch_id = create_batch(client, headers)
    confirmed_pair(client, headers, batch_id)
    response = enqueue(client, headers, batch_id)
    run_id = response.json()["id"]
    cfg = portal.state.settings
    with portal.state.SessionLocal.begin() as session:
        run = session.get(models.Run, run_id)
        run.status = "running"
        run.attempts = cfg.max_attempts
        run.lease_until = models.now() - 5
        run.lease_owner = "synthetic-expired-owner"
    assert claim(portal.state.SessionLocal, cfg) is None
    detail = client.get(f"{API}/runs/{run_id}").json()
    assert detail["status"] == "failed"
    assert detail["error"]
    assert detail["report_available"] is False
