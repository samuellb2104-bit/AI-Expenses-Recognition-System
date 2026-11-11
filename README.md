# Expenses Organizer (AI Expenses Recognition System)

Multi-tenant SaaS where a company drags in invoices/receipts (PDF or photo) and
Claude extracts vendor, amounts, and date via vision + structured JSON output,
auto-linking each document to a vendor and letting users organize spend by
category with summary reports. Scales from a single file to bulk batches of
50+ documents using Anthropic's Message Batches API instead of processing
everything synchronously — a deliberate architecture choice made to keep
per-document latency low without overloading a small single-worker backend.

**Stack:** Python, FastAPI, PostgreSQL (Supabase), SQLAlchemy + Alembic,
Anthropic Claude API (vision, structured outputs, Message Batches), Tesseract
OCR (optional), React, TypeScript, Vite, Supabase Auth + Storage, Docker,
Render + Vercel.

---

## Funcionalidades

- **Subida de documentos**: uno, varios o carpetas completas (arrastrar y soltar). PDFs e imágenes.
- **Extracción con Claude**: proveedor (`vendor_name`, NIT), fecha, total, impuesto, moneda, líneas de detalle y notas, como JSON estructurado.
- **Organización**: cada documento se vincula automáticamente a un proveedor y a una categoría de gasto; ambos se pueden corregir a mano.
- **Tabla de documentos**: filtros por proveedor, categoría, rango de fechas del documento y "información faltante"; paginación; previsualización del archivo; reintento de procesamiento fallido y borrado.
- **Vista de proveedores** con paginación.
- **Reportes**: totales por categoría y por proveedor, con gráficas.
- **Revisión de duplicados**: pestaña que, al pulsar "Revisar duplicados", agrupa los documentos que parecen el mismo egreso (por ejemplo, una factura y su comprobante de pago) y muestra cuánto se estaría contando de más. Permite previsualizar, eliminar o marcar el grupo como "No es duplicado".
- **Login** con Supabase Auth (sin registro público) y aislamiento de datos por empresa.

## Arquitectura

```text
expenses_organizer/
  backend/                  FastAPI + SQLAlchemy + Alembic
    app/
      api/                  routers (delgados)
      core/                 configuración (pydantic-settings)
      db/                   sesión, seed, scripts de administración
      models/               modelos ORM
      schemas/              esquemas Pydantic
      services/             lógica de negocio (extracción, OCR, auth, storage...)
      tests/                pytest
    alembic/                migraciones
    Dockerfile              imagen usada en Render (incluye Tesseract y Poppler)
    main.py
  frontend/                 React + TypeScript + Vite
    src/components/         Login, UploadDocument, DocumentsTable, VendorsView, Reports
```

**Flujo de procesamiento:**

1. El frontend sube cada archivo (`POST /documents/upload`); se guarda en Supabase Storage.
2. Con menos de 10 archivos, cada documento se procesa de forma síncrona con Claude. Con 10 o más, se envían en un solo **Message Batch** de Anthropic (`POST /documents/batch-extract`) y `GET /documents` consulta los lotes pendientes e ingiere los resultados cuando están listos.
3. Claude devuelve los campos estructurados, guardados en `document_extractions` (`is_final=true`) para trazabilidad.
4. Si hay proveedor, se busca un `Vendor` existente de la empresa (por NIT, o por nombre sin distinguir mayúsculas/espacios) o se crea, y se asigna la categoría por defecto del proveedor.
5. Los documentos que quedan atascados en `uploaded`/`processing` se reanudan solos en el siguiente `GET /documents`.

**Multi-tenant y seguridad:** el backend valida el token de Supabase contra `GET {SUPABASE_URL}/auth/v1/user` y deriva `company_id`/`user_id` del token, nunca de parámetros del cliente. Las operaciones por ID comprueban que el recurso pertenezca a la empresa del usuario.

## Desarrollo local

### Backend

