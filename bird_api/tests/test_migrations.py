import hashlib
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from app.config import settings
from tests.factories import CARDINAL_ID

ORIGINAL_BIRDS_DDL = """
CREATE TABLE IF NOT EXISTS "birds" (
    id TEXT PRIMARY KEY NOT NULL,
    binomial_name TEXT NOT NULL,
    common_name TEXT NOT NULL,
    conservation_status TEXT NOT NULL,
    kingdom TEXT NOT NULL,
    phylum TEXT NOT NULL,
    class TEXT NOT NULL,
    "order" TEXT NOT NULL,
    family TEXT NOT NULL,
    genus TEXT NOT NULL,
    species TEXT NOT NULL,
    image BLOB NOT NULL
)
"""

TAXONOMY_COLUMNS = [
    "id",
    "binomial_name",
    "common_name",
    "conservation_status",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]
BIRD_COLUMNS = [*TAXONOMY_COLUMNS, "image"]
BIRD_IMAGE_COLUMNS = ["bird_id", "data", "media_type", "sha256", "size", "alt_text", "credit", "license", "source_url"]


IMAGE_METADATA_COLUMNS = [
    "image_media_type",
    "image_sha256",
    "image_size",
    "image_alt_text",
    "image_credit",
    "image_license",
    "image_source_url",
]
PREVIOUS_REVISION = "891a7254d1d7"
IMAGE_METADATA_REVISION = "c1acf131e21c"
IMAGE_TABLE_REVISION = "99fdb77b15b5"
PNG_BIRD_ID = UUID("0b6f1c1e-6a8f-4d55-9a53-3f2f4b8f5c11")
LEGACY_INSERT = (
    "INSERT INTO birds (id, binomial_name, common_name, conservation_status, kingdom, phylum, "
    'class, "order", family, genus, species, image) '
    "VALUES (?, ?, 'Northern cardinal', 'Least Concern', 'Animalia', 'Chordata', 'Aves', "
    "'Passeriformes', 'Cardinalidae', 'Cardinalis', 'cardinalis', ?)"
)
TAXONOMY_INSERT = (
    "INSERT INTO birds (id, binomial_name, common_name, conservation_status, kingdom, phylum, "
    'class, "order", family, genus, species) '
    "VALUES (?, ?, 'Northern cardinal', ?, 'Animalia', 'Chordata', 'Aves', "
    "'Passeriformes', 'Cardinalidae', 'Cardinalis', 'cardinalis')"
)
IMAGE_METADATA_INSERT = (
    "INSERT INTO birds (id, binomial_name, common_name, conservation_status, kingdom, phylum, "
    f'class, "order", family, genus, species, image, {", ".join(IMAGE_METADATA_COLUMNS)}) '
    "VALUES (?, ?, 'Northern cardinal', 'Least Concern', 'Animalia', 'Chordata', 'Aves', "
    "'Passeriformes', 'Cardinalidae', 'Cardinalis', 'cardinalis', ?, ?, ?, ?, ?, ?, ?, ?)"
)
BIRD_IMAGE_INSERT = f"INSERT INTO bird_images ({', '.join(BIRD_IMAGE_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
JPEG = b"\xff\xd8\xff\xe1" + b"\x00" * 10
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
IMAGE_METADATA_ROWS = [
    (
        CARDINAL_ID.hex,
        "Cardinalis cardinalis",
        JPEG,
        "image/jpeg",
        hashlib.sha256(JPEG).hexdigest(),
        len(JPEG),
        "Male northern cardinal on a branch",
        "Rhododendrites",
        "CC BY-SA 4.0",
        "https://commons.wikimedia.org/wiki/File:Male_northern_cardinal_in_Central_Park_(52612).jpg",
    ),
    (
        PNG_BIRD_ID.hex,
        "Turdus migratorius",
        PNG,
        "image/png",
        hashlib.sha256(PNG).hexdigest(),
        len(PNG),
        "American robin on a lawn",
        "Jane Photographer",
        "CC0 1.0",
        "https://example.com/robin.png",
    ),
]


