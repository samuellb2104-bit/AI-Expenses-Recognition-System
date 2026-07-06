# Repository Guidelines

## Project Structure & Module Organization

The main code lives in `expenses_organizer/backend/`. Keep FastAPI code under `backend/app/`, organized by responsibility: `api/` for routes, `core/` for settings, `db/` for database setup, `models/` for ORM models, `schemas/` for Pydantic schemas, and `services/` for business logic. Add tests in `backend/app/tests/`.

## Build, Test, and Development Commands

- `uvicorn app.main:app --reload` from `expenses_organizer/backend/`: runs the API locally with hot reload.
- `python -m pytest`: runs tests once they are added.
- `pip install -r requirements.txt`: installs the Python dependencies.

## Coding Style & Naming Conventions

Use 4-space indentation for Python. Prefer descriptive snake_case for files, functions, and variables. Keep API routers small and move document-processing logic into services. Name SQLAlchemy models in singular form (`Document`), and use lowercase plural table names (`documents`).

## Testing Guidelines

Use `pytest` for backend tests. Name test files `test_*.py` and keep them close to the feature they cover, such as `backend/app/tests/test_health.py`. Focus on route behavior, schema validation, and service logic.

## Commit & Pull Request Guidelines

Write short, imperative commit messages such as `add document upload endpoint`. Pull requests should explain the change, list any setup steps, and include screenshots or sample API responses when UI or endpoint behavior changes.

## Security & Configuration Tips

Do not commit secrets. Copy `backend/.env.example` to `.env` locally and keep `DATABASE_URL` and any future API keys out of version control.
