import asyncio
from uuid import UUID, uuid4

from app.models.document import Document
from app.schemas.document import DocumentUploadResponse
from app.services import document_service


class FakeUploadFile:
    filename = "invoice.pdf"
    content_type = "application/pdf"

    async def read(self) -> bytes:
        return b"%PDF-1.4 test"


class FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

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
    log = session.added[1]

    assert isinstance(response, DocumentUploadResponse)
    assert isinstance(response.id, UUID)
    assert response.company_id == company_id
    assert response.status == "uploaded"
    assert response.storage_path == "uploads/test-invoice.pdf"
    assert document.original_filename == "invoice.pdf"
    assert document.file_size_bytes == len(b"%PDF-1.4 test")
    assert log.step_name == "upload"
    assert log.status == "success"
    assert session.committed is True