@pytest.fixture
def previous_revision_engine(alembic_config):
    command.upgrade(alembic_config, PREVIOUS_REVISION)
    engine = create_engine(settings.database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def image_metadata_revision_engine(alembic_config):
    command.upgrade(alembic_config, IMAGE_METADATA_REVISION)
    engine = create_engine(settings.database_url)
    yield engine
    engine.dispose()


def insert_image_metadata_birds(engine):
    with engine.begin() as connection:
        for row in IMAGE_METADATA_ROWS:
            connection.exec_driver_sql(IMAGE_METADATA_INSERT, row)


def image_metadata_rows(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            f"SELECT id, binomial_name, image, {', '.join(IMAGE_METADATA_COLUMNS)} FROM birds ORDER BY binomial_name"
        ).all()


def bird_image_rows(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            f"SELECT b.id, b.binomial_name, {', '.join(f'i.{name}' for name in BIRD_IMAGE_COLUMNS[1:])} "
            "FROM birds b JOIN bird_images i ON i.bird_id = b.id ORDER BY b.binomial_name"
        ).all()


def foreign_key_violations(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql("PRAGMA foreign_key_check").all()


def table_names(engine):
    return sorted(inspect(engine).get_table_names())


def base_revision(alembic_config):
    base = ScriptDirectory.from_config(alembic_config).get_base()
    assert base is not None
    return base


def insert_legacy_bird(engine, bird_id, binomial_name, image):
    with engine.begin() as connection:
        connection.exec_driver_sql(LEGACY_INSERT, (bird_id.hex, binomial_name, image))


def columns(engine, table="birds"):
    with engine.connect() as connection:
        return connection.exec_driver_sql(f"PRAGMA table_info({table})").mappings().all()


def column_names(engine, table="birds"):
    return [column["name"] for column in columns(engine, table)]


def unique_constraints(engine):
    return [(constraint["name"], constraint["column_names"]) for constraint in inspect(engine).get_unique_constraints("birds")]


def check_constraints(engine):
    return inspect(engine).get_check_constraints("birds")


def current_revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def insert_bird(engine, conservation_status, with_image=True):
    image = b"\xff\xd8\xff\xe1"
    with engine.begin() as connection:
        connection.exec_driver_sql(TAXONOMY_INSERT, (CARDINAL_ID.hex, "Cardinalis cardinalis", conservation_status))
        if with_image:
            connection.exec_driver_sql(
                BIRD_IMAGE_INSERT,
                (
                    CARDINAL_ID.hex,
                    image,
                    "image/jpeg",
                    hashlib.sha256(image).hexdigest(),
                    len(image),
                    "Alt text",
                    "Credit",
                    "CC BY-SA 4.0",
                    "https://example.com/cardinal.jpg",
                ),
            )


def test_upgrade_head_matches_model_metadata(migrated_engine):
    with migrated_engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []


def test_upgrade_head_adds_unique_constraint_on_binomial_name(migrated_engine):
    assert unique_constraints(migrated_engine) == [("uq_birds_binomial_name", ["binomial_name"])]


def test_upgrade_head_adds_conservation_status_check_constraint_matching_model(migrated_engine):
    model_engine = create_engine("sqlite://")
    try:
        SQLModel.metadata.create_all(model_engine)
        model_constraints = check_constraints(model_engine)
    finally:
        model_engine.dispose()

    constraints = check_constraints(migrated_engine)
    assert [constraint["name"] for constraint in constraints] == ["ck_birds_conservation_status"]
    assert constraints == model_constraints


def test_upgrade_head_rejects_unknown_conservation_status(migrated_engine):
    with pytest.raises(IntegrityError, match="ck_birds_conservation_status"):
        insert_bird(migrated_engine, "Mostly Harmless")


def test_upgrade_head_accepts_known_conservation_status(migrated_engine):
    insert_bird(migrated_engine, "Least Concern")

    with migrated_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT conservation_status FROM birds").scalars().all() == ["Least Concern"]


def test_downgrade_to_unique_constraint_revision_removes_check_constraint_and_keeps_rows(alembic_config, migrated_engine):
    insert_bird(migrated_engine, "Least Concern")

    command.downgrade(alembic_config, "3453d99012b6")

    assert current_revision(migrated_engine) == "3453d99012b6"
    assert check_constraints(migrated_engine) == []
    assert unique_constraints(migrated_engine) == [("uq_birds_binomial_name", ["binomial_name"])]
    with migrated_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT id, conservation_status FROM birds").all() == [
            (CARDINAL_ID.hex, "Least Concern")
        ]


def test_image_metadata_revision_adds_not_null_image_metadata_columns(image_metadata_revision_engine):
    bird_columns = columns(image_metadata_revision_engine)

    assert [column["name"] for column in bird_columns] == BIRD_COLUMNS + IMAGE_METADATA_COLUMNS
    assert all(column["notnull"] for column in bird_columns)


def test_upgrade_head_keeps_only_taxonomy_columns_in_birds(migrated_engine):
    bird_columns = columns(migrated_engine)

    assert [column["name"] for column in bird_columns] == TAXONOMY_COLUMNS
    assert all(column["notnull"] for column in bird_columns)


def test_upgrade_head_creates_bird_images_table_keyed_by_bird_id(migrated_engine):
    image_columns = columns(migrated_engine, "bird_images")
    [foreign_key] = inspect(migrated_engine).get_foreign_keys("bird_images")

    assert [column["name"] for column in image_columns] == BIRD_IMAGE_COLUMNS
    assert all(column["notnull"] for column in image_columns)
    assert [column["name"] for column in image_columns if column["pk"]] == ["bird_id"]
    assert (foreign_key["name"], foreign_key["constrained_columns"], foreign_key["referred_table"]) == (
        "fk_bird_images_bird_id_birds",
        ["bird_id"],
        "birds",
    )
    assert foreign_key["referred_columns"] == ["id"]


def test_upgrade_moves_images_and_metadata_to_bird_images_unchanged(alembic_config, image_metadata_revision_engine):
    insert_image_metadata_birds(image_metadata_revision_engine)

    command.upgrade(alembic_config, "head")

    assert column_names(image_metadata_revision_engine) == TAXONOMY_COLUMNS
    assert bird_image_rows(image_metadata_revision_engine) == IMAGE_METADATA_ROWS
    assert foreign_key_violations(image_metadata_revision_engine) == []


def test_downgrade_restores_image_columns_and_values_in_birds(alembic_config, image_metadata_revision_engine):
    insert_image_metadata_birds(image_metadata_revision_engine)
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, IMAGE_METADATA_REVISION)

    assert current_revision(image_metadata_revision_engine) == IMAGE_METADATA_REVISION
    assert "bird_images" not in table_names(image_metadata_revision_engine)
    bird_columns = columns(image_metadata_revision_engine)
    assert [column["name"] for column in bird_columns] == BIRD_COLUMNS + IMAGE_METADATA_COLUMNS
    assert all(column["notnull"] for column in bird_columns)
    assert image_metadata_rows(image_metadata_revision_engine) == IMAGE_METADATA_ROWS
    assert unique_constraints(image_metadata_revision_engine) == [("uq_birds_binomial_name", ["binomial_name"])]
    assert [constraint["name"] for constraint in check_constraints(image_metadata_revision_engine)] == [
        "ck_birds_conservation_status"
    ]


