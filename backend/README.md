# CompareForms V1 — backend y ensayo local

FastAPI/PostgreSQL con worker persistente para comparación manual, motor A de mínimo error y Excel descargable. React se compila en WSL; Node/node_modules no se despliegan al 201. La arquitectura futura encoder-decoder permanece deshabilitada: superar 1000 PDF únicos solo habilitaría evaluación del corpus, no entrenamiento automático.

Estas instrucciones corresponden a `/home/mdconsgroup/projects/compareforms` en WSL local. **No se ha desplegado esta V1 al servidor 201.** API local en `127.0.0.1:8027`; los ejemplos productivos de `ops/` reservan `127.0.0.1:8015` y requieren configuración/validación separada. No usar el servidor de desarrollo Vite como servicio productivo.

## 1. Entorno Python y PostgreSQL local

Desde la raíz WSL; reutilice el entorno virtual si ya existe:

```bash
cd /home/mdconsgroup/projects/compareforms
test -d backend/.venv || python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

Se requieren Docker con Compose y un daemon local disponible. `ops/compose.local.yml` fija PostgreSQL 17.11, publica solo `127.0.0.1:54327` y usa el volumen persistente `compareforms-local_compareforms_pg`. No elimina ni reutiliza bases de Roboti. No ejecutar `docker compose down -v` si desea preservar datos.

Genere `.env.local` **solo si no existe**. El comando crea una contraseña aleatoria privada y no sobrescribe un archivo existente ni muestra credenciales:

```bash
cd /home/mdconsgroup/projects/compareforms/backend
test -f ../.env.local || .venv/bin/python -m app.cli init-local-env --path ../.env.local
cd ..
docker compose --env-file .env.local -f ops/compose.local.yml -p compareforms-local up -d
docker compose --env-file .env.local -f ops/compose.local.yml -p compareforms-local ps
```

Espere a que PostgreSQL indique `healthy`. `.env.local` contiene código de asignación de shell confiable generado localmente; no copiar contenido de un ZIP ni compartir ese archivo. Mantenerlo fuera de Git, con permisos 0600. El puerto 54327 debe estar libre. Cambiar una contraseña en `.env.local` después de inicializar el volumen no modifica por sí solo la contraseña del usuario PostgreSQL existente.

## 2. Migraciones y acceso compartido con Roboti / Aitrol

```bash
cd /home/mdconsgroup/projects/compareforms/backend
source .venv/bin/activate
set -a
source ../.env.local
source ../ops/auth.local.env
set +a
alembic upgrade head
PYTHONPATH="$PWD" python scripts/probe_aitrol_identity.py
```

**Use el mismo correo y contraseña de Roboti / Aitrol; no cree otro administrador ni otra contraseña en CompareForms.** `ops/auth.local.env` activa Aitrol y apunta a `/home/mdconsgroup/projects/roboti/formsgenerator/.env`. Este último se lee como datos de configuración, sin ejecutarlo, copiarlo ni modificarlo. El probe solo comprueba conexión, columnas requeridas y modo de solo lectura; no lista usuarios ni contraseñas.

La cuenta debe estar activa, tener uno de los roles permitidos por Roboti y acceso a una empresa activa. Si tiene varias empresas, el portal solicita elegir una antes de crear sesión. Los usuarios y sus contraseñas se administran en Aitrol. La nueva membresía interna se registra en PostgreSQL al primer ingreso, sin copiar la contraseña ni su hash de Aitrol. Consulte [AUTENTICACION_AITROL.md](AUTENTICACION_AITROL.md) para roles, permisos, pruebas y límites.

El archivo local configura cookie no segura solo para HTTP en localhost; producción requiere HTTPS y `SESSION_COOKIE_SECURE=true`. CompareForms mantiene una sesión propia: compartir credenciales no implica inicio de sesión automático al entrar en Roboti.

## 3. API y worker: dos terminales

En la primera:

```bash
cd /home/mdconsgroup/projects/compareforms
bash ops/start-local.sh api
```

En otra terminal:

```bash
cd /home/mdconsgroup/projects/compareforms
bash ops/start-local.sh worker
```

`start-local.sh` no instala ni migra nada. Solo acepta WSL del usuario `mdconsgroup`, la ruta local acordada y `.env.local` privado. También exige `ops/auth.local.env` con el proveedor Aitrol; si falta, se detiene, sin cambiar silenciosamente a cuentas locales. Crea un directorio temporal privado para el proceso; si al salir contiene archivos, lo conserva e informa la ruta para revisión. El worker debe permanecer ejecutándose para procesar la cola; el API por sí solo no ejecuta las comparaciones.

Verificación de readiness:

```bash
curl --fail http://127.0.0.1:8027/api/v1/health
```

Debe devolver `status: ready`; un fallo de PostgreSQL/columnas de identidad devuelve 503. Esto no comprueba disponibilidad de Aitrol: use el probe del apartado 2. Tampoco valida exactitud del motor ni disponibilidad de Ollama/GPU.

## 4. React local y acceso del auditor

Requiere Node compatible con `frontend/package.json` y lockfile versionado. Todo `node_modules` queda únicamente en local:

```bash
cd /home/mdconsgroup/projects/compareforms/frontend
npm ci
npm test
npm run build
COMPAREFORMS_API_TARGET=http://127.0.0.1:8027 npm run dev
```

Abra `http://127.0.0.1:5173`. La variable del último comando dirige el proxy Vite a la API local 8027; no usar el puerto 8015 de los ejemplos productivos. También puede abrir `http://127.0.0.1:8027` con el build terminado y solo la API activa: FastAPI sirve `frontend/dist`. Inicie sesión con su correo/contraseña de Roboti / Aitrol, seleccione empresa si corresponde, cree un lote, active carga manual, suba los ZIP, confirme las parejas y ejecute primero **un expediente**. Descargue el Excel desde esa ejecución.

