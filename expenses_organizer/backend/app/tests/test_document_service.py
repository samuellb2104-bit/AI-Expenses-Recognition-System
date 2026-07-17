import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.models.document import Document
from app.schemas.document import DocumentUploadResponse
from app.services import document_service
from app.services.storage_service import StorageError


class FakeUploadFile:
    filename = "invoice.pdf"
    content_type = "application/pdf"

    async def read(self) -> bytes:
        return b"%PDF-1.4 test"


class FakeSession:
    def __init__(self, document=None):
        self._document = document
        self.added = []
        self.deleted = []
        self.committed = False

    def get(self, model, document_id):
        if model is Document and self._document is not None and document_id == self._document.id:
            return self._document
        return None

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def flush(self):
        for obj in self.added:
            if isinstance(obj, Document) and obj.id is None:
                obj.id = uuid4()

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        return None


def test_create_uploaded_document_stores_file_and_logs_upload(monkeypatch):
    company_id = uuid4()
    session = FakeSession()

    monkeypatch.setattr(document_service.settings, "supabase_url", None)
    monkeypatch.setattr(document_service.settings, "supabase_service_role_key", None)
    monkeypatch.setattr(
        document_service,
        "store_file_locally",
        lambda upload_dir, filename, content: "uploads/test-invoice.pdf",
    )

    response = asyncio.run(
        document_service.create_uploaded_document(
            db=session,
            file=FakeUploadFile(),
            company_id=company_id,
            document_type="invoice",
        )
    )

    document = session.added[0]
    document_file = session.added[1]
    log = session.added[2]

    assert isinstance(response, DocumentUploadResponse)
    assert isinstance(response.id, UUID)
    assert response.company_id == company_id
    assert response.status == "uploaded"
    assert response.storage_path == "uploads/test-invoice.pdf"
    assert document.original_filename == "invoice.pdf"
    assert document.file_size_bytes == len(b"%PDF-1.4 test")
    assert document_file.file_kind == "original"
    assert document_file.storage_path == "uploads/test-invoice.pdf"
    assert document_file.document_id == document.id
    assert log.step_name == "upload"
    assert log.status == "success"
    assert session.committed is True


def _build_document() -> Document:
    return Document(
        id=uuid4(),
        company_id=uuid4(),
        original_filename="invoice.pdf",
        source_format="pdf",
        status="ai_extraction_completed",
        mime_type="application/pdf",
        storage_path="s3://documents/some-object.pdf",
    )


def test_delete_document_removes_record_and_deletes_storage_file(monkeypatch):
    document = _build_document()
    session = FakeSession(document)

    deleted_paths = []
    monkeypatch.setattr(document_service, "delete_file", lambda storage_path: deleted_paths.append(storage_path))

    document_service.delete_document(db=session, document_id=document.id, company_id=document.company_id)

    assert deleted_paths == ["s3://documents/some-object.pdf"]
    assert session.deleted == [document]
    assert session.committed is True


def test_delete_document_raises_404_when_document_missing():
    session = FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        document_service.delete_document(db=session, document_id=uuid4(), company_id=uuid4())

    assert exc_info.value.status_code == 404


def test_delete_document_raises_404_when_company_id_does_not_match():
    document = _build_document()
    session = FakeSession(document)

    with pytest.raises(HTTPException) as exc_info:
        document_service.delete_document(db=session, document_id=document.id, company_id=uuid4())

    assert exc_info.value.status_code == 404


def test_delete_document_still_deletes_record_when_storage_delete_fails(monkeypatch):
    document = _build_document()
    session = FakeSession(document)

    def _raise_storage_error(storage_path):
        raise StorageError("Supabase Storage connection failed: timeout")

    monkeypatch.setattr(document_service, "delete_file", _raise_storage_error)

    document_service.delete_document(db=session, document_id=document.id, company_id=document.company_id)

    assert session.deleted == [document]
    assert session.committed is True
