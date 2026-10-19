from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models import (
    Bird,
    BirdCreate,
    BirdImage,
    BirdPublic,
    ConservationStatus,
    build_bird,
    build_bird_public,
    detect_image_media_type,
)
from tests.factories import CARDINAL_ID, CONSERVATION_STATUSES, GIF_IMAGE, IMAGE, PNG_IMAGE, bird_payload, encode, sha256

ROW: dict[str, Any] = {
    "id": "e91c2f2d-923e-4122-b43f-a61b867d89c1",
    "binomial_name": "Cardinalis cardinalis",
    "common_name": "Northern cardinal",
    "conservation_status": "Least Concern",
    "kingdom": "Animalia",
    "phylum": "Chordata",
    "class": "Aves",
    "order": "Passeriformes",
    "family": "Cardinalidae",
    "genus": "Cardinalis",
    "species": "cardinalis",
}
IMAGE_ROW = {
    "bird_id": "e91c2f2d-923e-4122-b43f-a61b867d89c1",
    "data": b"\xff\xd8\xff\xe0",
    "media_type": "image/jpeg",
    "sha256": sha256(b"\xff\xd8\xff\xe0"),
    "size": 4,
    "alt_text": "A northern cardinal on a branch",
    "credit": "Jane Photographer",
    "license": "CC BY-SA 4.0",
    "source_url": "https://example.com/photos/northern-cardinal.jpg",
}
PUBLIC_IMAGE_FIELDS = {
    "image_media_type": "image/jpeg",
    "image_size": 4,
    "image_alt_text": "A northern cardinal on a branch",
    "image_credit": "Jane Photographer",
    "image_license": "CC BY-SA 4.0",
    "image_source_url": "https://example.com/photos/northern-cardinal.jpg",
}


def bird_with_image():
    bird = Bird.model_validate(ROW)
    bird.image = BirdImage.model_validate(IMAGE_ROW)
    return bird


def test_bird_parses_database_row():
    bird = Bird.model_validate(ROW)

    assert bird.id == UUID("e91c2f2d-923e-4122-b43f-a61b867d89c1")
    assert bird.class_ == "Aves"


def test_bird_has_no_image_fields():
    assert [field for field in Bird.model_fields if field.startswith("image")] == []


def test_bird_image_parses_database_row():
    image = BirdImage.model_validate(IMAGE_ROW)

    assert image.bird_id == CARDINAL_ID
    assert image.data == b"\xff\xd8\xff\xe0"
    assert image.size == 4


def test_bird_accepts_class_by_field_name():
    row = {key: value for key, value in ROW.items() if key != "class"}

    bird = Bird(**row, class_="Aves")  # type: ignore[call-arg]

    assert bird.class_ == "Aves"


def test_bird_serializes_class_by_alias():
    data = Bird.model_validate(ROW).model_dump(mode="json", by_alias=True)

    assert data["class"] == "Aves"
    assert "class_" not in data


def test_build_bird_public_serializes_bird_and_image_metadata_without_image():
    data = build_bird_public(bird_with_image()).model_dump(mode="json", by_alias=True)

    assert data["id"] == "e91c2f2d-923e-4122-b43f-a61b867d89c1"
    assert data["class"] == "Aves"
    assert "image" not in data
    assert "image_sha256" not in data
    assert data["image_url"] == "/api/v1/birds/e91c2f2d-923e-4122-b43f-a61b867d89c1/image"
    assert {field: data[field] for field in PUBLIC_IMAGE_FIELDS} == PUBLIC_IMAGE_FIELDS


@pytest.mark.parametrize("field", ROW.keys())
def test_bird_rejects_null_field(field):
    with pytest.raises(ValidationError):
        Bird.model_validate({**ROW, field: None})


@pytest.mark.parametrize("field", ROW.keys())
def test_bird_rejects_missing_field(field):
    row = {key: value for key, value in ROW.items() if key != field}

    with pytest.raises(ValidationError):
        Bird.model_validate(row)


@pytest.mark.parametrize("field", IMAGE_ROW.keys())
def test_bird_image_rejects_null_field(field):
    with pytest.raises(ValidationError):
        BirdImage.model_validate({**IMAGE_ROW, field: None})


@pytest.mark.parametrize("field", IMAGE_ROW.keys())
def test_bird_image_rejects_missing_field(field):
    row = {key: value for key, value in IMAGE_ROW.items() if key != field}

    with pytest.raises(ValidationError):
        BirdImage.model_validate(row)


@pytest.mark.parametrize(("image", "media_type"), [(IMAGE, "image/jpeg"), (PNG_IMAGE, "image/png")])
def test_build_bird_derives_image_metadata_from_image_bytes(image, media_type):
    bird = build_bird(BirdCreate.model_validate(bird_payload(image=encode(image))), CARDINAL_ID)

    assert bird.id == CARDINAL_ID
    assert bird.image.bird_id == CARDINAL_ID
    assert bird.image.data == image
    assert (bird.image.media_type, bird.image.sha256, bird.image.size) == (media_type, sha256(image), len(image))


def test_build_bird_copies_image_attribution_to_image():
    bird = build_bird(BirdCreate.model_validate(bird_payload()), CARDINAL_ID)

    assert (bird.image.alt_text, bird.image.credit, bird.image.license, bird.image.source_url) == (
        "A northern cardinal on a branch",
        "Jane Photographer",
        "CC BY-SA 4.0",
        "https://example.com/photos/northern-cardinal.jpg",
    )


def test_conservation_status_values_are_iucn_category_names():
    assert [status.value for status in ConservationStatus] == CONSERVATION_STATUSES


def test_bird_parses_conservation_status_as_enum():
    assert Bird.model_validate(ROW).conservation_status is ConservationStatus.LEAST_CONCERN


def test_bird_public_rejects_unknown_conservation_status():
    with pytest.raises(ValidationError):
        BirdPublic.model_validate({**ROW, **PUBLIC_IMAGE_FIELDS, "conservation_status": "Mostly Harmless"})


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (PNG_IMAGE, "image/png"),
    ],
)
def test_detect_image_media_type_recognizes_jpeg_and_png(data, media_type):
    assert detect_image_media_type(data) == media_type


@pytest.mark.parametrize(
    "data",
    [b"", b"\xff\xd8", b"\x89PNG\r\n\x1a", GIF_IMAGE, b"RIFF\x00\x00\x00\x00WEBP", b"\x00\xff\xd8\xff", b"not an image"],
)
def test_detect_image_media_type_returns_none_for_other_data(data):
    assert detect_image_media_type(data) is None
