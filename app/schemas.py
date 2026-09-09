from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_ollama: bool = Field(default=True, description="Solicitar resumen narrativo a Ollama")


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str
    run_id: str
    status: str
    pairs: int
    failures: int
    artifacts: dict[str, str]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    version: str
    ollama_model: str
