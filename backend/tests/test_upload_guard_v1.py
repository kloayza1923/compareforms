"""ASGI-level upload guard tests; no multipart parser or real documents used."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app import db as models
from app.config import Settings
from app.security import digest
from app.upload_guard import MULTIPART_ALLOWANCE, UploadGuardMiddleware


@pytest.fixture()
def guarded(tmp_path: Path):
    cfg = Settings(
        database_url=f"sqlite:///{(tmp_path / 'guard.sqlite').as_posix()}",
        documents_root=tmp_path / "private",
        max_upload_bytes=32,
        testing=True,
        session_secure=False,
    )
    engine, factory = models.connect(cfg)
    models.Base.metadata.create_all(engine)
    with factory.begin() as session:
        organization = models.Organization(name="Synthetic organization")
        session.add(organization)
        session.flush()
        user = models.User(
            organization_id=organization.id, username="synthetic", role="auditor",
            password_hash="unused-no-login-in-this-test",
        )
        session.add(user)
        session.flush()
        session.add(models.Session(
            token_hash=digest("synthetic-session-token"), user_id=user.id,
            csrf="synthetic-csrf-token", expires=models.now() + 600,
        ))

    captured = {"calls": 0, "body": b""}

    async def downstream(scope, receive, send):
        captured["calls"] += 1
        while True:
            message = await receive()
            assert message["type"] == "http.request"
            captured["body"] += message.get("body", b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guard = UploadGuardMiddleware(downstream, settings=cfg, session_factory=factory)
    yield guard, cfg, captured
    engine.dispose()


def invoke(guard, *, body_chunks=(b"abc",), authenticated=True, csrf=True, content_length=None,
           path="/api/v1/batches/synthetic-batch/uploads", extra_headers=(), disconnect=False):
    headers = [(b"host", b"testserver")]
    if authenticated:
        headers.append((b"cookie", b"compareforms_session=synthetic-session-token"))
    if csrf:
        headers.append((b"x-csrf-token", b"synthetic-csrf-token"))
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    headers.extend(extra_headers)
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"side=original", "root_path": "",
        "headers": headers, "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
    }
    received = {"calls": 0}
    events = []
    for index, chunk in enumerate(body_chunks):
        events.append({"type": "http.request", "body": chunk, "more_body": index < len(body_chunks)-1 or disconnect})
    if disconnect:
        events.append({"type": "http.disconnect"})
    sent = []

    async def receive():
        received["calls"] += 1
        return events.pop(0) if events else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(guard(scope, receive, send))
    status = next((message["status"] for message in sent if message["type"] == "http.response.start"), None)
    payload = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, payload, received


def no_staging_files(cfg):
    return not cfg.documents_root.exists() or not any(p.is_file() for p in cfg.documents_root.rglob("*"))


def test_no_session_rejected_before_any_body_read(guarded):
    guard, cfg, captured = guarded
    status, payload, received = invoke(guard, authenticated=False)
    assert status == 401
    assert json.loads(payload)["detail"]
    assert received["calls"] == captured["calls"] == 0
    assert not cfg.documents_root.exists()


def test_missing_csrf_rejected_before_any_body_read(guarded):
    guard, cfg, captured = guarded
    status, _, received = invoke(guard, csrf=False)
    assert status == 403
    assert received["calls"] == captured["calls"] == 0
    assert not cfg.documents_root.exists()


def test_content_length_excess_rejected_without_reading_or_spooling(guarded):
    guard, cfg, captured = guarded
    status, _, received = invoke(guard, content_length=cfg.max_upload_bytes + MULTIPART_ALLOWANCE + 1)
    assert status == 413
    assert received["calls"] == captured["calls"] == 0
    assert not cfg.documents_root.exists()


def test_chunked_excess_never_invokes_partial_multipart_parser(guarded):
    guard, cfg, captured = guarded
    status, _, received = invoke(
        guard, body_chunks=(b"a" * MULTIPART_ALLOWANCE, b"b" * 33),
        extra_headers=[(b"transfer-encoding", b"chunked")],
    )
    assert status == 413
    assert received["calls"] == 2
    assert captured == {"calls": 0, "body": b""}
    assert no_staging_files(cfg)


def test_complete_body_is_replayed_exactly_and_private_spool_removed(guarded):
    guard, cfg, captured = guarded
    body = (b"first chunk", b"second chunk")
    status, _, received = invoke(guard, body_chunks=body, content_length=sum(map(len, body)))
    assert status == 200
    assert captured == {"calls": 1, "body": b"".join(body)}
    assert received["calls"] == 2
    assert no_staging_files(cfg)


def test_body_at_allowed_boundary_is_accepted(guarded):
    guard, cfg, captured = guarded
    body = b"a" * (cfg.max_upload_bytes + MULTIPART_ALLOWANCE)
    status, _, _ = invoke(guard, body_chunks=(body,), content_length=len(body))
    assert status == 200
    assert captured["body"] == body
    assert no_staging_files(cfg)


def test_disconnect_discards_incomplete_body_without_downstream(guarded):
    guard, cfg, captured = guarded
    status, _, _ = invoke(guard, body_chunks=(b"incomplete",), disconnect=True)
    assert status is None
    assert captured["calls"] == 0
    assert no_staging_files(cfg)


@pytest.mark.parametrize("length", ["-1", "abc", "1, 2"])
def test_invalid_content_length_rejected_before_body(guarded, length):
    guard, cfg, captured = guarded
    status, _, received = invoke(guard, content_length=length)
    assert status == 400
    assert received["calls"] == captured["calls"] == 0
    assert not cfg.documents_root.exists()


def test_declared_size_mismatch_does_not_reach_parser(guarded):
    guard, cfg, captured = guarded
    status, _, _ = invoke(guard, content_length=10, body_chunks=(b"abc",))
    assert status == 400
    assert captured["calls"] == 0
    assert no_staging_files(cfg)


def test_other_routes_passthrough_without_auth_or_spooling(guarded):
    guard, cfg, captured = guarded
    status, _, _ = invoke(guard, authenticated=False, csrf=False, path="/api/v1/auth/login")
    assert status == 200
    assert captured["calls"] == 1
    assert not cfg.documents_root.exists()
