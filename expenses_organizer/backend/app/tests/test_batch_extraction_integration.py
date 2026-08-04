"""Integration tests for the Anthropic Message Batch extraction path, against the real
Supabase Postgres (Anthropic calls themselves are monkeypatched -- these tests exercise
the real SQL claim/query logic in document_service.py and document_processing_service.py,
not network I/O). Cleans up its own rows so it can run repeatedly."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.company import Company
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.processing_log import ProcessingLog
from app.services import document_processing_service, document_service


def _make_document_id(db, company_id, status="uploaded", batch_id=None) -> UUID:
    """Creates a Document row and returns its id as a plain UUID -- callers should use
    that id for everything afterward rather than holding onto the ORM object, since a
    later commit() on the same session (expire_on_commit=True, the default) expires
    already-created objects' attributes, and accessing them after the session closes
    raises DetachedInstanceError."""
    document = Document(
        company_id=company_id,
        original_filename="factura.pdf",
        source_format="pdf",
        status=status,
        mime_type="application/pdf",
        storage_path="uploads/factura.pdf",
        batch_id=batch_id,
    )
    db.add(document)
    db.commit()
    document_id = document.id
    return document_id


def _cleanup(document_ids):
    with SessionLocal() as db:
        db.query(ProcessingLog).filter(ProcessingLog.document_id.in_(document_ids)).delete(
            synchronize_session=False
        )
        db.query(DocumentExtraction).filter(DocumentExtraction.document_id.in_(document_ids)).delete(
            synchronize_session=False
        )
        db.query(Document).filter(Document.id.in_(document_ids)).delete(synchronize_session=False)
        db.commit()


def test_try_claim_batch_result_for_ingestion_is_atomic_and_company_scoped():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        other_company_id = uuid4()
        document_id = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_abc")

    try:
        with SessionLocal() as db:
            # Wrong company -> no claim.
            assert (
                document_service.try_claim_batch_result_for_ingestion(
                    db, document_id, "batch_abc", other_company_id
                )
                is False
            )
            # Wrong batch_id -> no claim.
            assert (
                document_service.try_claim_batch_result_for_ingestion(
                    db, document_id, "batch_wrong", company_id
                )
                is False
            )
            # Correct scope -> claims once.
            assert (
                document_service.try_claim_batch_result_for_ingestion(
                    db, document_id, "batch_abc", company_id
                )
                is True
            )
            # Already claimed (status is no longer 'batch_queued') -> second claim fails.
            assert (
                document_service.try_claim_batch_result_for_ingestion(
                    db, document_id, "batch_abc", company_id
                )
                is False
            )
    finally:
        _cleanup([document_id])


def test_list_outstanding_batch_ids_scoped_to_company():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        doc_a = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_1")
        doc_b = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_1")
        doc_c = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_2")
        doc_done = _make_document_id(db, company_id, status="ai_extraction_completed", batch_id="batch_3")

    try:
        with SessionLocal() as db:
            batch_ids = set(document_service.list_outstanding_batch_ids(db, company_id))
        assert batch_ids == {"batch_1", "batch_2"}
    finally:
        _cleanup([doc_a, doc_b, doc_c, doc_done])


def test_list_resumable_document_ids_never_returns_batch_queued_documents():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        stale_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)

        stale_uploaded_id = _make_document_id(db, company_id, status="uploaded")
        db.query(Document).filter(Document.id == stale_uploaded_id).update({"created_at": stale_cutoff})

        stale_batch_queued_id = _make_document_id(
            db, company_id, status="batch_queued", batch_id="batch_x"
        )
        db.query(Document).filter(Document.id == stale_batch_queued_id).update({"created_at": stale_cutoff})
        db.commit()

    try:
        with SessionLocal() as db:
            resumable_ids = set(document_service.list_resumable_document_ids(db, company_id))
        assert stale_uploaded_id in resumable_ids
        assert stale_batch_queued_id not in resumable_ids
    finally:
        _cleanup([stale_uploaded_id, stale_batch_queued_id])


def test_submit_batch_ai_extraction_happy_path_and_skips(monkeypatch):
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        eligible_id = _make_document_id(db, company_id, status="uploaded")
        already_processed_id = _make_document_id(db, company_id, status="ai_extraction_completed")

        # A genuine second company (not a random uuid4()) -- documents.company_id has a
        # foreign key to companies.id, so a non-existent company_id would fail on insert.
        other_company = Company(name="Other Test Company", contact_email="other@expenses-organizer.local")
        db.add(other_company)
        db.commit()
        other_company_id = other_company.id
        foreign_company_doc_id = _make_document_id(db, other_company_id, status="uploaded")

    monkeypatch.setattr(document_processing_service, "read_file_bytes", lambda storage_path: b"fake-bytes")

    class FakeBatch:
        id = "batch_new"

    monkeypatch.setattr(document_processing_service, "submit_batch", lambda requests: FakeBatch())

    try:
        with SessionLocal() as db:
            batch_id, submitted_ids, skipped_ids = document_processing_service.submit_batch_ai_extraction(
                db,
                document_ids=[eligible_id, already_processed_id, foreign_company_doc_id],
                company_id=company_id,
            )

        assert batch_id == "batch_new"
        assert submitted_ids == [eligible_id]
        assert set(skipped_ids) == {already_processed_id, foreign_company_doc_id}

        with SessionLocal() as db:
            refreshed = db.get(Document, eligible_id)
            assert refreshed.status == "batch_queued"
            assert refreshed.batch_id == "batch_new"
    finally:
        _cleanup([eligible_id, already_processed_id, foreign_company_doc_id])
        with SessionLocal() as db:
            db.query(Company).filter(Company.id == other_company_id).delete()
            db.commit()


def test_submit_batch_ai_extraction_returns_empty_when_nothing_eligible():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        done_id = _make_document_id(db, company.id, status="ai_extraction_completed")
        company_id = company.id

    try:
        with SessionLocal() as db:
            batch_id, submitted_ids, skipped_ids = document_processing_service.submit_batch_ai_extraction(
                db, document_ids=[done_id], company_id=company_id
            )
        assert batch_id is None
        assert submitted_ids == []
        assert skipped_ids == [done_id]
    finally:
        _cleanup([done_id])


def test_poll_and_ingest_batch_noop_when_not_ended(monkeypatch):
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        document_id = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_pending")

    class FakeBatch:
        processing_status = "in_progress"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(document_processing_service, "retrieve_batch", lambda batch_id: FakeBatch())

    try:
        with SessionLocal() as db:
            document_processing_service.poll_and_ingest_batch(db, "batch_pending", company_id)

        with SessionLocal() as db:
            refreshed = db.get(Document, document_id)
            assert refreshed.status == "batch_queued"
    finally:
        _cleanup([document_id])


def test_poll_and_ingest_batch_marks_expired_documents_needs_review(monkeypatch):
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        document_id = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_expired")

    class FakeBatch:
        processing_status = "in_progress"
        expires_at = datetime.now(timezone.utc) - timedelta(hours=1)  # already past expiry

    monkeypatch.setattr(document_processing_service, "retrieve_batch", lambda batch_id: FakeBatch())

    try:
        with SessionLocal() as db:
            document_processing_service.poll_and_ingest_batch(db, "batch_expired", company_id)

        with SessionLocal() as db:
            refreshed = db.get(Document, document_id)
            assert refreshed.status == "needs_review"
            log = (
                db.query(ProcessingLog)
                .filter(ProcessingLog.document_id == document_id, ProcessingLog.step_name == "ai_extraction")
                .one()
            )
            assert log.status == "failed"
            assert "expired" in log.message
    finally:
        _cleanup([document_id])


def test_poll_and_ingest_batch_ingests_succeeded_and_errored_results(monkeypatch):
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)
        company_id = company.id
        ok_document_id = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_done")
        failed_document_id = _make_document_id(db, company_id, status="batch_queued", batch_id="batch_done")

    class FakeBatch:
        processing_status = "ended"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(document_processing_service, "retrieve_batch", lambda batch_id: FakeBatch())
    monkeypatch.setattr(
        document_processing_service,
        "get_or_create_vendor",
        lambda db, company_id, name, tax_id=None: None,
    )

    def fake_results(batch_id):
        yield str(ok_document_id), {"vendor_name": "Tienda X", "total_amount": 5000}, None
        yield str(failed_document_id), None, "Claude batch item errored: overloaded_error"

    monkeypatch.setattr(document_processing_service, "iter_batch_results", fake_results)

    try:
        with SessionLocal() as db:
            document_processing_service.poll_and_ingest_batch(db, "batch_done", company_id)

        with SessionLocal() as db:
            refreshed_ok = db.get(Document, ok_document_id)
            assert refreshed_ok.status == "ai_extraction_completed"
            extraction = (
                db.query(DocumentExtraction)
                .filter(DocumentExtraction.document_id == ok_document_id, DocumentExtraction.is_final.is_(True))
                .one()
            )
            assert extraction.extracted_data["vendor_name"] == "Tienda X"

            refreshed_failed = db.get(Document, failed_document_id)
            assert refreshed_failed.status == "needs_review"
            log = (
                db.query(ProcessingLog)
                .filter(
                    ProcessingLog.document_id == failed_document_id,
                    ProcessingLog.step_name == "ai_extraction",
                )
                .one()
            )
            assert log.status == "failed"

        # Re-polling the same (already-ingested) batch is a safe no-op: the atomic
        # claim finds nothing left in 'batch_queued' for these documents.
        with SessionLocal() as db:
            document_processing_service.poll_and_ingest_batch(db, "batch_done", company_id)
    finally:
        _cleanup([ok_document_id, failed_document_id])