Los nombres de archivos son sugerencias, no identificadores definitivos del paciente/atención. Revise la asociación antes de confirmar. No se inicia con cero pares ni se presenta una ejecución vacía como «sin diferencias». Origen DALIA no se atribuye automáticamente a fallas de Roboti. Las páginas de Excel corresponden al contador físico de los PDF; una eliminación sin contraparte tiene página modificada no aplicable.

## 5. Evidencia, pruebas y límites de esta entrega

```bash
cd /home/mdconsgroup/projects/compareforms/backend
.venv/bin/python -m pytest -q
```

Los tests automatizados no sustituyen aceptación de un caso real con auditoría. OCR ilegible, cambios visuales y asociaciones ambiguas deben conservar advertencias/revisión; diferencias de compresión o metadatos no prueban cambios médicos. No se modifica ninguna regla de Roboti automáticamente.

**El Excel es un snapshot de la comparación al generarse.** Las confirmaciones, falsos positivos o comentarios registrados después se conservan en la base, pero no reescriben automáticamente el Excel ya generado. No presentar ese archivo anterior como una exportación actualizada de toda la revisión posterior; esta regeneración versionada es trabajo pendiente.

Los scripts y resultados legacy, incluido `run_compare.py`, se conservan para transición. Las carpetas mensuales previas no se borran ni se migran automáticamente a la base. El portal guarda cargas nuevas bajo `documents/` privado; importar resultados históricos requiere una operación explícita con trazabilidad. El botón usa el servicio/worker V1, no una línea de shell suministrada por el navegador.

## 6. Producción: aún no ejecutada

Consulte `../ops/README-deploy.md` para el gate y `bash ../deploy_front.sh --help` para publicación solo de estáticos. El deploy frontend no despliega backend/worker, no migra PostgreSQL y no copia documentos. Las plantillas TLS, permisos, servicios y los puertos deben aprobarse antes de activar 201. La integración automática Roboti requiere un contrato M2M propio aún pendiente; el flujo manual permite ensayar sin modificar Roboti.
