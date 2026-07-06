from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.document import DocumentUploadResponse
from app.services.document_service import create_uploaded_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    company_id: UUID = Form(...),
    uploaded_by: UUID | None = Form(None),
    document_type: str | None = Form(None),
    db: Session = Depends(get_db),
):
    return await create_uploaded_document(
        db=db,
        file=file,
        company_id=company_id,
        uploaded_by=uploaded_by,
        document_type=document_type,
    )
