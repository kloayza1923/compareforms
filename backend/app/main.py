from __future__ import annotations
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete, text
from sqlalchemy.exc import IntegrityError
from .config import Settings
from . import db as m
from .security import identity, public_user, password_hash, verify, digest, throttle
from .storage import ingest_zip, private_path, name_key
from .upload_guard import UploadGuardMiddleware
from .aitrol_identity import AitrolIdentityProvider, IdentityUnavailable, membership

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    company_id: str | None = Field(default=None, min_length=1, max_length=100)
class BatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    period: str = Field(pattern=r"^20\d{2}_(0[1-9]|1[0-2])$")
    source_mode: Literal["manual", "roboti"] = "manual"
    source_system: Literal["dalia", "manual_otro", "roboti"] = "dalia"
class PairIn(BaseModel):
    original_id: str
    modified_id: str
    patient_name: str = Field(min_length=1, max_length=300)
class RunIn(BaseModel): allow_partial: bool = False
class UserIn(LoginIn):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "auditor", "supervisor"] = "auditor"
class ReviewIn(BaseModel):
    finding_id: str = Field(min_length=1, max_length=100)
    decision: Literal["confirmed", "false_positive", "needs_review"]
    comment: str = Field(default="", max_length=6000)
class ManualIn(BaseModel):
    description: str = Field(min_length=1, max_length=6000)
    before: str = Field(default="", max_length=12000)
    after: str = Field(default="", max_length=12000)
    page_original: int | None = Field(default=None, ge=1)
    page_modified: int | None = Field(default=None, ge=1)
    change_type: Literal["added", "removed", "modified", "relocated", "review"]
class ImprovementIn(BaseModel):
    run_id: str
    case_id: str
    finding_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=6000)
    expected_benefit: str = Field(min_length=1, max_length=6000)

def batch_out(b):
    return {k: getattr(b, k) for k in ("id", "name", "period", "status", "source_mode", "source_system", "created_at")}
def doc_out(d):
    return {k: getattr(d, k) for k in ("id", "side", "original_name", "patient_name")}
def case_out(c):
    return {k: getattr(c, k) for k in ("id", "patient_name", "original_id", "modified_id", "status", "comparison")}

def inventory(db, batch):
    documents = db.scalars(select(m.Document).where(m.Document.batch_id == batch.id)).all()
    pairs = db.scalars(select(m.Pair).where(m.Pair.batch_id == batch.id)).all()
    paired = {p.original_id for p in pairs} | {p.modified_id for p in pairs}
    result = [{"id": p.id, "patient_name": p.patient_name, "original_id": p.original_id, "modified_id": p.modified_id, "confirmed": True} for p in pairs]
    groups = defaultdict(lambda: defaultdict(list))
    for d in documents:
        if d.id not in paired: groups[name_key(d.patient_name + ".pdf")][d.side].append(d)
    for sides in groups.values():
        if len(sides["original"]) == 1 and len(sides["modified"]) == 1:
            a, b = sides["original"][0], sides["modified"][0]
            result.append({"id": "suggestion-" + a.id, "patient_name": a.patient_name, "original_id": a.id, "modified_id": b.id, "confirmed": False})
    return {"documents": [doc_out(d) for d in documents], "pairs": result, "unpaired": [doc_out(d) for d in documents if d.id not in paired], "rejections": batch.rejections, "can_run": bool(pairs)}

