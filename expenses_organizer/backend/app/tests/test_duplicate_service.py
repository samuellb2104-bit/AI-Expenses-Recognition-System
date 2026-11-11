from datetime import date

from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.vendor import Vendor
from app.services.duplicate_service import (
    find_probable_duplicates,
    normalize_vendor_name,
    vendor_names_similar,
)


def test_normalize_vendor_name_drops_accents_and_legal_suffixes():
    assert normalize_vendor_name("Cláro Colombia S.A.S.") == "claro colombia"
    assert normalize_vendor_name(None) == ""


def test_vendor_names_similar():
    assert vendor_names_similar("Claro", "CLARO Colombia S.A.S.")
    assert vendor_names_similar("Droguerias Cruz Verde", "Drogueria Cruz Verde")
    assert not vendor_names_similar("Claro", "Movistar")
    assert not vendor_names_similar(None, "Claro")


def _doc(db, company_id, vendor_id, amount, doc_date, currency="COP", name="doc.pdf"):
    document = Document(
        company_id=company_id,
        original_filename=name,
        source_format="pdf",
        status="ai_extraction_completed",
        storage_path=f"uploads/{name}",
        vendor_id=vendor_id,
        total_amount=amount,
        currency=currency,
        document_date=doc_date,
    )
    db.add(document)
    db.flush()
    return document


def test_find_probable_duplicates_groups_invoice_and_receipt():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        vendor_a = Vendor(company_id=company.id, name="Dup Test Claro SAS")
        vendor_b = Vendor(company_id=company.id, name="Dup Test Claro")
        vendor_other = Vendor(company_id=company.id, name="Dup Test Otro Proveedor")
        db.add_all([vendor_a, vendor_b, vendor_other])
        db.flush()

        # Unusual amounts so leftovers in the shared seed company can't collide.
        invoice = _doc(db, company.id, vendor_a.id, 987654.32, date(2026, 5, 1), name="factura.pdf")
        receipt = _doc(db, company.id, vendor_b.id, 987654.32, date(2026, 5, 3), name="comprobante.pdf")
        other_vendor = _doc(db, company.id, vendor_other.id, 987654.32, date(2026, 5, 1), name="otro.pdf")
        too_far = _doc(db, company.id, vendor_a.id, 987654.32, date(2026, 6, 20), name="lejos.pdf")
        other_currency = _doc(db, company.id, vendor_a.id, 987654.32, date(2026, 5, 1), currency="USD", name="usd.pdf")
        db.commit()

        ids = [invoice.id, receipt.id, other_vendor.id, too_far.id, other_currency.id]
        try:
            result = find_probable_duplicates(db, company_id=company.id)
            ours = [g for g in result.groups if any(d.id in set(ids) for d in g.documents)]

            assert len(ours) == 1
            group_ids = {d.id for d in ours[0].documents}
            assert group_ids == {invoice.id, receipt.id}
            assert ours[0].possible_overcount == 987654.32
            assert "Proveedor similar" in ours[0].reasons
        finally:
            with SessionLocal() as cleanup_db:
                cleanup_db.query(Document).filter(Document.id.in_(ids)).delete(synchronize_session=False)
                cleanup_db.query(Vendor).filter(
                    Vendor.id.in_([vendor_a.id, vendor_b.id, vendor_other.id])
                ).delete(synchronize_session=False)
                cleanup_db.commit()


def test_dismissed_group_is_no_longer_flagged_and_is_company_scoped():
    from uuid import uuid4

    import pytest
    from fastapi import HTTPException

    from app.models.duplicate_dismissal import DuplicateDismissal
    from app.services.duplicate_service import dismiss_duplicate_group

    with SessionLocal() as db:
        company, user = seed_test_company_and_user(db)
        vendor = Vendor(company_id=company.id, name="Dup Test Descartado")
        db.add(vendor)
        db.flush()

        doc_a = _doc(db, company.id, vendor.id, 876543.21, date(2026, 4, 1), name="desc-a.pdf")
        doc_b = _doc(db, company.id, vendor.id, 876543.21, date(2026, 4, 2), name="desc-b.pdf")
        db.commit()
        ids = [doc_a.id, doc_b.id]

        try:
            def ours():
                result = find_probable_duplicates(db, company_id=company.id)
                return [g for g in result.groups if any(d.id in set(ids) for d in g.documents)]

            assert len(ours()) == 1

            assert dismiss_duplicate_group(db, company.id, user.id, ids) == 1
            assert ours() == []
            # Idempotent: dismissing again records nothing new.
            assert dismiss_duplicate_group(db, company.id, user.id, ids) == 0

            # A document id from outside the caller's company is rejected.
            with pytest.raises(HTTPException) as exc:
                dismiss_duplicate_group(db, company.id, user.id, [doc_a.id, uuid4()])
            assert exc.value.status_code == 404
        finally:
            with SessionLocal() as cleanup_db:
                cleanup_db.query(DuplicateDismissal).filter(
                    DuplicateDismissal.document_a_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.query(Document).filter(Document.id.in_(ids)).delete(synchronize_session=False)
                cleanup_db.query(Vendor).filter(Vendor.id == vendor.id).delete(synchronize_session=False)
                cleanup_db.commit()
