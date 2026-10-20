import hashlib
import os
import subprocess
import sys

from sqlmodel import Session, select

from app.database.seed import SEED_DIRECTORY, load_seed_birds, seed_birds
from app.models import Bird, BirdCreate, BirdImage, build_bird, build_bird_public
from tests.conftest import PROJECT_ROOT
from tests.factories import CARDINAL_ID


def run_seed_command(engine):
    return subprocess.run(
        [sys.executable, "-m", "app.database.seed"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "BIRD_API_DATABASE_URL": engine.url.render_as_string(hide_password=False)},
        capture_output=True,
        text=True,
        check=True,
    )


def bird_rows(birds):
    return [{**bird.model_dump(), "image": bird.image.model_dump()} for bird in birds]


def stored_birds(engine):
    with Session(engine) as session:
        return bird_rows(session.exec(select(Bird)).all())


def test_load_seed_birds_returns_northern_cardinal_with_image_file():
    [bird] = load_seed_birds()

    assert bird.id == CARDINAL_ID
    assert bird.binomial_name == "Cardinalis cardinalis"
    assert bird.common_name == "Northern cardinal"
    assert bird.conservation_status == "Least Concern"
    assert bird.kingdom == "Animalia"
    assert bird.phylum == "Chordata"
    assert bird.class_ == "Aves"
    assert bird.order == "Passeriformes"
    assert bird.family == "Cardinalidae"
    assert bird.genus == "Cardinalis"
    assert bird.species == "cardinalis"
    assert bird.image.bird_id == CARDINAL_ID
    assert bird.image.data == (SEED_DIRECTORY / "images" / "northern-cardinal.jpg").read_bytes()
    assert len(bird.image.data) == 32529
    assert bird.image.data.startswith(b"\xff\xd8\xff")


def test_load_seed_birds_returns_northern_cardinal_image_attribution():
    [bird] = load_seed_birds()

    assert bird.image.alt_text == "Male northern cardinal with bright red plumage perched on a bare branch"
    assert bird.image.credit == "Rhododendrites"
    assert bird.image.license == "CC BY-SA 4.0"
    assert bird.image.source_url == "https://commons.wikimedia.org/wiki/File:Male_northern_cardinal_in_Central_Park_(52612).jpg"


def test_load_seed_birds_derives_image_metadata_from_image_file():
    [bird] = load_seed_birds()
    image = (SEED_DIRECTORY / "images" / "northern-cardinal.jpg").read_bytes()

    assert bird.image.media_type == "image/jpeg"
    assert bird.image.sha256 == hashlib.sha256(image).hexdigest()
    assert bird.image.size == 32529


def test_seed_birds_satisfy_create_validation():
    for bird in load_seed_birds():
        validated = BirdCreate.model_validate({**build_bird_public(bird).model_dump(by_alias=True), "image": bird.image.data})

        assert bird_rows([build_bird(validated, bird.id)]) == bird_rows([bird])


def test_seed_command_loads_seed_birds_into_migrated_database(migrated_engine):
    run_seed_command(migrated_engine)

    assert stored_birds(migrated_engine) == bird_rows(load_seed_birds())


def test_seed_command_is_idempotent(migrated_engine):
    run_seed_command(migrated_engine)
    run_seed_command(migrated_engine)

    assert stored_birds(migrated_engine) == bird_rows(load_seed_birds())
    with Session(migrated_engine) as session:
        assert len(session.exec(select(BirdImage)).all()) == 1


def test_seed_birds_inserts_only_missing_ids(session):
    assert seed_birds(session) == 1
    assert seed_birds(session) == 0
    assert [bird.id for bird in session.exec(select(Bird)).all()] == [CARDINAL_ID]
    assert [image.bird_id for image in session.exec(select(BirdImage)).all()] == [CARDINAL_ID]
