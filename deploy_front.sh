#!/usr/bin/env bash
# Run only in the local Linux/WSL checkout. Production receives static files only.
set -Eeuo pipefail
umask 077

HOST=192.168.66.33
USER_NAME=sistemas201
REMOTE_ROOT=/home/sistemas201/projects/compareforms/frontend-runtime
DRY_RUN=0
ROLLBACK=
RELEASE=
LOCAL_STAGE=
LOCKED=0
TOKEN=
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

usage() {
  cat <<'HELP'
Uso (WSL, desde el repositorio):
  bash deploy_front.sh [--host 192.168.66.33] [--user sistemas201] [--dry-run]
  bash deploy_front.sh --rollback <release-id> [--dry-run]
  bash deploy_front.sh --release <release-id> [--dry-run]

Compila con npm ci + npm test + npm run build solo en local; envía solo dist.
El destino es fijo: /home/sistemas201/projects/compareforms/frontend-runtime.
--dry-run no compila, no conecta por SSH y no escribe en el servidor.
--rollback activa una release ya existente, verifica checksum y API antes de cambiar.
--release permite un ID [A-Za-z0-9][A-Za-z0-9_-]{0,63}; no se sobrescribe.
Se requieren clave/agent SSH y host key previamente verificada. No pide contraseñas.
HELP
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --host|--user|--release|--rollback)
      (($# >= 2)) || die "Falta valor para $1"
      case "$1" in
        --host) HOST=$2;; --user) USER_NAME=$2;;
        --release) RELEASE=$2;; --rollback) ROLLBACK=$2;;
      esac
      shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    --help|-h) usage; exit 0;;
    *) die "Opción no reconocida: $1";;
  esac
