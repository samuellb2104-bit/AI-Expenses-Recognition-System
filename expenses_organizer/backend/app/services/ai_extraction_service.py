from __future__ import annotations

import base64
import json
from datetime import date, datetime

import anthropic

from app.core.config import settings

PDF_MIME_TYPE = "application/pdf"

INVOICE_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_name": {
            "type": ["string", "null"],
            "description": "Name of the company or person who issued the document.",
        },
        "document_date": {
            "type": ["string", "null"],
            "description": "Date the invoice/receipt was issued, formatted YYYY-MM-DD if determinable.",
        },
        "total_amount": {
            "type": ["number", "null"],
            "description": "Final total amount charged, including tax.",
        },
        "tax_amount": {
            "type": ["number", "null"],
            "description": "Tax amount (e.g. IVA), if broken out separately.",
        },
        "currency": {
            "type": ["string", "null"],
            "description": "ISO 4217 currency code, e.g. COP, USD.",
        },
        "line_items": {
            "type": "array",
            "description": "Individual products/services billed on the document.",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "total": {"type": ["number", "null"]},
                },
                "required": ["description", "quantity", "unit_price", "total"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": ["string", "null"],
            "description": "Anything relevant that doesn't fit the fields above, including doubts about illegible fields.",
        },
    },
    "required": [
        "vendor_name",
        "document_date",
        "total_amount",
        "tax_amount",
        "currency",
        "line_items",
        "notes",
    ],
    "additionalProperties": False,
}

EXTRACTION_PROMPT = (
    "Extract the invoice/receipt fields from this document. "
    "If a field is not present or illegible, use null. "
    "Use notes for anything ambiguous, such as a value you are not confident about."
)


class AIExtractionError(RuntimeError):
    pass


def _document_content_block(content: bytes, mime_type: str | None) -> dict:
    encoded = base64.standard_b64encode(content).decode("ascii")
    if mime_type == PDF_MIME_TYPE:
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": PDF_MIME_TYPE, "data": encoded},
        }
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime_type or "image/jpeg", "data": encoded},
    }


def parse_document_date(value) -> date | None:
    """Parses the `document_date` field Claude extracts ("YYYY-MM-DD if
    determinable") into a date, or None if missing/malformed -- the single place
    that knows the extraction schema's date format, reused by both the
    persistence path and reports."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _client() -> anthropic.Anthropic:
    if not settings.anthropic_api_key:
        raise AIExtractionError("ANTHROPIC_API_KEY is not configured.")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _message_params(content: bytes, mime_type: str | None) -> dict:
    return {
        "model": settings.anthropic_model,
        "max_tokens": 2048,
        "output_config": {"format": {"type": "json_schema", "schema": INVOICE_EXTRACTION_SCHEMA}},
        "messages": [
            {
                "role": "user",
                "content": [
                    _document_content_block(content, mime_type),
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    }


def _extract_ai_data(message) -> dict:
    """Parses a Claude Message response (from either a live messages.create() call
    or a succeeded Message Batch result) into the extracted fields dict."""
    if message.stop_reason == "refusal":
        raise AIExtractionError("Claude declined to process this document.")
    if message.stop_reason == "max_tokens":
        raise AIExtractionError("Claude response was truncated before completing extraction.")

    text_block = next((block.text for block in message.content if block.type == "text"), None)
    if text_block is None:
        raise AIExtractionError("Claude did not return a text response.")

    try:
        return json.loads(text_block)
    except json.JSONDecodeError as exc:
        raise AIExtractionError("Claude response was not valid JSON.") from exc


def extract_with_claude(content: bytes, mime_type: str | None) -> dict:
    client = _client()

    try:
        response = client.messages.create(**_message_params(content, mime_type))
    except anthropic.RateLimitError as exc:
        raise AIExtractionError("Claude API rate limit exceeded.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIExtractionError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise AIExtractionError(f"Claude API error ({exc.status_code}): {exc.message}") from exc

    return _extract_ai_data(response)


def build_batch_request(custom_id: str, content: bytes, mime_type: str | None) -> dict:
    """Builds one entry of the `requests` list passed to submit_batch. `custom_id`
    is used to match this request back to its document once results come in --
    callers should pass str(document.id)."""
    return {"custom_id": custom_id, "params": _message_params(content, mime_type)}


def submit_batch(requests: list[dict]):
    """Submits a Message Batch covering all given requests in a single Anthropic API
    call. Returns the created MessageBatch (id, processing_status, expires_at, ...)."""
    client = _client()
    try:
        return client.messages.batches.create(requests=requests)
    except anthropic.RateLimitError as exc:
        raise AIExtractionError("Claude API rate limit exceeded.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIExtractionError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise AIExtractionError(f"Claude API error ({exc.status_code}): {exc.message}") from exc


def retrieve_batch(batch_id: str):
    """Fetches current status of a previously-submitted batch (processing_status,
    expires_at, request_counts, ...) -- used to poll for completion."""
    client = _client()
    try:
        return client.messages.batches.retrieve(batch_id)
    except anthropic.RateLimitError as exc:
        raise AIExtractionError("Claude API rate limit exceeded.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIExtractionError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise AIExtractionError(f"Claude API error ({exc.status_code}): {exc.message}") from exc


def iter_batch_results(batch_id: str):
    """Yields (custom_id, ai_data, error) for every item in a completed batch.
    Exactly one of ai_data/error is set. Only valid once the batch's
    processing_status is 'ended'. Results are not guaranteed to arrive in the
    order requests were submitted."""
    client = _client()
    try:
        results = client.messages.batches.results(batch_id)
    except anthropic.RateLimitError as exc:
        raise AIExtractionError("Claude API rate limit exceeded.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIExtractionError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise AIExtractionError(f"Claude API error ({exc.status_code}): {exc.message}") from exc

    for item in results:
        result = item.result
        if result.type == "succeeded":
            try:
                yield item.custom_id, _extract_ai_data(result.message), None
            except AIExtractionError as exc:
                yield item.custom_id, None, str(exc)
        elif result.type == "errored":
            yield item.custom_id, None, f"Claude batch item errored: {result.error.error.message}"
        elif result.type == "canceled":
            yield item.custom_id, None, "Claude batch item was canceled before processing."
        else:
            yield item.custom_id, None, "Claude batch item expired before processing."
