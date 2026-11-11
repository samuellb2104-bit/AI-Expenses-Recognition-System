# CLAUDE.md

Guía para Claude Code en este repositorio. Para detalle de endpoints, OCR, extracción y reportes, lee primero el `README.md` de la raíz; no lo dupliques aquí.

## Descripción del proyecto

**Expenses Organizer (AI Expenses Recognition System)**: SaaS multi-tenant donde una empresa sube facturas/recibos (PDF o foto) y Claude extrae proveedor, montos y fecha mediante visión + salida JSON estructurada. Cada documento se vincula automáticamente a un proveedor (`Vendor`) y permite organizar el gasto por categoría (`ExpenseCategory`), con reportes de totales. Escala de un archivo a lotes de 50+ usando la Message Batches API de Anthropic (decisión deliberada para no sobrecargar un backend pequeño de un solo worker).

Objetivos del proyecto:
- **Piloto con una empresa real**: hospedado centralmente por Samuel; la empresa entra como un nuevo `Company` (tenant) en el mismo proyecto de Supabase. **No** se empaqueta con Docker/on-prem para el cliente (decisión cerrada; solo se revisa si hay una venta real o exigencia de soberanía de datos).
- **Portafolio** de Samuel: favorecer resultados pulidos y demostrables (GIF/demo, README claro).

### Stack

- **Backend** (`expenses_organizer/backend/`): Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL en Supabase, Supabase Storage, Tesseract + Poppler (OCR), Anthropic API (`claude-haiku-4-5` por defecto).
- **Frontend** (`expenses_organizer/frontend/`): React 19 + TypeScript + Vite, `@supabase/supabase-js` para login, gráficas hechas a mano en CSS (sin librería de charts).
- **Auth**: Supabase Auth, sin registro público. El backend valida el token contra `GET {SUPABASE_URL}/auth/v1/user` (`app/services/auth_service.py`, `app/api/deps.py::get_auth_context`) y reutiliza el UUID de Supabase como `users.id`.
- **Despliegue**: backend en **Render** (usa el `Dockerfile`, Root Directory `expenses_organizer/backend`; Railway fue abandonado por problemas de propagación de variables de entorno), frontend en **Vercel**.

### Arquitectura (resumen)

Flujo: subida → (OCR opcional, ya no es default) → extracción con Claude (siempre corre; es el único paso que produce `vendor_name`, `total_amount`, etc.) → vinculación automática de proveedor → categoría por defecto según proveedor → reportes. Subidas grandes se procesan vía Message Batches. Hay auto-recuperación de documentos atascados en `uploaded`/`processing`.

Backend por capas en `backend/app/`: `api/` (routers delgados), `core/` (settings), `db/` (sesión, seed, scripts), `models/`, `schemas/`, `services/` (lógica de negocio), `tests/`.

## Comandos

```powershell
# Backend (desde expenses_organizer/backend)
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --reload          # OJO: es main:app, no app.main:app
python -m pytest                   # suite del backend
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
python -m app.db.seed              # datos semilla
python -m app.db.create_admin_user # crea cuentas (interactivo, usa getpass)

# Frontend (desde expenses_organizer/frontend)
npm install
npm run dev
npm run build                      # tsc -b && vite build
npm run lint                       # oxlint
```

## Convenciones

- Python con 4 espacios, `snake_case`; modelos en singular (`Document`), tablas en plural minúscula (`documents`). Routers pequeños; la lógica va en `services/`.
- Tests con `pytest` en `backend/app/tests/test_*.py`, cerca de la funcionalidad que cubren.
- Mensajes de commit cortos e imperativos. **No** agregar el trailer `Co-Authored-By: Claude` en commits de este repo (el historial queda a nombre de Samuel).
- Nunca commitear secretos. `.env` (backend y frontend) está en `.gitignore`.
- Todo router debe derivar `company_id`/`user_id` del `AuthContext` verificado; **no** aceptar `company_id` del cliente ni reintroducir `VITE_COMPANY_ID`/`VITE_USER_ID`. Las operaciones por ID (borrar, clasificar, actualizar) deben comprobar pertenencia a la empresa (anti-IDOR).
- Validar las funcionalidades contra servicios reales (Supabase, Anthropic) con documentos de muestra reales, no solo mocks.
- Supabase: usar el connection string del **pooler** (modo Transaction, puerto 6543); la conexión directa solo resuelve por IPv6.

