"""add unique binomial_name to birds

Revision ID: 3453d99012b6
Revises: 3744c2fc21ed
Create Date: 2026-10-19 15:51:14.899281

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3453d99012b6"
down_revision: str | Sequence[str] | None = "3744c2fc21ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("birds") as batch_op:
        batch_op.create_unique_constraint("uq_birds_binomial_name", ["binomial_name"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("birds") as batch_op:
        batch_op.drop_constraint("uq_birds_binomial_name", type_="unique")
