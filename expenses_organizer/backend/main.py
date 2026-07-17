from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.api.expense_categories import router as expense_categories_router
from app.api.health import router as health_router
from app.api.reports import router as reports_router
from app.api.vendors import router as vendors_router
from app.core.config import settings


app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(vendors_router)
app.include_router(expense_categories_router)
app.include_router(reports_router)
