"""move images to bird_images

Revision ID: 99fdb77b15b5
Revises: c1acf131e21c
Create Date: 2026-10-19 16:33:21.681015

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "99fdb77b15b5"
down_revision: str | Sequence[str] | None = "c1acf131e21c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS: dict[str, tuple[str, sa.types.TypeEngine[Any]]] = {
    "image": ("data", sa.LargeBinary()),
    "image_media_type": ("media_type", sa.String()),
    "image_sha256": ("sha256", sa.String()),
    "image_size": ("size", sa.Integer()),
    "image_alt_text": ("alt_text", sa.String()),
    "image_credit": ("credit", sa.String()),
    "image_license": ("license", sa.String()),
    "image_source_url": ("source_url", sa.String()),
}
BIRD_COLUMNS = ", ".join(COLUMNS)
IMAGE_COLUMNS = ", ".join(name for name, _ in COLUMNS.values())


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "bird_images",
        sa.Column("bird_id", sa.Uuid(), nullable=False),
        *(sa.Column(name, type_, nullable=False) for name, type_ in COLUMNS.values()),
        sa.ForeignKeyConstraint(["bird_id"], ["birds.id"], name="fk_bird_images_bird_id_birds"),
        sa.PrimaryKeyConstraint("bird_id"),
    )
    op.execute(f"INSERT INTO bird_images (bird_id, {IMAGE_COLUMNS}) SELECT id, {BIRD_COLUMNS} FROM birds")
    with op.batch_alter_table("birds") as batch_op:
        for name in COLUMNS:
            batch_op.drop_column(name)


def downgrade() -> None:
    """Downgrade schema."""
    missing = (
        op.get_bind()
        .exec_driver_sql("SELECT id FROM birds WHERE id NOT IN (SELECT bird_id FROM bird_images) ORDER BY id")
        .scalars()
        .all()
    )
    if missing:
        raise ValueError(f"cannot downgrade: these birds have no bird_images row: {', '.join(missing)}")

    with op.batch_alter_table("birds") as batch_op:
        for name, (_, type_) in COLUMNS.items():
            batch_op.add_column(sa.Column(name, type_, nullable=True))
    op.execute(f"UPDATE birds SET ({BIRD_COLUMNS}) = (SELECT {IMAGE_COLUMNS} FROM bird_images WHERE bird_id = birds.id)")
    with op.batch_alter_table("birds") as batch_op:
        for name, (_, type_) in COLUMNS.items():
            batch_op.alter_column(name, existing_type=type_, nullable=False)
    op.drop_table("bird_images")
