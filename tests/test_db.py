import importlib

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

import app.database.db as db
from app.config import settings
from app.models import Bird, BirdCreate, BirdImage, BirdPageQuery, BirdSort, ConservationStatus
from tests.factories import CARDINAL_ID, IMAGE, add_bird, bird_payload, sha256


@pytest.fixture
def configured_database_url(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'configured.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    working_directory = tmp_path / "elsewhere"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    db.engine.dispose()
    importlib.reload(db)
    yield database_url
    db.engine.dispose()
    monkeypatch.undo()
    importlib.reload(db)


def test_get_bird_page_reads_database_regardless_of_working_directory(configured_database_url):
    SQLModel.metadata.create_all(db.engine)

    with Session(db.engine) as session:
        add_bird(session, bird_id=CARDINAL_ID)
        birds = db.get_bird_page(session, BirdPageQuery())[0]

    assert [bird.id for bird in birds] == [CARDINAL_ID]


def test_engine_uses_configured_database_url(configured_database_url):
    assert db.engine.url.render_as_string(hide_password=False) == configured_database_url


def test_get_bird_page_returns_bird_models(session):
    add_bird(session)

    birds = db.get_bird_page(session, BirdPageQuery())[0]

    assert birds
    assert all(isinstance(bird, Bird) for bird in birds)


def test_get_bird_page_reads_existing_uuid(session):
    add_bird(session, bird_id=CARDINAL_ID)
    session.expunge_all()

    birds = db.get_bird_page(session, BirdPageQuery())[0]

    assert CARDINAL_ID in [bird.id for bird in birds]


def test_bird_can_be_looked_up_by_existing_uuid(session):
    add_bird(session, bird_id=CARDINAL_ID)
    session.expunge_all()

    bird = session.get(Bird, CARDINAL_ID)

    assert bird is not None
    assert bird.common_name == "Northern cardinal"


def test_bird_ids_are_stored_as_hex_without_dashes(session):
    add_bird(session, bird_id=CARDINAL_ID)

    ids = session.connection().exec_driver_sql("SELECT id FROM birds").scalars().all()

    assert ids == [CARDINAL_ID.hex]
    assert all(len(bird_id) == 32 and "-" not in bird_id for bird_id in ids)


@pytest.mark.parametrize("table", ["birds", "bird_images"])
def test_tables_have_no_nullable_columns(session, table):
    columns = session.connection().exec_driver_sql(f"PRAGMA table_info({table})").mappings().all()

    assert columns
    assert [column["name"] for column in columns if not column["notnull"]] == []


def test_birds_table_has_no_image_columns(session):
    columns = session.connection().exec_driver_sql("PRAGMA table_info(birds)").scalars("name").all()

    assert [column for column in columns if column.startswith("image")] == []


def test_bird_images_are_stored_with_bird_id_as_hex(session):
    add_bird(session, bird_id=CARDINAL_ID)

    rows = session.connection().exec_driver_sql("SELECT bird_id, data FROM bird_images").all()

    assert rows == [(CARDINAL_ID.hex, IMAGE)]


def test_session_fixture_enforces_foreign_keys(session):
    assert session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_app_engine_enforces_foreign_keys():
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_bird_image_for_unknown_bird_is_rejected(session):
    session.add(
        BirdImage.model_validate(
            {
                "bird_id": CARDINAL_ID,
                "data": IMAGE,
                "media_type": "image/jpeg",
                "sha256": sha256(IMAGE),
                "size": len(IMAGE),
                "alt_text": "Alt text",
                "credit": "Credit",
                "license": "CC BY-SA 4.0",
                "source_url": "https://example.com/cardinal.jpg",
            }
        )
    )

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        session.commit()


def test_get_bird_page_excludes_bird_without_image_row(session):
    add_bird(session, bird_id=CARDINAL_ID)
    add_bird(session, image=None, binomial_name="Turdus migratorius")

    assert [bird.id for bird in db.get_bird_page(session, BirdPageQuery())[0]] == [CARDINAL_ID]


def test_get_bird_page_returns_filtered_sorted_page_and_total(session):
    for genus in ["Alpha", "Bravo", "Charlie"]:
        add_bird(session, binomial_name=f"{genus} species", genus=genus)
    add_bird(session, binomial_name="Delta species", genus="Delta", family="Turdidae")

    birds, total = db.get_bird_page(session, BirdPageQuery(family="Cardinalidae", sort=BirdSort.GENUS_DESC, offset=1, limit=1))

    assert ([bird.genus for bird in birds], total) == (["Bravo"], 3)


def test_get_bird_returns_none_for_bird_without_image_row(session):
    add_bird(session, bird_id=CARDINAL_ID, image=None)

    assert db.get_bird(session, CARDINAL_ID) is None


def test_get_bird_image_returns_image_row(session):
    add_bird(session, bird_id=CARDINAL_ID)
    session.expunge_all()

    image = db.get_bird_image(session, CARDINAL_ID)

    assert image is not None
    assert image.data == IMAGE


def test_get_bird_image_returns_none_for_bird_without_image_row(session):
    add_bird(session, bird_id=CARDINAL_ID, image=None)

    assert db.get_bird_image(session, CARDINAL_ID) is None


def test_duplicate_binomial_name_raises_integrity_error(session):
    add_bird(session)

    with pytest.raises(IntegrityError):
        add_bird(session, common_name="Another cardinal")


def test_binomial_name_differing_only_in_case_raises_integrity_error(session):
    add_bird(session)

    with pytest.raises(IntegrityError, match="UNIQUE"):
        add_bird(session, common_name="Another cardinal", binomial_name="cardinalis CARDINALIS")


def test_conservation_status_is_stored_as_full_name_and_read_as_enum(session):
    add_bird(session, bird_id=CARDINAL_ID)
    session.expunge_all()

    stored = session.connection().exec_driver_sql("SELECT conservation_status FROM birds").scalars().all()

    assert stored == ["Least Concern"]
    assert session.get(Bird, CARDINAL_ID).conservation_status is ConservationStatus.LEAST_CONCERN


def test_check_constraint_rejects_unknown_conservation_status(session):
    bird = add_bird(session)
    bird.conservation_status = "Mostly Harmless"

    with pytest.raises(IntegrityError, match="ck_birds_conservation_status"):
        session.commit()


def test_create_bird_raises_duplicate_bird_error_and_rolls_back(session):
    add_bird(session)

    with pytest.raises(db.DuplicateBirdError):
        db.create_bird(session, BirdCreate.model_validate(bird_payload()))

    assert len(db.get_bird_page(session, BirdPageQuery())[0]) == 1
    assert session.connection().exec_driver_sql("SELECT COUNT(*) FROM bird_images").scalar() == 1
