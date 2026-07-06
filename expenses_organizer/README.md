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

La API expone `GET /health`, `GET /health/db` y `POST /documents/upload`.

## Pruebas

```powershell
cd expenses_organizer/backend
python -m pytest
```