def test_downgrade_fails_when_bird_has_no_image_row(alembic_config, migrated_engine):
    insert_bird(migrated_engine, "Least Concern", with_image=False)

    with pytest.raises(ValueError, match=CARDINAL_ID.hex):
        command.downgrade(alembic_config, IMAGE_METADATA_REVISION)

    assert current_revision(migrated_engine) == IMAGE_TABLE_REVISION
    assert column_names(migrated_engine) == TAXONOMY_COLUMNS
    assert "bird_images" in table_names(migrated_engine)


def test_upgrade_backfills_image_metadata_from_existing_image_bytes(alembic_config, previous_revision_engine):
    jpeg = b"\xff\xd8\xff\xe1" + b"\x00" * 10
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    insert_legacy_bird(previous_revision_engine, CARDINAL_ID, "Cardinalis cardinalis", jpeg)
    insert_legacy_bird(previous_revision_engine, PNG_BIRD_ID, "Turdus migratorius", png)

    command.upgrade(alembic_config, IMAGE_METADATA_REVISION)

    with previous_revision_engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT id, image, {', '.join(IMAGE_METADATA_COLUMNS)} FROM birds ORDER BY binomial_name"
        ).all()
    unknown = ("Unknown", "Unknown", "Unknown", "Unknown")
    assert rows == [
        (CARDINAL_ID.hex, jpeg, "image/jpeg", hashlib.sha256(jpeg).hexdigest(), len(jpeg), *unknown),
        (PNG_BIRD_ID.hex, png, "image/png", hashlib.sha256(png).hexdigest(), len(png), *unknown),
    ]


def test_upgrade_fails_when_existing_image_is_not_jpeg_or_png(alembic_config, previous_revision_engine):
    insert_legacy_bird(previous_revision_engine, CARDINAL_ID, "Cardinalis cardinalis", b"GIF89a\x01\x00\x01\x00")

    with pytest.raises(ValueError, match=CARDINAL_ID.hex):
        command.upgrade(alembic_config, "head")

    assert current_revision(previous_revision_engine) == PREVIOUS_REVISION


