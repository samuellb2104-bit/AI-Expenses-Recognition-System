# Expenses Organizer

Backend base para la app de gestion de egresos con FastAPI y PostgreSQL.

## Estructura

```text
expenses_organizer/
  backend/
    app/
      api/
      core/
      db/
      models/
      schemas/
      services/
      tests/
    main.py
    requirements.txt
    .env.example
```

## Desarrollo local

```powershell
cd expenses_organizer/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --reload
```

Si `DATABASE_URL` apunta a Supabase, usa el connection string de **Connection Pooling** (modo Transaction, puerto 6543) desde Project Settings -> Database, no la conexión directa (`db.<project-ref>.supabase.co`): esa solo resuelve por IPv6 y falla en redes sin salida IPv6. Ver comentarios en `.env.example`.

La API expone `GET /health`, `GET /health/db`, `POST /documents/upload`, `GET /documents`, `PATCH /documents/{id}/classify`, `POST /documents/{id}/ocr`, `POST /documents/{id}/ai-extract`, `GET|POST /vendors`, `PATCH /vendors/{id}`, `GET|POST /expense-categories`, `PATCH|DELETE /expense-categories/{id}` y `GET /reports/expense-summary`.

## OCR local (Tesseract)

El endpoint `POST /documents/{id}/ocr` extrae texto de PDFs e imágenes usando Tesseract, corriendo localmente y sin costo. Requiere instalar Tesseract y Poppler (para convertir páginas PDF a imagen):

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
winget install --id oschwartz10612.Poppler -e
```

Si quedan en el PATH del sistema, no hace falta configurar nada más. Si no, define en `.env` las rutas absolutas (ver `.env.example`): `TESSERACT_CMD`, `POPPLER_PATH`, `TESSDATA_PREFIX`. El idioma de reconocimiento se controla con `OCR_LANGUAGES` (por defecto `spa+eng`); el traineddata de `spa` no viene con la instalación por defecto de Tesseract y hay que descargarlo aparte desde [tesseract-ocr/tessdata](https://github.com/tesseract-ocr/tessdata) si no está ya en tu `tessdata`.

## Extracción con Claude (corre despues de cada OCR)

`POST /documents/{id}/ocr` corre OCR primero (Tesseract, local y sin costo — texto crudo y `confidence_score` guardados como señal de calidad para revisión manual, visible en el frontend) y **siempre**, a continuación, corre Claude sobre el mismo PDF/imagen para obtener campos estructurados (`vendor_name`, `document_date`, `total_amount`, `tax_amount`, `currency`, `line_items`, `notes`) como JSON garantizado — es el único paso que produce estos campos, así que el reconocimiento de proveedor y los reportes dependen de que corra en todos los documentos, no solo en los que el OCR leyó mal. Ambos pasos quedan guardados en `document_extractions` (el de OCR con `is_final=false`, el de IA con `is_final=true`) para trazabilidad.

`POST /documents/{id}/ai-extract` vuelve a correr solo el paso de Claude sin repetir el OCR (útil para reintentar tras un error transitorio de la API, o para documentos donde el OCR ni siquiera vale la pena, como recibos manuscritos).

Configura en `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...   # tu API key de https://console.anthropic.com
ANTHROPIC_MODEL=claude-haiku-4-5
```

`claude-haiku-4-5` es el modelo más barato ($1/$5 por 1M tokens) — buena opción ya que corre en el 100% de los documentos (~$0.003-0.004 USD por documento). Si ves errores de extracción en documentos difíciles, prueba con `claude-sonnet-5` o `claude-opus-4-8` (más caros pero más capaces).

## Organizacion: proveedores y categorias de gasto

Cada `Document` puede vincularse a un `Vendor` (el proveedor/empresa que emitio la factura, distinto de `Company`, que es el tenant que usa la app) y a una `ExpenseCategory` (Transporte, Suministros, Inventario, Servicios Publicos, Nomina, Arriendo, Otros — sembradas por defecto para cada `Company` nueva, editables despues).

- Cuando Claude extrae `vendor_name`, el sistema busca un `Vendor` existente en esa empresa (por NIT si lo hay, si no por nombre sin distinguir mayusculas/espacios) y lo crea si no existe, vinculandolo automaticamente al documento.
- `PATCH /documents/{id}/classify` permite asignar o corregir manualmente `vendor_id` y/o `expense_category_id` (por ejemplo, para fusionar un duplicado o corregir una categoria).
- `GET /documents?company_id=...&vendor_id=...&expense_category_id=...` lista documentos filtrando por proveedor y/o categoria — la base para las vistas del frontend ("gastos por Transporte", "facturas de tal proveedor").
- `GET/POST /vendors` y `GET/POST/PATCH/DELETE /expense-categories` son el CRUD para gestionarlos directamente.

## Reportes: totales y resumenes (para pandas/matplotlib)

`GET /reports/expense-summary?company_id=...&vendor_id=...&expense_category_id=...` devuelve:

- `rows`: una fila por documento (`document_date`, `vendor_name`, `expense_category_name`, `currency`, `total_amount`, `tax_amount`) — pensada para cargarla directo en un DataFrame: `pd.DataFrame(response.json()["rows"])`, y de ahi agrupar/graficar como quieras con matplotlib.
- `totals_by_category` y `totals_by_vendor`: montos ya sumados por categoria y por proveedor, para graficas rapidas sin tener que agrupar tu mismo.
- `grand_total` y `document_count`.

Los montos salen de la extraccion de Claude (`DocumentExtraction.is_final=true`); documentos sin esa extraccion (por ejemplo si `POST /documents/{id}/ai-extract` fallo) aparecen en `rows` con `total_amount=null` y no suman a los totales, para no inflar los reportes con datos faltantes. `pandas` y `matplotlib` no son dependencias del backend — instalalos donde vayas a consumir la API (notebook, script de analisis, el futuro frontend).

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
