from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_root: Path = Path(os.getenv("COMPAREFORMS_DATA_ROOT", PROJECT_ROOT))
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "gemma4:e2b-it-qat")
    ollama_timeout_seconds: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
    max_diff_snippets: int = int(os.getenv("MAX_DIFF_SNIPPETS", "30"))
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    ocr_lang: str = os.getenv("OCR_LANG", "spa")
    ocr_dpi: int = int(os.getenv("OCR_DPI", "200"))
    ocr_min_chars: int = int(os.getenv("OCR_MIN_CHARS", "30"))

    def month_dir(self, month: str) -> Path:
        self.validate_month(month)
        root = self.data_root.resolve()
        candidate = (root / month).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("La ruta mensual sale del directorio de datos")
        return candidate

    def validate_month(self, month: str) -> str:
        import re
        if not re.fullmatch(r"20\d{2}_(?:0[1-9]|1[0-2])", month):
            raise ValueError("El mes debe tener formato YYYY_MM")
        return month
