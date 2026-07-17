from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context
from app.db.session import get_db
from app.schemas.expense_category import ExpenseCategoryCreate, ExpenseCategoryRead, ExpenseCategoryUpdate
from app.services.auth_service import AuthContext
from app.services.expense_category_service import (
    create_expense_category,
    delete_expense_category,
    list_expense_categories,
    update_expense_category,
)

router = APIRouter(prefix="/expense-categories", tags=["expense-categories"])


@router.get("", response_model=list[ExpenseCategoryRead])
def get_expense_categories(db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)):
    return list_expense_categories(db=db, company_id=auth.company_id)


@router.post("", response_model=ExpenseCategoryRead, status_code=status.HTTP_201_CREATED)
def post_expense_category(
    payload: ExpenseCategoryCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    return create_expense_category(db=db, company_id=auth.company_id, name=payload.name)


@router.patch("/{category_id}", response_model=ExpenseCategoryRead)
def patch_expense_category(
    category_id: UUID,
    payload: ExpenseCategoryUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    return update_expense_category(db=db, category_id=category_id, company_id=auth.company_id, name=payload.name)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_expense_category(
    category_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    delete_expense_category(db=db, category_id=category_id, company_id=auth.company_id)
