from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_file import DocumentFile
from app.models.processing_log import ProcessingLog
from app.schemas.document import DocumentUploadResponse
from app.services.storage_service import (
    StorageError,
    delete_file,
    store_file_locally,
    upload_to_supabase_storage,
)


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


def classify_document(
    db: Session,
    document_id: UUID,
    company_id: UUID,
    vendor_id: UUID | None = None,
    expense_category_id: UUID | None = None,
) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if vendor_id is not None:
        document.vendor_id = vendor_id
    if expense_category_id is not None:
        document.expense_category_id = expense_category_id

    db.commit()
    db.refresh(document)
    return document


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


def list_documents(
    db: Session,
    company_id: UUID,
    vendor_id: UUID | None = None,
    expense_category_id: UUID | None = None,
) -> list[Document]:
    query = db.query(Document).filter(Document.company_id == company_id)
    if vendor_id is not None:
        query = query.filter(Document.vendor_id == vendor_id)
    if expense_category_id is not None:
        query = query.filter(Document.expense_category_id == expense_category_id)
    return query.order_by(Document.created_at.desc()).all()
