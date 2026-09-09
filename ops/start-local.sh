#!/usr/bin/env bash
# Local WSL development launcher only. Does not install or deploy anything.
set -Eeuo pipefail
umask 077

usage() {
  printf 'Uso: bash ops/start-local.sh api|worker\n'
  printf 'Solo WSL local mdconsgroup; API en http://127.0.0.1:8027.\n'
}
[[ ${1:-} != --help && ${1:-} != -h ]] || { usage; exit 0; }
[[ $# == 1 && ( $1 == api || $1 == worker ) ]] || { usage >&2; exit 64; }
grep -qi microsoft /proc/sys/kernel/osrelease || { printf 'Este wrapper solo permite WSL local.\n' >&2; exit 65; }
[[ $(id -un) == mdconsgroup ]] || { printf 'Usuario local esperado: mdconsgroup.\n' >&2; exit 65; }
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$root" == /home/mdconsgroup/projects/compareforms ]] || { printf 'Ejecute la copia WSL en /home/mdconsgroup/projects/compareforms.\n' >&2; exit 65; }
env_file="$root/.env.local"
[[ -f "$env_file" && ! -L "$env_file" && $(stat -c %u "$env_file") == $(id -u) ]] || { printf 'Falta .env.local privado, regular y propio. Consulte backend/README.md.\n' >&2; exit 66; }
permissions=$(stat -c %a "$env_file")
(( (8#$permissions & 077) == 0 )) || { printf '.env.local debe tener permisos privados (chmod 600).\n' >&2; exit 65; }
python="$root/backend/.venv/bin/python"
[[ -x "$python" ]] || { printf 'Falta backend/.venv. Consulte backend/README.md.\n' >&2; exit 66; }

# This is the user's locally generated trusted file, never an uploaded artifact.
set -a
source "$env_file"
auth_file="$root/ops/auth.local.env"
[[ -f "$auth_file" && ! -L "$auth_file" && $(stat -c %u "$auth_file") == $(id -u) ]] || { printf 'Falta ops/auth.local.env confiable; no se permite volver a cuentas locales.\n' >&2; exit 65; }
auth_permissions=$(stat -c %a "$auth_file")
(( (8#$auth_permissions & 022) == 0 )) || { printf 'La configuración de identidad no debe admitir escritura ajena.\n' >&2; exit 65; }
source "$auth_file"
set +a
[[ ${COMPAREFORMS_AUTH_PROVIDER:-} == aitrol && -n ${AITROL_ROBOTI_ENV_FILE:-} ]] || { printf 'El portal local debe usar la identidad compartida Aitrol/Roboti.\n' >&2; exit 65; }
[[ ${DATABASE_URL:-} == postgresql+* ]] || { printf 'Configure DATABASE_URL PostgreSQL.\n' >&2; exit 65; }
private_tmp=$(mktemp -d /tmp/compareforms-local.XXXXXXXX)
export TMPDIR="$private_tmp"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
cleanup() {
  # Only remove an empty, exact directory we created. Preserve unexpected contents.
  if ! rmdir -- "$private_tmp" 2>/dev/null; then
    printf 'Temporal privado no vacío conservado para revisión: %s\n' "$private_tmp" >&2
  fi
}
trap cleanup EXIT
cd -- "$root/backend"
if [[ $1 == api ]]; then
  "$python" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8027 --limit-concurrency 8 --no-access-log
else
  "$python" -m app.worker
fi
