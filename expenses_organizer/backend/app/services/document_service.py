from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_file import DocumentFile
from app.models.processing_log import ProcessingLog
from app.schemas.document import DocumentListItem, DocumentUploadResponse
from app.services.storage_service import (
    StorageError,
    delete_file,
    read_file_bytes,
    store_file_locally,
    upload_to_supabase_storage,
)

STALE_UPLOAD_THRESHOLD = timedelta(minutes=2)
# Longer than STALE_UPLOAD_THRESHOLD: a genuinely in-flight OCR/AI pass normally finishes
# in well under a minute (see processing_log timings), so this only fires when the
# background task that claimed the document died mid-flight (e.g. a redeploy/restart)
# and never got to update the status at all.
STALE_PROCESSING_THRESHOLD = timedelta(minutes=5)


ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
}


def _source_format_from_mime(mime_type: str | None) -> str:
    if mime_type == "application/pdf":
        return "pdf"
    return "image"


async def create_uploaded_document(
    db: Session,
    file: UploadFile,
    company_id,
    uploaded_by=None,
    document_type: str | None = None,
) -> DocumentUploadResponse:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF and image files are supported.",
        )

    contents = await file.read()
    original_filename = file.filename or "document"
    source_format = _source_format_from_mime(file.content_type)

    try:
        if settings.supabase_url and settings.supabase_service_role_key:
            storage_ref = upload_to_supabase_storage(original_filename, contents, file.content_type)
            storage_path = f"s3://{settings.supabase_storage_bucket}/{storage_ref}"
        else:
            storage_path = store_file_locally(settings.upload_dir, original_filename, contents)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    document = Document(
        company_id=company_id,
        uploaded_by=uploaded_by,
        original_filename=original_filename,
        document_type=document_type,
        source_format=source_format,
        status="uploaded",
        file_size_bytes=len(contents),
        mime_type=file.content_type,
        storage_path=storage_path,
    )

    db.add(document)
    db.flush()

    db.add(
        DocumentFile(
            document_id=document.id,
            file_kind="original",
            storage_path=storage_path,
            mime_type=file.content_type,
            file_size_bytes=len(contents),
        )
    )

    db.add(
        ProcessingLog(
            document_id=document.id,
            step_name="upload",
            status="success",
            message="Document uploaded and stored successfully.",
            meta={
                "filename": original_filename,
                "mime_type": file.content_type,
                "file_size_bytes": len(contents),
                "storage_path": storage_path,
            },
        )
    )
    db.commit()
    db.refresh(document)

    return DocumentUploadResponse(
        id=document.id,
        status=document.status,
        original_filename=document.original_filename,
        storage_path=document.storage_path,
        company_id=document.company_id,
    )


def _to_list_item(db: Session, document: Document) -> DocumentListItem:
    return DocumentListItem(
        id=document.id,
        original_filename=document.original_filename,
        status=document.status,
        document_type=document.document_type,
        vendor_id=document.vendor_id,
        expense_category_id=document.expense_category_id,
        confidence_score=document.confidence_score,
        total_amount=document.total_amount,
        currency=document.currency,
        document_date=document.document_date,
        created_at=document.created_at,
    )


def classify_document(
    db: Session,
    document_id: UUID,
    company_id: UUID,
    vendor_id: UUID | None = None,
    expense_category_id: UUID | None = None,
) -> DocumentListItem:
    document = db.get(Document, document_id)
    if document is None or document.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if vendor_id is not None:
        document.vendor_id = vendor_id
    if expense_category_id is not None:
        document.expense_category_id = expense_category_id

    db.commit()
    db.refresh(document)
    return _to_list_item(db, document)


def delete_document(db: Session, document_id: UUID, company_id: UUID) -> None:
    document = db.get(Document, document_id)
    if document is None or document.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    try:
        delete_file(document.storage_path)
    except StorageError:
        # Best-effort: don't block removing the record (e.g. duplicate cleanup) just
        # because the underlying storage object was already gone or unreachable.
        pass

    db.delete(document)
    db.commit()


def get_document_file(db: Session, document_id: UUID, company_id: UUID) -> tuple[bytes, str, str]:
    """Returns (content, mime_type, filename) for previewing/downloading the
    original uploaded file -- used by the frontend's document preview."""
    document = db.get(Document, document_id)
    if document is None or document.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    try:
        content = read_file_bytes(document.storage_path)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return content, document.mime_type or "application/octet-stream", document.original_filename


