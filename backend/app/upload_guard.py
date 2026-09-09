"""Authenticate and bound upload bodies before FastAPI parses multipart data.

Only complete, size-checked bodies are replayed to the application. Buffering
uses a private temporary file, never an in-memory copy of the complete ZIP.
The file is removed on success, rejection, disconnect and downstream errors.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from anyio import CancelScope
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .security import identity


MULTIPART_ALLOWANCE = 1024 * 1024
REPLAY_CHUNK_SIZE = 64 * 1024
UPLOAD_PATH = re.compile(r"^/api/v1/batches/[^/]+/uploads/?$")


class UploadGuardMiddleware:
    """Pure ASGI guard for the ZIP intake endpoint (``side`` is a query arg).

    ``session_factory`` is the same SQLAlchemy factory used by the application.
    The route still authorizes the batch and validates its state after this
    guard; authentication here is intentionally repeated before body parsing.
    """

    def __init__(self, app: ASGIApp, *, settings, session_factory):
        self.app = app
        self.settings = settings
        self.session_factory = session_factory
        self.max_body_bytes = settings.max_upload_bytes + MULTIPART_ALLOWANCE

    def _authenticate(self, scope: Scope) -> None:
        # SQLAlchemy/Argon operations never run on the ASGI event loop.
        with self.session_factory() as session:
            identity(Request(scope), session, mutate=True)

    def _open_spool(self):
        root = Path(self.settings.documents_root).resolve()
        staging = (root / ".upload-staging").resolve()
        if staging == root or not staging.is_relative_to(root):
            raise ValueError("Directorio temporal fuera del almacenamiento privado")
        staging.mkdir(parents=True, mode=0o700, exist_ok=True)
        # UUIDs/filenames from requests cannot influence this path. tempfile
        # creates the file exclusively, with private permissions, and deletes it.
        return tempfile.TemporaryFile(mode="w+b", dir=staging, prefix="request-")

    @staticmethod
    async def _reject(scope, receive, send, status: int, detail: str):
        await JSONResponse(
            {"detail": detail}, status_code=status,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope.get("method") != "POST" or not UPLOAD_PATH.fullmatch(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        try:
            await run_in_threadpool(self._authenticate, scope)
        except HTTPException as exc:
            await self._reject(scope, receive, send, exc.status_code, exc.detail)
            return

        headers = Headers(scope=scope)
        lengths = headers.getlist("content-length")
        declared_length = None
        if lengths:
            # Reject ambiguous framing; do not guess which duplicate is trusted.
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]) or headers.get("transfer-encoding"):
                await self._reject(scope, receive, send, 400, "Longitud de carga inválida.")
                return
            try:
                declared_length = int(lengths[0])
            except ValueError:  # Includes the interpreter's integer-digit cap.
                await self._reject(scope, receive, send, 400, "Longitud de carga inválida.")
                return
            if declared_length > self.max_body_bytes:
                await self._reject(scope, receive, send, 413, "La carga supera el límite permitido.")
                return

        try:
            spool = await run_in_threadpool(self._open_spool)
        except (OSError, ValueError):
            await self._reject(scope, receive, send, 503, "El almacenamiento temporal no está disponible.")
            return

        try:
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    await self._reject(scope, receive, send, 400, "Flujo de carga inválido.")
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.max_body_bytes:
                    # The multipart parser has not run and cannot have accepted
                    # a valid prefix of this rejected upload.
                    await self._reject(scope, receive, send, 413, "La carga supera el límite permitido.")
                    return
                if chunk:
                    await run_in_threadpool(spool.write, chunk)
                if not message.get("more_body", False):
                    break
            if declared_length is not None and declared_length != total:
                await self._reject(scope, receive, send, 400, "La carga está incompleta o su longitud no coincide.")
                return

            await run_in_threadpool(spool.seek, 0)
            remaining = total
            final_sent = False

            async def replay() -> dict:
                nonlocal remaining, final_sent
                if not final_sent:
                    chunk = await run_in_threadpool(spool.read, min(REPLAY_CHUNK_SIZE, remaining))
                    remaining -= len(chunk)
                    final_sent = remaining == 0
                    return {"type": "http.request", "body": chunk, "more_body": not final_sent}
                # Preserve disconnect semantics if the downstream application
                # keeps listening after the final body event.
                return await receive()

            await self.app(scope, replay, send)
        finally:
            # A disconnected/cancelled request must still release its disk file.
            with CancelScope(shield=True):
                await run_in_threadpool(spool.close)
