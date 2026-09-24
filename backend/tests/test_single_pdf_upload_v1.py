from test_portal_v1 import API, create_batch, enqueue, inventory, login, pdf_bytes, portal, client, upload

def direct(client, headers, batch, side, name, content):
    return client.post(f"{API}/batches/{batch}/uploads", params={"side": side},
                       files={"file": (name, content, "application/pdf")}, headers=headers)

def test_two_pdf_flow(client):
    headers = login(client)
    batch = create_batch(client, headers)
    assert direct(client, headers, batch, "original", "PACIENTE PRUEBA.pdf", pdf_bytes("origin")).status_code == 200
    assert not inventory(client, batch)["can_run"]
    assert direct(client, headers, batch, "modified", "PACIENTE PRUEBA - PROCESO AUTOMATICO.pdf", pdf_bytes("modified")).status_code == 200
    before = inventory(client, batch)
    assert len(before["documents"]) == 2 and not before["can_run"]
    docs = {item["side"]: item for item in before["documents"]}
    result = client.post(f"{API}/batches/{batch}/pairs", json={"original_id": docs["original"]["id"],
                         "modified_id": docs["modified"]["id"], "patient_name": "PACIENTE PRUEBA"}, headers=headers)
    assert result.status_code == 201, result.text
    ready = inventory(client, batch)
    assert ready["can_run"] and len([p for p in ready["pairs"] if p["confirmed"]]) == 1
    assert enqueue(client, headers, batch).status_code == 202

def test_rejections_and_zip_regression(client, portal):
    headers = login(client)
    batch = create_batch(client, headers)
    assert direct(client, headers, batch, "original", "bad.pdf", b"not pdf").status_code == 422
    assert direct(client, headers, batch, "original", "bad.txt", pdf_bytes()).status_code == 422
    assert inventory(client, batch)["documents"] == []
    assert upload(client, headers, batch, "original", [("PACIENTE PRUEBA.pdf", pdf_bytes("origin"))]).status_code == 200
    assert direct(client, headers, batch, "modified", "PACIENTE PRUEBA modificado.pdf", pdf_bytes("modified")).status_code == 200
    assert len(inventory(client, batch)["documents"]) == 2

def test_oversize_pdf_rejected(client, portal):
    headers = login(client)
    batch = create_batch(client, headers)
    object.__setattr__(portal.state.settings, "max_pdf_bytes", 128)
    assert direct(client, headers, batch, "original", "large.pdf", pdf_bytes()).status_code == 422
    assert inventory(client, batch)["documents"] == []
