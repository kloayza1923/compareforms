from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    documents_root: Path = field(default_factory=lambda: Path(os.getenv("COMPAREFORMS_DATA_ROOT", str(ROOT / "documents"))))
    frontend_dist: Path = field(default_factory=lambda: Path(os.getenv("FRONTEND_DIST", str(ROOT / "frontend" / "dist"))))
    session_secure: bool = field(default_factory=lambda: os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true")
    testing: bool = False
    auth_provider: str = field(default_factory=lambda: os.getenv("COMPAREFORMS_AUTH_PROVIDER", "local"))
    aitrol_env_file: str = field(default_factory=lambda: os.getenv("AITROL_ROBOTI_ENV_FILE", ""))
    roboti_proxy_token: str = field(default_factory=lambda: os.getenv("COMPAREFORMS_PROXY_TOKEN") or dotenv_values(ROOT / ".env.roboti").get("COMPAREFORMS_PROXY_TOKEN", ""))
    session_hours: int = 8
    max_upload_bytes: int = 512 * 1024 * 1024
    max_pdf_bytes: int = 100 * 1024 * 1024
    max_unpacked_bytes: int = 2 * 1024 * 1024 * 1024
    max_zip_entries: int = 2000
    max_pdf_pages: int = 500
    lease_seconds: int = 180
    max_attempts: int = 3
    ocr_enabled: bool = field(default_factory=lambda: os.getenv("OCR_ENABLED", "true").lower() == "true")

    def validate(self):
        if self.roboti_proxy_token and len(self.roboti_proxy_token) < 32:
            raise RuntimeError("COMPAREFORMS_PROXY_TOKEN requiere al menos 32 caracteres.")
        if self.auth_provider not in {"local", "aitrol"}:
            raise RuntimeError("COMPAREFORMS_AUTH_PROVIDER debe ser local o aitrol.")
        if self.auth_provider == "aitrol" and not self.aitrol_env_file:
            raise RuntimeError("Configure AITROL_ROBOTI_ENV_FILE para el acceso compartido.")
        if not self.database_url:
            raise RuntimeError("Configure DATABASE_URL de PostgreSQL antes de iniciar.")
        if not self.testing and not self.database_url.startswith("postgresql+"):
            raise RuntimeError("El portal requiere PostgreSQL; SQLite se admite únicamente en pruebas.")
