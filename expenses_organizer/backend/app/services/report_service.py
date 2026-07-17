from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.expense_category import ExpenseCategory
from app.models.vendor import Vendor
from app.schemas.report import ExpenseCategoryTotal, ExpenseSummaryResponse, ExpenseSummaryRow, VendorTotal

UNCATEGORIZED_LABEL = "Sin categoria"
UNKNOWN_VENDOR_LABEL = "Sin proveedor"


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def get_expense_summary(
    db: Session,
    company_id: uuid.UUID,
    vendor_id: uuid.UUID | None = None,
    expense_category_id: uuid.UUID | None = None,
) -> ExpenseSummaryResponse:
    document_query = db.query(Document).filter(Document.company_id == company_id)
    if vendor_id is not None:
        document_query = document_query.filter(Document.vendor_id == vendor_id)
    if expense_category_id is not None:
        document_query = document_query.filter(Document.expense_category_id == expense_category_id)
    documents = document_query.all()

    if not documents:
        return ExpenseSummaryResponse(
            rows=[], totals_by_category=[], totals_by_vendor=[], grand_total=0.0, document_count=0
        )

    document_ids = [d.id for d in documents]

    # Final (AI-extracted) rows only, most recent one per document if a document
    # was ever re-extracted.
    final_extractions = (
        db.query(DocumentExtraction)
        .filter(DocumentExtraction.document_id.in_(document_ids), DocumentExtraction.is_final.is_(True))
        .order_by(DocumentExtraction.created_at.desc())
        .all()
    )
    latest_by_document: dict[uuid.UUID, DocumentExtraction] = {}
    for extraction in final_extractions:
        latest_by_document.setdefault(extraction.document_id, extraction)

    vendor_ids = {d.vendor_id for d in documents if d.vendor_id is not None}
    category_ids = {d.expense_category_id for d in documents if d.expense_category_id is not None}
    vendors_by_id = (
        {v.id: v for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()} if vendor_ids else {}
    )
    categories_by_id = (
        {c.id: c for c in db.query(ExpenseCategory).filter(ExpenseCategory.id.in_(category_ids)).all()}
        if category_ids
        else {}
    )

    rows: list[ExpenseSummaryRow] = []
    category_totals: dict[uuid.UUID | None, dict] = {}
    vendor_totals: dict[uuid.UUID | None, dict] = {}
    grand_total = 0.0

    for document in documents:
        extraction = latest_by_document.get(document.id)
        data = extraction.extracted_data if extraction is not None else {}

        total_amount = _to_float(data.get("total_amount"))
        tax_amount = _to_float(data.get("tax_amount"))
        document_date = _to_date(data.get("document_date"))
        currency = data.get("currency")

        vendor = vendors_by_id.get(document.vendor_id)
        category = categories_by_id.get(document.expense_category_id)

        rows.append(
            ExpenseSummaryRow(
                document_id=document.id,
                document_date=document_date,
                vendor_id=document.vendor_id,
                vendor_name=vendor.name if vendor is not None else None,
                expense_category_id=document.expense_category_id,
                expense_category_name=category.name if category is not None else None,
                currency=currency,
                total_amount=total_amount,
                tax_amount=tax_amount,
            )
        )

        if total_amount is None:
            continue

        grand_total += total_amount

        category_bucket = category_totals.setdefault(
            document.expense_category_id,
            {"name": category.name if category is not None else UNCATEGORIZED_LABEL, "total": 0.0, "count": 0},
        )
        category_bucket["total"] += total_amount
        category_bucket["count"] += 1

        vendor_bucket = vendor_totals.setdefault(
            document.vendor_id,
            {"name": vendor.name if vendor is not None else UNKNOWN_VENDOR_LABEL, "total": 0.0, "count": 0},
        )
        vendor_bucket["total"] += total_amount
        vendor_bucket["count"] += 1

    totals_by_category = [
        ExpenseCategoryTotal(
            expense_category_id=key,
            expense_category_name=bucket["name"],
            total_amount=round(bucket["total"], 2),
            document_count=bucket["count"],
        )
        for key, bucket in sorted(category_totals.items(), key=lambda item: item[1]["total"], reverse=True)
    ]
    totals_by_vendor = [
        VendorTotal(
            vendor_id=key,
            vendor_name=bucket["name"],
            total_amount=round(bucket["total"], 2),
            document_count=bucket["count"],
        )
        for key, bucket in sorted(vendor_totals.items(), key=lambda item: item[1]["total"], reverse=True)
    ]

    return ExpenseSummaryResponse(
        rows=rows,
        totals_by_category=totals_by_category,
        totals_by_vendor=totals_by_vendor,
        grand_total=round(grand_total, 2),
        document_count=len(documents),
    )
