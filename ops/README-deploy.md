# Operación y despliegue V1 — sin Node en 201

Estos archivos son plantillas y herramientas entregadas para ensayo. **No ejecutan ni acreditan un despliegue productivo.** Antes de activar 201 se requiere gate sénior, respaldo/restauración, inventario de puertos, HTTPS, usuarios y aceptación de un expediente. El modo inicial es carga manual; Roboti M2M y entrenamiento siguen deshabilitados.

## Contrato de runtime

- Local WSL: `/home/mdconsgroup/projects/compareforms`; Node compatible con `frontend/package.json`, `npm`, `python3`, `ssh` y `rsync`.
- Destino permitido: `sistemas201@192.168.66.33`, `/home/sistemas201/projects/compareforms/frontend-runtime`. El script rechaza otros destinos; no permite rutas arbitrarias.
- 201 requiere Python3, Bash, rsync, utilidades GNU, API/worker y proxy; **no necesita npm, Node ni node_modules**.
- API V1: `backend/.venv/bin/uvicorn app.main:create_app --factory`, bind privado `127.0.0.1:8015`; worker independiente `backend/.venv/bin/python -m app.worker`.
- `GET /api/v1/health` público y sin datos personales debe retornar HTTP200, `status=ready` y versión `>=0.2.0,<0.3.0`. La verificación comprueba readiness real de la BD/migración declarada por el backend; no sustituye smoke de contratos. Cambiar versión exige revisar backend/frontend juntos.
- Nginx termina HTTPS, publica únicamente HTML/assets y envía `/api/v1/` a FastAPI. PDF/XLSX siempre se obtienen por endpoints autenticados; nunca exponer `documents` con alias.
- `SESSION_COOKIE_SECURE=true` en producción. Configurar `DATABASE_URL`, `COMPAREFORMS_DATA_ROOT=/home/sistemas201/projects/compareforms/documents` y `COMPAREFORMS_PUBLIC_URL=https://<dominio-aprobado>` en `/etc/compareforms/compareforms.env`, propiedad root y permisos0600. No versionar ni copiar `.env` mediante el frontend. Las rutas de runtime requieren permisos específicos; no usar `chmod -R 777`.
- **Identidad Aitrol/Roboti (actualización 2026-09-08):** configurar explícitamente `COMPAREFORMS_AUTH_PROVIDER=aitrol` y `AITROL_ROBOTI_ENV_FILE` con una ruta privada verificada en ese servidor. Provisionar lectura mínima para la cuenta de servicio, sin exponer el `.env` de Roboti ni reutilizar tokens M2M. Aplicar migración `0002_aitrol_identity` y ejecutar el probe de identidad antes de activar; comprobar acceso real por empresa. No usar bootstrap de contraseñas locales. Consulte `../backend/AUTENTICACION_AITROL.md`; esta integración solo se verificó en WSL local.

Los servicios de ejemplo emplean una cuenta dedicada `compareforms`. Antes de instalarlos, el administrador debe crear la cuenta y concederle lectura del código/venv, recorrido de directorios antecesores y escritura solo en documentos y almacenamiento temporal. Nginx solo necesita lectura del árbol `frontend-runtime` y recorrido de sus antecesores, no lectura de PDFs o secretos. La cuenta SSH existente `sistemas201` no ofrece separación fuerte frente a otros proyectos de ese mismo usuario: para endurecimiento productivo, aprobar una identidad de publicación limitada al árbol frontend y actualizar el script por revisión, no ampliar permisos de todos los proyectos.

## Publicar el frontend desde WSL

```bash
cd /home/mdconsgroup/projects/compareforms
bash deploy_front.sh --host 192.168.66.33 --user sistemas201 --dry-run
bash deploy_front.sh --host 192.168.66.33 --user sistemas201
```

El modo `--dry-run` muestra el plan **sin build, SSH ni escrituras remotas**; no certifica conectividad ni permisos. El modo real ejecuta `npm ci`, tests y build locales (requiere lockfile revisado), valida una lista estricta de archivos estáticos y envía únicamente el contenido de `dist` más manifiestos SHA-256/compatibilidad. Las versiones fijadas/lockfile y el build no garantizan que el bundle no contenga secretos: revisar código y variables de build; ningún `VITE_*` puede ser secreto.

SSH exige autenticación por clave/agent, `BatchMode=yes` y `StrictHostKeyChecking=yes`. Verificar la huella por canal confiable antes de registrar la clave del host. El script no almacena ni solicita contraseña ni acepta automáticamente claves desconocidas.

