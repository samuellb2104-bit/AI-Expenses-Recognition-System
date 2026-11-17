"""enable RLS on public tables

Supabase exposes the public schema through its Data API, which accepts the
public anon key shipped in the frontend. Tables without RLS can be read and
written by anyone holding that key. The backend connects as the postgres role
(bypasses RLS) and the frontend only uses Supabase for auth, so enabling RLS
with no policies denies Data API access without affecting the app.

Revision ID: e3a9c1f04b72
Revises: d41f8a2c7e10
Create Date: 2026-11-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3a9c1f04b72'
down_revision: Union[str, Sequence[str], None] = 'd41f8a2c7e10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "alembic_version",
    "expense_categories",
    "vendors",
    "duplicate_dismissals",
)


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
