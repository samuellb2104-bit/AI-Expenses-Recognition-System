from pydantic import BaseModel
from uuid import UUID


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
