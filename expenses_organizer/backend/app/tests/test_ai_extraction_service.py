import pytest

from app.services import ai_extraction_service
from app.services.ai_extraction_service import AIExtractionError, extract_with_claude


class FakeTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self.content = [FakeTextBlock(text)]
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception

    def create(self, **kwargs):
        if self._exception is not None:
            raise self._exception
        return self._response


class FakeAnthropicClient:
    def __init__(self, response=None, exception=None, **kwargs):
        self.messages = FakeMessages(response=response, exception=exception)


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
