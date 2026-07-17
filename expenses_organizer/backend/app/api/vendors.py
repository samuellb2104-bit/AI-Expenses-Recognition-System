from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import get_auth_context
from app.db.session import get_db
from app.schemas.vendor import VendorCreate, VendorRead, VendorUpdate
from app.services.auth_service import AuthContext
from app.services.vendor_service import create_vendor, list_vendors, update_vendor
from sqlalchemy.orm import Session

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=list[VendorRead])
def get_vendors(db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)):
    return list_vendors(db=db, company_id=auth.company_id)


@router.post("", response_model=VendorRead, status_code=status.HTTP_201_CREATED)
def post_vendor(
    payload: VendorCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    return create_vendor(db=db, company_id=auth.company_id, name=payload.name, tax_id=payload.tax_id)


@router.patch("/{vendor_id}", response_model=VendorRead)
def patch_vendor(
    vendor_id: UUID,
    payload: VendorUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    return update_vendor(
        db=db,
        vendor_id=vendor_id,
        company_id=auth.company_id,
        name=payload.name,
        tax_id=payload.tax_id,
    )
