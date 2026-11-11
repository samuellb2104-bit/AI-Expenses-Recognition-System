from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.services.ai_extraction_service import parse_amount, resolve_amount

# Peso amounts under this are almost certainly a value read without its thousands
# ("186.900" stored as 186.9), not a real receipt.
COP_IMPLAUSIBLY_SMALL = 1000

# Line items rarely add up to the cent (rounding, discounts), so only flag a
# mismatch beyond this fraction of the total (with a 1-unit floor).
LINES_TOLERANCE_RATIO = 0.005

_ID_CHUNK = 500


def _format_amount(value: float) -> str:
    if value == round(value):
        return f"{value:,.0f}".replace(",", ".")
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def check_amounts(
    total_amount: float | None,
    currency: str | None,
    tax_amount: float | None = None,
    line_totals: list[float | None] | None = None,
) -> list[str]:
    """Plausibility checks on an extracted amount. Returns human-readable warnings
    (Spanish, shown in the UI); an empty list means nothing looks off. These are
    hints for a person to look at the document, not proof of an error."""
    if total_amount is None:
        return []

    warnings: list[str] = []
    is_cop = (currency or "").upper() == "COP"

    if is_cop and 0 < total_amount < COP_IMPLAUSIBLY_SMALL:
        warnings.append(
            f"Valor menor a $1.000 COP ({_format_amount(total_amount)}): puede faltar la parte de los miles."
        )
    elif is_cop and total_amount != round(total_amount):
        warnings.append(
            f"Valor con decimales en COP ({_format_amount(total_amount)}): puede estar mal leído."
        )

    if not currency:
        warnings.append("No se detectó la moneda.")

    if tax_amount is not None and tax_amount > total_amount:
        warnings.append(
            f"El impuesto ({_format_amount(tax_amount)}) es mayor que el total ({_format_amount(total_amount)})."
        )

    if line_totals and all(t is not None for t in line_totals):
        lines_sum = sum(t for t in line_totals if t is not None)
        tolerance = max(1.0, LINES_TOLERANCE_RATIO * total_amount)
        # Line totals may or may not include tax, so accept either reading.
        if abs(lines_sum - total_amount) > tolerance and abs(lines_sum + (tax_amount or 0) - total_amount) > tolerance:
            warnings.append(
                f"La suma de las líneas ({_format_amount(lines_sum)}) no coincide con el total "
                f"({_format_amount(total_amount)})."
            )

    return warnings


def _latest_final_extractions(db: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    latest: dict[uuid.UUID, dict] = {}
    for start in range(0, len(document_ids), _ID_CHUNK):
        chunk = document_ids[start : start + _ID_CHUNK]
        rows = (
            db.query(DocumentExtraction)
            .filter(DocumentExtraction.document_id.in_(chunk), DocumentExtraction.is_final.is_(True))
            .order_by(DocumentExtraction.created_at.desc())
            .all()
        )
        for row in rows:
            latest.setdefault(row.document_id, row.extracted_data or {})
    return latest


def load_amount_warnings(db: Session, documents: Iterable[Document]) -> dict[uuid.UUID, list[str]]:
    """Warnings per document id (only documents that have any). Computed on read from
    what is stored, so reprocessing a document clears its warnings with no extra state
    to keep in sync."""
    documents = [d for d in documents if d.total_amount is not None]
    if not documents:
        return {}

    extractions = _latest_final_extractions(db, [d.id for d in documents])

    result: dict[uuid.UUID, list[str]] = {}
    for document in documents:
        data = extractions.get(document.id, {})
        line_totals = [parse_amount(line.get("total")) for line in (data.get("line_items") or []) if isinstance(line, dict)]
        warnings = check_amounts(
            total_amount=float(document.total_amount),
            currency=document.currency,
            tax_amount=resolve_amount(data, "tax_amount"),
            line_totals=line_totals,
        )
        if warnings:
            result[document.id] = warnings
    return result
