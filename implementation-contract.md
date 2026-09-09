# Contrato de implementación V1

Raíz de autoría: compareforms_project (Windows). Copia final al mismo proyecto WSL; no escribir sobre los originales ni desplegar al 201 en esta etapa.

Usuario eligió A funcional y reserva futura B encoder-decoder (renombrada respecto de alternativas anteriores). Más de 1000 PDF únicos es condición para evaluar ML, no autoentrenamiento. No crear modelo ni usar dependencias ML ahora.

## Backend / frontend

API mismo origen `/api/v1`; cookie sesión HttpOnly y cabecera `X-CSRF-Token` para mutaciones autenticadas. `GET /auth/config` público devuelve `{provider:"aitrol"|"local",password_management:"aitrol"|"local"}`. La instalación WSL usa `aitrol`, la misma fuente de Roboti; local solo compatibilidad/pruebas explícitas.

`POST /auth/login` JSON `{username,password,company_id?}`; `username` es el correo de Aitrol. Con varias empresas y sin elección devuelve `{requires_company:true,companies:[{id,name}]}`, sin sesión. Reenviar credenciales y empresa seleccionada crea sesión. Con una empresa se selecciona automáticamente. Acceso válido devuelve `{user:{id,username,role,organization_id,auth_provider,company_id,company_name},csrf_token}`. `GET /auth/me` misma respuesta. `POST /auth/logout` revoca la sesión propia aun si Aitrol está caído, conservando control CSRF. Nunca compartir la cookie de Roboti ni sus tokens M2M.

- GET/POST `/batches`: lista directa `[]`; crear `{name,period,source_mode:"manual"|"roboti",source_system:"dalia"|"manual_otro"|"roboti"}`. Batch `{id,name,period,status,source_mode,source_system,created_at}`.
- POST `/batches/{id}/uploads?side=original|modified` multipart `file` ZIP. Retorna inventario. Solo manual disponible V1; roboti devuelve bloqueo explícito.
- GET `/batches/{id}/inventory` -> `{documents:[{id,side,original_name,patient_name}],pairs:[{id,patient_name,original_id,modified_id,confirmed}],unpaired:[document],rejections:[{name,reason}],can_run:bool}`.
- POST `/batches/{id}/pairs` JSON `{original_id,modified_id,patient_name}` confirma/asocia; DELETE `/batches/{id}/pairs/{pair_id}` desasocia. Parejas sugeridas por nombre necesitan confirmación explícita.
- POST `/batches/{id}/runs` JSON `{allow_partial:bool}` cabecera `Idempotency-Key` -> 202 `{id,status}`. Cero pares confirmados =>422; faltantes sin allow_partial=>422.
- GET `/runs` lista; GET `/runs/{id}` -> `{id,batch_id,status,completed,total,error,report_available,cases:[{id,patient_name,original_id,modified_id,status,comparison}]} `.
- GET `/runs/{id}/report` descarga Excel autorizado.
- GET `/documents/{id}/content` PDF autenticado; frontend puede iframe con fragment `#page=N`.
- POST `/runs/{run_id}/cases/{case_id}/reviews` `{finding_id,decision:"confirmed"|"false_positive"|"needs_review",comment}`.
- POST `/runs/{run_id}/cases/{case_id}/findings` `{description,before,after,page_original?,page_modified?,change_type}` hallazgo manual.
- GET/POST `/improvements`: listar/crear `{run_id,case_id,finding_id,description,expected_benefit}`. Propuesta sin aplicación automática; nunca muta Roboti.
- GET `/users` admin: consulta de membresías ya registradas en esta empresa, no directorio completo de Aitrol. POST `/users` bloqueado en modo Aitrol; altas/cambios en Aitrol. En compatibilidad local únicamente, crear `{username,password,role}` misma organización. Fuente rol1 → admin; roles11/22 → auditor. Supervisor queda reservado a un futuro contrato explícito de permisos.
- GET `/capabilities` -> `{roboti:{enabled:false,reason},ml:{enabled:false,architecture:"encoder_decoder",unique_pdf_count,threshold:1000,eligible_for_evaluation:bool,reason}}`.

Errores `{"detail":"texto legible"}`. IDs UUID. Estados run queued/running/completed/partial/failed/cancelled. Usuario no autorizado 401/403/404. Los filenames nunca son rutas públicas ni claves de emparejamiento definitivas.

## Motor y Excel (agente dev motor)

Crear backend/app/comparison.py con `compare_documents(original: Path, modified: Path, *, ocr_enabled: bool = True) -> dict`.
Resultado: `{status, pages_original:int,pages_modified:int,pages_added:int,pages_removed:int,pages_relocated:int,findings:[],page_map:[],limitations:[],engine_version:str}`.
Status `with_differences`, `no_differences_detected`, `inconclusive`.
Finding `{id,change_type:"added"|"removed"|"modified"|"relocated"|"review",category,description,before,after,page_original:int|null,page_modified:int|null,confidence,review_required:bool}`.
page_map `{page_original:int|null,page_modified:int|null,status,similarity}`.
No truncar resultados silenciosamente. Ambigüedad/OCR ilegible=>inconclusive. Reordenación global uno-a-uno; scipy.optimize.linear_sum_assignment con dummies/unmatched. Clasificar cambios de líneas/montos sin mostrar fragmentos OCR absurdos como importes confirmados. Comparación visual conservadora si implementable; no afirmar autenticidad.

Crear backend/app/reporting.py con `write_report(path:Path, *, period:str, run_id:str, cases:list[dict], status:str) -> Path`.
cases cada `{id,patient_name,original_id,modified_id,status,comparison}`. Paciente primero en todas las tablas, filtros por tipo, antes/después y páginas como columnas distintas. Añadido página origen n/a; retirado página modificado n/a. Usar openpyxl para runtime Python solicitado, no Node en servidor. Generador valida contenido y estructura; comprobación visual se hará local. Tests nuevos solo test_comparison_v1.py y test_reporting_v1.py.

## Propiedad

- dev frontend: solo frontend/.
- dev motor: backend/app/comparison.py, reporting.py, tests específicos.
- raíz: config/db/auth/API/jobs/storage/migrations/CLI/docs/ML interfaces y sincronización WSL.
- test y senior: revisiones independientes, tests adicionales sin pisar archivos.
- deploy: deploy_front.sh/ops después de contratos de runtime.
