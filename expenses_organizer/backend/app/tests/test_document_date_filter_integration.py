"""Integration test for filtering documents by document_date, against the real
Supabase Postgres. Cleans up its own rows so it can run repeatedly."""
from datetime import date
from uuid import UUID

from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.document import Document
from app.services import document_service


def _make_document_id(db, company_id, document_date: date | None) -> UUID:
    document = Document(
        company_id=company_id,
        original_filename="factura.pdf",
        source_format="pdf",
        status="ai_extraction_completed",
        mime_type="application/pdf",
        storage_path="uploads/factura.pdf",
        document_date=document_date,
    )
    db.add(document)
    db.commit()
    return document.id


def _cleanup(document_ids):
    with SessionLocal() as db:
        db.query(Document).filter(Document.id.in_(document_ids)).delete(synchronize_session=False)
        db.commit()


def test_list_documents_filters_by_document_date_range():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        july_id = _make_document_id(db, company_id, date(2026, 7, 15))
        august_id = _make_document_id(db, company_id, date(2026, 8, 1))
        no_date_id = _make_document_id(db, company_id, None)

    try:
        with SessionLocal() as db:
            july_only = document_service.list_documents(
                db, company_id, document_date_from=date(2026, 7, 1), document_date_to=date(2026, 7, 31)
            )
            all_docs = document_service.list_documents(db, company_id)
            from_august = document_service.list_documents(db, company_id, document_date_from=date(2026, 8, 1))

        july_only_ids = {item.id for item in july_only}
        assert july_only_ids == {july_id}

        all_ids = {item.id for item in all_docs}
        assert {july_id, august_id, no_date_id} <= all_ids

        from_august_ids = {item.id for item in from_august}
        assert august_id in from_august_ids
        assert july_id not in from_august_ids
        assert no_date_id not in from_august_ids  # NULL document_date never matches a range filter
    finally:
        _cleanup([july_id, august_id, no_date_id])
