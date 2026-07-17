from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context
from app.db.session import get_db
from app.schemas.report import ExpenseSummaryResponse
from app.services.auth_service import AuthContext
from app.services.report_service import get_expense_summary

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/expense-summary", response_model=ExpenseSummaryResponse)
def expense_summary(
    vendor_id: UUID | None = Query(None),
    expense_category_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Returns per-document rows (date, vendor, category, amounts) plus totals grouped
    by category and by vendor. `rows` is shaped for `pd.DataFrame(response["rows"])` --
    load it into pandas and plot with matplotlib however you need; `totals_by_category`
    and `totals_by_vendor` are pre-aggregated for quick charts without extra grouping."""
    return get_expense_summary(
        db=db,
        company_id=auth.company_id,
        vendor_id=vendor_id,
        expense_category_id=expense_category_id,
    )
