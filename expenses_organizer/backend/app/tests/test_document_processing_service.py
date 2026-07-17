from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.document import Document
from app.services import document_processing_service
from app.services.ai_extraction_service import AIExtractionError
from app.services.ocr_service import OCRError, OCRResult
from app.services.storage_service import StorageError


class FakeSession:
    def __init__(self, document):
        self._document = document
        self.added = []
        self.committed = False

    def get(self, model, document_id):
        if model is Document and document_id == self._document.id:
            return self._document
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        return None


class FakeVendor:
    def __init__(self):
        self.id = uuid4()


def _build_document() -> Document:
    return Document(
        id=uuid4(),
        company_id=uuid4(),
        original_filename="invoice.pdf",
        source_format="pdf",
        status="uploaded",
        mime_type="application/pdf",
        storage_path="uploads/invoice.pdf",
    )


def test_run_ocr_extraction_always_runs_ai_extraction_after_ocr(monkeypatch):
    document = _build_document()
    session = FakeSession(document)
    fake_vendor = FakeVendor()

    monkeypatch.setattr(document_processing_service, "read_file_bytes", lambda storage_path: b"fake-bytes")
    monkeypatch.setattr(
        document_processing_service,
        "run_ocr",
        # High confidence on purpose: proves AI still runs even when OCR did fine,
        # since only Claude extracts structured fields like vendor_name/total_amount.
        lambda content, mime_type: OCRResult(raw_text="FACTURA Total: 45000", confidence_score=91.5, page_count=1),
    )
    monkeypatch.setattr(
        document_processing_service,
        "extract_with_claude",
        lambda content, mime_type: {"vendor_name": "Panaderia El Trigo", "total_amount": 45000},
    )
    monkeypatch.setattr(
        document_processing_service,
        "get_or_create_vendor",
        lambda db, company_id, name, tax_id=None: fake_vendor,
    )

    extraction = document_processing_service.run_ocr_extraction(db=session, document_id=document.id, company_id=document.company_id)

    assert extraction.extraction_method == "ai"
    assert extraction.provider_name == "claude"
    assert extraction.is_final is True
    assert extraction.extracted_data["vendor_name"] == "Panaderia El Trigo"
    assert document.status == "ai_extraction_completed"
    assert document.vendor_id == fake_vendor.id
    assert document.page_count == 1
    assert document.confidence_score == 91.5  # OCR confidence is kept as a review signal
    assert session.committed is True

    ocr_extractions = [obj for obj in session.added if getattr(obj, "extraction_method", None) == "ocr"]
    assert len(ocr_extractions) == 1  # the OCR pass is still kept for audit
    assert ocr_extractions[0].raw_text == "FACTURA Total: 45000"

    log_steps = [obj.step_name for obj in session.added if obj.__class__.__name__ == "ProcessingLog"]
    assert log_steps == ["ocr", "ai_extraction"]


def test_run_ocr_extraction_raises_404_when_document_missing():
    session = FakeSession(_build_document())

    with pytest.raises(HTTPException) as exc_info:
        document_processing_service.run_ocr_extraction(db=session, document_id=uuid4(), company_id=uuid4())

    assert exc_info.value.status_code == 404


def test_run_ocr_extraction_raises_404_when_company_id_does_not_match():
    document = _build_document()
    session = FakeSession(document)

    with pytest.raises(HTTPException) as exc_info:
        document_processing_service.run_ocr_extraction(db=session, document_id=document.id, company_id=uuid4())

    assert exc_info.value.status_code == 404


