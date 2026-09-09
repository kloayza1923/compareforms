# CompareForms

## Portal V1 — entrega local 2026-09-07

La interfaz nueva está en `frontend/` (React + Bootstrap); FastAPI, motor A y PostgreSQL en `backend/`. Consulte **[backend/README.md](backend/README.md)** para iniciar API/worker. Los usuarios cargan ZIP, confirman paciente/pareja y descargan Excel desde el portal.

**Actualización 2026-09-08: acceso con el mismo correo y contraseña de Roboti / Aitrol.** La instalación WSL usa la misma fuente de identidad MySQL en modo de solo lectura, con empresa seleccionada y validación de permisos. No se crean contraseñas independientes en el portal. PostgreSQL conserva comparaciones, membresías y sesiones propias, no contraseñas de Aitrol. Detalles y verificación en [backend/AUTENTICACION_AITROL.md](backend/AUTENTICACION_AITROL.md). Esta actualización es local, no un despliegue al 201.

`design.md` e `implementation-contract.md` describen el alcance. `deploy_front.sh` compila localmente y publica únicamente estáticos: no instala Node en 201. Su activación productiva requiere preparar primero API, PostgreSQL, permisos y HTTPS; **no se desplegó a 201 en esta entrega**.

Se conserva el código anterior abajo por compatibilidad: `app/`, `.venv`, `run_compare.py`, meses y `deploy.sh` siguen siendo **legacy**, no son el portal V1. No ejecutar `deploy.sh` esperando publicar el portal. No se movieron ni eliminaron los PDF originales. El almacenamiento nuevo de cargas es `documents/`.

V1 usa la opción A determinista, OCR en CPU y revisión humana ante incertidumbre. No entrena modelos ni llama Ollama/GPU. La arquitectura reserva B encoder-decoder para evaluación con más de 1000 PDF únicos y anotaciones validadas; no se activa por alcanzar una cifra. La integración Roboti M2M y la aplicación automática de reglas están deshabilitadas.

## Herramienta anterior (legacy)

Servicio mensual para comparar PDF entregados por un proceso automatizado con sus versiones ajustadas. El emparejamiento, extracción, diferencias y puntajes son determinísticos. Ollama solo redacta un resumen a partir del JSON calculado.

## Estructura de datos

```text
2025_10/
  pdf_origen/
    1 - NOMBRE.pdf
  pdf_modificado/
    1 - NOMBRE.pdf
  results/                   # generado
```

Cada archivo se empareja por el prefijo numérico. Los índices duplicados producen error y los faltantes quedan registrados. Los PDF nunca se modifican.

## Instalación y ejecución

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a; source .env; set +a
python run_compare.py 2025_10
```

Para una ejecución sin Ollama:

```bash
python run_compare.py 2025_10 --no-ollama
```

Para validar uno o varios expedientes antes de lanzar el mes completo:

```bash
python run_compare.py 2025_10 --indices 6
python run_compare.py 2025_10 --indices 6,30,35
```

El manifiesto etiqueta estas corridas como `selected_indices`, para no confundirlas con un mes completo.

El proceso genera `comparison_details.json`, `comparison_summary.csv` y `comparison_summary.xlsx` dentro de `results/`. Los tres reportes registran tokens enviados, recibidos y totales consumidos por Ollama para cada expediente.

## Ollama

El modelo predeterminado es `gemma4:e2b-it-qat`. Debe estar instalado en el servidor y disponible en `OLLAMA_URL`. El servicio envía únicamente métricas agregadas anonimizadas con identificadores de evidencia; nunca nombres, cédulas, diagnósticos ni extractos clínicos. Una respuesta inválida tiene un reintento y luego usa un resumen determinístico.

## API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- `GET /health`
- `GET /months`
- `POST /months/{YYYY_MM}/run` con `{"use_ollama": true}`
- `GET /months/{YYYY_MM}/results`
- `GET /months/{YYYY_MM}/results/{index}`

La API escucha solamente en `127.0.0.1`; publíquela mediante un proxy autenticado si se requiere acceso remoto. La ejecución HTTP es síncrona. Para volúmenes grandes, configure el proxy con un timeout suficiente o ejecute el CLI.

Antes de comparar, el CLI/API comprueba que Ollama y `gemma4:e2b-it-qat` estén disponibles. Nunca descarga modelos automáticamente. Use `--no-ollama` cuando solo necesite los resultados determinísticos.

Ollama selecciona automáticamente la GPU NVIDIA disponible. Durante una ejecución puede confirmarlo con `ollama ps`: la columna `PROCESSOR` debe mostrar GPU (idealmente `100% GPU`) y no `100% CPU`.

## Despliegue

`deploy.sh` usa `rsync` y `ssh`. No copia `.env` ni carpetas mensuales salvo que `INCLUDE_MONTHS=1`; no contiene credenciales.

```bash
export DEPLOY_HOST=servidor
export DEPLOY_USER=usuario
export DEPLOY_PATH=/home/sistemas201/projects/compareforms
# export PYTHON_BIN=python3.12  # si el servidor ofrece varias versiones
# export INCLUDE_MONTHS=1       # solo si también desea copiar carpetas mensuales
# export RESTART_COMMAND='systemctl --user restart compareforms'
bash deploy.sh
```

Por defecto no reinicia servicios y no copia carpetas mensuales. Cree y proteja `.env` directamente en el servidor.

## Limitaciones

- En Linux usa Poppler y Tesseract (`spa`) para páginas con poco texto. Registra páginas OCR aplicadas y pendientes; si falta un binario continúa y deja advertencia.
- El componente visual servidor-seguro compara geometría y rotación, no píxeles. Puede ampliarse con Poppler como dependencia del sistema.
- Importes, fechas, identificadores, códigos diagnósticos y términos de firma se detectan con expresiones regulares y pueden tener falsos positivos.
- Los puntajes sirven para priorizar revisión; no determinan corrección clínica, contractual ni legal.

## Pruebas

```bash
python -m pytest -q
```
