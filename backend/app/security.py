import hashlib
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request
from sqlalchemy import select, func
from .db import Session, User, LoginAttempt, now

hasher = PasswordHasher()
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def password_hash(password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError("La contraseña debe tener entre 12 y 256 caracteres.")
    return hasher.hash(password)

def verify(password, hashed):
    try: return hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError): return False

def identity(request: Request, db, *, mutate=False):
    token = request.cookies.get("compareforms_session", "")
    session = db.get(Session, digest(token)) if token else None
    user = db.get(User, session.user_id) if session and session.expires > now() else None
    if not user or not user.active: raise HTTPException(401, "Inicie sesión para continuar.")
    cfg = db.info.get("settings")
    provider_name = cfg.auth_provider if cfg else "local"
    if user.auth_provider != provider_name:
        raise HTTPException(401, "Inicie sesión con el proveedor de identidad vigente.")
    if mutate and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf):
        raise HTTPException(403, "La sesión de seguridad cambió. Actualice la página.")
    if provider_name == "aitrol":
        from .aitrol_identity import AitrolIdentityProvider, IdentityUnavailable, role_for
        from .db import Organization
        org = db.get(Organization, user.organization_id)
        if not org or not org.external_company_id or not user.external_user_id:
            raise HTTPException(401, "Identidad externa incompleta.")
        application = request.scope.get("app")
        provider = getattr(application.state, "identity_provider", None) if application else None
        provider = provider or AitrolIdentityProvider(cfg)
        try: actor = provider.revalidate(user.external_user_id, org.external_company_id)
        except IdentityUnavailable:
            raise HTTPException(503, "No se pudo verificar el acceso en Aitrol. Intente nuevamente.") from None
        if actor is None: raise HTTPException(401, "El acceso fue revocado en Aitrol. Inicie sesión nuevamente.")
        user.role, user.external_email = role_for(actor), actor.email
        user._company_id = org.external_company_id
        user._company_name = next(c["name"] for c in actor.companies if c["id"] == org.external_company_id)
    return user, session

def public_user(user):
    return {"id": user.id, "username": user.external_email if user.auth_provider == "aitrol" else user.username,
            "role": user.role, "organization_id": user.organization_id, "auth_provider": user.auth_provider,
            "company_id": getattr(user, "_company_id", None), "company_name": getattr(user, "_company_name", None)}

def throttle(db, username, ip):
    key = digest(username.casefold())
    count = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.key == key, LoginAttempt.created > now()-900))
    if count >= 10: raise HTTPException(429, "Demasiados intentos. Espere 15 minutos.")
    db.add(LoginAttempt(key=key))
    db.commit()
