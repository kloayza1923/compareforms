from __future__ import annotations

from fastapi import FastAPI, HTTPException

from . import __version__
from .config import Settings
from .ollama import OllamaUnavailable
from .schemas import HealthResponse, RunRequest, RunResponse
from .service import list_months, load_results, run_month


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    app = FastAPI(title="CompareForms", version=__version__)

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "ollama_model": cfg.ollama_model}

    @app.get("/months")
    def months(): return {"months": list_months(cfg)}

    @app.post("/months/{month}/run", response_model=RunResponse)
    def run(month: str, request: RunRequest):
        try: return run_month(month, cfg, use_ollama=request.use_ollama)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
        except OllamaUnavailable as exc: raise HTTPException(503, str(exc)) from exc
        except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc

    @app.get("/months/{month}/results")
    def results(month: str):
        try: return load_results(month, cfg)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc

    @app.get("/months/{month}/results/{index}")
    def result(month: str, index: int):
        try: manifest = load_results(month, cfg)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
        for item in manifest["comparisons"]:
            if item["index"] == index: return item
        raise HTTPException(404, f"Índice {index} no encontrado")

    return app


app = create_app()
