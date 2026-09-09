"""Maintenance only; auditors use the portal."""
from pathlib import Path
import argparse
import getpass
import secrets
from sqlalchemy import select, delete
from .config import Settings, ROOT
from . import db as m
from .security import password_hash

def create_admin(settings, username, password, organization_name):
    engine, factory = m.connect(settings)
    with factory.begin() as db:
        username = username.strip().casefold()
        if not username: raise ValueError("Usuario obligatorio.")
        if db.scalar(select(m.User).where(m.User.username == username)): raise ValueError("Usuario ya existe; no se sobrescribe.")
        org = m.Organization(name=organization_name); db.add(org); db.flush()
        user = m.User(username=username, password_hash=password_hash(password), role="admin", organization_id=org.id)
        db.add(user); db.flush(); m.event(db, user, "bootstrap_admin", user.id)
        return user

def init_local_env(path):
    path = Path(path)
    # Exclusive create: never overwrite existing credentials.
    password = secrets.token_hex(24)
    text = f"POSTGRES_PASSWORD={password}\nDATABASE_URL=postgresql+psycopg://compareforms:{password}@127.0.0.1:54327/compareforms\nCOMPAREFORMS_DATA_ROOT={ROOT / 'documents'}\nSESSION_COOKIE_SECURE=false\n"
    with path.open("x", encoding="utf-8") as file: file.write(text)
    path.chmod(0o600)

def deactivate_user(settings, username):
    engine, factory = m.connect(settings)
    try:
        with factory.begin() as db:
            user = db.scalar(select(m.User).where(m.User.username == username.strip().casefold()))
            if not user: raise ValueError("Usuario no encontrado; no se cambió ningún registro.")
            user.active = False
            db.execute(delete(m.Session).where(m.Session.user_id == user.id))
            # Local maintenance is not an action performed by the target user.
            m.event(db, None, "maintenance_deactivate_user", user.id)
    finally: engine.dispose()

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    admin = sub.add_parser("create-admin"); admin.add_argument("--username", required=True); admin.add_argument("--organization", required=True)
    init = sub.add_parser("init-local-env"); init.add_argument("--path", default=str(ROOT / ".env.local"))
    disable = sub.add_parser("deactivate-user"); disable.add_argument("--username", required=True)
    args = parser.parse_args()
    if args.cmd == "init-local-env":
        init_local_env(args.path); print("Configuración local creada sin mostrar credenciales."); return
    if args.cmd == "deactivate-user":
        deactivate_user(Settings(), args.username); print("Usuario desactivado y sesiones revocadas; historial conservado."); return
    password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
    if password != getpass.getpass("Confirmar contraseña: "): raise SystemExit("Las contraseñas no coinciden.")
    create_admin(Settings(), args.username, password, args.organization)
    print("Administrador creado. Inicie sesión en el portal.")

if __name__ == "__main__": main()