def test_run_ocr_extraction_marks_document_failed_when_storage_download_fails(monkeypatch):
    document = _build_document()
    session = FakeSession(document)

    def _raise_storage_error(storage_path):
        raise StorageError("Supabase Storage connection failed: timeout")

    monkeypatch.setattr(document_processing_service, "read_file_bytes", _raise_storage_error)

    with pytest.raises(HTTPException) as exc_info:
        document_processing_service.run_ocr_extraction(db=session, document_id=document.id, company_id=document.company_id)

    assert exc_info.value.status_code == 502
    assert document.status == "ocr_failed"
    assert session.committed is True

    log_entries = [obj for obj in session.added if obj.__class__.__name__ == "ProcessingLog"]
    assert log_entries[0].step_name == "ocr"
    assert log_entries[0].status == "failed"


def test_run_ocr_extraction_marks_document_failed_when_ocr_raises(monkeypatch):
    document = _build_document()
    session = FakeSession(document)

    monkeypatch.setattr(document_processing_service, "read_file_bytes", lambda storage_path: b"fake-bytes")

    def _raise_ocr_error(content, mime_type):
        raise OCRError("Tesseract executable not found.")

    monkeypatch.setattr(document_processing_service, "run_ocr", _raise_ocr_error)

    with pytest.raises(HTTPException) as exc_info:
        document_processing_service.run_ocr_extraction(db=session, document_id=document.id, company_id=document.company_id)

    assert exc_info.value.status_code == 502
    assert document.status == "ocr_failed"


def test_run_ocr_extraction_keeps_ocr_result_when_ai_extraction_fails(monkeypatch):
    document = _build_document()
    session = FakeSession(document)

    monkeypatch.setattr(document_processing_service, "read_file_bytes", lambda storage_path: b"fake-bytes")
    monkeypatch.setattr(
        document_processing_service,
        "run_ocr",
        lambda content, mime_type: OCRResult(raw_text="borroso", confidence_score=None, page_count=1),
    )

    def _raise_ai_error(content, mime_type):
        raise AIExtractionError("ANTHROPIC_API_KEY is not configured.")

    monkeypatch.setattr(document_processing_service, "extract_with_claude", _raise_ai_error)

    extraction = document_processing_service.run_ocr_extraction(db=session, document_id=document.id, company_id=document.company_id)

    assert extraction.extraction_method == "ocr"
    assert document.status == "needs_review"

    log_entries = [obj for obj in session.added if obj.__class__.__name__ == "ProcessingLog"]
    assert log_entries[-1].step_name == "ai_extraction"
    assert log_entries[-1].status == "failed"


def test_run_ai_extraction_runs_claude_directly(monkeypatch):
    document = _build_document()
    session = FakeSession(document)
    fake_vendor = FakeVendor()

    monkeypatch.setattr(document_processing_service, "read_file_bytes", lambda storage_path: b"fake-bytes")
    monkeypatch.setattr(
        document_processing_service,
        "extract_with_claude",
        lambda content, mime_type: {"vendor_name": "Tienda X", "total_amount": 9900},
    )
    monkeypatch.setattr(
        document_processing_service,
        "get_or_create_vendor",
        lambda db, company_id, name, tax_id=None: fake_vendor,
    )

    extraction = document_processing_service.run_ai_extraction(db=session, document_id=document.id, company_id=document.company_id)

    assert extraction.extraction_method == "ai"
    assert extraction.extracted_data["vendor_name"] == "Tienda X"
    assert document.status == "ai_extraction_completed"
    assert document.vendor_id == fake_vendor.id


def test_run_ai_extraction_raises_502_when_claude_fails(monkeypatch):
    document = _build_document()
    session = FakeSession(document)

    monkeypatch.setattr(document_processing_service, "read_file_bytes", lambda storage_path: b"fake-bytes")

    def _raise_ai_error(content, mime_type):
        raise AIExtractionError("Claude API rate limit exceeded.")

    monkeypatch.setattr(document_processing_service, "extract_with_claude", _raise_ai_error)

    with pytest.raises(HTTPException) as exc_info:
        document_processing_service.run_ai_extraction(db=session, document_id=document.id, company_id=document.company_id)

    assert exc_info.value.status_code == 502
    assert document.status == "needs_review"
