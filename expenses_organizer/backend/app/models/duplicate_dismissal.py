from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DuplicateDismissal(Base):
    """A pair of documents the user confirmed are NOT the same expense, so the
    duplicate review stops flagging them. Stored with document_a_id < document_b_id
    so each pair has exactly one canonical row."""

    __tablename__ = "duplicate_dismissals"
    __table_args__ = (
        UniqueConstraint("document_a_id", "document_b_id", name="uq_duplicate_dismissals_pair"),
        CheckConstraint("document_a_id < document_b_id", name="ck_duplicate_dismissals_ordered"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    document_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    document_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    dismissed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), nullable=False)
