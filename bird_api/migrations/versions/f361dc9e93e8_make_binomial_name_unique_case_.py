"""make binomial name unique case insensitively

Revision ID: f361dc9e93e8
Revises: 99fdb77b15b5
Create Date: 2026-10-19 16:41:22.161757

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f361dc9e93e8"
down_revision: str | Sequence[str] | None = "99fdb77b15b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CASE_DUPLICATES_QUERY = (
    "SELECT group_concat(binomial_name, ', ') FROM birds GROUP BY binomial_name COLLATE NOCASE HAVING count(*) > 1"
)


def upgrade() -> None:
    """Upgrade schema."""
    duplicates = op.get_bind().exec_driver_sql(CASE_DUPLICATES_QUERY).scalars().all()
    if duplicates:
        raise ValueError(f"binomial names differ only in case: {'; '.join(duplicates)}")
    with op.batch_alter_table("birds") as batch_op:
        batch_op.alter_column(
            "binomial_name", existing_type=sa.String(), type_=sa.String(collation="NOCASE"), existing_nullable=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("birds") as batch_op:
        batch_op.alter_column(
            "binomial_name", existing_type=sa.String(collation="NOCASE"), type_=sa.String(), existing_nullable=False
        )
