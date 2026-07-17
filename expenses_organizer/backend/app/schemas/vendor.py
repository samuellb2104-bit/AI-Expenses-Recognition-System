from uuid import UUID

from pydantic import BaseModel


class VendorCreate(BaseModel):
    name: str
    tax_id: str | None = None


class VendorUpdate(BaseModel):
    name: str | None = None
    tax_id: str | None = None


class VendorRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    tax_id: str | None

    model_config = {"from_attributes": True}