La transacción remota usa un lock exclusivo: ningún segundo despliegue/rollback puede avanzar mientras exista `.deploy-lock`. Se verifican usuario, ruta canónica sin symlinks, entradas y checksums. Se envía a `incoming/<token>`, verifica API y mueve a `releases/<release-id>` en el mismo filesystem; finalmente cambia `current` con rename atómico. No se sobrescriben releases ni se usa `rsync --delete`. El trap intenta liberar solo su propio lock. Si se interrumpe abruptamente, puede quedar lock/entrada temporal: **no borrarlos automáticamente**; verificar que no exista despliegue activo, conservar diagnóstico y pedir intervención del administrador.

Estructura de producción:

```text
frontend-runtime/
├── releases/20260907T220000Z-abc12345/
│   ├── index.html
│   ├── assets/
│   ├── .vite/manifest.json
│   ├── release.json
│   └── checksums.json
├── current -> releases/20260907T220000Z-abc12345
└── incoming/
```

El build usa `FRONTEND_BASE_PATH=/releases/<release-id>/`. Una pestaña abierta antes del despliegue sigue accediendo a sus propios JS/CSS gracias al location versionado del proxy. El HTML se revalida. La plantilla Nginx solo publica assets permitidos y el index actual; los manifiestos no se publican. Las releases se retienen: definir una ventana operativa de retención y una limpieza revisada por separado. El despliegue no elimina ninguna. El directorio temporal local de empaquetado también se conserva y se muestra al salir; contiene solo artefactos frontend.

ID determinista opcional (debe ser nuevo y no se sobreescribe):

```bash
bash deploy_front.sh --release portal-v1-ensayo01
```

## Rollback del frontend

Usar el ID informado como anterior en una publicación, inspeccionado previamente:

```bash
bash deploy_front.sh --rollback portal-v1-ensayo01 --dry-run
bash deploy_front.sh --rollback portal-v1-ensayo01
```

Rollback no compila ni transfiere: verifica integridad/API de la release existente y conmuta `current` bajo el mismo lock. No revierte backend ni BD. Si la API no es compatible, **se rechaza**, y se necesita un plan conjunto; no forzar symlinks a mano ni prometer reversión de datos por cambiar HTML.

## Gate de operación backend/worker

`deploy_front.sh` no modifica `deploy.sh`, servicios, PostgreSQL, documentos ni Roboti. El primer corte backend necesita un plan separado: detener nuevas ejecuciones, drenar/checkpointar worker, respaldo consistente de BD+archivos con manifiesto, ensayo de restauración aislada, migración expand/contract revisada, activación y readiness. Preservar meses y resultados legacy; no renombrar ni borrar documentos como efecto de publicar código. Cambios de payload/lease necesitan compatibilidad con trabajos existentes, no solo una versión HTTP.

Los `.service.example` y `.conf.example` no se instalan automáticamente. Antes de usarlos, verificar puerto8015 libre, rutas/venv/dependencias reales, permisos y límites de subida, certificado/DNS, disponibilidad PostgreSQL/OCR/Ollama, políticas de logs y retención. El OCR usa CPU; Ollama usa la GPU NVIDIA del servidor, no un proceso Node. Readiness del portal no prueba disponibilidad GPU; los resultados deben conservar limitaciones del motor.

## Smoke y evidencia pendientes en 201

1. Validar sintaxis de proxy con `nginx -t` y unidades con `systemd-analyze verify` después de adaptar/provisionar rutas reales. No reiniciar servicios ajenos.
2. Abrir HTTPS, iniciar sesión, cargar ZIPs de un expediente y confirmar asociación; cerrar/reabrir navegador sin perder el job.
3. Revisar paciente, filtros añadido/retirado/cambiado, páginas físicas y enlaces al PDF modificado; descargar el Excel de esa ejecución.
4. Verificar que usuario ajeno no descargue PDF/Excel, CSRF se rechace y errores/0 pares nunca muestren «sin diferencias».
5. Mantener una pestaña anterior abierta, publicar nueva release y abrir un recurso antiguo: ningún JS/CSS devuelve404; luego ensayar rollback compatible.
6. Documentar ID/hash/versión, resultados del smoke y responsable de aceptación. Un build local o una simulación no acreditan estos puntos.

## Verificación local reproducible del script

```bash
bash -n deploy_front.sh
bash deploy_front.sh --help
bash deploy_front.sh --dry-run
bash deploy_front.sh --rollback prueba-segura --dry-run
# Deben fallar sin SSH:
bash deploy_front.sh --host otro-host --dry-run
bash deploy_front.sh --rollback ../escape --dry-run
```

Los checks de sintaxis/simulación son ensayos no mutantes; activación, bloqueo remoto, permisos, Nginx y rollback reales requieren un entorno autorizado y no se declaran probados solo por esos checks.
