from datetime import date

import pytest

from app.services import ai_extraction_service
from app.services.ai_extraction_service import (
    AIExtractionError,
    build_batch_request,
    extract_with_claude,
    parse_document_date,
)


class FakeTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self.content = [FakeTextBlock(text)]
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, response=None, exception=None, batches=None):
        self._response = response
        self._exception = exception
        self.batches = batches

    def create(self, **kwargs):
        if self._exception is not None:
            raise self._exception
        return self._response


class FakeBatch:
    def __init__(self, id="batch_123", processing_status="in_progress"):
        self.id = id
        self.processing_status = processing_status


class FakeBatches:
    def __init__(self, batch=None, results=None, exception=None):
        self._batch = batch
        self._results = results if results is not None else []
        self._exception = exception
        self.create_kwargs = None

    def create(self, **kwargs):
        if self._exception is not None:
            raise self._exception
        self.create_kwargs = kwargs
        return self._batch

    def retrieve(self, batch_id):
        if self._exception is not None:
            raise self._exception
        return self._batch

    def results(self, batch_id):
        if self._exception is not None:
            raise self._exception
        return self._results


class FakeSucceededResult:
    def __init__(self, message):
        self.type = "succeeded"
        self.message = message


class FakeErrorObject:
    def __init__(self, message: str):
        self.message = message


class FakeErrorResponse:
    def __init__(self, message: str):
        self.error = FakeErrorObject(message)


class FakeErroredResult:
    def __init__(self, message: str = "overloaded_error"):
        self.type = "errored"
        self.error = FakeErrorResponse(message)


class FakeCanceledResult:
    type = "canceled"


class FakeExpiredResult:
    type = "expired"


class FakeBatchResultItem:
    def __init__(self, custom_id: str, result):
        self.custom_id = custom_id
        self.result = result


class FakeAnthropicClient:
    def __init__(self, response=None, exception=None, batches=None, **kwargs):
        self.messages = FakeMessages(response=response, exception=exception, batches=batches)


def test_extract_with_claude_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", None)

    with pytest.raises(AIExtractionError, match="ANTHROPIC_API_KEY"):
        extract_with_claude(b"fake-bytes", "image/jpeg")


def test_extract_with_claude_parses_structured_json(monkeypatch):
    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", "sk-test")
    payload = '{"vendor_name": "Panaderia El Trigo", "document_date": "2026-07-09", ' \
        '"total_amount": 128500, "tax_amount": 0, "currency": "COP", "line_items": [], "notes": null}'
    fake_response = FakeResponse(payload)
    monkeypatch.setattr(
        ai_extraction_service.anthropic,
        "Anthropic",
        lambda **kwargs: FakeAnthropicClient(response=fake_response),
    )

    result = extract_with_claude(b"fake-bytes", "image/jpeg")

    assert result["vendor_name"] == "Panaderia El Trigo"
    assert result["total_amount"] == 128500


def test_extract_with_claude_raises_on_refusal(monkeypatch):
    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", "sk-test")
    fake_response = FakeResponse("", stop_reason="refusal")
    monkeypatch.setattr(
        ai_extraction_service.anthropic,
        "Anthropic",
        lambda **kwargs: FakeAnthropicClient(response=fake_response),
    )

    with pytest.raises(AIExtractionError, match="declined"):
        extract_with_claude(b"fake-bytes", "image/jpeg")


def test_extract_with_claude_wraps_rate_limit_error(monkeypatch):
    import anthropic as anthropic_module
    import httpx

    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", "sk-test")

    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    rate_limit_error = anthropic_module.RateLimitError("rate limited", response=response, body=None)
    monkeypatch.setattr(
        ai_extraction_service.anthropic,
        "Anthropic",
        lambda **kwargs: FakeAnthropicClient(exception=rate_limit_error),
    )

    with pytest.raises(AIExtractionError, match="rate limit"):
        extract_with_claude(b"fake-bytes", "image/jpeg")


def test_build_batch_request_shape():
    request = build_batch_request("doc-123", b"fake-bytes", "application/pdf")

    assert request["custom_id"] == "doc-123"
    assert request["params"]["model"] == ai_extraction_service.settings.anthropic_model
    assert "output_config" in request["params"]
    assert request["params"]["messages"][0]["content"][0]["type"] == "document"


def test_submit_batch_returns_created_batch(monkeypatch):
    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", "sk-test")
    fake_batch = FakeBatch(id="batch_abc")
    fake_batches = FakeBatches(batch=fake_batch)
    monkeypatch.setattr(
        ai_extraction_service.anthropic,
        "Anthropic",
        lambda **kwargs: FakeAnthropicClient(batches=fake_batches),
    )

    requests = [build_batch_request("doc-1", b"fake-bytes", "image/jpeg")]
    result = ai_extraction_service.submit_batch(requests)

    assert result.id == "batch_abc"
    assert fake_batches.create_kwargs == {"requests": requests}


