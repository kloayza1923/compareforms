# CompareForms en servidor 201

Instalado y verificado el 2026-09-09.

- Portal LAN: http://192.168.66.33:8016 (nginx y firewall permiten 192.168.66.0/24).
- API privada: 127.0.0.1:8015; servicio `compareforms.service`.
- Cola: `compareforms-worker.service`; ambos habilitados al arranque.
- Python 3.12: `/home/virtual/compareforms`. No reutilizar el venv copiado desde WSL.
- Configuración privada: `/etc/compareforms/compareforms.env`, root, modo 0600.
- PostgreSQL 17.11: contenedor `compareforms-postgres-1`, puerto 127.0.0.1:54327, volumen `compareforms_compareforms_pg`, restart unless-stopped.
- Migración aplicada: `0002_aitrol_identity`.
- Documentos de cargas: `/home/sistemas201/projects/compareforms/documents`.
- Frontend: `/home/sistemas201/projects/compareforms/frontend-runtime/current`, release `portal-20260909`.
- Nginx: `/etc/nginx/sites-available/compareforms`, enlazado en sites-enabled; no necesita un proceso Node ni otro servicio systemd para el frontend.

## Comprobaciones

120 pruebas backend y 27 frontend pasaron. HTML, JS y CSS responden 200 desde el equipo local. `/api/v1/health` devuelve ready, versión 0.2.0. La API privada responde 401 sin sesión; `.env` y manifiestos de release responden 404. `nginx -t` pasó. Los servicios API, worker y nginx están activos.

Identidad comprobada: conexión a MySQL de pruebas 192.168.66.54:3307 disponible, esquema compatible y consultas en modo solo lectura. Se corrigió nginx para conservar el puerto público con `proxy_set_header Host $http_host`; el origen del portal se acepta y un origen externo sigue rechazado.

Acceso validado: por instrucción explícita del usuario se asignó `EMPRESA PRUEBA SISTEMAS` (`0916293723001`) a `sis_convenio@mail.com` en `usuario_empresa` del MySQL local de Aitrol. Se insertó una sola relación; no se cambió el rol ni la contraseña. Login, consulta de sesión, listado de lotes y logout de CompareForms devolvieron HTTP 200. La sesión de prueba quedó cerrada.

El acceso solicitado es HTTP de LAN, con SESSION_COOKIE_SECURE=false. Si se habilita HTTPS, cambiar esta opción a true y actualizar COMPAREFORMS_PUBLIC_URL y nginx.

## Operación

```bash
sudo systemctl status compareforms compareforms-worker
sudo journalctl -u compareforms -u compareforms-worker -n 50 --no-pager
curl --fail http://127.0.0.1:8015/api/v1/health
sudo nginx -t
```

Para actualizaciones del frontend, ejecutar `deploy_front.sh` desde WSL con Node 24 y autenticación SSH configurada; compila localmente y publica estáticos versionados. No copia backend ni instala Node en 201. Para actualizaciones backend, instalar dependencias en `/home/virtual/compareforms`, revisar/aplicar migraciones con el entorno privado y reiniciar ambos servicios una vez terminados los trabajos activos. No copiar `.venv`, `.env.local` ni `ops/auth.local.env` desde WSL.
