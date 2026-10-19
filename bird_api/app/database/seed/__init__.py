import json
from pathlib import Path
from uuid import UUID

from sqlmodel import Session

from app.models import Bird, BirdCreate, build_bird

SEED_DIRECTORY = Path(__file__).resolve().parent


def load_seed_birds() -> list[Bird]:
    records = json.loads((SEED_DIRECTORY / "birds.json").read_text())
    return [
        build_bird(
            BirdCreate.model_validate({**record, "image": (SEED_DIRECTORY / record["image"]).read_bytes()}), UUID(record["id"])
        )
        for record in records
    ]


def seed_birds(session: Session) -> int:
    missing = [bird for bird in load_seed_birds() if session.get(Bird, bird.id) is None]
    session.add_all(missing)
    session.commit()
    return len(missing)
