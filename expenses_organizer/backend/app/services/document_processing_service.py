from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.processing_log import ProcessingLog
from app.services.ai_extraction_service import AIExtractionError, extract_with_claude
from app.services.ocr_service import OCRError, run_ocr
from app.services.storage_service import StorageError, read_file_bytes
from app.services.vendor_service import get_or_create_vendor


def _get_document_or_404(db: Session, document_id: UUID, company_id: UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


def _create_ai_extraction(db: Session, document: Document, content: bytes) -> DocumentExtraction:
    ai_data = extract_with_claude(content, document.mime_type)

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
