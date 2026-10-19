import base64
import hashlib
from uuid import UUID, uuid4

from app.models import Bird, BirdImage

IMAGE = b"\xff\xd8\xff\xe0"
PNG_IMAGE = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
GIF_IMAGE = b"GIF89a\x01\x00\x01\x00"
CARDINAL_ID = UUID("e91c2f2d-923e-4122-b43f-a61b867d89c1")
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
TEXT_FIELDS = [
    "binomial_name",
    "common_name",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
    "image_alt_text",
    "image_credit",
    "image_license",
]
MEDIA_TYPES = {IMAGE: "image/jpeg", PNG_IMAGE: "image/png"}


def encode(image):
    return base64.b64encode(image).decode("ascii")


def sha256(image):
    return hashlib.sha256(image).hexdigest()


def bird_payload(**overrides):
    payload = {
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
        "image": encode(IMAGE),
        "image_alt_text": "A northern cardinal on a branch",
        "image_credit": "Jane Photographer",
        "image_license": "CC BY-SA 4.0",
        "image_source_url": "https://example.com/photos/northern-cardinal.jpg",
    }
    return {**payload, **overrides}


def add_bird(session, bird_id=None, image=IMAGE, **overrides):
    bird_id = bird_id or uuid4()
    payload = bird_payload(**overrides)
    bird = Bird.model_validate({**payload, "id": bird_id})
    if image is not None:
        bird.image = BirdImage.model_validate(
            {
                "bird_id": bird_id,
                "data": image,
                "media_type": MEDIA_TYPES[image],
                "sha256": sha256(image),
                "size": len(image),
                "alt_text": payload["image_alt_text"],
                "credit": payload["image_credit"],
                "license": payload["image_license"],
                "source_url": payload["image_source_url"],
            }
        )
    session.add(bird)
    session.commit()
    return bird
