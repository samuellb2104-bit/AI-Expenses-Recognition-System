from fastapi import APIRouter

from app.db.session import ping_database

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
def health_database() -> dict[str, str]:
    ping_database()
    return {"status": "ok", "database": "reachable"}
