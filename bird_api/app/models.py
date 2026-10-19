import base64
import hashlib
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    HttpUrl,
    PlainSerializer,
    StringConstraints,
    UrlConstraints,
    computed_field,
    field_validator,
    model_validator,
)
from sqlalchemy import CheckConstraint, Column, Enum, ForeignKeyConstraint, LargeBinary, String, UniqueConstraint, column
from sqlmodel import Field, Relationship, SQLModel

MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


class ConservationStatus(StrEnum):
    EXTINCT = "Extinct"
    EXTINCT_IN_THE_WILD = "Extinct in the Wild"
    CRITICALLY_ENDANGERED = "Critically Endangered"
    ENDANGERED = "Endangered"
    VULNERABLE = "Vulnerable"
    NEAR_THREATENED = "Near Threatened"
    LEAST_CONCERN = "Least Concern"
    DATA_DEFICIENT = "Data Deficient"
    NOT_EVALUATED = "Not Evaluated"


CONSERVATION_STATUS_VALUES = [status.value for status in ConservationStatus]


class BirdSort(StrEnum):
    COMMON_NAME = "common_name"
    COMMON_NAME_DESC = "-common_name"
    BINOMIAL_NAME = "binomial_name"
    BINOMIAL_NAME_DESC = "-binomial_name"
    CONSERVATION_STATUS = "conservation_status"
    CONSERVATION_STATUS_DESC = "-conservation_status"
    FAMILY = "family"
    FAMILY_DESC = "-family"
    GENUS = "genus"
    GENUS_DESC = "-genus"


def detect_image_media_type(data: bytes) -> str | None:
    for signature, media_type in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return media_type
    return None


class BirdBase(SQLModel):
    model_config = {"validate_by_name": True}

    binomial_name: str = Field(sa_type=String(collation="NOCASE"))
    common_name: str
    conservation_status: ConservationStatus = Field(
        sa_type=Enum(ConservationStatus, native_enum=False, values_callable=lambda _: CONSERVATION_STATUS_VALUES)
    )
    kingdom: str
    phylum: str
    class_: str = Field(alias="class", sa_column=Column("class", String, nullable=False))
    order: str
    family: str
    genus: str
    species: str


class BirdImage(SQLModel, table=True):
    __tablename__ = "bird_images"
    __table_args__ = (ForeignKeyConstraint(["bird_id"], ["birds.id"], name="fk_bird_images_bird_id_birds"),)

    bird_id: UUID = Field(primary_key=True)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    media_type: str
    sha256: str
    size: int
    alt_text: str
    credit: str
    license: str
    source_url: str


class Bird(BirdBase, table=True):
    __tablename__ = "birds"
    __table_args__ = (
        UniqueConstraint("binomial_name", name="uq_birds_binomial_name"),
        CheckConstraint(column("conservation_status").in_(CONSERVATION_STATUS_VALUES), name="ck_birds_conservation_status"),
    )

    id: UUID = Field(primary_key=True)
    image: BirdImage = Relationship()


class BirdAttributionBase(BirdBase):
    image_alt_text: str
    image_credit: str
    image_license: str
    image_source_url: str


class BirdPublic(BirdAttributionBase):
    id: UUID
    image_media_type: str
    image_size: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def image_url(self) -> str:
        return f"/api/v1/birds/{self.id}/image"


class BirdPage(SQLModel):
    items: list[BirdPublic]
    total: int
    offset: int
    limit: int


class BirdFilters(SQLModel):
    conservation_status: ConservationStatus | None = None
    kingdom: str | None = None
    phylum: str | None = None
    class_: str | None = Field(default=None, alias="class")
    order: str | None = None
    family: str | None = None
    genus: str | None = None


class BirdPageQuery(BirdFilters):
    sort: BirdSort = BirdSort.COMMON_NAME
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=100)


class BirdCreate(BirdAttributionBase):
    model_config = {"str_strip_whitespace": True, "str_min_length": 1, "str_max_length": 200}

    genus: Annotated[str, StringConstraints(pattern=r"^[A-Z][a-z]+$")]
    species: Annotated[str, StringConstraints(pattern=r"^[a-z]+(-[a-z]+)*$")]
    image: bytes
    image_source_url: Annotated[HttpUrl, UrlConstraints(max_length=2000), AfterValidator(str), PlainSerializer(str)]  # type: ignore[assignment]

    @field_validator("image", mode="before")
    @classmethod
    def decode_image(cls, image: object) -> object:
        if isinstance(image, str):
            return base64.b64decode(image, validate=True)
        return image

    @field_validator("image")
    @classmethod
    def check_image(cls, image: bytes) -> bytes:
        if len(image) > MAX_IMAGE_BYTES:
            raise ValueError("image must be at most 5 MiB after base64 decoding")
        if detect_image_media_type(image) is None:
            raise ValueError("image must be a JPEG or PNG")
        return image

    @model_validator(mode="after")
    def check_binomial_name(self) -> Self:
        expected = f"{self.genus} {self.species}"
        if self.binomial_name != expected:
            raise ValueError(f"binomial_name must be the genus and species separated by one space: expected {expected!r}")
        return self


def build_bird(bird_create: BirdCreate, bird_id: UUID) -> Bird:
    data = bird_create.image
    image = BirdImage.model_validate(
        {
            "bird_id": bird_id,
            "data": data,
            "media_type": detect_image_media_type(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "alt_text": bird_create.image_alt_text,
            "credit": bird_create.image_credit,
            "license": bird_create.image_license,
            "source_url": bird_create.image_source_url,
        }
    )
    return Bird.model_validate(bird_create, update={"id": bird_id, "image": image})


def build_bird_public(bird: Bird) -> BirdPublic:
    image = bird.image
    return BirdPublic.model_validate(
        bird,
        update={
            "image_media_type": image.media_type,
            "image_size": image.size,
            "image_alt_text": image.alt_text,
            "image_credit": image.credit,
            "image_license": image.license,
            "image_source_url": image.source_url,
        },
    )
