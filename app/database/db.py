from collections.abc import Iterator
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import contains_eager
from sqlmodel import Session, col, create_engine, func, select
from sqlmodel.sql.expression import SelectOfScalar

from app.config import settings
from app.database.sqlite import enable_foreign_keys
from app.models import Bird, BirdCreate, BirdFilters, BirdImage, BirdPageQuery, build_bird

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)
enable_foreign_keys(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


class DuplicateBirdError(Exception):
    pass


def select_birds_with_image_metadata() -> SelectOfScalar[Bird]:
    return select(Bird).join(Bird.image).options(contains_eager(Bird.image).defer(BirdImage.data))  # type: ignore[arg-type]


def get_bird_page(session: Session, query: BirdPageQuery) -> tuple[list[Bird], int]:
    filters = query.model_dump(include=set(BirdFilters.model_fields), exclude_none=True)
    statement = select_birds_with_image_metadata().where(
        *(col(getattr(Bird, field)) == value for field, value in filters.items())
    )
    sort_column = col(getattr(Bird, query.sort.removeprefix("-")))
    sort_order = sort_column.desc() if query.sort.startswith("-") else sort_column.asc()
    items = statement.order_by(sort_order, col(Bird.id)).offset(query.offset).limit(query.limit)
    total = select(func.count()).select_from(statement.subquery())
    return list(session.exec(items).all()), session.exec(total).one()


def get_bird(session: Session, bird_id: UUID) -> Bird | None:
    return session.exec(select_birds_with_image_metadata().where(col(Bird.id) == bird_id)).first()


def get_bird_image(session: Session, bird_id: UUID) -> BirdImage | None:
    return session.get(BirdImage, bird_id)


def create_bird(session: Session, bird_create: BirdCreate) -> Bird:
    bird = build_bird(bird_create, uuid4())
    session.add(bird)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicateBirdError from error
    session.refresh(bird)
    return bird
