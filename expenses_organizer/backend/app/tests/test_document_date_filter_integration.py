"""Integration test for filtering documents by document_date, against the real
Supabase Postgres. Cleans up its own rows so it can run repeatedly."""
from datetime import date
from uuid import UUID, uuid4

from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.expense_category import ExpenseCategory
from app.models.vendor import Vendor
from app.services import document_service


def _make_document_id(
    db, company_id, document_date: date | None, vendor_id=None, expense_category_id=None
) -> UUID:
    document = Document(
        company_id=company_id,
        original_filename="factura.pdf",
        source_format="pdf",
        status="ai_extraction_completed",
        mime_type="application/pdf",
        storage_path="uploads/factura.pdf",
        document_date=document_date,
        vendor_id=vendor_id,
        expense_category_id=expense_category_id,
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
            july_only, july_only_total = document_service.list_documents(
                db, company_id, document_date_from=date(2026, 7, 1), document_date_to=date(2026, 7, 31)
            )
            all_docs, all_total = document_service.list_documents(db, company_id, limit=1000)
            from_august, _ = document_service.list_documents(db, company_id, document_date_from=date(2026, 8, 1))

        july_only_ids = {item.id for item in july_only}
        assert july_only_ids == {july_id}
        assert july_only_total == 1

        all_ids = {item.id for item in all_docs}
        assert {july_id, august_id, no_date_id} <= all_ids
        assert all_total == len(all_docs)

        from_august_ids = {item.id for item in from_august}
        assert august_id in from_august_ids
        assert july_id not in from_august_ids
        assert no_date_id not in from_august_ids  # NULL document_date never matches a range filter
    finally:
        _cleanup([july_id, august_id, no_date_id])


def test_list_documents_paginates_and_filters_missing_info():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id

        # A dedicated vendor scopes every query below to exactly these 3 documents,
        # regardless of any unrelated rows already sitting in this shared test company.
        vendor = Vendor(company_id=company_id, name=f"Proveedor Paginacion {uuid4()}")
        category = ExpenseCategory(company_id=company_id, name=f"Categoria Paginacion {uuid4()}")
        db.add_all([vendor, category])
        db.commit()
        vendor_id, category_id = vendor.id, category.id

        ids = [_make_document_id(db, company_id, date(2026, 7, d), vendor_id=vendor_id) for d in (1, 2, 3)]

        # Give the first two a total_amount and category so they no longer count as
        # "missing info"; the third keeps both NULL despite having a vendor.
        db.query(Document).filter(Document.id.in_(ids[:2])).update(
            {"total_amount": 1000, "expense_category_id": category_id}, synchronize_session=False
        )
        db.commit()

    try:
        with SessionLocal() as db:
            page_one, total = document_service.list_documents(db, company_id, vendor_id=vendor_id, limit=2, offset=0)
            page_two, total_again = document_service.list_documents(
                db, company_id, vendor_id=vendor_id, limit=2, offset=2
            )
            missing_only, missing_total = document_service.list_documents(
                db, company_id, vendor_id=vendor_id, missing_info=True
            )

        assert total == total_again == 3
        assert len(page_one) == 2
        assert len(page_two) == 1
        assert {item.id for item in page_one} | {item.id for item in page_two} == set(ids)

        assert missing_total == 1
        assert missing_only[0].id == ids[2]
    finally:
        _cleanup(ids)
        with SessionLocal() as db:
            db.query(Vendor).filter(Vendor.id == vendor_id).delete()
            db.query(ExpenseCategory).filter(ExpenseCategory.id == category_id).delete()
            db.commit()


def test_get_last_category_for_vendor_returns_most_recent():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id

        vendor = Vendor(company_id=company_id, name=f"Proveedor Test {uuid4()}")
        older_category = ExpenseCategory(company_id=company_id, name=f"Categoria Vieja {uuid4()}")
        newer_category = ExpenseCategory(company_id=company_id, name=f"Categoria Nueva {uuid4()}")
        db.add_all([vendor, older_category, newer_category])
        db.commit()
        vendor_id, older_category_id, newer_category_id = vendor.id, older_category.id, newer_category.id

        older_doc_id = _make_document_id(db, company_id, None, vendor_id=vendor_id, expense_category_id=older_category_id)
        newer_doc_id = _make_document_id(db, company_id, None, vendor_id=vendor_id, expense_category_id=newer_category_id)
        uncategorized_doc_id = _make_document_id(db, company_id, None, vendor_id=vendor_id)

    try:
        with SessionLocal() as db:
            result = document_service.get_last_category_for_vendor(db, company_id=company_id, vendor_id=vendor_id)
        assert result == newer_category_id
    finally:
        _cleanup([older_doc_id, newer_doc_id, uncategorized_doc_id])
        with SessionLocal() as db:
            db.query(Vendor).filter(Vendor.id == vendor_id).delete()
            db.query(ExpenseCategory).filter(ExpenseCategory.id.in_([older_category_id, newer_category_id])).delete(
                synchronize_session=False
            )
            db.commit()
