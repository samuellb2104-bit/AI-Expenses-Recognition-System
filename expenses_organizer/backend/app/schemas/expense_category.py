from uuid import UUID

from pydantic import BaseModel


class ExpenseCategoryCreate(BaseModel):
    name: str


class ExpenseCategoryUpdate(BaseModel):
    name: str


class ExpenseCategoryRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str

    model_config = {"from_attributes": True}
