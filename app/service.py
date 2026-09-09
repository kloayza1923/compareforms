from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import json
import uuid

from .comparator import compare_pair, discover
from .config import Settings
from .ollama import preflight, summarize
from .reporting import write_reports


_month_locks: dict[str, Lock] = {}
_registry_lock = Lock()


def month_lock(month: str) -> Lock:
    with _registry_lock:
        return _month_locks.setdefault(month, Lock())


def list_months(settings: Settings) -> list[dict[str, Any]]:
    if not settings.data_root.exists(): return []
    output = []
    for folder in sorted(settings.data_root.iterdir(), reverse=True):
        if not folder.is_dir(): continue
        try: settings.validate_month(folder.name)
        except ValueError: continue
        before = folder / "pdf_origen"; after = folder / "pdf_modificado"
        output.append({"month": folder.name, "ready": before.is_dir() and after.is_dir(), "has_results": (folder / "results" / "latest.json").is_file()})
    return output


def run_month(month: str, settings: Settings, use_ollama: bool = True, workers: int = 2, indices: set[int] | None = None) -> dict[str, Any]:
    settings.validate_month(month)
    lock = month_lock(month)
    if not lock.acquire(blocking=False): raise RuntimeError(f"Ya existe una ejecución activa para {month}")
    try:
        folder = settings.month_dir(month); before_dir = folder / "pdf_origen"; after_dir = folder / "pdf_modificado"
        if use_ollama:
            print(f"[preflight] comprobando Ollama y modelo {settings.ollama_model}", flush=True)
            preflight(settings.ollama_url, settings.ollama_model, settings.ollama_timeout_seconds)
        before, ignored_before = discover(before_dir); after, ignored_after = discover(after_dir)
        shared_all = sorted(set(before) & set(after)); missing_before = sorted(set(after) - set(before)); missing_after = sorted(set(before) - set(after))
        shared = [index for index in shared_all if indices is None or index in indices]
        if indices is not None:
            unavailable = sorted(indices - set(shared_all))
            if unavailable:
                raise ValueError(f"Índices solicitados sin par completo: {unavailable}")
        comparisons: list[dict[str, Any]] = []; failures: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = {executor.submit(compare_pair, index, before[index], after[index], settings.max_diff_snippets, settings.ocr_enabled, settings.ocr_lang, settings.ocr_dpi, settings.ocr_min_chars): index for index in shared}
            for completed, future in enumerate(as_completed(futures), 1):
                index = futures[future]
                try: comparisons.append(future.result())
                except Exception as exc: failures.append({"index": index, "error": f"{type(exc).__name__}: {exc}"})
                print(f"[comparacion] {completed}/{len(shared)} expedientes procesados", flush=True)
        comparisons.sort(key=lambda x: x["index"]); failures.sort(key=lambda x: x["index"])
        if use_ollama:
            for completed, comparison in enumerate(comparisons, 1):
                comparison["ollama"] = summarize(comparison, settings.ollama_url, settings.ollama_model, settings.ollama_timeout_seconds)
                print(f"[ollama] {completed}/{len(comparisons)} resúmenes procesados", flush=True)
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        manifest = {
            "schema_version": "1.0", "run_id": run_id, "month": month, "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "selected_indices" if indices is not None else "full_month", "requested_indices": sorted(indices) if indices is not None else None,
            "pair_count": len(comparisons), "failure_count": len(failures), "missing_before_indices": missing_before, "missing_after_indices": missing_after,
            "ignored_before": ignored_before, "ignored_after": ignored_after, "failures": failures, "comparisons": comparisons,
            "limitations": ["OCR Tesseract se aplica solo a páginas con texto extraíble insuficiente.", "Señales sensibles basadas en expresiones regulares.", "Ollama solo recibe métricas anonimizadas y puede no estar disponible."],
        }
        results_root = folder / "results"
        artifacts = write_reports(month, results_root / run_id, manifest)
        print(f"[reportes] ejecución {run_id} completada", flush=True)
        latest = {"run_id": run_id, "manifest": artifacts["json"], "artifacts": artifacts}
        results_root.mkdir(parents=True, exist_ok=True)
        (results_root / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"month": month, "run_id": run_id, "status": "completed_with_errors" if failures else "completed", "pairs": len(comparisons), "failures": len(failures), "artifacts": artifacts}
    finally:
        lock.release()


def load_results(month: str, settings: Settings) -> dict[str, Any]:
    settings.validate_month(month)
    latest_path = settings.month_dir(month) / "results" / "latest.json"
    if not latest_path.is_file(): raise FileNotFoundError(f"No hay resultados para {month}")
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    path = Path(latest["manifest"]).resolve()
    month_root = settings.month_dir(month).resolve()
    if not path.is_relative_to(month_root) or not path.is_file(): raise FileNotFoundError("Manifiesto latest inválido")
    return json.loads(path.read_text(encoding="utf-8"))
