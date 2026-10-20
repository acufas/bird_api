"""add conservation status check to birds

Revision ID: 891a7254d1d7
Revises: 3453d99012b6
Create Date: 2026-10-19 15:59:55.035296

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "891a7254d1d7"
down_revision: str | Sequence[str] | None = "3453d99012b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSERVATION_STATUSES = [
    "Extinct",
    "Extinct in the Wild",
    "Critically Endangered",
    "Endangered",
    "Vulnerable",
    "Near Threatened",
    "Least Concern",
    "Data Deficient",
    "Not Evaluated",
]


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("birds") as batch_op:
        batch_op.create_check_constraint(
            "ck_birds_conservation_status",
            sa.column("conservation_status").in_(CONSERVATION_STATUSES),
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("birds") as batch_op:
        batch_op.drop_constraint("ck_birds_conservation_status", type_="check")