def list_resumable_document_ids(
    db: Session,
    company_id: UUID,
    uploaded_older_than: timedelta = STALE_UPLOAD_THRESHOLD,
    processing_older_than: timedelta = STALE_PROCESSING_THRESHOLD,
) -> list[UUID]:
    """Finds documents that need to be (re)kicked into OCR/AI extraction:

    - stuck in 'uploaded' past the normal upload->OCR handoff window (e.g. the browser
      tab closed/lost connection between the upload call and the follow-up processing
      call), or
    - stuck in 'processing' well past how long that step normally takes -- meaning the
      background task that claimed it died mid-flight (worker restart/redeploy) before
      ever finishing or recording a failure.

    Used to auto-resume them instead of relying on someone noticing the stuck status and
    clicking retry."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    uploaded_cutoff = now - uploaded_older_than
    processing_cutoff = now - processing_older_than
    rows = (
        db.query(Document.id)
        .filter(
            Document.company_id == company_id,
            or_(
                and_(Document.status == "uploaded", Document.created_at < uploaded_cutoff),
                and_(Document.status == "processing", Document.updated_at < processing_cutoff),
            ),
        )
        .all()
    )
    return [row.id for row in rows]


def try_claim_document_for_processing(db: Session, document_id: UUID) -> bool:
    """Atomically flips a document to 'processing' from either 'uploaded' or a
    stale 'processing' (see list_resumable_document_ids) so concurrent sweeps (e.g.
    multiple open tabs refreshing the document list) don't both trigger OCR/AI
    extraction for the same document at once. The update also bumps updated_at,
    resetting the staleness clock for this new attempt."""
    result = db.execute(
        update(Document)
        .where(Document.id == document_id, Document.status.in_(["uploaded", "processing"]))
        .values(status="processing")
    )
    db.commit()
    return result.rowcount == 1


def try_claim_batch_result_for_ingestion(
    db: Session, document_id: UUID, batch_id: str, company_id: UUID
) -> bool:
    """Atomically flips a single document out of 'batch_queued' before writing its
    batch result, scoped to both batch_id and company_id so a concurrent poll sweep
    (multiple open tabs, or overlapping background sweeps) can't double-ingest the
    same result, and so a result can never be written onto another company's
    document even though Anthropic's batch itself has no notion of company."""
    result = db.execute(
        update(Document)
        .where(
            Document.id == document_id,
            Document.batch_id == batch_id,
            Document.company_id == company_id,
            Document.status == "batch_queued",
        )
        .values(status="processing")
    )
    db.commit()
    return result.rowcount == 1


def list_outstanding_batch_ids(db: Session, company_id: UUID) -> list[str]:
    """Distinct Anthropic batch ids this company still has documents queued
    against, used to poll each outstanding batch for completion."""
    rows = (
        db.query(Document.batch_id)
        .filter(Document.company_id == company_id, Document.status == "batch_queued")
        .distinct()
        .all()
    )
    return [row.batch_id for row in rows if row.batch_id is not None]


def list_document_ids_for_batch(db: Session, batch_id: str, company_id: UUID) -> list[UUID]:
    """Documents still queued against a given batch -- used only to resolve a
    batch that expired (24h) before Anthropic finished processing it."""
    rows = (
        db.query(Document.id)
        .filter(
            Document.company_id == company_id,
            Document.batch_id == batch_id,
            Document.status == "batch_queued",
        )
        .all()
    )
    return [row.id for row in rows]


def get_last_category_for_vendor(db: Session, company_id: UUID, vendor_id: UUID) -> UUID | None:
    """Most recently touched expense_category_id among this vendor's other
    documents, if any -- used to default a newly-extracted document's category to
    whatever this vendor was last categorized as."""
    document = (
        db.query(Document)
        .filter(
            Document.company_id == company_id,
            Document.vendor_id == vendor_id,
            Document.expense_category_id.isnot(None),
        )
        .order_by(Document.updated_at.desc())
        .first()
    )
    return document.expense_category_id if document is not None else None


def _document_query(
    db: Session,
    company_id: UUID,
    vendor_id: UUID | None = None,
    expense_category_id: UUID | None = None,
    document_date_from: date | None = None,
    document_date_to: date | None = None,
    missing_info: bool = False,
):
    query = db.query(Document).filter(Document.company_id == company_id)
    if vendor_id is not None:
        query = query.filter(Document.vendor_id == vendor_id)
    if expense_category_id is not None:
        query = query.filter(Document.expense_category_id == expense_category_id)
    if document_date_from is not None:
        query = query.filter(Document.document_date >= document_date_from)
    if document_date_to is not None:
        query = query.filter(Document.document_date <= document_date_to)
    if missing_info:
        query = query.filter(
            or_(
                Document.vendor_id.is_(None),
                Document.expense_category_id.is_(None),
                Document.total_amount.is_(None),
            )
        )
    return query


def list_documents(
    db: Session,
    company_id: UUID,
    vendor_id: UUID | None = None,
    expense_category_id: UUID | None = None,
    document_date_from: date | None = None,
    document_date_to: date | None = None,
    missing_info: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DocumentListItem], int]:
    query = _document_query(
        db, company_id, vendor_id, expense_category_id, document_date_from, document_date_to, missing_info
    )
    total = query.count()
    documents = query.order_by(Document.created_at.desc()).limit(limit).offset(offset).all()

    items = [
        DocumentListItem(
            id=document.id,
            original_filename=document.original_filename,
            status=document.status,
            document_type=document.document_type,
            vendor_id=document.vendor_id,
            expense_category_id=document.expense_category_id,
            confidence_score=document.confidence_score,
            total_amount=document.total_amount,
            currency=document.currency,
            document_date=document.document_date,
            created_at=document.created_at,
        )
        for document in documents
    ]
    return items, total
