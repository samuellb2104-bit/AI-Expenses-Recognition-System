"""One-off backfill for the `document_date` column added after documents were
already being processed -- their date already sits unused inside the stored
DocumentExtraction.extracted_data JSON, this just copies it onto the new column.
Idempotent (only touches rows where document_date IS NULL), safe to re-run.

Run with: .venv/Scripts/python.exe -m app.db.backfill_document_dates
"""
from __future__ import annotations

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.services.ai_extraction_service import parse_document_date


def main() -> None:
    with SessionLocal() as db:
        documents = db.query(Document).filter(Document.document_date.is_(None)).all()
        print(f"{len(documents)} documents with no document_date yet.")

        updated = 0
        skipped_no_extraction = 0
        skipped_unparseable = 0

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

            parsed = parse_document_date(extraction.extracted_data.get("document_date"))
            if parsed is None:
                skipped_unparseable += 1
                continue

            document.document_date = parsed
            updated += 1

        db.commit()

    print(f"Updated: {updated}")
    print(f"Skipped (no final extraction yet): {skipped_no_extraction}")
    print(f"Skipped (no usable document_date in extraction): {skipped_unparseable}")


if __name__ == "__main__":
    main()
