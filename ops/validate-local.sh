#!/usr/bin/env bash
set -euo pipefail
stage='/mnt/c/102025_IESS_Dr. Carlos Robles Medranda/compareforms_project'
project='/home/mdconsgroup/projects/compareforms'
rsync -a --exclude=.venv --exclude=__pycache__ "$stage/backend/" "$project/backend/"
rsync -a --exclude=node_modules --exclude=dist "$stage/frontend/" "$project/frontend/"
rsync -a "$stage/ops/" "$project/ops/"
cd "$project/backend"
set -a
. ../.env.local
set +a
.venv/bin/alembic upgrade head
.venv/bin/alembic check
.venv/bin/python -m pytest tests -q
cd "$project/frontend"
export PATH="/home/mdconsgroup/.nvm/versions/node/v24.18.0/bin:$PATH"
npm test
npm run build
cp package-lock.json "$stage/frontend/package-lock.json"
