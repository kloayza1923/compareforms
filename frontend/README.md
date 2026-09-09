# Portal CompareForms

React, TypeScript, Vite y Bootstrap empaquetado localmente. No usa CDN, telemetría, fuentes externas, tokens en localStorage ni datos clínicos de demostración. El código depende del contrato en `../implementation-contract.md`.

## Compilar únicamente en WSL local

Se recomienda Node 24.18 (el servidor 201 no requiere Node). Desde `frontend/`:

```bash
npm ci
npm test
npm run build
```

`package-lock.json` debe versionarse después de la instalación inicial de dependencias fijadas. No copiar `node_modules` al servidor. El artefacto de producción es únicamente `dist/`; el backend/proxy lo sirve en el mismo origen que `/api/v1`.

Para desarrollo local con backend en `127.0.0.1:8015`:

```bash
npm run dev
```

Si el backend usa otro puerto, configura **solo en desarrollo** `COMPAREFORMS_API_TARGET=http://127.0.0.1:PUERTO`. El proxy conserva el origen del navegador para sesión y CSRF. El backend debe admitir ese origen de desarrollo expresamente; producción debe usar HTTPS y cookies Secure. No incluir contraseñas o secretos en variables `VITE_*`.

El despliegue puede compilar con `FRONTEND_BASE_PATH=/frontend/releases/IDENTIFICADOR/` para que los assets de una pestaña anterior conserven su dirección después de publicar una nueva release. En publicación simple del primer entorno puede utilizarse `/`.

## Flujo V1

1. Login con usuario autorizado. La sesión es una cookie HttpOnly; CSRF se conserva solo en memoria.
2. Crear revisión y marcar la alternativa manual. Roboti automático permanece bloqueado con explicación.
3. Cargar ZIP original y modificado. Revisar aceptados/rechazados; confirmar las asociaciones sugeridas o asociar manualmente.
4. Iniciar con al menos un par confirmado. El alcance parcial requiere aceptación explícita.
5. Consultar progreso persistente y seleccionar paciente. Filtrar incorporados, retirados, modificados, reubicados o por revisar.
6. Abrir evidencia antes/después con páginas independientes; registrar revisión, diferencia omitida o propuesta de mejora.
7. Descargar el Excel de esa ejecución, no un archivo global «último».

## Acceso con Roboti / Aitrol

El frontend consulta `GET /api/v1/auth/config` para conocer el proveedor de autenticación. En modo `aitrol`, el formulario solicita el mismo correo y contraseña usados en Roboti/Aitrol; en modo `local` conserva el acceso de CompareForms.

Si `POST /auth/login` devuelve `requires_company: true`, todavía **no hay sesión iniciada**: el portal muestra únicamente las empresas autorizadas y exige escoger una. Al confirmar, vuelve a leer correo y contraseña directamente del formulario y envía `company_id`. La contraseña no se copia a React state, localStorage ni sessionStorage. Cambiar correo o contraseña limpia la selección de empresa; al iniciar sesión correctamente se vacían los campos y se muestra la empresa activa.

En modo Aitrol, «Usuarios y permisos» es solo de consulta. No se muestra el formulario de creación local; usuarios, altas y recuperación/cambio de contraseñas se administran en Aitrol. Los permisos efectivos y el ámbito de empresa se verifican siempre en backend, aunque se manipule la interfaz.

El visor usa el componente PDF del navegador y enlaces `#page=N`; no dibuja regiones ni compara píxeles en la interfaz. En página completa incorporada/retirada se muestra «No corresponde» en el lado inexistente. Una incorporación o retiro de datos dentro de una página puede tener referencia en ambos PDF. La detección y autorización se realizan en backend, no en controles visuales.

## Alcance honesto

- Mejoras: registro vinculado a evidencia, no edición automática de reglas ni publicación en Roboti.
- Modelos: arquitectura futura B encoder-decoder, sin modelo, entrenamiento ni inferencia neuronal nueva. Superar 1000 PDF únicos habilita solo evaluar una futura fase, sujeta a aprobación y corpus adjudicado.
- Usuarios: creación por administrador únicamente en modo local; con Aitrol, la gestión de usuarios/contraseñas permanece en el sistema de identidad. Recuperación local y MFA quedan fuera de esta V1.
- Revisiones: el historial y las observaciones manuales se leen de PostgreSQL a través del API; la confirmación de guardado no adjudica la verdad clínica ni sustituye revisión de supervisor. Se distinguen del resultado original automático.
- Los formularios PDF se sirven por endpoints autenticados. Nunca deben exponerse como archivos estáticos de `dist`.

## Pruebas

`npm test` comprueba bloqueo de cero pares, consentimiento de alcance parcial, sugerencia vs. confirmación, páginas inexistentes, paciente como primera columna, filtro por tipo, descargas por ejecución y modo manual explícito. Todos los datos en fixtures son sintéticos.

Para aceptación integral adicional: login real, ZIP real autorizado, confirmación de par, worker, descarga de Excel y revisión de evidencia en navegador. Los tests unitarios no sustituyen esa aceptación.