def create_app(settings: Settings | None = None):
    cfg = settings or Settings()
    engine, SessionLocal = m.connect(cfg)
    app = FastAPI(title="CompareForms", version="0.2.0")
    app.state.engine, app.state.SessionLocal, app.state.settings = engine, SessionLocal, cfg
    app.state.identity_provider = AitrolIdentityProvider(cfg) if cfg.auth_provider == "aitrol" else None
    app.add_middleware(UploadGuardMiddleware, settings=cfg, session_factory=SessionLocal)
    prefix = "/api/v1"

    def batch_for(db, user, batch_id):
        b = db.get(m.Batch, batch_id)
        if not b or b.organization_id != user.organization_id: raise HTTPException(404, "Revisión no encontrada.")
        return b
    def run_for(db, user, run_id):
        r = db.get(m.Run, run_id)
        if not r: raise HTTPException(404, "Ejecución no encontrada.")
        batch_for(db, user, r.batch_id)
        return r
    def case_for(db, user, run_id, case_id):
        run_for(db, user, run_id)
        c = db.get(m.RunCase, case_id)
        if not c or c.run_id != run_id: raise HTTPException(404, "Expediente no encontrado.")
        return c
    def finding_exists(db, c, finding_id):
        ids = {str(f["id"]) for f in (c.comparison or {}).get("findings", [])}
        manual = db.get(m.ManualFinding, finding_id)
        if finding_id not in ids and not (manual and manual.case_id == c.id):
            raise HTTPException(404, "Hallazgo no encontrado en este expediente.")

    @app.middleware("http")
    async def security_headers(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            allowed = urlsplit(str(request.base_url))
            incoming = urlsplit(origin)
            if (incoming.scheme, incoming.netloc) != (allowed.scheme, allowed.netloc):
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=403, content={"detail": "Origen de solicitud no permitido."})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'self'; frame-ancestors 'self'; base-uri 'self'; object-src 'none'"
        if request.url.path.startswith(prefix): response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={"detail": "La operación ya existe o entra en conflicto. Actualice la página."})

    @app.get(prefix + "/health")
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT id,auth_provider,external_user_id,external_email,organization_id FROM users LIMIT 0"))
                connection.execute(text("SELECT external_company_id FROM organizations LIMIT 0"))
        except Exception: raise HTTPException(503, "Base de datos no lista. Verifique la migración.")
        return {"status": "ready", "version": "0.2.0"}

    @app.get(prefix + "/auth/config")
    def auth_config():
        return {"provider": cfg.auth_provider, "password_management": cfg.auth_provider}

    @app.post(prefix + "/auth/login")
    def login(data: LoginIn, request: Request, response: Response):
        with SessionLocal() as db:
            username = data.username.strip().casefold()
            throttle(db, username, request.client.host if request.client else "unknown")
            if cfg.auth_provider == "aitrol":
                try: actor = app.state.identity_provider.authenticate(username, data.password)
                except IdentityUnavailable:
                    raise HTTPException(503, "No se pudo verificar el acceso en Aitrol. Intente nuevamente.") from None
                if actor is None: raise HTTPException(401, "Usuario o contraseña incorrectos.")
                if not actor.companies: raise HTTPException(403, "No tiene empresas activas autorizadas en Aitrol.")
                if data.company_id is None and len(actor.companies) > 1:
                    return {"requires_company": True, "companies": list(actor.companies)}
                company_id = data.company_id or actor.companies[0]["id"]
                user = membership(db, actor, company_id)
            else:
                user = db.scalar(select(m.User).where(m.User.username == username, m.User.active == True, m.User.auth_provider == "local"))
                if not user or not verify(data.password, user.password_hash): raise HTTPException(401, "Usuario o contraseña incorrectos.")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.add(m.Session(token_hash=digest(token), user_id=user.id, csrf=csrf, expires=m.now()+3600*cfg.session_hours))
            db.execute(delete(m.LoginAttempt).where(m.LoginAttempt.key == digest(username)))
            m.event(db, user, "login", user.id); db.commit()
            response.set_cookie("compareforms_session", token, httponly=True, secure=cfg.session_secure, samesite="strict", max_age=3600*cfg.session_hours, path="/")
            return {"user": public_user(user), "csrf_token": csrf}

    @app.get(prefix + "/auth/me")
    def me(request: Request):
        with SessionLocal() as db:
            user, session = identity(request, db)
            return {"user": public_user(user), "csrf_token": session.csrf}

    @app.post(prefix + "/auth/logout")
    def logout(request: Request, response: Response):
        with SessionLocal() as db:
            # Revocation must work even if Aitrol is offline or the user lost access.
            token = request.cookies.get("compareforms_session", "")
            session = db.get(m.Session, digest(token)) if token else None
            if session:
                if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf):
                    raise HTTPException(403, "La sesión de seguridad cambió. Actualice la página.")
                user = db.get(m.User, session.user_id)
                db.delete(session); m.event(db, user, "logout", session.user_id); db.commit()
        response.delete_cookie("compareforms_session", path="/")
        return {"status": "logged_out"}

    @app.get(prefix + "/users")
    def users(request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db)
            if user.role != "admin": raise HTTPException(403, "Requiere administrador.")
            return [public_user(u) for u in db.scalars(select(m.User).where(m.User.organization_id == user.organization_id))]

    @app.post(prefix + "/users", status_code=201)
    def add_user(data: UserIn, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True)
            if cfg.auth_provider == "aitrol": raise HTTPException(403, "Usuarios y contraseñas se administran en Aitrol.")
            if user.role != "admin": raise HTTPException(403, "Requiere administrador.")
            try: hashed = password_hash(data.password)
            except ValueError as e: raise HTTPException(422, str(e))
            created = m.User(username=data.username.strip().casefold(), password_hash=hashed, role=data.role, organization_id=user.organization_id)
            db.add(created); db.flush(); m.event(db, user, "create_user", created.id); db.commit()
            return public_user(created)

    @app.get(prefix + "/capabilities")
    def capabilities(request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db)
            count = db.scalar(select(func.count(func.distinct(m.Document.sha256))).join(m.Batch).where(m.Batch.organization_id == user.organization_id))
            return {"roboti": {"enabled": False, "reason": "Pendiente contrato M2M autorizado para buscar, generar y descargar. Use carga manual."}, "ml": {"enabled": False, "architecture": "encoder_decoder", "unique_pdf_count": count, "threshold": 1000, "eligible_for_evaluation": count > 1000, "reason": "Sin modelo entrenado. Superar 1000 PDF únicos permite evaluar el corpus; requiere etiquetas adjudicadas y aprobación."}}

    @app.get(prefix + "/batches")
    def batches(request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db)
            return [batch_out(b) for b in db.scalars(select(m.Batch).where(m.Batch.organization_id == user.organization_id).order_by(m.Batch.created_at.desc()))]

    @app.post(prefix + "/batches", status_code=201)
    def add_batch(data: BatchIn, request: Request):
        if data.source_mode == "manual" and data.source_system == "roboti": raise HTTPException(422, "Seleccione DALIA u otro origen manual.")
        if data.source_mode == "roboti" and data.source_system != "roboti": raise HTTPException(422, "Procedencia incoherente con modo Roboti.")
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True)
            b = m.Batch(**data.model_dump(), organization_id=user.organization_id, creator_id=user.id)
            db.add(b); db.flush(); m.event(db, user, "create_batch", b.id); db.commit()
            return batch_out(b)

    @app.get(prefix + "/batches/{batch_id}/inventory")
    def get_inventory(batch_id: str, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db)
            return inventory(db, batch_for(db, user, batch_id))

    @app.post(prefix + "/batches/{batch_id}/uploads")
    def upload(batch_id: str, request: Request, side: Literal["original", "modified"], file: UploadFile = File(...)):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True)
            b = batch_for(db, user, batch_id)
            if side == "original" and b.source_mode != "manual": raise HTTPException(409, "Active carga manual para subir el origen.")
            # Intake stored under UUID; never source ZIP filenames as paths.
            folder = private_path(cfg.documents_root, f"{b.period}/batches/{b.id}/uploads/{m.uid()}")
            try: docs, rejections = ingest_zip(file.file, folder, cfg)
            except ValueError as e: raise HTTPException(422, str(e))
            existing = set(db.scalars(select(m.Document.sha256).where(m.Document.batch_id == b.id, m.Document.side == side)))
            for d in docs:
                if d["sha256"] in existing:
                    rejections.append({"name": d["original_name"], "reason": "PDF duplicado del mismo lado; no se cuenta de nuevo"}); continue
                existing.add(d["sha256"])
                path = d.pop("path")
                db.add(m.Document(batch_id=b.id, side=side, storage_key=str(path.relative_to(cfg.documents_root.resolve())), **d))
            b.rejections = [*b.rejections, *rejections]
            m.event(db, user, "upload_" + side, b.id); db.commit()
            return inventory(db, b)

    @app.post(prefix + "/batches/{batch_id}/pairs", status_code=201)
    def confirm_pair(batch_id: str, data: PairIn, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True); b = batch_for(db, user, batch_id)
            a, z = db.get(m.Document, data.original_id), db.get(m.Document, data.modified_id)
            if not a or not z or a.batch_id != b.id or z.batch_id != b.id or a.side != "original" or z.side != "modified":
                raise HTTPException(422, "Seleccione un original y un modificado de esta revisión.")
            existing = db.scalar(select(m.Pair).where(m.Pair.batch_id == b.id, m.Pair.original_id == a.id, m.Pair.modified_id == z.id))
            if existing: return {"id": existing.id, "confirmed": True}
            p = m.Pair(batch_id=b.id, confirmed_by=user.id, **data.model_dump())
            db.add(p); db.flush(); m.event(db, user, "confirm_pair", p.id); db.commit()
            return {"id": p.id, "confirmed": True}

    @app.delete(prefix + "/batches/{batch_id}/pairs/{pair_id}")
    def remove_pair(batch_id: str, pair_id: str, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True); batch_for(db, user, batch_id)
            pair = db.get(m.Pair, pair_id)
            if not pair or pair.batch_id != batch_id: raise HTTPException(404, "Asociación no encontrada.")
            db.delete(pair); m.event(db, user, "remove_pair", pair_id); db.commit()
            return {"status": "removed"}

    @app.post(prefix + "/batches/{batch_id}/runs", status_code=202)
    def start_run(batch_id: str, data: RunIn, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True); b = batch_for(db, user, batch_id)
            key = request.headers.get("Idempotency-Key", "")
            if not key or len(key) > 128: raise HTTPException(422, "Falta Idempotency-Key válida.")
            payload_hash = digest(json.dumps(data.model_dump(), sort_keys=True))
            existing = db.scalar(select(m.Run).where(m.Run.batch_id == b.id, m.Run.idempotency_key == key))
            if existing:
                if existing.payload_hash != payload_hash: raise HTTPException(409, "Clave reutilizada con parámetros diferentes.")
                return {"id": existing.id, "status": existing.status}
            if b.source_mode == "roboti": raise HTTPException(409, "Generación Roboti no disponible aún. Cree una revisión manual.")
            inv = inventory(db, b)
            confirmed = [p for p in inv["pairs"] if p["confirmed"]]
            if not confirmed: raise HTTPException(422, "NO_COMPARABLE_PAIRS: confirme al menos una pareja de PDF.")
            partial = bool(inv["unpaired"]) or any(r.get("blocking", True) for r in inv["rejections"])
            if partial and not data.allow_partial: raise HTTPException(422, "Hay documentos sin comparar/rechazados. Acepte expresamente el alcance parcial.")
            run = m.Run(batch_id=b.id, creator_id=user.id, idempotency_key=key, payload_hash=payload_hash, total=len(confirmed), partial_scope=partial)
            db.add(run); db.flush()
            for pair in confirmed:
                db.add(m.RunCase(run_id=run.id, patient_name=pair["patient_name"], original_id=pair["original_id"], modified_id=pair["modified_id"]))
            m.event(db, user, "enqueue_run", run.id); db.commit()
            return {"id": run.id, "status": run.status}

    @app.get(prefix + "/runs")
    def runs(request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db)
            return [{"id": r.id, "batch_id": r.batch_id, "status": r.status, "completed": r.completed, "total": r.total, "created_at": r.created_at, "report_available": bool(r.report_key)} for r in db.scalars(select(m.Run).join(m.Batch).where(m.Batch.organization_id == user.organization_id).order_by(m.Run.created_at.desc()))]

    @app.get(prefix + "/runs/{run_id}")
    def get_run(run_id: str, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db); r = run_for(db, user, run_id)
            cases = db.scalars(select(m.RunCase).where(m.RunCase.run_id == r.id)).all()
            values = []
            for c in cases:
                value = case_out(c)
                value["manual_findings"] = [{"id": f.id, **f.data} for f in db.scalars(select(m.ManualFinding).where(m.ManualFinding.case_id == c.id))]
                value["reviews"] = [{"id": v.id, "finding_id": v.finding_id, "decision": v.decision, "comment": v.comment} for v in db.scalars(select(m.Review).where(m.Review.case_id == c.id).order_by(m.Review.created_at))]
                values.append(value)
            return {"id": r.id, "batch_id": r.batch_id, "status": r.status, "completed": r.completed, "total": r.total, "error": r.error, "report_available": bool(r.report_key), "partial_scope": r.partial_scope, "cases": values}

    @app.post(prefix + "/runs/{run_id}/cancel")
    def cancel(run_id: str, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True); r = run_for(db, user, run_id)
            if r.status not in ("queued", "running"): raise HTTPException(409, "La ejecución ya terminó.")
            r.status = "cancelled"; r.lease_owner = None
            m.event(db, user, "cancel_run", r.id); db.commit()
            return {"id": r.id, "status": r.status}

    @app.get(prefix + "/documents/{document_id}/content")
    def document(document_id: str, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db); d = db.get(m.Document, document_id)
            if not d: raise HTTPException(404, "Documento no encontrado.")
            batch_for(db, user, d.batch_id)
            path = private_path(cfg.documents_root, d.storage_key)
            if not path.is_file(): raise HTTPException(404, "Archivo no disponible. Contacte al administrador.")
            m.event(db, user, "view_pdf", d.id); db.commit()
            return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline", "Content-Security-Policy": "sandbox"})

    @app.get(prefix + "/runs/{run_id}/report")
    def report(run_id: str, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db); r = run_for(db, user, run_id)
            if not r.report_key: raise HTTPException(409, "El Excel aún no está disponible.")
            path = private_path(cfg.documents_root, r.report_key)
            if not path.is_file(): raise HTTPException(404, "Reporte no disponible.")
            m.event(db, user, "download_excel", r.id); db.commit()
            return FileResponse(path, filename=f"comparativo_{r.id}.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get(prefix + "/runs/{run_id}/cases/{case_id}/findings/{finding_id}/evidence")
    def evidence(run_id: str, case_id: str, finding_id: str, request: Request, side: Literal["original", "modified"]):
        from .evidence import render_evidence
        with SessionLocal() as db:
            user, _ = identity(request, db)
            case = case_for(db, user, run_id, case_id)
            finding = next((f for f in (case.comparison or {}).get("findings", []) if str(f["id"]) == finding_id), None)
            if finding is None:
                manual = db.get(m.ManualFinding, finding_id)
                if manual and manual.case_id == case.id:
                    finding = manual.data
            if finding is None: raise HTTPException(404, "Observación no encontrada")
            number = finding.get("page_" + side)
            if not number: raise HTTPException(404, "Esta observación no tiene página en esta versión")
            document = db.get(m.Document, case.original_id if side == "original" else case.modified_id)
            if not document or document.batch_id != db.get(m.Run, case.run_id).batch_id: raise HTTPException(404, "Documento no encontrado")
            path = private_path(cfg.documents_root, document.storage_key)
            if not path.is_file(): raise HTTPException(404, "Archivo no disponible")
            content = finding.get("before" if side == "original" else "after", "")
        try:
            return render_evidence(path, int(number), content, ocr_enabled=cfg.ocr_enabled)
        except (ValueError, RuntimeError):
            raise HTTPException(422, "No se pudo mostrar esta página. Abre el PDF para consultarla.") from None

    @app.post(prefix + "/runs/{run_id}/cases/{case_id}/reviews", status_code=201)
    def review(run_id: str, case_id: str, data: ReviewIn, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True); c = case_for(db, user, run_id, case_id)
            finding_exists(db, c, data.finding_id)
            v = m.Review(case_id=c.id, user_id=user.id, **data.model_dump()); db.add(v); db.flush()
            m.event(db, user, "review_finding", v.id); db.commit()
            return {"id": v.id, "status": "recorded"}

    @app.post(prefix + "/runs/{run_id}/cases/{case_id}/findings", status_code=201)
    def add_finding(run_id: str, case_id: str, data: ManualIn, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True); c = case_for(db, user, run_id, case_id)
            if not c.comparison: raise HTTPException(409, "Espere el resultado del expediente.")
            for field, pages in (("page_original", "pages_original"), ("page_modified", "pages_modified")):
                value = getattr(data, field)
                if value and value > c.comparison[pages]: raise HTTPException(422, "Página fuera del documento.")
            if not data.page_original and not data.page_modified: raise HTTPException(422, "Indique al menos una página de evidencia.")
            f = m.ManualFinding(case_id=c.id, user_id=user.id, data=data.model_dump()); db.add(f); db.flush()
            m.event(db, user, "manual_finding", f.id); db.commit()
            return {"id": f.id}

    @app.get(prefix + "/improvements")
    def improvements(request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db)
            return [{**{k: getattr(p, k) for k in ("id", "case_id", "finding_id", "description", "expected_benefit", "source_system", "status", "created_at")}, "run_id": c.run_id} for p, c in db.execute(select(m.Improvement, m.RunCase).join(m.RunCase, m.RunCase.id == m.Improvement.case_id).where(m.Improvement.organization_id == user.organization_id).order_by(m.Improvement.created_at.desc()))]

    @app.post(prefix + "/improvements", status_code=201)
    def propose(data: ImprovementIn, request: Request):
        with SessionLocal() as db:
            user, _ = identity(request, db, mutate=True); c = case_for(db, user, data.run_id, data.case_id)
            finding_exists(db, c, data.finding_id)
            r = run_for(db, user, data.run_id); b = batch_for(db, user, r.batch_id)
            p = m.Improvement(organization_id=user.organization_id, case_id=c.id, user_id=user.id, finding_id=data.finding_id, description=data.description, expected_benefit=data.expected_benefit, source_system=b.source_system)
            db.add(p); db.flush(); m.event(db, user, "propose_improvement", p.id); db.commit()
            return {"id": p.id, "status": "proposed", "applied_to_roboti": False}

    if cfg.frontend_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=cfg.frontend_dist / "assets"), name="assets")
        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"): raise HTTPException(404)
            return FileResponse(cfg.frontend_dist / "index.html", headers={"Cache-Control": "no-cache"})
    return app
