# Acceso compartido: CompareForms, Roboti y Aitrol

Implementación local · 2026-09-08. Ruta: `/home/mdconsgroup/projects/compareforms`.

## Para el auditor

1. Inicie CompareForms con su **correo y contraseña habituales de Roboti / Aitrol**.
2. Si tiene varias empresas autorizadas, seleccione la empresa con la que trabajará. Todavía no hay sesión antes de elegirla.
3. La empresa activa aparece en la cabecera. Para cambiarla, cierre sesión e ingrese nuevamente.
4. Solicite altas, recuperación de contraseña y permisos al administrador de Aitrol; no cree otra cuenta en CompareForms.

Es acceso con las mismas credenciales, **no SSO**: estar conectado a Roboti no inicia automáticamente una sesión en CompareForms. El portal tiene su propia cookie y sesión. Los datos anteriores de cuentas locales no se reasignan por coincidencia de correo; eso requeriría una migración de titularidad autorizada.

## Fuente y reglas verificadas en el código de Roboti

Se revisaron `app/repository.py`, `app/main.py`, `app/db.py`, `app/core/config.py` y `tests/test_repository_auth.py` de `/home/mdconsgroup/projects/roboti/formsgenerator`.

| Control | Implementación en CompareForms |
|---|---|
| Cuenta | `users.email` sin distinguir mayúsculas; `estado=1`. Si hay dos cuentas activas con el mismo correo, se rechaza la ambigüedad. |
| Contraseña | Comprobación bcrypt compatible con Roboti y hashes PHP `$2y$`. No se añade una política de longitud mínima que invalide contraseñas existentes. |
| Rol fuente 1 | Administrador en CompareForms; empresas activas de Aitrol. |
| Roles fuente 11 y 22 | Auditor en CompareForms; únicamente empresas activas asociadas mediante `usuario_empresa`. No se les concede administración. |
| Otros roles | Acceso rechazado, como en Roboti. |
| Revalidación | Cada solicitud autenticada comprueba estado, rol y acceso a la empresa. Una caída de Aitrol devuelve 503; no habilita cuentas locales. |
| Usuarios del portal | La pantalla muestra membresías que ya ingresaron a esa empresa, no todo el directorio de Aitrol. Es de solo consulta en este modo. |

No se consulta `deleted_at`: el código y las pruebas actuales de Roboti usan el esquema legado sin esa columna. El rol supervisor del portal no se asigna automáticamente a ningún rol de Aitrol; requiere una definición posterior explícita.

## Qué se guarda y qué no

La conexión MySQL se inicia en modo de transacción de solo lectura. El adaptador solo contiene consultas `SELECT` de identidad y empresas; no genera formularios ni cambia datos de Aitrol. Este modo no sustituye una cuenta de base de datos con privilegios mínimos: la revisión de grants y TLS es un requisito de producción.

PostgreSQL conserva el identificador externo del usuario, correo, empresa, rol efectivo, membresía y sesiones propias, además de la información documental del portal. **No persiste la contraseña ni el hash bcrypt externo.** Los usuarios externos tienen un marcador no utilizable como contraseña local. Las cuentas locales anteriores se conservan como antecedentes, pero no autentican cuando el proveedor es Aitrol.

No se comparten cookies de Roboti, su almacén de sesiones, `AITROL_APP_ID`, `AITROL_APP_TOKEN` ni secretos de proxy. La autenticación humana no habilita el contrato M2M de generación de formularios, que sigue pendiente.

## Configuración local ya aplicada

`ops/auth.local.env` contiene exclusivamente estas asignaciones no secretas y debe permanecer como archivo confiable, privado y fuera de Git:

```dotenv
COMPAREFORMS_AUTH_PROVIDER=aitrol
AITROL_ROBOTI_ENV_FILE=/home/mdconsgroup/projects/roboti/formsgenerator/.env
```

`ops/start-local.sh` carga `.env.local` de CompareForms y después este archivo. Rechaza configuración faltante o un proveedor distinto de Aitrol. No cambie `.env.local` para copiar contraseñas de usuarios. Reinicie una API/worker que estuvieran ejecutando la versión anterior para que carguen el código actualizado.

El adaptador lee el `.env` de Roboti **como datos**, sin `source`, importaciones de su aplicación ni evaluación de shell. Usa `DB_PROFILE` y los campos `DB_*` o `SOURCE_DB_*` correspondientes. No copia el archivo ni propaga sus otras variables al entorno de CompareForms. Los valores de conexión deben estar resueltos: `${VARIABLE}` no se expande silenciosamente.

