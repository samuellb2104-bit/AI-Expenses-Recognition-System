from datetime import date
from uuid import UUID

from pydantic import BaseModel


class ExpenseSummaryRow(BaseModel):
    document_id: UUID
    document_date: date | None
    vendor_id: UUID | None
    vendor_name: str | None
    expense_category_id: UUID | None
    expense_category_name: str | None
    currency: str | None
    total_amount: float | None
    tax_amount: float | None


class ExpenseCategoryTotal(BaseModel):
    expense_category_id: UUID | None
    expense_category_name: str
    total_amount: float
    document_count: int


class VendorTotal(BaseModel):
    vendor_id: UUID | None
    vendor_name: str
    total_amount: float
    document_count: int


class ExpenseSummaryResponse(BaseModel):
    rows: list[ExpenseSummaryRow]
    totals_by_category: list[ExpenseCategoryTotal]
    totals_by_vendor: list[VendorTotal]
    grand_total: float
    document_count: int
