"""add image metadata to birds

Revision ID: c1acf131e21c
Revises: 891a7254d1d7
Create Date: 2026-10-19 16:09:03.692821

"""

import hashlib
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1acf131e21c"
down_revision: str | Sequence[str] | None = "891a7254d1d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}
COLUMNS: dict[str, sa.types.TypeEngine[Any]] = {
    "image_media_type": sa.String(),
    "image_sha256": sa.String(),
    "image_size": sa.Integer(),
    "image_alt_text": sa.String(),
    "image_credit": sa.String(),
    "image_license": sa.String(),
    "image_source_url": sa.String(),
}
UNKNOWN_ATTRIBUTION = {
    "image_alt_text": "Unknown",
    "image_credit": "Unknown",
    "image_license": "Unknown",
    "image_source_url": "Unknown",
}


def detect_image_media_type(data: bytes) -> str | None:
    for signature, media_type in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return media_type
    return None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("birds") as batch_op:
        for name, type_ in COLUMNS.items():
            batch_op.add_column(sa.Column(name, type_, nullable=True))

    birds = sa.table("birds", sa.column("id"), sa.column("image", sa.LargeBinary()), *(sa.column(name) for name in COLUMNS))
    connection = op.get_bind()
    for bird_id, image in connection.execute(sa.select(birds.c.id, birds.c.image)).all():
        media_type = detect_image_media_type(image)
        if media_type is None:
            raise ValueError(f"bird {bird_id} has an image that is not a JPEG or PNG")
        connection.execute(
            birds.update()
            .where(birds.c.id == bird_id)
            .values(
                image_media_type=media_type,
                image_sha256=hashlib.sha256(image).hexdigest(),
                image_size=len(image),
                **UNKNOWN_ATTRIBUTION,
            )
        )

    with op.batch_alter_table("birds") as batch_op:
        for name, type_ in COLUMNS.items():
            batch_op.alter_column(name, existing_type=type_, nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("birds") as batch_op:
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
