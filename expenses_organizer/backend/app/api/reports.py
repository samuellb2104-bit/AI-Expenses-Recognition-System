from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context
from app.db.session import get_db
from app.schemas.duplicate import DuplicateDismissRequest, DuplicateDismissResponse, DuplicateReviewResponse
from app.schemas.report import ExpenseSummaryResponse
from app.services.auth_service import AuthContext
from app.services.duplicate_service import (
    DEFAULT_DATE_WINDOW_DAYS,
    dismiss_duplicate_group,
    find_probable_duplicates,
)
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


@router.get("/probable-duplicates", response_model=DuplicateReviewResponse)
def probable_duplicates(
    date_window_days: int = Query(DEFAULT_DATE_WINDOW_DAYS, ge=0, le=30),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Groups documents that look like the same expense (e.g. a factura plus its
    comprobante de pago): same total and currency, same or similar vendor, and
    document dates within `date_window_days` of each other."""
    return find_probable_duplicates(db=db, company_id=auth.company_id, date_window_days=date_window_days)


@router.post("/probable-duplicates/dismiss", response_model=DuplicateDismissResponse)
def dismiss_probable_duplicates(
    payload: DuplicateDismissRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Records that the given documents are NOT duplicates of each other, so they
    stop appearing in the duplicate review."""
    created = dismiss_duplicate_group(
        db=db, company_id=auth.company_id, user_id=auth.user_id, document_ids=payload.document_ids
    )
    return DuplicateDismissResponse(dismissed_pairs=created)
