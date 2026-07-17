from __future__ import annotations

import base64
import json

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


def extract_with_claude(content: bytes, mime_type: str | None) -> dict:
    if not settings.anthropic_api_key:
        raise AIExtractionError("ANTHROPIC_API_KEY is not configured.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            output_config={"format": {"type": "json_schema", "schema": INVOICE_EXTRACTION_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        _document_content_block(content, mime_type),
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
    except anthropic.RateLimitError as exc:
        raise AIExtractionError("Claude API rate limit exceeded.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIExtractionError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise AIExtractionError(f"Claude API error ({exc.status_code}): {exc.message}") from exc

    if response.stop_reason == "refusal":
        raise AIExtractionError("Claude declined to process this document.")
    if response.stop_reason == "max_tokens":
        raise AIExtractionError("Claude response was truncated before completing extraction.")

    text_block = next((block.text for block in response.content if block.type == "text"), None)
    if text_block is None:
        raise AIExtractionError("Claude did not return a text response.")

    try:
        return json.loads(text_block)
    except json.JSONDecodeError as exc:
        raise AIExtractionError("Claude response was not valid JSON.") from exc
