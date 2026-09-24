"""Import checks use temporary SQLite, a fake identity provider, and synthetic PDFs only."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfWriter
from sqlalchemy import func, select

from app import db as models
from test_aitrol_identity import client, portal
from test_roboti_proxy import setup


URL = "/api/v1/roboti/origin"
FIELDS = {"source_batch_id": "synthetic-roboti-batch-072024",
          "period": "2024_07", "name": "Revision sintetica",
          "expected_pdf_count": "1"}
PDF_NAME = "PACIENTE SINTETICO UNO.pdf"


def pdf_bytes():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    return output.getvalue()


def source_zip(entries=None):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, payload in entries or [(PDF_NAME, pdf_bytes())]:
            archive.writestr(name, payload)
    return output.getvalue()


def import_source(client, headers, *, entries=None, fields=None):
    return client.post(
        URL, data=fields or FIELDS,
        files={"file": ("synthetic-origin.zip", source_zip(entries), "application/zip")},
        headers=headers,
    )


def batch_id(response):
    payload = response.json()
    return payload.get("id") or payload.get("batch", {}).get("id")


def test_origin_requires_trusted_proxy_and_live_company_membership(portal, client):
    good = setup(portal)
    assert import_source(client, {}).status_code in {401, 403}
    assert import_source(client, {**good, "X-Roboti-Proxy-Token": "forged"}).status_code == 401
    assert import_source(client, {**good, "X-Roboti-Company": "forbidden"}).status_code == 403
    with portal.state.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Batch)) == 0


def test_origin_import_is_reusable_and_allows_existing_review_flow(portal, client):
    trusted = setup(portal)
    first = import_source(client, trusted)
    assert first.status_code in {200, 201}, first.text
    review_id = batch_id(first)
    assert review_id
    second = import_source(client, trusted)
    assert second.status_code in {200, 201}, second.text
    assert batch_id(second) == review_id

    listed = client.get("/api/v1/batches", headers=trusted)
    assert listed.status_code == 200
    review = next(batch for batch in listed.json() if batch["id"] == review_id)
    assert review["period"] == "2024_07"
    assert review["source_mode"] == review["source_system"] == "roboti"
    inventory = client.get(f"/api/v1/batches/{review_id}/inventory", headers=trusted)
    assert inventory.status_code == 200
    originals = [doc for doc in inventory.json()["documents"] if doc["side"] == "original"]
    assert len(originals) == 1
    assert originals[0]["original_name"] == PDF_NAME

    original_upload = client.post(
        f"/api/v1/batches/{review_id}/uploads", params={"side": "original"},
        files={"file": ("synthetic.zip", source_zip(), "application/zip")}, headers=trusted,
    )
    assert original_upload.status_code == 409
    modified_upload = client.post(
        f"/api/v1/batches/{review_id}/uploads", params={"side": "modified"},
        files={"file": ("synthetic.zip", source_zip(), "application/zip")}, headers=trusted,
    )
    assert modified_upload.status_code == 200, modified_upload.text
    modified = next(doc for doc in modified_upload.json()["documents"] if doc["side"] == "modified")
    pair = client.post(
        f"/api/v1/batches/{review_id}/pairs",
        json={"original_id": originals[0]["id"], "modified_id": modified["id"],
              "patient_name": "PACIENTE SINTETICO UNO"}, headers=trusted,
    )
    assert pair.status_code == 201, pair.text
    run = client.post(
        f"/api/v1/batches/{review_id}/runs", json={"allow_partial": False},
        headers={**trusted, "Idempotency-Key": "synthetic-review-run"},
    )
    assert run.status_code == 202, run.text


def test_origin_rejects_duplicate_pdf_content_without_partial_import(portal, client):
    trusted = setup(portal)
    duplicate = pdf_bytes()
    response = import_source(
        client, trusted,
        entries=[("ONE.pdf", duplicate), ("TWO.pdf", duplicate)],
        fields={**FIELDS, "expected_pdf_count": "2", "source_batch_id": "duplicate-pdfs"},
    )
    assert response.status_code == 422, response.text
    with portal.state.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Batch)) == 0
        assert db.scalar(select(func.count()).select_from(models.Document)) == 0
