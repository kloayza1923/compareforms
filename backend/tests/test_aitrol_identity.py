"""Shared-identity regression checks using synthetic SQLite and fake MySQL only.

No real .env, external account, patient record, or network connection is used.
"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import os
import secrets

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text

from app import aitrol_identity as identity_source
from app import db as m
from app.aitrol_identity import Actor, AitrolIdentityProvider, IdentityUnavailable
from app.config import Settings
from app.main import create_app
from app.security import digest, password_hash

API = "/api/v1"
EMAIL = "synthetic.auditor@example.invalid"
PASSWORD = "Prueba-sintética-única!42"
COMPANIES = ({"id": "company-a", "name": "Empresa sintética A"},
             {"id": "company-b", "name": "Empresa sintética B"})


class FakeProvider:
    def __init__(self):
        self.actor = Actor("synthetic-user-1", EMAIL, 11, COMPANIES)
        self.available = True
        self.enabled = True
        self.calls = []

    def authenticate(self, email, password):
        self.calls.append(("authenticate", email))
        if not self.available:
            raise IdentityUnavailable("Synthetic outage")
        if not self.enabled or email != EMAIL or password != PASSWORD:
            return None
        return self.actor

    def revalidate(self, user_id, company_id):
        self.calls.append(("revalidate", user_id, company_id))
        if not self.available:
            raise IdentityUnavailable("Synthetic outage")
        if (not self.enabled or self.actor.role_id not in {1, 11, 22}
                or user_id != self.actor.user_id
                or company_id not in {c["id"] for c in self.actor.companies}):
            return None
        return self.actor


@pytest.fixture
def portal(tmp_path):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'identity.sqlite').as_posix()}",
        documents_root=tmp_path / "documents", frontend_dist=tmp_path / "missing-dist",
        testing=True, session_secure=False, auth_provider="aitrol", aitrol_env_file="fake")
    app = create_app(settings)
    m.Base.metadata.create_all(app.state.engine)
    app.state.identity_provider = FakeProvider()
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(portal):
    with TestClient(portal) as session:
        yield session


def login(client, company_id="company-a", **overrides):
    data = {"username": EMAIL, "password": PASSWORD}
    if company_id is not None:
        data["company_id"] = company_id
    data.update(overrides)
    return client.post(API + "/auth/login", json=data)


def counts(portal):
    with portal.state.SessionLocal() as db:
        return tuple(db.scalar(select(func.count()).select_from(model))
                     for model in (m.Organization, m.User, m.Session))


def test_company_selection_does_not_create_session_or_shadow(portal, client):
    response = login(client, None)
    assert response.status_code == 200
    assert response.json() == {"requires_company": True, "companies": list(COMPANIES)}
    assert "set-cookie" not in response.headers
    assert not client.cookies
    assert counts(portal) == (0, 0, 0)


def test_single_company_is_selected_automatically(portal, client):
    portal.state.identity_provider.actor = replace(portal.state.identity_provider.actor,
        companies=(COMPANIES[0],))
    response = login(client, None)
    assert response.status_code == 200
    assert response.json()["user"]["company_id"] == "company-a"
    assert counts(portal) == (1, 1, 1)


@pytest.mark.parametrize("company_id", ["unauthorized-company", "company-a' OR 1=1 --"])
def test_company_cannot_be_selected_without_membership(portal, client, company_id):
    response = login(client, company_id)
    assert response.status_code == 403
    assert counts(portal) == (0, 0, 0)
    assert "set-cookie" not in response.headers


def test_no_active_company_denies_login(portal, client):
    portal.state.identity_provider.actor = replace(portal.state.identity_provider.actor, companies=())
    assert login(client, None).status_code == 403
    assert counts(portal) == (0, 0, 0)


@pytest.mark.parametrize("role_id,expected_role", [(1, "admin"), (11, "auditor"), (22, "auditor")])
def test_external_role_mapping_and_identity_metadata(portal, client, role_id, expected_role):
    portal.state.identity_provider.actor = replace(portal.state.identity_provider.actor, role_id=role_id)
    response = login(client, username="  SYNTHETIC.AUDITOR@EXAMPLE.INVALID  ")
    assert response.status_code == 200
    user = response.json()["user"]
    assert (user["username"], user["role"], user["auth_provider"]) == (EMAIL, expected_role, "aitrol")
    assert (user["company_id"], user["company_name"]) == ("company-a", COMPANIES[0]["name"])
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get(API + "/auth/me").json()["user"] == user


def test_no_password_or_remote_hash_is_persisted(portal, client):
    assert login(client).status_code == 200
    with portal.state.SessionLocal() as db:
        user = db.scalar(select(m.User))
        assert user.password_hash == "!external-authentication-no-local-password!"
        assert user.external_user_id == "synthetic-user-1"
        assert user.external_email == EMAIL
        assert user.username != EMAIL
        for row in db.scalars(select(m.AuditEvent)):
            assert PASSWORD not in str(vars(row))
        session = db.scalar(select(m.Session))
        assert session.token_hash == digest(client.cookies.get("compareforms_session"))
        assert session.token_hash != client.cookies.get("compareforms_session")


def test_existing_local_email_is_not_linked_or_overwritten(portal, client):
    with portal.state.SessionLocal() as db:
        org = m.Organization(name="Local legacy company")
        db.add(org); db.flush()
        local = m.User(organization_id=org.id, username=EMAIL,
            password_hash=password_hash(PASSWORD), role="admin")
        db.add(local); db.commit()
        local_id, old_hash, old_org = local.id, local.password_hash, org.id
    response = login(client)
    assert response.status_code == 200
    assert response.json()["user"]["id"] != local_id
    assert response.json()["user"]["organization_id"] != old_org
    with portal.state.SessionLocal() as db:
        user = db.get(m.User, local_id)
        assert (user.password_hash, user.role, user.auth_provider) == (old_hash, "admin", "local")
        assert user.external_user_id is None
    assert counts(portal) == (2, 2, 1)


def test_company_sessions_keep_independent_organizations(portal):
    with TestClient(portal) as a, TestClient(portal) as b:
        first, second = login(a), login(b, "company-b")
        assert first.status_code == second.status_code == 200
        ua, ub = first.json()["user"], second.json()["user"]
        assert ua["id"] != ub["id"] and ua["organization_id"] != ub["organization_id"]
        created = a.post(API + "/batches", headers={"X-CSRF-Token": first.json()["csrf_token"]},
            json={"name": "Synthetic company A batch", "period": "2026_06"})
        assert created.status_code == 201
        assert len(a.get(API + "/batches").json()) == 1
        assert b.get(API + "/batches").json() == []
        assert b.get(API + "/batches/" + created.json()["id"] + "/inventory").status_code == 404
        assert a.get(API + "/auth/me").json()["user"]["company_id"] == "company-a"
        assert b.get(API + "/auth/me").json()["user"]["company_id"] == "company-b"


@pytest.mark.parametrize("revocation", ["inactive", "role", "company"])
def test_authorization_is_revalidated_on_every_request(portal, client, revocation):
    assert login(client).status_code == 200
    provider = portal.state.identity_provider
    assert client.get(API + "/batches").status_code == 200
    if revocation == "inactive":
        provider.enabled = False
    elif revocation == "role":
        provider.actor = replace(provider.actor, role_id=3)
    else:
        provider.actor = replace(provider.actor, companies=(COMPANIES[1],))
    assert client.get(API + "/auth/me").status_code == 401
    assert client.get(API + "/batches").status_code == 401
    assert sum(call[0] == "revalidate" for call in provider.calls) == 3


def test_administrator_downgrade_is_effective_without_relogin(portal, client):
    provider = portal.state.identity_provider
    provider.actor = replace(provider.actor, role_id=1)
    assert login(client).status_code == 200
    assert client.get(API + "/users").status_code == 200
    provider.actor = replace(provider.actor, role_id=11)
    assert client.get(API + "/users").status_code == 403
    assert client.get(API + "/auth/me").json()["user"]["role"] == "auditor"


def test_local_session_rejected_when_aitrol_provider_is_active(portal, client):
    raw_token = secrets.token_urlsafe(32)
    with portal.state.SessionLocal() as db:
        org = m.Organization(name="Local only")
        db.add(org); db.flush()
        user = m.User(organization_id=org.id, username=EMAIL,
            password_hash=password_hash(PASSWORD), role="admin", auth_provider="local")
        db.add(user); db.flush()
        db.add(m.Session(token_hash=digest(raw_token), user_id=user.id, csrf="synthetic-csrf", expires=m.now()+300))
        db.commit()
    client.cookies.set("compareforms_session", raw_token)
    assert client.get(API + "/auth/me").status_code == 401
    portal.state.identity_provider.available = False
    assert login(client).status_code == 503
    assert counts(portal) == (1, 1, 1)


def test_login_and_requests_fail_closed_during_source_outage(portal, client):
    provider = portal.state.identity_provider
    provider.available = False
    response = login(client)
    assert response.status_code == 503
    assert "Synthetic outage" not in response.text
    assert counts(portal) == (0, 0, 0)
    provider.available = True
    assert login(client).status_code == 200
    provider.available = False
    assert client.get(API + "/batches").status_code == 503


def test_logout_revokes_local_session_even_when_source_is_down(portal, client):
    data = login(client).json()
    portal.state.identity_provider.available = False
    assert client.post(API + "/auth/logout", headers={"X-CSRF-Token": "incorrect"}).status_code == 403
    assert counts(portal)[2] == 1
    response = client.post(API + "/auth/logout", headers={"X-CSRF-Token": data["csrf_token"]})
    assert response.status_code == 200
    assert counts(portal)[2] == 0
    assert client.get(API + "/auth/me").status_code == 401


def test_external_administrator_cannot_create_local_password(portal, client):
    portal.state.identity_provider.actor = replace(portal.state.identity_provider.actor, role_id=1)
    result = login(client).json()
    response = client.post(API + "/users", headers={"X-CSRF-Token": result["csrf_token"]},
        json={"username": "forbidden@example.invalid", "password": PASSWORD, "role": "admin"})
    assert response.status_code == 403
    assert counts(portal) == (1, 1, 1)


def test_health_checks_migrated_columns_without_reading_identity_rows(portal, client):
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(portal.state.engine, "before_cursor_execute", capture)
    try:
        response = client.get(API + "/health")
    finally:
        event.remove(portal.state.engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert len(statements) == 2
    assert all(sql.lstrip().upper().startswith("SELECT") and "LIMIT 0" in sql for sql in statements)
    assert {"auth_provider", "external_user_id", "external_email", "organization_id"}.issubset(
        set(statements[0].split(" FROM ")[0].replace("SELECT ", "").split(",")))
    assert "external_company_id" in statements[1]
    assert portal.state.identity_provider.calls == []


@pytest.mark.parametrize("missing_column", ["auth_provider", "external_user_id", "external_email", "organization_id", "external_company_id"])
def test_health_is_unready_when_identity_migration_is_incomplete(tmp_path, missing_column):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'incomplete-schema.sqlite').as_posix()}",
        testing=True, auth_provider="aitrol", aitrol_env_file="fake",
        documents_root=tmp_path / "documents", frontend_dist=tmp_path / "missing-dist")
    app = create_app(settings)
    user_columns = [name for name in ("id", "auth_provider", "external_user_id", "external_email", "organization_id")
                    if name != missing_column]
    org_columns = [name for name in ("id", "external_company_id") if name != missing_column]
    try:
        with app.state.engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (" + ",".join(name + " TEXT" for name in user_columns) + ")"))
            connection.execute(text("CREATE TABLE organizations (" + ",".join(name + " TEXT" for name in org_columns) + ")"))
        with TestClient(app) as session:
            response = session.get(API + "/health")
        assert response.status_code == 503
        assert "migración" in response.json()["detail"]
        assert missing_column not in response.text  # Do not expose raw database errors.
    finally:
        app.state.engine.dispose()


class FakeCursor:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)
        self.statements = []
        self.rows = []

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        self.rows = self.result_sets.pop(0)
        if isinstance(self.rows, BaseException):
            raise self.rows
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, result_sets):
        self.cursor_value = FakeCursor(result_sets)
        self.closed = False
    def cursor(self): return self.cursor_value
    def close(self): self.closed = True


def mysql_provider(monkeypatch, result_sets):
    connection = FakeConnection(result_sets)
    options = {}
    def fake_connect(**kwargs):
        options.update(kwargs)
        return connection
    monkeypatch.setattr(identity_source, "source_config", lambda cfg: identity_source.MysqlConfig(
        "synthetic.invalid", 3306, "fake_db", "fake_reader", "synthetic-db-password"))
    monkeypatch.setattr(identity_source.pymysql, "connect", fake_connect)
    return AitrolIdentityProvider(SimpleNamespace()), connection, options


@pytest.fixture(scope="module")
def php_bcrypt_hash():
    return bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode().replace("$2b$", "$2y$", 1)


def user_row(php_bcrypt_hash, **changes):
    return {"id": "synthetic-user-1", "email": EMAIL, "password": php_bcrypt_hash,
            "id_tipo_usuario": 11, **changes}


def test_php_bcrypt_unicode_and_parameterized_read_only_connection(monkeypatch, php_bcrypt_hash):
    provider, conn, options = mysql_provider(monkeypatch, [[user_row(php_bcrypt_hash)], [COMPANIES[0]]])
    supplied_email = "synthetic' OR 1=1 --@example.invalid"
    actor = provider.authenticate(supplied_email, PASSWORD)
    assert actor == Actor("synthetic-user-1", EMAIL, 11, (COMPANIES[0],))
    sql, args = conn.cursor_value.statements[0]
    assert supplied_email not in sql and args == (supplied_email,)
    assert "estado=1" in sql and "LIMIT 2" in sql
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in conn.cursor_value.statements)
    assert conn.cursor_value.statements[1][1] == ("synthetic-user-1",)
    assert options["init_command"] == "SET SESSION TRANSACTION READ ONLY"
    assert options["local_infile"] is False
    assert options["charset"] == "utf8mb4" and options["connect_timeout"] <= 5
    assert conn.closed


@pytest.mark.parametrize("reason", ["invalid_password", "forbidden_role", "invalid_hash", "duplicate_email", "inactive_or_missing"])
def test_mysql_auth_denies_invalid_or_ambiguous_identity(monkeypatch, php_bcrypt_hash, reason):
    rows = [user_row(php_bcrypt_hash)]
    password = PASSWORD
    if reason == "invalid_password": password = "wrong-password"
    if reason == "forbidden_role": rows[0]["id_tipo_usuario"] = 3
    if reason == "invalid_hash": rows[0]["password"] = "not-a-bcrypt-hash"
    if reason == "duplicate_email": rows.append(user_row(php_bcrypt_hash, id="duplicate-id"))
    if reason == "inactive_or_missing": rows = []
    provider, conn, _ = mysql_provider(monkeypatch, [rows])
    assert provider.authenticate(EMAIL, password) is None
    assert len(conn.cursor_value.statements) == 1
    assert conn.closed


def test_revalidation_uses_current_active_role_and_company(monkeypatch):
    row = {"id": "synthetic-user-1", "email": EMAIL, "id_tipo_usuario": 22}
    provider, conn, _ = mysql_provider(monkeypatch, [[row], [COMPANIES[0]]])
    assert provider.revalidate("synthetic-user-1", "company-b") is None
    sql, args = conn.cursor_value.statements[0]
    assert "estado=1" in sql and "id_tipo_usuario IN (1,11,22)" in sql
    assert args == ("synthetic-user-1",)
    assert "e.estado=1" in conn.cursor_value.statements[1][0]


def test_mysql_connection_errors_do_not_expose_credentials(monkeypatch):
    monkeypatch.setattr(identity_source, "source_config", lambda cfg: identity_source.MysqlConfig(
        "synthetic.invalid", 3306, "fake_db", "fake_reader", "secret-should-not-escape"))
    def unavailable(**kwargs):
        raise RuntimeError("secret-should-not-escape")
    monkeypatch.setattr(identity_source.pymysql, "connect", unavailable)
    with pytest.raises(IdentityUnavailable) as caught:
        AitrolIdentityProvider(SimpleNamespace()).authenticate(EMAIL, PASSWORD)
    assert "secret-should-not-escape" not in str(caught.value)


@pytest.mark.parametrize("legacy", [False, True])
def test_probe_checks_schema_and_read_only_for_mysql_variants(monkeypatch, legacy):
    results = [[], [], []]
    if legacy:
        results.append(identity_source.pymysql.err.OperationalError(1193, "Unknown system variable"))
    results.append([{"read_only": 1}])
    provider, conn, _ = mysql_provider(monkeypatch, results)
    assert provider.probe() == {"identity_source": "aitrol", "schema": "compatible", "transaction": "read_only"}
    statements = [sql for sql, _ in conn.cursor_value.statements]
    assert len(statements) == (5 if legacy else 4)
    assert all(sql.startswith("SELECT") and "LIMIT 0" in sql for sql in statements[:3])
    assert "@@session.transaction_read_only" in statements[3]
    if legacy:
        assert "@@session.tx_read_only" in statements[4]
    assert conn.closed


def test_probe_does_not_fallback_on_unrelated_mysql_error(monkeypatch):
    error = identity_source.pymysql.err.OperationalError(1045, "synthetic-sensitive-server-detail")
    provider, conn, _ = mysql_provider(monkeypatch, [[], [], [], error])
    with pytest.raises(IdentityUnavailable) as caught:
        provider.probe()
    assert "synthetic-sensitive-server-detail" not in str(caught.value)
    assert len(conn.cursor_value.statements) == 4
    assert not any("@@session.tx_read_only" in sql for sql, _ in conn.cursor_value.statements)
    assert conn.closed


@pytest.mark.parametrize("legacy", [False, True])
def test_probe_rejects_writable_session_for_both_mysql_variants(monkeypatch, legacy):
    results = [[], [], []]
    if legacy:
        results.append(identity_source.pymysql.err.OperationalError(1193, "Unknown system variable"))
    results.append([{"read_only": 0}])
    provider, conn, _ = mysql_provider(monkeypatch, results)
    with pytest.raises(IdentityUnavailable):
        provider.probe()
    assert conn.closed


def test_probe_fails_closed_on_incompatible_identity_schema(monkeypatch):
    error = identity_source.pymysql.err.OperationalError(1054, "synthetic-private-column-detail")
    provider, conn, _ = mysql_provider(monkeypatch, [error])
    with pytest.raises(IdentityUnavailable) as caught:
        provider.probe()
    assert "synthetic-private-column-detail" not in str(caught.value)
    assert len(conn.cursor_value.statements) == 1
    assert conn.closed


def config_file(tmp_path, content):
    path = tmp_path / "synthetic.env"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return SimpleNamespace(aitrol_env_file=str(path))


@pytest.mark.parametrize("profile,prefix,port", [("test", "DB_", 3307), ("production", "SOURCE_DB_", 3306)])
def test_source_config_selects_whitelisted_profile_without_environment_side_effects(tmp_path, monkeypatch, profile, prefix, port):
    monkeypatch.setenv("DB_PASSWORD", "process-value-should-remain")
    before = dict(os.environ)
    config = config_file(tmp_path, f"DB_PROFILE={profile}\n{prefix}HOST=synthetic.invalid\n"
        f"{prefix}DATABASE=fake_database\n{prefix}USERNAME=fake_readonly\n{prefix}PASSWORD=synthetic-only-secret\n"
        "M2M_TOKEN=unrelated-token\nPROXY_TOKEN=another-token\n")
    parsed = identity_source.source_config(config)
    assert (parsed.host, parsed.database, parsed.user, parsed.port) == ("synthetic.invalid", "fake_database", "fake_readonly", port)
    assert parsed.password == "synthetic-only-secret"
    assert set(vars(parsed)) == {"host", "port", "database", "user", "password"}
    assert "synthetic-only-secret" not in repr(parsed)
    assert dict(os.environ) == before


@pytest.mark.parametrize("content", [
    "DB_PROFILE=other\nDB_PASSWORD=synthetic\n",
    "APP_ENV=production\nDB_PROFILE=test\nDB_PASSWORD=synthetic\n",
    "DB_PROFILE=test\nDB_PASSWORD=${DO_NOT_EXPAND}\n",
    "DB_PROFILE=test\nDB_PASSWORD=synthetic\nDB_PORT=99999\n",
    "DB_PROFILE=production\nSOURCE_DB_PASSWORD=synthetic\n",
    "DB_PROFILE=test\nM2M_TOKEN=must-not-become-db-password\n",
])
def test_source_config_fails_closed_for_invalid_or_incomplete_inputs(tmp_path, content):
    with pytest.raises(IdentityUnavailable):
        identity_source.source_config(config_file(tmp_path, content))


def test_source_config_requires_absolute_regular_path(tmp_path):
    with pytest.raises(IdentityUnavailable):
        identity_source.source_config(SimpleNamespace(aitrol_env_file="relative.env"))
    with pytest.raises(IdentityUnavailable):
        identity_source.source_config(SimpleNamespace(aitrol_env_file=str(tmp_path)))


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and permissions")
def test_source_config_rejects_shared_writable_or_symlink_file(tmp_path):
    settings = config_file(tmp_path, "DB_PASSWORD=synthetic-only\n")
    path = Path(settings.aitrol_env_file)
    path.chmod(0o666)
    with pytest.raises(IdentityUnavailable):
        identity_source.source_config(settings)
    path.chmod(0o600)
    link = tmp_path / "alias.env"
    link.symlink_to(path)
    with pytest.raises(IdentityUnavailable):
        identity_source.source_config(SimpleNamespace(aitrol_env_file=str(link)))
