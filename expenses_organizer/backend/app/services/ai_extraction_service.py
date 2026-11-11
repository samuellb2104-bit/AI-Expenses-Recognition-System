from __future__ import annotations

import base64
import json
import re
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
        "total_amount_text": {
            "type": ["string", "null"],
            "description": (
                "The final total exactly as printed on the document, character by character "
                "(e.g. '$ 186.900' or '1.234.567,50'), WITHOUT converting or reformatting it."
            ),
        },
        "total_amount": {
            "type": ["number", "null"],
            "description": (
                "Final total amount charged, including tax, as a plain number with no thousands "
                "separators. Colombian documents use '.' for thousands, so '186.900' is 186900."
            ),
        },
        "tax_amount_text": {
            "type": ["string", "null"],
            "description": "The tax amount (e.g. IVA) exactly as printed on the document, without converting it.",
        },
        "tax_amount": {
            "type": ["number", "null"],
            "description": "Tax amount (e.g. IVA), if broken out separately, as a plain number.",
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
        "total_amount_text",
        "total_amount",
        "tax_amount_text",
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
    "Use notes for anything ambiguous, such as a value you are not confident about.\n\n"
    "Number format: these documents are usually Colombian. They use '.' as the thousands "
    "separator and ',' as the decimal separator, so '186.900' means one hundred eighty-six "
    "thousand nine hundred (186900), NOT 186.9, and '1.234.567,50' means 1234567.50. "
    "Peso (COP) amounts normally have no decimals, so a value under 1000 pesos is very unlikely: "
    "re-read the digits before answering.\n"
    "For total_amount_text and tax_amount_text, copy the amount exactly as it is printed on the "
    "document, character by character (for example '$ 186.900'), without converting it. "
    "For total_amount and tax_amount, give the plain number without any thousands separator."
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


def parse_amount(value) -> float | None:
    """Parses a numeric field Claude extracts (total_amount, tax_amount) into a
    float, or None if missing/malformed."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_AMOUNT_NOISE = re.compile(r"[^\d.,]")


def parse_amount_text(text) -> float | None:
    """Parses an amount exactly as printed on a document ("$ 186.900", "1.234.567,50",
    "186,9") into a float with a fixed, deterministic rule -- so how a number is read
    never depends on the model silently guessing a locale.

    Rules: if both '.' and ',' appear, the last one is the decimal separator. If only
    one kind appears, a repeated separator ("1.234.567") is a thousands separator, and a
    single separator followed by exactly 3 digits ("186.900", "186,900") is also a
    thousands separator, since money never has 3 decimals. Anything else ("186,9",
    "186.90") is a decimal. Returns None when no amount can be read."""
    if not isinstance(text, str):
        return None

    # Only trailing separators are noise (e.g. "Total: 186.900."); a leading one is
    # meaningful (".50").
    cleaned = _AMOUNT_NOISE.sub("", text).rstrip(".,")
    if not any(ch.isdigit() for ch in cleaned):
        return None

    has_dot, has_comma = "." in cleaned, "," in cleaned
    if has_dot and has_comma:
        decimal_sep = "." if cleaned.rfind(".") > cleaned.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        normalized = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        parts = cleaned.split(sep)
        if len(parts) > 2:
            if not all(len(part) == 3 for part in parts[1:]):
                return None
            normalized = "".join(parts)
        else:
            integer_part, fraction = parts
            if len(fraction) == 3 and integer_part not in ("", "0"):
                normalized = integer_part + fraction
            else:
                normalized = f"{integer_part or '0'}.{fraction}"
    else:
        normalized = cleaned

    try:
        return float(normalized)
    except ValueError:
        return None


def resolve_amount(data: dict, field: str) -> float | None:
    """The single place that turns an extraction into a numeric amount for `field`
    ('total_amount' or 'tax_amount'). The text exactly as printed (`<field>_text`)
    wins when present and readable; the model's own number is the fallback, which is
    also what extractions saved before the text fields existed rely on."""
    from_text = parse_amount_text(data.get(f"{field}_text"))
    if from_text is not None:
        return from_text
    return parse_amount(data.get(field))


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