def test_downgrade_image_metadata_revision_removes_image_metadata_columns_and_keeps_rows(
    alembic_config, image_metadata_revision_engine
):
    insert_image_metadata_birds(image_metadata_revision_engine)

    command.downgrade(alembic_config, PREVIOUS_REVISION)

    assert current_revision(image_metadata_revision_engine) == PREVIOUS_REVISION
    assert column_names(image_metadata_revision_engine) == BIRD_COLUMNS
    with image_metadata_revision_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT id, image FROM birds ORDER BY binomial_name").all() == [
            (CARDINAL_ID.hex, JPEG),
            (PNG_BIRD_ID.hex, PNG),
        ]


def test_upgrade_head_with_rows_has_no_foreign_key_violations(migrated_engine):
    insert_bird(migrated_engine, "Least Concern")

    assert foreign_key_violations(migrated_engine) == []


def test_upgrade_head_records_head_revision(alembic_config, migrated_engine):
    with migrated_engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()

    assert current == ScriptDirectory.from_config(alembic_config).get_current_head()


def test_baseline_creates_existing_birds_table_without_unique_constraint(alembic_config):
    command.upgrade(alembic_config, base_revision(alembic_config))
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            columns = connection.exec_driver_sql("PRAGMA table_info(birds)").mappings().all()
        constraints = unique_constraints(engine)
    finally:
        engine.dispose()

    assert [column["name"] for column in columns] == BIRD_COLUMNS
    assert all(column["notnull"] for column in columns)
    assert [column["name"] for column in columns if column["pk"]] == ["id"]
    assert constraints == []


def test_downgrade_to_base_removes_birds_table(alembic_config, migrated_engine):
    command.downgrade(alembic_config, "base")

    assert inspect(migrated_engine).get_table_names() == ["alembic_version"]


def test_stamped_existing_database_upgrades_without_losing_rows(alembic_config):
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(ORIGINAL_BIRDS_DDL)
            connection.exec_driver_sql(
                "INSERT INTO birds VALUES (?, 'Cardinalis cardinalis', 'Northern cardinal', 'Least Concern', "
                "'Animalia', 'Chordata', 'Aves', 'Passeriformes', 'Cardinalidae', 'Cardinalis', 'cardinalis', ?)",
                (CARDINAL_ID.hex, b"\xff\xd8\xff\xe1"),
            )

        command.stamp(alembic_config, base_revision(alembic_config))
        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT b.id, b.binomial_name, i.data FROM birds b JOIN bird_images i ON i.bird_id = b.id"
            ).all()
        constraints = unique_constraints(engine)
    finally:
        engine.dispose()

    assert rows == [(CARDINAL_ID.hex, "Cardinalis cardinalis", b"\xff\xd8\xff\xe1")]
    assert constraints == [("uq_birds_binomial_name", ["binomial_name"])]


def insert_taxonomy(engine, binomial_name):
    with engine.begin() as connection:
        connection.exec_driver_sql(TAXONOMY_INSERT, (uuid4().hex, binomial_name, "Least Concern"))


@pytest.fixture
def image_table_revision_engine(alembic_config):
    command.upgrade(alembic_config, IMAGE_TABLE_REVISION)
    engine = create_engine(settings.database_url)
    yield engine
    engine.dispose()


def test_upgrade_head_rejects_binomial_name_differing_only_in_case(migrated_engine):
    insert_taxonomy(migrated_engine, "Cardinalis cardinalis")

    with pytest.raises(IntegrityError, match="UNIQUE"):
        insert_taxonomy(migrated_engine, "cardinalis CARDINALIS")


def test_upgrade_keeps_binomial_names_and_their_case(alembic_config, image_table_revision_engine):
    insert_taxonomy(image_table_revision_engine, "Cardinalis cardinalis")

    command.upgrade(alembic_config, "head")

    with image_table_revision_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT binomial_name FROM birds").scalars().all() == ["Cardinalis cardinalis"]


def test_upgrade_fails_when_binomial_names_differ_only_in_case(alembic_config, image_table_revision_engine):
    insert_taxonomy(image_table_revision_engine, "Cardinalis cardinalis")
    insert_taxonomy(image_table_revision_engine, "cardinalis cardinalis")

    with pytest.raises(ValueError, match="Cardinalis cardinalis"):
        command.upgrade(alembic_config, "head")

    assert current_revision(image_table_revision_engine) == IMAGE_TABLE_REVISION


def test_downgrade_makes_binomial_name_case_sensitive_again(alembic_config, migrated_engine):
    insert_taxonomy(migrated_engine, "Cardinalis cardinalis")

    command.downgrade(alembic_config, IMAGE_TABLE_REVISION)
    insert_taxonomy(migrated_engine, "cardinalis cardinalis")

    assert unique_constraints(migrated_engine) == [("uq_birds_binomial_name", ["binomial_name"])]