```powershell
cd expenses_organizer/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # completa SUPABASE_*, DATABASE_URL y ANTHROPIC_API_KEY
alembic upgrade head
uvicorn main:app --reload
```

Si `DATABASE_URL` apunta a Supabase, usa el connection string de **Connection Pooling** (modo Transaction, puerto 6543) desde Project Settings → Database, no la conexión directa (`db.<project-ref>.supabase.co`): esa solo resuelve por IPv6 y falla en redes sin salida IPv6. Ver comentarios en `.env.example`.

### Frontend

```powershell
cd expenses_organizer/frontend
npm install
Copy-Item .env.example .env      # VITE_API_BASE_URL, VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
npm run dev
```

### Crear usuarios

No hay registro público. Las cuentas y empresas se crean con un script interactivo (la contraseña se pide con `getpass`):

```powershell
cd expenses_organizer/backend
python -m app.db.create_admin_user
```

`python -m app.db.seed` crea datos semilla (empresa y categorías por defecto).

## Variables de entorno

| Variable | Dónde | Descripción |
| --- | --- | --- |
| `DATABASE_URL` | backend | Connection string de PostgreSQL (pooler de Supabase, esquema `postgresql+psycopg://`) |
| `SUPABASE_URL` | backend | URL del proyecto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | backend | Clave de servicio (Storage y verificación de tokens). **Secreta** |
| `SUPABASE_STORAGE_BUCKET` | backend | Bucket de archivos (`documents`) |
| `ANTHROPIC_API_KEY` | backend | API key de [console.anthropic.com](https://console.anthropic.com). **Secreta** |
| `ANTHROPIC_MODEL` | backend | Modelo de extracción (por defecto `claude-haiku-4-5`) |
| `CORS_ALLOW_ORIGINS` | backend | Orígenes permitidos, separados por coma; en producción debe incluir la URL de Vercel |
| `OCR_LANGUAGES`, `TESSERACT_CMD`, `POPPLER_PATH`, `TESSDATA_PREFIX` | backend | Configuración del OCR opcional |
| `VITE_API_BASE_URL` | frontend | URL del backend |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | frontend | Credenciales públicas de Supabase (se incrustan al compilar: redesplegar tras cambiarlas) |

Nunca subas `.env` al repositorio.

## API

Todos los endpoints, salvo `/health*`, requieren `Authorization: Bearer <access_token de Supabase>`.

| Método y ruta | Descripción |
| --- | --- |
| `GET /health`, `GET /health/db` | Estado del servicio y de la conexión a la base de datos |
| `POST /documents/upload` | Sube un archivo |
| `POST /documents/batch-extract` | Envía varios documentos como un Anthropic Message Batch |
| `POST /documents/{id}/ai-extract` | (Re)ejecuta la extracción con Claude |
| `POST /documents/{id}/ocr` | Ejecuta OCR local opcional (Tesseract) y luego la extracción |
| `GET /documents` | Lista paginada. Filtros: `vendor_id`, `expense_category_id`, `document_date_from`, `document_date_to`, `missing_info`, `limit`, `offset` |
| `GET /documents/{id}/file` | Descarga/previsualiza el archivo |
| `PATCH /documents/{id}/classify` | Asigna o corrige `vendor_id` y/o `expense_category_id` |
| `DELETE /documents/{id}` | Borra el documento, sus filas relacionadas y el archivo |
| `GET`, `POST /vendors`; `PATCH /vendors/{id}` | Proveedores |
| `GET`, `POST /expense-categories`; `PATCH`, `DELETE /expense-categories/{id}` | Categorías de gasto (Transporte, Suministros, Inventario, Servicios Públicos, Nómina, Arriendo, Otros por defecto) |
| `GET /reports/expense-summary` | Resumen de gastos (ver abajo) |
| `GET /reports/probable-duplicates` | Grupos de documentos probablemente duplicados (ver abajo). Filtro: `date_window_days` (0-30, por defecto 5) |
| `POST /reports/probable-duplicates/dismiss` | Marca un grupo (`document_ids`) como "no es duplicado" para que no vuelva a aparecer |

### Reportes

`GET /reports/expense-summary` (acepta `vendor_id` y `expense_category_id`) devuelve:

- `rows`: una fila por documento (`document_date`, `vendor_name`, `expense_category_name`, `currency`, `total_amount`, `tax_amount`), lista para `pd.DataFrame(response.json()["rows"])`.
- `totals_by_category` y `totals_by_vendor`: montos ya sumados.
- `grand_total` y `document_count`.

Los montos salen de la extracción final de Claude; los documentos sin extracción aparecen con `total_amount=null` y no suman a los totales.

### Detección de duplicados

`GET /reports/probable-duplicates` compara los documentos de la empresa que tienen valor (`total_amount > 0`) y los agrupa cuando coinciden en:

- **Valor y moneda**: idénticos al centavo.
- **Proveedor**: el mismo (por ID o NIT) o uno de nombre similar; se ignoran tildes, mayúsculas y sufijos como S.A.S. o Ltda. Dos proveedores claramente distintos no se agrupan.
- **Fecha del documento**: a no más de `date_window_days` días entre sí.

Si a un documento le falta el proveedor o la fecha, puede aparecer igual pero con menos confianza; si faltan ambos, no se compara. Cada grupo trae una `confidence` (`alta`, `media`, `baja`), las `reasons` de la coincidencia y `possible_overcount` (el monto que se cuenta de más si todos son el mismo egreso). Tres o más documentos del mismo egreso salen en un solo grupo.

`POST /reports/probable-duplicates/dismiss` guarda cada par del grupo en `duplicate_dismissals`; esos pares dejan de marcarse (y se borran solos si se elimina el documento). Verifica que todos los documentos pertenezcan a la empresa del usuario.

## Extracción con Claude

Claude es el único paso que produce los campos estructurados, por lo que corre en todos los documentos. Con `claude-haiku-4-5` ($1/$5 por 1M tokens) el costo ronda los $0.003–0.004 USD por documento. Si hay errores en documentos difíciles, prueba `claude-sonnet-5-5` u otro modelo más capaz cambiando `ANTHROPIC_MODEL`.

## OCR local (opcional)

El OCR con Tesseract ya no forma parte del flujo por defecto; queda como acción manual (`POST /documents/{id}/ocr`) que guarda el texto crudo y un `confidence_score` como señal de calidad. Requiere Tesseract y Poppler:

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
winget install --id oschwartz10612.Poppler -e
```

Si quedan en el PATH no hace falta configurar nada más; si no, define `TESSERACT_CMD`, `POPPLER_PATH` y `TESSDATA_PREFIX` en `.env`. `OCR_LANGUAGES` controla el idioma (por defecto `spa+eng`); el traineddata de `spa` hay que descargarlo aparte desde [tesseract-ocr/tessdata](https://github.com/tesseract-ocr/tessdata) si no está en tu `tessdata`. En producción, el `Dockerfile` ya instala Tesseract (con español) y Poppler.

## Migraciones (Alembic)

```powershell
cd expenses_organizer/backend
alembic revision --autogenerate -m "descripcion del cambio"
alembic upgrade head
```

## Pruebas

```powershell
cd expenses_organizer/backend
python -m pytest
```

Las pruebas de integración usan la base de datos configurada en `.env`.

## Despliegue

- **Backend: Render**, con el `Dockerfile` (Root Directory `expenses_organizer/backend`). Al arrancar ejecuta `alembic upgrade head` y luego `uvicorn`. Variables de entorno según la tabla de arriba.
- **Frontend: Vercel**, build estático de Vite (Root Directory `expenses_organizer/frontend`).
- **Base de datos y archivos: Supabase** (PostgreSQL + Storage + Auth). En el plan gratuito, Supabase pausa los proyectos inactivos; si el backend deja de responder, revisa primero que el proyecto esté activo.
- Al cambiar `CORS_ALLOW_ORIGINS` o las variables `VITE_*`, redespliega el servicio correspondiente.
