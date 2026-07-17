"""Integration test for POST /documents/upload against the real Supabase Postgres + Storage.

Requires a valid backend/.env (DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).
Creates and cleans up its own rows/objects so it can run repeatedly against the shared DB.
"""
from urllib import request as urllib_request

from fastapi.testclient import TestClient

from app.api.deps import get_auth_context
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.seed import seed_test_company_and_user
from app.models.document import Document
from app.models.document_file import DocumentFile
from app.models.processing_log import ProcessingLog
from app.services.auth_service import AuthContext
from main import app

client = TestClient(app)


def _delete_from_supabase_storage(object_name: str) -> None:
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{settings.supabase_storage_bucket}/{object_name}"
    req = urllib_request.Request(
        url,
        headers={
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
        },
        method="DELETE",
    )
    urllib_request.urlopen(req)


def test_upload_document_persists_rows_and_uploads_to_supabase_storage():
    with SessionLocal() as db:
        company, user = seed_test_company_and_user(db)

    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=user.id, company_id=company.id, email=user.email
    )

    files = {"file": ("integration-test.pdf", b"%PDF-1.4 integration test", "application/pdf")}
    data = {"document_type": "invoice"}

    try:
        response = client.post("/documents/upload", files=files, data=data)
        assert response.status_code == 201
        body = response.json()
        document_id = body["id"]
    finally:
        app.dependency_overrides.pop(get_auth_context, None)

    try:
        with SessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.status == "uploaded"
            assert document.company_id == company.id

            document_file = db.query(DocumentFile).filter(DocumentFile.document_id == document_id).one()
            assert document_file.file_kind == "original"
            assert document_file.storage_path == document.storage_path

            log = db.query(ProcessingLog).filter(ProcessingLog.document_id == document_id).one()
            assert log.step_name == "upload"
            assert log.status == "success"

        assert document.storage_path.startswith(f"s3://{settings.supabase_storage_bucket}/")
        object_name = document.storage_path.split("/", 3)[-1]
    finally:
        with SessionLocal() as db:
            db.query(ProcessingLog).filter(ProcessingLog.document_id == document_id).delete()
            db.query(DocumentFile).filter(DocumentFile.document_id == document_id).delete()
            db.query(Document).filter(Document.id == document_id).delete()
            db.commit()

        if settings.supabase_url and settings.supabase_service_role_key:
            _delete_from_supabase_storage(object_name)
