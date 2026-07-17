from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.expense_category import ExpenseCategory

DEFAULT_EXPENSE_CATEGORIES = [
    "Transporte",
    "Suministros",
    "Inventario",
    "Servicios Publicos",
    "Nomina",
    "Arriendo",
    "Otros",
]


def seed_default_expense_categories(db: Session, company_id: uuid.UUID) -> list[ExpenseCategory]:
    existing_names = {
        name
        for (name,) in db.query(ExpenseCategory.name).filter(ExpenseCategory.company_id == company_id).all()
    }

    created = []
    for name in DEFAULT_EXPENSE_CATEGORIES:
        if name in existing_names:
            continue
        category = ExpenseCategory(company_id=company_id, name=name)
        db.add(category)
        created.append(category)

    if created:
        db.flush()
    return created


def list_expense_categories(db: Session, company_id: uuid.UUID) -> list[ExpenseCategory]:
    return (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.company_id == company_id)
        .order_by(ExpenseCategory.name)
        .all()
    )


def create_expense_category(db: Session, company_id: uuid.UUID, name: str) -> ExpenseCategory:
    stripped = name.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category name cannot be empty.")

    existing = (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.company_id == company_id, ExpenseCategory.name == stripped)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists.")

    category = ExpenseCategory(company_id=company_id, name=stripped)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_expense_category(db: Session, category_id: uuid.UUID, company_id: uuid.UUID, name: str) -> ExpenseCategory:
    category = db.get(ExpenseCategory, category_id)
    if category is None or category.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")

    stripped = name.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category name cannot be empty.")

    category.name = stripped
    db.commit()
    db.refresh(category)
    return category


def delete_expense_category(db: Session, category_id: uuid.UUID, company_id: uuid.UUID) -> None:
    category = db.get(ExpenseCategory, category_id)
    if category is None or category.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")

    db.delete(category)
    db.commit()
