from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.vendor import Vendor
from app.schemas.vendor import VendorRead


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


def _count_documents_for_vendor(db: Session, vendor_id: uuid.UUID) -> int:
    return db.query(func.count(Document.id)).filter(Document.vendor_id == vendor_id).scalar() or 0


def _to_vendor_read(vendor: Vendor, document_count: int) -> VendorRead:
    return VendorRead(
        id=vendor.id,
        company_id=vendor.company_id,
        name=vendor.name,
        tax_id=vendor.tax_id,
        document_count=document_count,
    )


def list_vendors(db: Session, company_id: uuid.UUID) -> list[VendorRead]:
    """Every vendor for this company plus how many documents reference it --
    powers the Proveedores tab (sorted by document_count so the vendors with the
    most files to review show up first) and stays a drop-in replacement for the
    classification dropdowns, which just ignore the extra field."""
    rows = (
        db.query(Vendor, func.count(Document.id))
        .outerjoin(Document, Document.vendor_id == Vendor.id)
        .filter(Vendor.company_id == company_id)
        .group_by(Vendor.id)
        .order_by(func.count(Document.id).desc(), Vendor.name)
        .all()
    )
    return [_to_vendor_read(vendor, count) for vendor, count in rows]


def create_vendor(db: Session, company_id: uuid.UUID, name: str, tax_id: str | None = None) -> VendorRead:
    vendor = get_or_create_vendor(db, company_id=company_id, name=name, tax_id=tax_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vendor name cannot be empty.")
    db.commit()
    db.refresh(vendor)
    return _to_vendor_read(vendor, _count_documents_for_vendor(db, vendor.id))


def update_vendor(
    db: Session,
    vendor_id: uuid.UUID,
    company_id: uuid.UUID,
    name: str | None = None,
    tax_id: str | None = None,
) -> VendorRead:
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
    return _to_vendor_read(vendor, _count_documents_for_vendor(db, vendor.id))
