"""create birds table

Revision ID: 3744c2fc21ed
Revises:
Create Date: 2026-10-19 15:51:14.493651

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3744c2fc21ed"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "birds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("binomial_name", sa.String(), nullable=False),
        sa.Column("common_name", sa.String(), nullable=False),
        sa.Column("conservation_status", sa.String(), nullable=False),
        sa.Column("kingdom", sa.String(), nullable=False),
        sa.Column("phylum", sa.String(), nullable=False),
        sa.Column("class", sa.String(), nullable=False),
        sa.Column("order", sa.String(), nullable=False),
        sa.Column("family", sa.String(), nullable=False),
        sa.Column("genus", sa.String(), nullable=False),
        sa.Column("species", sa.String(), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("birds")
