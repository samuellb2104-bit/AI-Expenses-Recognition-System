"""add duplicate_dismissals

Revision ID: d41f8a2c7e10
Revises: 2cb6cd0c9e90
Create Date: 2026-11-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd41f8a2c7e10'
down_revision: Union[str, Sequence[str], None] = '2cb6cd0c9e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'duplicate_dismissals',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_a_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_b_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('dismissed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('document_a_id < document_b_id', name='ck_duplicate_dismissals_ordered'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_a_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_b_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dismissed_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_a_id', 'document_b_id', name='uq_duplicate_dismissals_pair'),
    )
    op.create_index(op.f('ix_duplicate_dismissals_company_id'), 'duplicate_dismissals', ['company_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_duplicate_dismissals_company_id'), table_name='duplicate_dismissals')
    op.drop_table('duplicate_dismissals')
