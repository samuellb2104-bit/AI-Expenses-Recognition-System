from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context
from app.db.session import SessionLocal, get_db
from app.schemas.document import (
    DocumentClassifyRequest,
    DocumentExtractionRead,
    DocumentListItem,
    DocumentUploadResponse,
)
from app.services.auth_service import AuthContext
from app.services.document_processing_service import run_ai_extraction, run_ocr_extraction
from app.services.document_service import (
    classify_document,
    create_uploaded_document,
    delete_document,
    list_documents,
    list_resumable_document_ids,
    try_claim_document_for_processing,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _resume_stale_document(document_id: UUID, company_id: UUID) -> None:
    db = SessionLocal()
    try:
        if not try_claim_document_for_processing(db, document_id):
            return  # already picked up by another sweep/tab in the meantime
        run_ocr_extraction(db=db, document_id=document_id, company_id=company_id)
    except Exception:
        # Best-effort background resume -- run_ocr_extraction already records the
        # failure on the document/processing_log; nothing else to do with the
        # exception here since there's no request/response to report it through.
        pass
    finally:
        db.close()


@router.get("", response_model=list[DocumentListItem])
def get_documents(
    background_tasks: BackgroundTasks,
    vendor_id: UUID | None = Query(None),
    expense_category_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Lists documents for the caller's company, optionally filtered by vendor and/or
    expense category -- the endpoint the frontend will use to browse invoices grouped
    by proveedor/categoria.

    Also opportunistically resumes any documents stuck in 'uploaded' (e.g. the browser
    closed/lost connection between the upload call and the follow-up OCR call), or stuck
    in 'processing' because a previous resume attempt died mid-flight, since the frontend
    refreshes this list constantly -- so orphaned uploads self-heal without anyone needing
    to notice and click retry."""
    for stale_id in list_resumable_document_ids(db=db, company_id=auth.company_id):
        background_tasks.add_task(_resume_stale_document, stale_id, auth.company_id)

    return list_documents(
        db=db,
        company_id=auth.company_id,
        vendor_id=vendor_id,
        expense_category_id=expense_category_id,
    )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    document_type: str | None = Form(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    return await create_uploaded_document(
        db=db,
        file=file,
        company_id=auth.company_id,
        uploaded_by=auth.user_id,
        document_type=document_type,
    )


@router.post("/{document_id}/ocr", response_model=DocumentExtractionRead, status_code=status.HTTP_201_CREATED)
def process_document_ocr(
    document_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Runs OCR, then always runs the Claude structured extraction pass on the same
    document (regardless of OCR confidence) so vendor/amount/date fields are always
    populated."""
    return run_ocr_extraction(db=db, document_id=document_id, company_id=auth.company_id)


@router.post("/{document_id}/ai-extract", response_model=DocumentExtractionRead, status_code=status.HTTP_201_CREATED)
def process_document_ai_extraction(
    document_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Forces a Claude extraction pass regardless of OCR confidence. Useful for testing
    or for documents where OCR is known to be unreliable (e.g. handwritten receipts)."""
    return run_ai_extraction(db=db, document_id=document_id, company_id=auth.company_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_endpoint(
    document_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Deletes a document, its stored file, and its extraction/log history --
    for duplicates or mistaken uploads. Vendors/categories it referenced are untouched."""
    delete_document(db=db, document_id=document_id, company_id=auth.company_id)


@router.patch("/{document_id}/classify", response_model=DocumentListItem)
def classify_document_endpoint(
    document_id: UUID,
    payload: DocumentClassifyRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Manually assigns/corrects the vendor and/or expense category for a document."""
    return classify_document(
        db=db,
        document_id=document_id,
        company_id=auth.company_id,
        vendor_id=payload.vendor_id,
        expense_category_id=payload.expense_category_id,
    )
