#!/usr/bin/env bash
set -euo pipefail
project='/home/mdconsgroup/projects/compareforms'
stage='/mnt/c/102025_IESS_Dr. Carlos Robles Medranda/compareforms_project'
rsync -a --exclude=.venv --exclude=__pycache__ "$stage/backend/" "$project/backend/"
cd "$project/backend"
set -a
. ../.env.local
set +a
export PYTHONPATH="$PWD"
exec .venv/bin/python scripts/validate_one_patient.py --output "$stage/outputs/comparativo_alarcon_v1_validado.xlsx"
