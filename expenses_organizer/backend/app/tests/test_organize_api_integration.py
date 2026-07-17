"""Integration test for the vendor/expense-category organization endpoints against the
real Supabase Postgres + Storage. Cleans up its own rows so it can run repeatedly."""
from fastapi.testclient import TestClient

from app.api.deps import get_auth_context
from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.processing_log import ProcessingLog
from app.models.vendor import Vendor
from app.services.auth_service import AuthContext
from main import app

client = TestClient(app)


def test_vendors_categories_and_document_classification_end_to_end():
    with SessionLocal() as db:
        company, user = seed_test_company_and_user(db)

    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=user.id, company_id=company.id, email=user.email
    )

    try:
        vendor_resp = client.post(
            "/vendors", json={"name": "Proveedor de Prueba API", "tax_id": "900999999-1"}
        )
        assert vendor_resp.status_code == 201
        vendor_id = vendor_resp.json()["id"]

        categories_resp = client.get("/expense-categories")
        assert categories_resp.status_code == 200
        category_names = {c["name"] for c in categories_resp.json()}
        assert "Transporte" in category_names
        category_id = next(c["id"] for c in categories_resp.json() if c["name"] == "Transporte")

        files = {"file": ("factura-test.pdf", b"%PDF-1.4 test", "application/pdf")}
        data = {"document_type": "invoice"}
        upload_resp = client.post("/documents/upload", files=files, data=data)
        assert upload_resp.status_code == 201
        document_id = upload_resp.json()["id"]
        storage_path = upload_resp.json()["storage_path"]

        try:
            classify_resp = client.patch(
                f"/documents/{document_id}/classify",
                json={"vendor_id": vendor_id, "expense_category_id": category_id},
            )
            assert classify_resp.status_code == 200
            assert classify_resp.json()["vendor_id"] == vendor_id
            assert classify_resp.json()["expense_category_id"] == category_id

            list_resp = client.get("/documents", params={"vendor_id": vendor_id})
            assert list_resp.status_code == 200
            assert any(d["id"] == document_id for d in list_resp.json())

            list_by_category = client.get(
                "/documents", params={"expense_category_id": category_id}
            )
            assert list_by_category.status_code == 200
            assert any(d["id"] == document_id for d in list_by_category.json())
        finally:
            with SessionLocal() as db:
                db.query(ProcessingLog).filter(ProcessingLog.document_id == document_id).delete()
                db.query(Document).filter(Document.id == document_id).delete()
                db.query(Vendor).filter(Vendor.id == vendor_id).delete()
                db.commit()
    finally:
        app.dependency_overrides.pop(get_auth_context, None)

        if storage_path.startswith("s3://"):
            from urllib import request as urllib_request

            from app.core.config import settings

            object_name = storage_path.split("/", 3)[-1]
            req = urllib_request.Request(
                f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{settings.supabase_storage_bucket}/{object_name}",
                headers={
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    "apikey": settings.supabase_service_role_key,
                },
                method="DELETE",
            )
            urllib_request.urlopen(req)
