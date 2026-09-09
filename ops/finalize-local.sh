#!/usr/bin/env bash
set -euo pipefail
stage='/mnt/c/102025_IESS_Dr. Carlos Robles Medranda/compareforms_project'
project='/home/mdconsgroup/projects/compareforms'
rsync -a --exclude=.venv --exclude=__pycache__ "$stage/backend/" "$project/backend/"
rsync -a --exclude=node_modules --exclude=dist "$stage/frontend/" "$project/frontend/"
rsync -a "$stage/ops/" "$project/ops/"
for file in README.md design.md implementation-contract.md VALIDACION_V1.md .gitignore deploy_front.sh; do
    cp -- "$stage/$file" "$project/$file"
done
mkdir -p "$project/documents/validation-v1"
cp -- "$stage/outputs/comparativo_alarcon_v1_validado.xlsx" "$project/documents/validation-v1/"
cp -- "$stage/outputs/comparativo_alarcon_v1_validado.validation.json" "$project/documents/validation-v1/"
cd "$project/backend"
set -a
. ../.env.local
set +a
.venv/bin/python -m app.cli deactivate-user --username qa_visual_v1
.venv/bin/python -m pytest tests/test_reporting_v1.py tests/test_render_limits_v1.py tests/test_portal_v1.py -q
cd "$project"
bash -n deploy_front.sh
bash deploy_front.sh --dry-run
printf 'Sincronización local terminada. No se conectó al servidor 201.\n'
