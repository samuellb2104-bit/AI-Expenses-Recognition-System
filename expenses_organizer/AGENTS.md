# Repository Guidelines

## Project Structure & Module Organization

The backend lives in `expenses_organizer/backend/` and the React + TypeScript + Vite frontend in `expenses_organizer/frontend/`. Keep FastAPI code under `backend/app/`, organized by responsibility: `api/` for routes, `core/` for settings, `db/` for database setup and admin scripts, `models/` for ORM models, `schemas/` for Pydantic schemas, and `services/` for business logic. Add tests in `backend/app/tests/`. Database migrations live in `backend/alembic/versions/`. See the root `README.md` and `CLAUDE.md` for architecture and project status.

## Build, Test, and Development Commands

- `uvicorn main:app --reload` from `expenses_organizer/backend/`: runs the API locally with hot reload.
- `python -m pytest` from `expenses_organizer/backend/`: runs the backend test suite.
- `pip install -r requirements.txt`: installs the Python dependencies.
- `alembic upgrade head`: applies database migrations.
- `npm run dev` / `npm run build` / `npm run lint` from `expenses_organizer/frontend/`: run, type-check and build, and lint the frontend.

## Coding Style & Naming Conventions

Use 4-space indentation for Python. Prefer descriptive snake_case for files, functions, and variables. Keep API routers small and move document-processing logic into services. Name SQLAlchemy models in singular form (`Document`), and use lowercase plural table names (`documents`).

## Testing Guidelines

Use `pytest` for backend tests. Name test files `test_*.py` and keep them close to the feature they cover, such as `backend/app/tests/test_health.py`. Focus on route behavior, schema validation, and service logic.

## Commit & Pull Request Guidelines

Write short, imperative commit messages such as `add document upload endpoint`. Pull requests should explain the change, list any setup steps, and include screenshots or sample API responses when UI or endpoint behavior changes.

## Security & Configuration Tips

Do not commit secrets. Copy `backend/.env.example` to `.env` locally and keep `DATABASE_URL` and any future API keys out of version control.
