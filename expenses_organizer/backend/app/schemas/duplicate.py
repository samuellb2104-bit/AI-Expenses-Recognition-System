from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class DuplicateDocument(BaseModel):
    id: UUID
    original_filename: str
    document_type: str | None
    status: str
    vendor_id: UUID | None
    vendor_name: str | None
    total_amount: float
    currency: str | None
    document_date: date | None
    created_at: datetime


class DuplicateGroup(BaseModel):
    confidence: str  # "alta" | "media" | "baja"
    reasons: list[str]
    total_amount: float
    currency: str | None
    # Amount that is double-counted in reports if every document in the group is
    # the same expense: (documents - 1) * amount.
    possible_overcount: float
    documents: list[DuplicateDocument]


class DuplicateReviewResponse(BaseModel):
    groups: list[DuplicateGroup]
    scanned_document_count: int
    date_window_days: int


class DuplicateDismissRequest(BaseModel):
    document_ids: list[UUID]


class DuplicateDismissResponse(BaseModel):
    dismissed_pairs: int
