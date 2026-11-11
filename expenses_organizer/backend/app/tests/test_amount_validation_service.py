from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.services import document_service
from app.services.amount_validation_service import check_amounts


def test_cop_value_under_a_thousand_is_flagged_as_missing_thousands():
    warnings = check_amounts(total_amount=386.75, currency="COP")
    assert len(warnings) == 1
    assert "miles" in warnings[0]


def test_cop_decimals_are_flagged_when_value_is_not_tiny():
    warnings = check_amounts(total_amount=17390.72, currency="COP")
    assert len(warnings) == 1
    assert "decimales" in warnings[0]


def test_plausible_cop_amounts_have_no_warnings():
    assert check_amounts(total_amount=186900, currency="COP") == []
    assert check_amounts(total_amount=186900, currency="cop") == []
    # Small amounts are normal in other currencies.
    assert check_amounts(total_amount=45.5, currency="USD") == []


def test_missing_total_never_warns():
    assert check_amounts(total_amount=None, currency=None) == []


def test_missing_currency_is_flagged():
    assert any("moneda" in w for w in check_amounts(total_amount=186900, currency=None))


def test_tax_greater_than_total_is_flagged():
    warnings = check_amounts(total_amount=1000, currency="COP", tax_amount=5000)
    assert any("impuesto" in w for w in warnings)


def test_lines_sum_mismatch_is_flagged_but_tax_inclusive_and_exclusive_both_pass():
    # Lines clearly don't add up to the total (total misread by a factor of 1000).
    mismatch = check_amounts(total_amount=17390.72, currency="COP", line_totals=[17390715.0])
    assert any("suma de las líneas" in w for w in mismatch)

    # Lines add up exactly.
    assert check_amounts(total_amount=119000, currency="COP", line_totals=[100000, 19000]) == []
    # Lines are pre-tax; total includes the tax.
    assert check_amounts(total_amount=119000, currency="COP", tax_amount=19000, line_totals=[100000]) == []
    # Rounding within tolerance.
    assert check_amounts(total_amount=119000, currency="COP", line_totals=[100000, 19001]) == []
    # A line without a total makes the comparison meaningless, so it is skipped.
    assert check_amounts(total_amount=119000, currency="COP", line_totals=[100000, None]) == []


def _make_document(db, company_id, total_amount, currency, name):
    document = Document(
        company_id=company_id,
        original_filename=name,
        source_format="pdf",
        status="ai_extraction_completed",
        storage_path=f"uploads/{name}",
        total_amount=total_amount,
        currency=currency,
    )
    db.add(document)
    db.flush()
    return document


def test_list_documents_reports_warnings_and_filters_by_amount_alert():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        suspicious = _make_document(db, company.id, 386.75, "COP", "alerta-sospechoso.pdf")
        fine = _make_document(db, company.id, 386750, "COP", "alerta-correcto.pdf")
        mismatch = _make_document(db, company.id, 17390.72, "COP", "alerta-lineas.pdf")
        db.add(
            DocumentExtraction(
                document_id=mismatch.id,
                extraction_method="ai",
                provider_name="claude",
                extracted_data={"line_items": [{"description": "x", "total": 17390715}]},
                is_final=True,
            )
        )
        db.commit()
        ids = [suspicious.id, fine.id, mismatch.id]

        try:
            all_items, _ = document_service.list_documents(db, company.id, limit=1000)
            by_id = {item.id: item for item in all_items if item.id in set(ids)}
            assert by_id[suspicious.id].amount_warnings
            assert by_id[fine.id].amount_warnings == []
            assert any("suma de las líneas" in w for w in by_id[mismatch.id].amount_warnings)

            flagged, flagged_total = document_service.list_documents(
                db, company.id, amount_alert=True, limit=1000
            )
            flagged_ids = {item.id for item in flagged}
            assert {suspicious.id, mismatch.id} <= flagged_ids
            assert fine.id not in flagged_ids
            assert flagged_total == len(flagged)
            assert all(item.amount_warnings for item in flagged)

            # Pagination applies to the flagged set.
            page, page_total = document_service.list_documents(
                db, company.id, amount_alert=True, limit=1, offset=0
            )
            assert len(page) == 1
            assert page_total == flagged_total
        finally:
            with SessionLocal() as cleanup_db:
                cleanup_db.query(DocumentExtraction).filter(
                    DocumentExtraction.document_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.query(Document).filter(Document.id.in_(ids)).delete(synchronize_session=False)
                cleanup_db.commit()
