from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.processing_log import ProcessingLog
from app.services.ai_extraction_service import (
    AIExtractionError,
    build_batch_request,
    extract_with_claude,
    iter_batch_results,
    retrieve_batch,
    submit_batch,
)
from app.services.document_service import (
    list_document_ids_for_batch,
    try_claim_batch_result_for_ingestion,
)
from app.services.ocr_service import OCRError, run_ocr
from app.services.storage_service import StorageError, read_file_bytes
from app.services.vendor_service import get_or_create_vendor


def _get_document_or_404(db: Session, document_id: UUID, company_id: UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


def _persist_ai_extraction(db: Session, document: Document, ai_data: dict) -> DocumentExtraction:
    extraction = DocumentExtraction(
        document_id=document.id,
        extraction_method="ai",
        provider_name="claude",
        raw_text=None,
        extracted_data=ai_data,
        confidence_score=None,
        is_final=True,
    )
    db.add(extraction)

    document.status = "ai_extraction_completed"

    vendor_name = ai_data.get("vendor_name")
    if vendor_name:
        vendor = get_or_create_vendor(db, company_id=document.company_id, name=vendor_name)
        if vendor is not None:
            document.vendor_id = vendor.id

    db.add(
        ProcessingLog(
            document_id=document.id,
            step_name="ai_extraction",
            status="success",
            message="AI extraction completed.",
            meta={"provider_name": "claude", "model": settings.anthropic_model},
        )
    )
    db.commit()
    db.refresh(extraction)
    return extraction


def _create_ai_extraction(db: Session, document: Document, content: bytes) -> DocumentExtraction:
    ai_data = extract_with_claude(content, document.mime_type)
    return _persist_ai_extraction(db, document, ai_data)


def run_ocr_extraction(db: Session, document_id: UUID, company_id: UUID) -> DocumentExtraction:
    """Runs OCR first (kept for raw_text and confidence_score as a review-quality
    signal), then always runs the Claude structured extraction pass, since only Claude
    produces the structured fields (vendor_name, total_amount, etc.) that vendor
    auto-linking and expense reports depend on."""
    document = _get_document_or_404(db, document_id, company_id)

    try:
        content = read_file_bytes(document.storage_path)
        result = run_ocr(content, document.mime_type)
    except (StorageError, OCRError) as exc:
        document.status = "ocr_failed"
        db.add(
            ProcessingLog(
                document_id=document.id,
                step_name="ocr",
                status="failed",
                message=str(exc),
                meta={},
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    ocr_extraction = DocumentExtraction(
        document_id=document.id,
        extraction_method="ocr",
        provider_name="tesseract",
        raw_text=result.raw_text,
        extracted_data={},
        confidence_score=result.confidence_score,
        is_final=False,
    )
    db.add(ocr_extraction)

    document.page_count = result.page_count
    document.confidence_score = result.confidence_score

    db.add(
        ProcessingLog(
            document_id=document.id,
            step_name="ocr",
            status="success",
            message="OCR extraction completed successfully.",
            meta={
                "provider_name": "tesseract",
                "page_count": result.page_count,
                "confidence_score": result.confidence_score,
                "raw_text_length": len(result.raw_text),
            },
        )
    )
    db.commit()

    try:
        return _create_ai_extraction(db, document, content)
    except AIExtractionError as exc:
        document.status = "needs_review"
        db.add(
            ProcessingLog(
                document_id=document.id,
                step_name="ai_extraction",
                status="failed",
                message=str(exc),
                meta={},
            )
        )
        db.commit()
        db.refresh(ocr_extraction)
        return ocr_extraction


def run_ai_extraction(db: Session, document_id: UUID, company_id: UUID) -> DocumentExtraction:
    """Forces the Claude structured extraction directly, without requiring a prior OCR
    pass. Useful to retry after a transient API error, or for documents where OCR is
    known to be unreliable (e.g. handwritten receipts)."""
    document = _get_document_or_404(db, document_id, company_id)

    try:
        content = read_file_bytes(document.storage_path)
        return _create_ai_extraction(db, document, content)
    except (StorageError, AIExtractionError) as exc:
        document.status = "needs_review"
        db.add(
            ProcessingLog(
                document_id=document.id,
                step_name="ai_extraction",
                status="failed",
                message=str(exc),
                meta={},
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def submit_batch_ai_extraction(
    db: Session, document_ids: list[UUID], company_id: UUID
) -> tuple[str | None, list[UUID], list[UUID]]:
    """Submits every given document (that is actually this company's and still
    'uploaded') as a single Anthropic Message Batch, so large uploads (e.g. 50+
    files) are processed by Anthropic's infrastructure instead of one blocking
    Claude call per file on this backend. Returns (batch_id, submitted_ids,
    skipped_ids) -- skipped ids are silently ignored rather than erroring, since
    the caller may be re-submitting a batch that partially overlaps a previous one."""
    candidates = (
        db.query(Document)
        .filter(Document.id.in_(document_ids), Document.company_id == company_id)
        .all()
    )
    candidates_by_id = {document.id: document for document in candidates}

    eligible = [document for document in candidates if document.status == "uploaded"]
    skipped_ids = [
        document_id for document_id in document_ids if candidates_by_id.get(document_id) not in eligible
    ]

    if not eligible:
        return None, [], skipped_ids

    # Captured before commit: expire_on_commit (the default) invalidates ORM attributes
    # after commit, so reading document.id afterward would trigger an unplanned reload
    # query -- which, against Supabase's Transaction-mode pooler, can collide with a
    # stale prepared statement name from a different pooled connection and 500.
    eligible_ids = [document.id for document in eligible]

    requests = []
    for document in eligible:
        content = read_file_bytes(document.storage_path)
        requests.append(build_batch_request(str(document.id), content, document.mime_type))

    batch = submit_batch(requests)

    for document in eligible:
        document.status = "batch_queued"
        document.batch_id = batch.id
        db.add(
            ProcessingLog(
                document_id=document.id,
                step_name="ai_extraction_batch_submit",
                status="success",
                message="Submitted to Anthropic Message Batch.",
                meta={"batch_id": batch.id},
            )
        )
    db.commit()

    return batch.id, eligible_ids, skipped_ids


def poll_and_ingest_batch(db: Session, batch_id: str, company_id: UUID) -> None:
    """Checks an outstanding batch's status and, once Anthropic has finished
    processing it, ingests each result into its document. Safe to call repeatedly
    (e.g. from a periodic sweep) -- already-ingested documents are no longer
    'batch_queued' so results for them are naturally skipped by the atomic claim."""
    batch = retrieve_batch(batch_id)

    if batch.processing_status != "ended":
        if datetime.now(timezone.utc) > batch.expires_at:
            expired_ids = list_document_ids_for_batch(db, batch_id, company_id)
            for document_id in expired_ids:
                if not try_claim_batch_result_for_ingestion(db, document_id, batch_id, company_id):
                    continue
                document = db.get(Document, document_id)
                if document is None:
                    continue
                document.status = "needs_review"
                db.add(
                    ProcessingLog(
                        document_id=document_id,
                        step_name="ai_extraction",
                        status="failed",
                        message="Message Batch expired (24h) before Anthropic finished processing it.",
                        meta={"batch_id": batch_id},
                    )
                )
                db.commit()
        return

    for custom_id, ai_data, error in iter_batch_results(batch_id):
        document_id = UUID(custom_id)
        if not try_claim_batch_result_for_ingestion(db, document_id, batch_id, company_id):
            continue  # already ingested by a concurrent sweep, or the document was deleted

        document = db.get(Document, document_id)
        if document is None:
            continue

        if ai_data is not None:
            _persist_ai_extraction(db, document, ai_data)
        else:
            document.status = "needs_review"
            db.add(
                ProcessingLog(
                    document_id=document_id,
                    step_name="ai_extraction",
                    status="failed",
                    message=error,
                    meta={"batch_id": batch_id},
                )
            )
            db.commit()
