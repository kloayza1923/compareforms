"""Authenticate against Roboti's Aitrol/MySQL identity source, SELECT only.

No imports from Roboti's app (which starts stores/services), no M2M/proxy tokens,
no remote password/hash persistence, and no writes to Aitrol or Roboti.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import bcrypt
from dotenv import dotenv_values
import pymysql
from pymysql.cursors import DictCursor
from fastapi import HTTPException
from . import db as m


class IdentityUnavailable(Exception):
    """Deliberately excludes connection credentials and SQL values from errors."""
    def __init__(self, message, *, stage="identity", code=None):
        super().__init__(message)
        self.stage, self.code = stage, code


@dataclass(frozen=True)
class Actor:
    user_id: str
    email: str
    role_id: int
    companies: tuple[dict, ...]


@dataclass(frozen=True)
class MysqlConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)


def source_config(settings) -> MysqlConfig:
    """Read trusted configuration as data, never source/eval a foreign .env."""
    path = Path(settings.aitrol_env_file)
    try:
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise ValueError("Not a trusted regular configuration file")
        metadata = path.stat()
        if os.name == "posix" and (metadata.st_mode & 0o022 or metadata.st_uid not in {0, os.getuid()}):
            raise ValueError("Configuration is writable by another identity")
        values = dotenv_values(path, interpolate=False)
        profile = (values.get("DB_PROFILE") or "test").strip().lower()
        if profile not in {"test", "production"}:
            raise ValueError("Unknown database profile")
        if (values.get("APP_ENV") or "development").strip().lower() == "production" and profile != "production":
            raise ValueError("Production profile required")
        prefix = "SOURCE_DB_" if profile == "production" else "DB_"
        # Defaults mirror Roboti's app/core/config.py. Password remains required.
        defaults = {} if profile == "production" else {"HOST": "127.0.0.1", "DATABASE": "sis_medico", "USERNAME": "formsgenerator_ro"}
        selected = {key: values.get(prefix + key) or defaults.get(key, "") for key in ("HOST", "DATABASE", "USERNAME", "PASSWORD")}
        port = int(values.get(prefix + "PORT") or (3306 if profile == "production" else 3307))
        if not all(selected.values()) or not 0 < port < 65536:
            raise ValueError("Incomplete database configuration")
        if any("${" in value for value in selected.values()):
            raise ValueError("Use resolved values in the dedicated configuration file")
        return MysqlConfig(selected["HOST"], port, selected["DATABASE"], selected["USERNAME"], selected["PASSWORD"])
    except Exception:
        raise IdentityUnavailable("No se pudo cargar la conexión de identidad.") from None


class AitrolIdentityProvider:
    def __init__(self, settings): self.settings = settings

    @contextmanager
    def connection(self):
        cfg = source_config(self.settings)
        conn = None
        stage = "connection"
        try:
            conn = pymysql.connect(host=cfg.host, port=cfg.port, database=cfg.database, user=cfg.user,
                password=cfg.password, charset="utf8mb4", cursorclass=DictCursor, connect_timeout=5,
                read_timeout=10, write_timeout=10, autocommit=True, local_infile=False,
                init_command="SET SESSION TRANSACTION READ ONLY")
            stage = "query"
            yield conn
        except IdentityUnavailable:
            raise
        except Exception as exc:
            code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
            raise IdentityUnavailable("Aitrol no está disponible para verificar el acceso.", stage=stage, code=code) from None
        finally:
            if conn is not None: conn.close()

    @staticmethod
    def _companies(cursor, user_id, role_id):
        if role_id == 1:
            cursor.execute("SELECT id, COALESCE(nombrecomercial, razonsocial) AS name FROM empresa WHERE estado=1 ORDER BY name")
        else:
            cursor.execute("""SELECT DISTINCT e.id, COALESCE(e.nombrecomercial,e.razonsocial) AS name
                FROM empresa e JOIN usuario_empresa ue ON ue.id_empresa=e.id
                WHERE ue.id_usuario=%s AND e.estado=1 ORDER BY name""", (user_id,))
        return tuple({"id": str(row["id"]), "name": str(row["name"] or row["id"])} for row in cursor.fetchall())

    def authenticate(self, email: str, password: str) -> Actor | None:
        with self.connection() as conn, conn.cursor() as cursor:
            # No deleted_at: Roboti's current code/tests target the legacy schema.
            cursor.execute("SELECT id,email,password,id_tipo_usuario FROM users WHERE LOWER(email)=LOWER(%s) AND estado=1 LIMIT 2", (email,))
            rows = cursor.fetchall()
            if len(rows) != 1: return None  # Never select an arbitrary duplicate email.
            row = rows[0]
            try:
                valid = bcrypt.checkpw(password.encode("utf-8"), str(row["password"]).encode("utf-8"))
                role = int(row["id_tipo_usuario"])
            except (ValueError, TypeError):
                return None
            if not valid or role not in {1, 11, 22}: return None
            return Actor(str(row["id"]), str(row["email"]), role, self._companies(cursor, str(row["id"]), role))

    def revalidate(self, user_id: str, company_id: str) -> Actor | None:
        with self.connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT id,email,id_tipo_usuario FROM users WHERE id=%s AND estado=1 AND id_tipo_usuario IN (1,11,22)", (user_id,))
            row = cursor.fetchone()
            if not row: return None
            companies = self._companies(cursor, str(row["id"]), int(row["id_tipo_usuario"]))
            if company_id not in {c["id"] for c in companies}: return None
            return Actor(str(row["id"]), str(row["email"]), int(row["id_tipo_usuario"]), companies)

    def probe(self):
        # Connectivity/schema/read-only mode only. Never list user accounts/hashes.
        with self.connection() as conn, conn.cursor() as cursor:
            for sql in ("SELECT id,email,password,id_tipo_usuario,estado FROM users LIMIT 0",
                        "SELECT id_usuario,id_empresa FROM usuario_empresa LIMIT 0",
                        "SELECT id,nombrecomercial,razonsocial,estado FROM empresa LIMIT 0"):
                cursor.execute(sql)
            try:
                cursor.execute("SELECT @@session.transaction_read_only AS read_only")
            except pymysql.err.OperationalError as exc:
                if exc.args[0] != 1193: raise
                cursor.execute("SELECT @@session.tx_read_only AS read_only")
            if not int(cursor.fetchone()["read_only"]):
                raise IdentityUnavailable("La conexión no está en modo solo lectura.")
        return {"identity_source": "aitrol", "schema": "compatible", "transaction": "read_only"}


def role_for(actor: Actor):
    # Roles 11/22 gain audit capabilities, never administrator privileges.
    return "admin" if actor.role_id == 1 else "auditor"


def membership(db, actor: Actor, company_id: str):
    company = next((c for c in actor.companies if c["id"] == company_id), None)
    if not company: raise HTTPException(403, "No tiene acceso a esa empresa.")
    if len(actor.user_id) > 100 or len(company_id) > 100 or len(actor.email) > 254:
        raise HTTPException(403, "Identidad incompatible con el portal.")
    org_id = str(uuid5(NAMESPACE_URL, "compareforms:aitrol:company:" + company_id))
    org = db.get(m.Organization, org_id)
    if org is None:
        org = m.Organization(id=org_id, name=company["name"][:200], external_company_id=company_id)
        db.add(org); db.flush()
    if org.external_company_id != company_id: raise HTTPException(409, "Conflicto de identidad de empresa.")
    uid = str(uuid5(NAMESPACE_URL, "compareforms:aitrol:membership:" + actor.user_id + ":" + company_id))
    user = db.get(m.User, uid)
    if user is None:
        user = m.User(id=uid, organization_id=org_id, username="aitrol-" + hashlib.sha256(uid.encode()).hexdigest(),
            password_hash="!external-authentication-no-local-password!", role=role_for(actor),
            auth_provider="aitrol", external_user_id=actor.user_id, external_email=actor.email)
        db.add(user); db.flush()
    if user.auth_provider != "aitrol" or user.external_user_id != actor.user_id or user.organization_id != org_id:
        raise HTTPException(409, "Conflicto de identidad de usuario.")
    if not user.active: raise HTTPException(403, "Acceso al portal deshabilitado.")
    user.role, user.external_email = role_for(actor), actor.email
    user._company_id, user._company_name = company_id, company["name"]
    return user
