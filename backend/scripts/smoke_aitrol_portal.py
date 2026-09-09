"""Read-only local HTTP-contract smoke, without a real human login."""
import json
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def main():
    settings = Settings()
    settings.validate()
    if settings.auth_provider != "aitrol":
        raise SystemExit("Configure el proveedor Aitrol antes de esta verificación.")
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health")
        config = client.get("/api/v1/auth/config")
        unauthorized = client.get("/api/v1/auth/me")
        portal = client.get("/")
        assert health.status_code == 200 and health.json()["status"] == "ready"
        assert config.status_code == 200 and config.json() == {"provider": "aitrol", "password_management": "aitrol"}
        assert unauthorized.status_code == 401
        assert portal.status_code == 200 and "text/html" in portal.headers["content-type"]
        assert 'id="root"' in portal.text
    print(json.dumps({"postgresql": "ready", "auth_provider": "aitrol", "without_session": 401,
                      "compiled_portal": 200, "real_user_login": "not_tested"}))


if __name__ == "__main__":
    main()
