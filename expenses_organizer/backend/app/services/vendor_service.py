from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.vendor import Vendor


def get_or_create_vendor(db: Session, company_id: uuid.UUID, name: str, tax_id: str | None = None) -> Vendor | None:
    normalized_name = (name or "").strip()
    if not normalized_name:
        return None

    base_query = db.query(Vendor).filter(Vendor.company_id == company_id)

    if tax_id:
        vendor = base_query.filter(Vendor.tax_id == tax_id).first()
        if vendor is not None:
            return vendor

    vendor = base_query.filter(func.lower(Vendor.name) == normalized_name.lower()).first()
    if vendor is not None:
        if tax_id and not vendor.tax_id:
            vendor.tax_id = tax_id
        return vendor

    vendor = Vendor(company_id=company_id, name=normalized_name, tax_id=tax_id)
    db.add(vendor)
    db.flush()
    return vendor


def list_vendors(db: Session, company_id: uuid.UUID) -> list[Vendor]:
    return db.query(Vendor).filter(Vendor.company_id == company_id).order_by(Vendor.name).all()


def create_vendor(db: Session, company_id: uuid.UUID, name: str, tax_id: str | None = None) -> Vendor:
    vendor = get_or_create_vendor(db, company_id=company_id, name=name, tax_id=tax_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vendor name cannot be empty.")
    db.commit()
    db.refresh(vendor)
    return vendor


def update_vendor(
    db: Session,
    vendor_id: uuid.UUID,
    company_id: uuid.UUID,
    name: str | None = None,
    tax_id: str | None = None,
) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None or vendor.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found.")

    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vendor name cannot be empty.")
        vendor.name = stripped
    if tax_id is not None:
        vendor.tax_id = tax_id

    db.commit()
    db.refresh(vendor)
    return vendor