Esta integración lee el archivo indicado; no inspecciona posibles sobrescrituras de variables en un proceso/servicio ya iniciado de Roboti. Si Roboti usa otra configuración efectiva, el administrador debe alinear explícitamente la fuente. No debe apuntarse a una base productiva suponiendo que el perfil local es productivo.

**Una instalación PostgreSQL se vincula a una única fuente Aitrol estable.** No reutilice esa misma base de CompareForms cambiando entre MySQL de pruebas y producción: los ID externos de ambas fuentes podrían coincidir. Use bases/almacenamiento separados o una migración de identidades revisada. La V1 no implementa múltiples emisores de identidad en una misma instalación.

### Comprobación sin consultar cuentas

```bash
cd /home/mdconsgroup/projects/compareforms/backend
set -a
source ../.env.local
source ../ops/auth.local.env
set +a
.venv/bin/alembic upgrade head
PYTHONPATH="$PWD" .venv/bin/python scripts/probe_aitrol_identity.py
```

Resultado esperado: `identity_source=aitrol`, `schema=compatible`, `transaction=read_only`. El script comprueba columnas con `LIMIT 0`; no lista cuentas ni hashes. Ante fallo solo muestra etapa/código MySQL, nunca la cadena de conexión ni errores completos con secretos. `/api/v1/health` comprueba PostgreSQL y columnas de identidad; no prueba Aitrol.

Para iniciar API e interfaz compilada:

```bash
cd /home/mdconsgroup/projects/compareforms
bash ops/start-local.sh api
```

Abra `http://127.0.0.1:8027`. Para procesar comparaciones, mantenga además `bash ops/start-local.sh worker` en otra terminal. Node solo se usa al compilar el frontend local; no es necesario para servir `dist` desde FastAPI.

## Sesiones y límites de seguridad

- Sesión propia de hasta 8 horas, cookie HttpOnly/SameSite Strict y protección CSRF para mutaciones. HTTPS y cookie Secure son obligatorios fuera del ensayo en localhost.
- Diez intentos por correo en una ventana de 15 minutos producen bloqueo temporal. En producción, complemente con límites de IP/capacidad en el proxy y vigilancia de abuso.
- Estado, rol y empresa se revalidan en cada petición. La baja en Aitrol impide continuar; el cierre de sesión propio funciona incluso si Aitrol está caído.
- Cambiar únicamente la contraseña en Aitrol **no revoca automáticamente sesiones ya abiertas**; no se conserva el hash para comparar cambios ni existe un evento central de revocación. Para una baja inmediata, desactive la cuenta/permiso y revoque sesiones operativamente. Un contrato central de revocación/SSO sería una ampliación independiente.

## Evidencia y entrega

- Migración PostgreSQL local `0002_aitrol_identity` aplicada; verificación Alembic sin cambios de esquema pendientes. No modifica tablas MySQL.
- Conexión real a la fuente configurada por Roboti comprobada con esquema compatible y sesión de solo lectura. No se usaron contraseñas humanas reales.
- Pruebas automatizadas de autenticación: bcrypt PHP, estados/roles, empresas, aislamiento entre organizaciones, revocación, caída sin fallback, ausencia de contraseñas externas en PostgreSQL y cierre de sesión durante caída. Interfaz: selector de empresa, límites de correo, gestión de usuarios y preservación del modo local explícito para compatibilidad.
- Build React/TypeScript verificado en WSL; `frontend/dist` actualizado. Falta aceptación de un inicio de sesión real por un auditor autorizado; no es necesario compartir su contraseña con el desarrollador.
- No se desplegó esta actualización al 201. Allí deben verificarse la ruta/configuración real de Roboti, lectura mínima del secreto por la cuenta de servicio, privilegios MySQL, canal privado/TLS, PostgreSQL, HTTPS y acceso real antes de activar.

Para el servicio dedicado de producción, es preferible un archivo privado con **solo** la conexión de lectura de identidad y un usuario MySQL con permisos mínimos a las tablas requeridas, en vez de conceder lectura del `.env` completo de otro proyecto. Aprovisionarlo requiere al administrador; no se copian tokens M2M ni se cambian grants automáticamente. No publique el backend con proveedor local por omisión: configure explícitamente `COMPAREFORMS_AUTH_PROVIDER=aitrol` y `AITROL_ROBOTI_ENV_FILE` en su entorno de servicio.