done
[[ "$HOST" == 192.168.66.33 && "$USER_NAME" == sistemas201 ]] || die 'Host/usuario no autorizado por este script.'
[[ -z "$RELEASE" || "$RELEASE" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || die 'ID de release inválido.'
[[ -z "$ROLLBACK" || "$ROLLBACK" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || die 'ID de rollback inválido.'
[[ -z "$ROLLBACK" || -z "$RELEASE" ]] || die 'No combine --release y --rollback.'
if ((DRY_RUN)); then
  printf 'SIMULACIÓN: sin build, SSH, transferencias ni escrituras remotas.\nDestino: %s@%s:%s\n' "$USER_NAME" "$HOST" "$REMOTE_ROOT"
  if [[ -n "$ROLLBACK" ]]; then
    printf 'Plan: lock → verificar release %s, checksum y API → activar current atómicamente.\n' "$ROLLBACK"
  else
    printf 'Plan: npm ci → tests → build con base versionada → validación dist → lock → rsync → SHA-256/API → current atómico.\n'
  fi
  printf 'El modo simulación no comprueba conectividad, permisos, API ni disponibilidad del servidor.\n'
  exit 0
fi
for cmd in ssh rsync python3 realpath mktemp; do command -v "$cmd" >/dev/null || die "Falta $cmd"; done
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "$USER_NAME@$HOST")
TOKEN=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
if [[ -z "$RELEASE" && -z "$ROLLBACK" ]]; then RELEASE="$(date -u +%Y%m%dT%H%M%SZ)-${TOKEN:0:8}"; fi
ACTIVE_RELEASE=${ROLLBACK:-$RELEASE}

# Every remote operation runs this same guarded transaction. No configurable path
# or user-supplied shell fragments are accepted. A stale lock requires human review.
remote() {
  "${SSH[@]}" bash -s -- "$1" "$TOKEN" "$ACTIVE_RELEASE" <<'REMOTE'
set -Eeuo pipefail
umask 022
action=$1 token=$2 release=$3
root=/home/sistemas201/projects/compareforms/frontend-runtime
[[ "$token" =~ ^[a-f0-9]{32}$ && "$release" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || exit 64
[[ $(id -un) == sistemas201 ]] || { echo 'Usuario remoto incorrecto' >&2; exit 65; }
for part in /home /home/sistemas201 /home/sistemas201/projects /home/sistemas201/projects/compareforms; do
  [[ -d "$part" && ! -L "$part" && $(realpath -e -- "$part") == "$part" ]] || { echo "Ruta insegura: $part" >&2; exit 65; }
done
[[ ! -L "$root" ]] || exit 65
if [[ "$action" == lock ]]; then mkdir -p -- "$root"; fi
[[ -d "$root" && $(realpath -e -- "$root") == "$root" ]] || exit 65
for sub in releases incoming; do
  [[ ! -L "$root/$sub" ]] || exit 65
  if [[ "$action" == lock ]]; then mkdir -p -- "$root/$sub"; fi
  [[ -d "$root/$sub" && $(realpath -e -- "$root/$sub") == "$root/$sub" ]] || exit 65
done
if [[ "$action" == lock ]]; then
  mkdir -- "$root/.deploy-lock" || { echo 'Otro despliegue activo o lock pendiente de inspección.' >&2; exit 75; }
  printf '%s' "$token" > "$root/.deploy-lock/token"
  exit 0
fi
[[ ! -L "$root/.deploy-lock" && -d "$root/.deploy-lock" && ! -L "$root/.deploy-lock/token" ]] || exit 75
[[ $(< "$root/.deploy-lock/token") == "$token" ]] || exit 75
if [[ "$action" == unlock ]]; then
  rm -- "$root/.deploy-lock/token"
  rmdir -- "$root/.deploy-lock"
  exit 0
fi
target="$root/releases/$release"
stage="$root/incoming/$token"
case "$action" in
  prepare)
    [[ ! -e "$target" && ! -L "$target" && ! -e "$stage" && ! -L "$stage" ]] || exit 73
    mkdir -- "$stage"
    ;;
  activate|rollback)
    if [[ "$action" == activate ]]; then candidate=$stage; else candidate=$target; fi
    [[ -d "$candidate" && ! -L "$candidate" && $(realpath -e -- "$candidate") == "$candidate" ]] || exit 65
    python3 - "$candidate" "$release" <<'VERIFY'
import hashlib, json, pathlib, re, sys, urllib.request
root = pathlib.Path(sys.argv[1]); release = sys.argv[2]
allowed = re.compile(r'(index\.html|\.vite/manifest\.json|assets/[A-Za-z0-9_.-]+\.(?:js|css|svg|png|webp|ico|woff2?|ttf|jpg|jpeg|gif)|release\.json|checksums\.json)')
files = {}
for p in root.rglob('*'):
    if p.is_symlink(): raise SystemExit('No se aceptan symlinks en dist')
    if not p.is_file() and not p.is_dir(): raise SystemExit('Tipo de archivo no permitido')
    if p.is_file():
        name = p.relative_to(root).as_posix()
        if not allowed.fullmatch(name): raise SystemExit(f'Artefacto no permitido: {name}')
        if name != 'checksums.json': files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
if files != json.loads((root/'checksums.json').read_text()): raise SystemExit('SHA-256 incorrecto / archivos faltantes o extra')
manifest = json.loads((root/'release.json').read_text())
if manifest.get('release_id') != release or manifest.get('api_min') != '0.2.0' or manifest.get('api_max_exclusive') != '0.3.0': raise SystemExit('Contrato de release incompatible')
if f'/releases/{release}/assets/' not in (root/'index.html').read_text(): raise SystemExit('Base de assets no versionada correctamente')
with urllib.request.urlopen('http://127.0.0.1:8015/api/v1/health', timeout=10) as r: health = json.load(r)
version = tuple(int(v) for v in health.get('version','').split('.'))
if health.get('status') != 'ready' or not ((0,2,0) <= version < (0,3,0)): raise SystemExit('API no lista/incompatible; no se activa frontend')
print('Integridad y API verificadas')
VERIFY
    if [[ "$action" == activate ]]; then
      [[ ! -e "$target" && ! -L "$target" ]] || exit 73
      [[ $(stat -c %d "$stage") == $(stat -c %d "$root/releases") ]] || exit 65
      mv -T -- "$stage" "$target"
    fi
    old=
    if [[ -e "$root/current" || -L "$root/current" ]]; then
      [[ -L "$root/current" ]] || exit 65
      old=$(readlink -- "$root/current")
      [[ "$old" =~ ^releases/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ && -d "$root/$old" && ! -L "$root/$old" ]] || exit 65
    fi
    [[ ! -e "$root/.current-$token" && ! -L "$root/.current-$token" ]] || exit 65
    ln -s -- "releases/$release" "$root/.current-$token"
    mv -Tf -- "$root/.current-$token" "$root/current"
    previous=${old#releases/}
    printf 'Release activa: %s\nAnterior (ID para --rollback): %s\n' "$release" "${previous:-ninguna}"
    ;;
  *) exit 64;;
esac
REMOTE
}
cleanup() {
  local code=$?
  trap - EXIT
  if ((LOCKED)); then remote unlock || printf 'ADVERTENCIA: no se liberó lock remoto; inspeccionar antes de reintentar.\n' >&2; fi
  # Temporary output is retained on failure for diagnosis; never remove a broad path.
  if [[ -n "$LOCAL_STAGE" ]]; then printf 'Artefacto local conservado: %s\n' "$LOCAL_STAGE"; fi
  exit "$code"
}
trap cleanup EXIT

if [[ -z "$ROLLBACK" ]]; then
  command -v npm >/dev/null || die 'Falta npm en WSL de desarrollo (no en servidor).'
  [[ -f "$SCRIPT_ROOT/frontend/package-lock.json" ]] || die 'Falta frontend/package-lock.json; generar y revisar lockfile antes de desplegar.'
  (
    cd -- "$SCRIPT_ROOT/frontend"
    npm ci
    npm test
    FRONTEND_BASE_PATH="/releases/$RELEASE/" npm run build
  )
  LOCAL_STAGE=$(mktemp -d -t compareforms-front.XXXXXXXX)
  python3 - "$SCRIPT_ROOT/frontend/dist" "$LOCAL_STAGE" "$RELEASE" <<'PACKAGE'
import hashlib, json, pathlib, re, shutil, sys
source, target = map(pathlib.Path, sys.argv[1:3]); release = sys.argv[3]
allowed = re.compile(r'(index\.html|\.vite/manifest\.json|assets/[A-Za-z0-9_.-]+\.(?:js|css|svg|png|webp|ico|woff2?|ttf|jpg|jpeg|gif))')
if source.is_symlink() or not source.is_dir(): raise SystemExit('dist inválido')
for p in source.rglob('*'):
    if p.is_symlink(): raise SystemExit('Symlink no permitido en dist')
    if not p.is_file() and not p.is_dir(): raise SystemExit('Tipo de archivo no permitido en dist')
    if p.is_file():
        name = p.relative_to(source).as_posix()
        if not allowed.fullmatch(name): raise SystemExit(f'Archivo inesperado en dist: {name}')
        dest = target/name; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p,dest)
if f'/releases/{release}/assets/' not in (target/'index.html').read_text(): raise SystemExit('Base de assets no coincide con release')
(target/'release.json').write_text(json.dumps({'release_id':release,'api_min':'0.2.0','api_max_exclusive':'0.3.0'},indent=2))
checksums = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
(target/'checksums.json').write_text(json.dumps(checksums,sort_keys=True,indent=2))
PACKAGE
fi
remote lock
LOCKED=1
if [[ -n "$ROLLBACK" ]]; then
  remote rollback
else
  remote prepare
  rsync -rlt --safe-links --chmod=D755,F644 \
    -e 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10' \
    -- "$LOCAL_STAGE/" "$USER_NAME@$HOST:$REMOTE_ROOT/incoming/$TOKEN/"
  remote activate
fi
printf 'Publicación estática terminada. Hacer smoke HTTPS del portal y una pestaña anterior. No se modificó backend, documentos, BD ni Roboti.\n'
