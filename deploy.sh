#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_HOST:?Set DEPLOY_HOST}"
: "${DEPLOY_USER:?Set DEPLOY_USER}"
DEPLOY_PATH="${DEPLOY_PATH:-/home/sistemas201/projects/compareforms}"
INCLUDE_MONTHS="${INCLUDE_MONTHS:-0}"
RESTART_COMMAND="${RESTART_COMMAND:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

EXCLUDES=(--exclude '.env' --exclude '.venv/' --exclude '.testdeps/' --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude 'results/')
if [[ "$INCLUDE_MONTHS" != "1" ]]; then
  EXCLUDES+=(--exclude '20[0-9][0-9]_[0-1][0-9]/')
fi
rsync -az "${EXCLUDES[@]}" ./ "${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}/"

ssh "${DEPLOY_USER}@${DEPLOY_HOST}" \
  "cd '${DEPLOY_PATH}' && '${PYTHON_BIN}' -m venv .venv && .venv/bin/pip install -r requirements.txt"
if [[ -n "$RESTART_COMMAND" ]]; then
  ssh "${DEPLOY_USER}@${DEPLOY_HOST}" "$RESTART_COMMAND"
fi
