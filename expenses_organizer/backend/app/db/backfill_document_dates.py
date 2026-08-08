"""One-off backfill for the `document_date`/`total_amount`/`currency` columns
added after documents were already being processed -- these values already sit
unused inside the stored DocumentExtraction.extracted_data JSON, this just copies
them onto the real columns. Idempotent (only touches rows missing at least one of
these fields), safe to re-run.

Run with: .venv/Scripts/python.exe -m app.db.backfill_document_dates
"""
from __future__ import annotations

from sqlalchemy import or_

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.services.ai_extraction_service import parse_amount, parse_document_date


def main() -> None:
    with SessionLocal() as db:
        documents = (
            db.query(Document)
            .filter(or_(Document.document_date.is_(None), Document.total_amount.is_(None)))
            .all()
        )
        print(f"{len(documents)} documents missing document_date and/or total_amount/currency.")

        updated = 0
        skipped_no_extraction = 0

        for document in documents:
            extraction = (
                db.query(DocumentExtraction)
                .filter(DocumentExtraction.document_id == document.id, DocumentExtraction.is_final.is_(True))
                .order_by(DocumentExtraction.created_at.desc())
                .first()
            )
            if extraction is None:
                skipped_no_extraction += 1
                continue

            data = extraction.extracted_data
            touched = False

            if document.document_date is None:
                parsed_date = parse_document_date(data.get("document_date"))
                if parsed_date is not None:
                    document.document_date = parsed_date
                    touched = True

            if document.total_amount is None:
                parsed_amount = parse_amount(data.get("total_amount"))
                if parsed_amount is not None:
                    document.total_amount = parsed_amount
                    document.currency = data.get("currency")
                    touched = True

            if touched:
                updated += 1

        db.commit()

    print(f"Updated: {updated}")
    print(f"Skipped (no final extraction yet): {skipped_no_extraction}")


if __name__ == "__main__":
    main()
