from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentCreate(BaseModel):
    company_id: UUID
    uploaded_by: UUID | None = None
    original_filename: str
    document_type: str | None = None
    source_format: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    storage_path: str


class DocumentRead(DocumentCreate):
    id: UUID
    status: str


class DocumentUploadResponse(BaseModel):
    id: UUID
    status: str
    original_filename: str
    storage_path: str
    company_id: UUID


class DocumentExtractionRead(BaseModel):
    id: UUID
    document_id: UUID
    extraction_method: str
    provider_name: str | None
    raw_text: str | None
    extracted_data: dict
    confidence_score: float | None
    is_final: bool

    model_config = {"from_attributes": True}


class DocumentClassifyRequest(BaseModel):
    vendor_id: UUID | None = None
    expense_category_id: UUID | None = None


class DocumentListItem(BaseModel):
    id: UUID
    original_filename: str
    status: str
    document_type: str | None
    vendor_id: UUID | None
    expense_category_id: UUID | None
    confidence_score: float | None
    total_amount: float | None
    currency: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