def test_submit_batch_wraps_rate_limit_error(monkeypatch):
    import anthropic as anthropic_module
    import httpx

    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", "sk-test")
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages/batches"))
    rate_limit_error = anthropic_module.RateLimitError("rate limited", response=response, body=None)
    monkeypatch.setattr(
        ai_extraction_service.anthropic,
        "Anthropic",
        lambda **kwargs: FakeAnthropicClient(batches=FakeBatches(exception=rate_limit_error)),
    )

    with pytest.raises(AIExtractionError, match="rate limit"):
        ai_extraction_service.submit_batch([build_batch_request("doc-1", b"fake-bytes", "image/jpeg")])


def test_retrieve_batch_returns_current_status(monkeypatch):
    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", "sk-test")
    fake_batch = FakeBatch(id="batch_abc", processing_status="ended")
    monkeypatch.setattr(
        ai_extraction_service.anthropic,
        "Anthropic",
        lambda **kwargs: FakeAnthropicClient(batches=FakeBatches(batch=fake_batch)),
    )

    result = ai_extraction_service.retrieve_batch("batch_abc")

    assert result.processing_status == "ended"


def test_iter_batch_results_maps_all_result_types(monkeypatch):
    monkeypatch.setattr(ai_extraction_service.settings, "anthropic_api_key", "sk-test")
    succeeded_payload = (
        '{"vendor_name": "Tienda X", "document_date": null, "total_amount": 9900, '
        '"tax_amount": null, "currency": "COP", "line_items": [], "notes": null}'
    )
    items = [
        FakeBatchResultItem("doc-ok", FakeSucceededResult(FakeResponse(succeeded_payload))),
        FakeBatchResultItem("doc-refused", FakeSucceededResult(FakeResponse("", stop_reason="refusal"))),
        FakeBatchResultItem("doc-err", FakeErroredResult("overloaded_error")),
        FakeBatchResultItem("doc-canceled", FakeCanceledResult()),
        FakeBatchResultItem("doc-expired", FakeExpiredResult()),
    ]
    monkeypatch.setattr(
        ai_extraction_service.anthropic,
        "Anthropic",
        lambda **kwargs: FakeAnthropicClient(batches=FakeBatches(results=items)),
    )

    results = list(ai_extraction_service.iter_batch_results("batch_abc"))

    assert results[0] == ("doc-ok", {
        "vendor_name": "Tienda X",
        "document_date": None,
        "total_amount": 9900,
        "tax_amount": None,
        "currency": "COP",
        "line_items": [],
        "notes": None,
    }, None)

    assert results[1][0] == "doc-refused"
    assert results[1][1] is None
    assert "declined" in results[1][2]

    assert results[2] == ("doc-err", None, "Claude batch item errored: overloaded_error")
    assert results[3] == ("doc-canceled", None, "Claude batch item was canceled before processing.")
    assert results[4] == ("doc-expired", None, "Claude batch item expired before processing.")


def test_parse_document_date_valid():
    assert parse_document_date("2026-07-09") == date(2026, 7, 9)


def test_parse_document_date_none_when_missing():
    assert parse_document_date(None) is None


def test_parse_document_date_none_when_malformed():
    assert parse_document_date("not a date") is None
    assert parse_document_date("09/07/2026") is None


def test_parse_document_date_none_when_not_a_string():
    assert parse_document_date(20260709) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("186.900", 186900),  # the reported bug: '.' is thousands in Colombia
        ("$ 186.900", 186900),
        ("COP 186.900", 186900),
        ("186,900", 186900),
        ("1.234.567", 1234567),
        ("1.234.567,50", 1234567.50),
        ("1,234,567.50", 1234567.50),
        ("186.900,00", 186900),
        ("186,9", 186.9),
        ("186.90", 186.9),
        ("12.5", 12.5),
        ("0,500", 0.5),
        (".50", 0.5),
        ("186900", 186900),
        ("  $1.500  ", 1500),
    ],
)
def test_parse_amount_text_reads_colombian_and_us_formats(text, expected):
    assert ai_extraction_service.parse_amount_text(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [None, "", "   ", "n/a", "$", 186900, "1.23.456"])
def test_parse_amount_text_returns_none_when_unreadable(text):
    assert ai_extraction_service.parse_amount_text(text) is None


def test_resolve_amount_prefers_printed_text_over_models_number():
    # Claude returned the misread 186.9 as a number, but the printed text is right.
    data = {"total_amount": 186.9, "total_amount_text": "$ 186.900"}
    assert ai_extraction_service.resolve_amount(data, "total_amount") == 186900


def test_resolve_amount_falls_back_to_number_when_text_missing_or_unreadable():
    assert ai_extraction_service.resolve_amount({"total_amount": 9900}, "total_amount") == 9900
    assert ai_extraction_service.resolve_amount(
        {"total_amount": 9900, "total_amount_text": "ilegible"}, "total_amount"
    ) == 9900
    assert ai_extraction_service.resolve_amount({"tax_amount": None}, "tax_amount") is None


def test_extraction_schema_requires_printed_text_fields_and_prompt_explains_format():
    schema = ai_extraction_service.INVOICE_EXTRACTION_SCHEMA
    assert {"total_amount_text", "tax_amount_text"} <= set(schema["required"])
    assert set(schema["required"]) == set(schema["properties"])
    assert "186.900" in ai_extraction_service.EXTRACTION_PROMPT
