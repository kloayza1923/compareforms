#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from app.config import Settings
from app.service import run_month


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara un mes de documentos PDF")
    parser.add_argument("month", help="Mes en formato YYYY_MM, por ejemplo 2025_10")
    parser.add_argument("--no-ollama", action="store_true", help="No solicitar resúmenes a Ollama")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--indices", help="Procesar solo índices concretos, separados por coma; ejemplo: 6 o 6,30,35")
    args = parser.parse_args()
    selected = None
    if args.indices:
        try:
            selected = {int(value.strip()) for value in args.indices.split(",") if value.strip()}
        except ValueError as exc:
            parser.error("--indices debe contener enteros separados por coma")
        if not selected or any(value < 1 for value in selected):
            parser.error("--indices debe contener enteros positivos")
    result = run_month(args.month, Settings(), use_ollama=not args.no_ollama, workers=args.workers, indices=selected)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failures"] else 0


if __name__ == "__main__": raise SystemExit(main())