## Pasos que faltan para terminar el proyecto

Estado: backend, frontend, auth, lotes, filtros, vista de proveedores y previsualización de archivos están implementados. Lo pendiente es llevarlo a producción y pulirlo para el piloto/portafolio. Verifica el estado real antes de marcar algo como hecho.

### 1. Reactivar el despliegue — HECHO el 2026-11-11 (Supabase restaurado con sus 950 documentos, API key de Anthropic nueva, Render redesplegado, subida y extracción verificadas en producción). Solo queda la prevención de pausas.
- [ ] **Supabase**: el proyecto está pausado (plan gratuito). Restaurarlo desde el dashboard (Restore project) y esperar a que quede activo. Si ya pasó la ventana de restauración, habrá que crear un proyecto nuevo, correr `alembic upgrade head`, crear el bucket de Storage `documents` y recrear usuarios/`Company` (se pierden los datos).
- [ ] Tras restaurar, revisar si cambiaron credenciales/URLs: `DATABASE_URL` (pooler, puerto 6543), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` y la anon key. Actualizar `backend/.env` local, las variables de Render (backend) y las de Vercel (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE_URL`). Después de cambiar variables en Vercel hay que **redesplegar** el frontend (se compilan en el build).
- [ ] **Anthropic**: la `ANTHROPIC_API_KEY` venció/fue revocada. Crear una nueva en console.anthropic.com, revisar saldo/límites y ponerla en `.env` local y en Render. Verificar también que `ANTHROPIC_MODEL` siga siendo válido.
- [ ] Confirmar que `CORS_ALLOW_ORIGINS` en Render incluye la URL real de Vercel.
- [ ] Probar el flujo completo en producción: login, subida individual y por lote, extracción, clasificación, reportes, previsualización.
- [ ] Evitar que se repita: el plan gratuito de Supabase pausa proyectos inactivos; para el piloto considerar el plan Pro o un ping periódico a `/health/db`.
- [ ] Revisar el tamaño del pool de conexiones y el plan de Render/Supabase frente a ráfagas de subida masiva.
- [ ] Confirmar que los archivos subidos persisten en Supabase Storage (no en disco efímero de Render).

### 2. Onboarding de la empresa piloto
- [ ] Crear el `Company` y `CompanyMember` de la empresa piloto y sus cuentas con `python -m app.db.create_admin_user`.
- [ ] Verificar aislamiento entre tenants con datos reales de dos empresas.
- [ ] Definir el procedimiento de soporte/feedback con la empresa y cómo se cubre el costo de la API de Anthropic durante el piloto (~$0.003-0.004 USD por documento con Haiku).

### 3. Calidad y robustez
- [ ] Ampliar pruebas: no hay pruebas de frontend; considerar pruebas de la ruta de auth y de los reintentos/auto-recuperación de documentos atascados.
- [ ] Manejo claro de errores en el frontend (fallos de extracción, token expirado, límites de la API).
- [ ] Revisar límites de tamaño/tipo de archivo y validaciones de subida.
- [ ] Considerar CI (pytest + `npm run build` + lint) en GitHub Actions.

### 4. Documentación y portafolio
- [x] ~~GIF de demo~~: descartado (la empresa piloto ya aprobó el proyecto).
- [x] README reordenado y `.env.example` restaurado (2026-11-11).
- [ ] Actualizar `expenses_organizer/AGENTS.md` (menciona `app.main:app` y "tests una vez agregados", ya desactualizado) o eliminarlo a favor de este archivo.
- [ ] Capturas de pantalla y una breve explicación de decisiones de arquitectura (Message Batches, multi-tenant, auth remota).

### 5. Ideas opcionales (después del piloto)
- Exportar reportes a CSV/Excel; más gráficas o filtros por rango de fechas en reportes.
- Roles/permisos dentro de una empresa; invitación de usuarios sin usar el script.
- Empaquetado Docker/on-prem **solo** si hay una venta real o requisito de soberanía de datos.

## Notas de mantenimiento

- `Learning-Roadmaps/` está sin versionar y no forma parte de la app.
