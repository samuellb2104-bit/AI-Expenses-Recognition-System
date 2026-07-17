from uuid import uuid4

from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.expense_category import ExpenseCategory
from app.models.vendor import Vendor
from app.services.report_service import get_expense_summary


def _make_document(db, company_id, vendor_id=None, expense_category_id=None):
    document = Document(
        company_id=company_id,
        original_filename="test-invoice.pdf",
        source_format="pdf",
        status="ai_extraction_completed",
        mime_type="application/pdf",
        storage_path="uploads/test-invoice.pdf",
        vendor_id=vendor_id,
        expense_category_id=expense_category_id,
    )
    db.add(document)
    db.flush()
    return document


def _make_final_extraction(db, document_id, total_amount, tax_amount=0, currency="COP", document_date="2026-05-07"):
    extraction = DocumentExtraction(
        document_id=document_id,
        extraction_method="ai",
        provider_name="claude",
        raw_text=None,
        extracted_data={
            "vendor_name": "irrelevant here, comes from Vendor.name",
            "document_date": document_date,
            "total_amount": total_amount,
            "tax_amount": tax_amount,
            "currency": currency,
            "line_items": [],
            "notes": None,
        },
        confidence_score=None,
        is_final=True,
    )
    db.add(extraction)
    db.flush()
    return extraction


def test_expense_summary_aggregates_by_category_and_vendor():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        vendor_a = Vendor(company_id=company.id, name="Proveedor Reportes A")
        vendor_b = Vendor(company_id=company.id, name="Proveedor Reportes B")
        db.add_all([vendor_a, vendor_b])
        db.flush()

        category = (
            db.query(ExpenseCategory)
            .filter(ExpenseCategory.company_id == company.id, ExpenseCategory.name == "Transporte")
            .first()
        )

        doc1 = _make_document(db, company.id, vendor_id=vendor_a.id, expense_category_id=category.id)
        _make_final_extraction(db, doc1.id, total_amount=100000)

        doc2 = _make_document(db, company.id, vendor_id=vendor_a.id, expense_category_id=category.id)
        _make_final_extraction(db, doc2.id, total_amount=50000)

        doc3 = _make_document(db, company.id, vendor_id=vendor_b.id, expense_category_id=None)
        _make_final_extraction(db, doc3.id, total_amount=25000)

        db.commit()

        try:
            summary = get_expense_summary(db, company_id=company.id)

            our_doc_ids = {doc1.id, doc2.id, doc3.id}
            our_rows = [r for r in summary.rows if r.document_id in our_doc_ids]
            assert len(our_rows) == 3

            category_bucket = next(
                b for b in summary.totals_by_category if b.expense_category_id == category.id
            )
            assert category_bucket.total_amount == 150000
            assert category_bucket.document_count == 2

            uncategorized_bucket = next(
                b for b in summary.totals_by_category if b.expense_category_id is None
            )
            assert uncategorized_bucket.total_amount >= 25000

            vendor_a_bucket = next(b for b in summary.totals_by_vendor if b.vendor_id == vendor_a.id)
            assert vendor_a_bucket.total_amount == 150000
            assert vendor_a_bucket.document_count == 2

            vendor_b_bucket = next(b for b in summary.totals_by_vendor if b.vendor_id == vendor_b.id)
            assert vendor_b_bucket.total_amount == 25000
        finally:
            with SessionLocal() as cleanup_db:
                cleanup_db.query(DocumentExtraction).filter(
                    DocumentExtraction.document_id.in_([doc1.id, doc2.id, doc3.id])
                ).delete(synchronize_session=False)
                cleanup_db.query(Document).filter(Document.id.in_([doc1.id, doc2.id, doc3.id])).delete(
                    synchronize_session=False
                )
                cleanup_db.query(Vendor).filter(Vendor.id.in_([vendor_a.id, vendor_b.id])).delete(
                    synchronize_session=False
                )
                cleanup_db.commit()


def test_expense_summary_filters_by_vendor():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        vendor = Vendor(company_id=company.id, name="Proveedor Filtro Unico")
        db.add(vendor)
        db.flush()

        matching_doc = _make_document(db, company.id, vendor_id=vendor.id)
        _make_final_extraction(db, matching_doc.id, total_amount=10000)

        other_doc = _make_document(db, company.id, vendor_id=None)
        _make_final_extraction(db, other_doc.id, total_amount=99999)

        db.commit()

        try:
            summary = get_expense_summary(db, company_id=company.id, vendor_id=vendor.id)

            assert summary.document_count == 1
            assert summary.rows[0].document_id == matching_doc.id
            assert summary.grand_total == 10000
        finally:
            with SessionLocal() as cleanup_db:
                cleanup_db.query(DocumentExtraction).filter(
                    DocumentExtraction.document_id.in_([matching_doc.id, other_doc.id])
                ).delete(synchronize_session=False)
                cleanup_db.query(Document).filter(
                    Document.id.in_([matching_doc.id, other_doc.id])
                ).delete(synchronize_session=False)
                cleanup_db.query(Vendor).filter(Vendor.id == vendor.id).delete()
                cleanup_db.commit()


def test_expense_summary_returns_empty_result_for_a_filter_with_no_matches():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        # A vendor_id that can't possibly match anything guarantees an empty result
        # regardless of what other tests may have left in the shared seed company.
        summary = get_expense_summary(db, company_id=company.id, vendor_id=uuid4())

        assert summary.rows == []
        assert summary.totals_by_category == []
        assert summary.totals_by_vendor == []
        assert summary.grand_total == 0.0
        assert summary.document_count == 0
