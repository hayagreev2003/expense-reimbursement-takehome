"""manual figures on an extracted line

Revision ID: c41a7f0e91b2
Revises: 9925bc9566ca
Create Date: 2026-09-15 10:04:11.000000

`extracted_line_item` is what a hand-corrected document stores its figures in, and a lodging
line is measured against a *per-night* limit (§3.1). Without a nights column a typed-in folio
would be checked against one night's tariff and most of it disallowed - so the column is part of
the correction flow, not decoration.

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c41a7f0e91b2"
down_revision: str | Sequence[str] | None = "9925bc9566ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("extracted_line_item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nights", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("extracted_line_item", schema=None) as batch_op:
        batch_op.drop_column("nights")
