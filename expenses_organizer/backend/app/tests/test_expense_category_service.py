import pytest
from fastapi import HTTPException

from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.expense_category import ExpenseCategory
from app.services.expense_category_service import (
    DEFAULT_EXPENSE_CATEGORIES,
    create_expense_category,
    delete_expense_category,
    list_expense_categories,
    seed_default_expense_categories,
    update_expense_category,
)


def test_seed_default_expense_categories_is_idempotent():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        categories = list_expense_categories(db, company_id=company.id)
        names = {c.name for c in categories}
        assert set(DEFAULT_EXPENSE_CATEGORIES).issubset(names)

        # Calling seed again should not create duplicates.
        created_again = seed_default_expense_categories(db, company.id)
        db.commit()
        assert created_again == []

        categories_after = list_expense_categories(db, company_id=company.id)
        assert len(categories_after) == len(categories)


def test_create_duplicate_category_raises_conflict():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        with pytest.raises(HTTPException) as exc_info:
            create_expense_category(db, company_id=company.id, name="Transporte")

        assert exc_info.value.status_code == 409


def test_create_update_and_delete_custom_category():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        category = create_expense_category(db, company_id=company.id, name="Categoria De Prueba")
        assert category.name == "Categoria De Prueba"

        updated = update_expense_category(db, category_id=category.id, company_id=company.id, name="Categoria Actualizada")
        assert updated.name == "Categoria Actualizada"

        delete_expense_category(db, category_id=category.id, company_id=company.id)

        remaining = db.query(ExpenseCategory).filter(ExpenseCategory.id == category.id).first()
        assert remaining is None
