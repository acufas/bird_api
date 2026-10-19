from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from app.config import settings
from app.database.db import DuplicateBirdError, SessionDep, create_bird, get_bird, get_bird_image, get_bird_page
from app.models import BirdCreate, BirdPage, BirdPageQuery, BirdPublic, build_bird_public
from app.observability import setup_observability

app = FastAPI(title="Bird API")
setup_observability(app, settings.log_level)
health_router = APIRouter(prefix="/health", tags=["health"])
birds_router = APIRouter(prefix="/api/v1/birds", tags=["birds"])
IMAGE_CACHE_CONTROL = "public, max-age=86400"


@health_router.get("/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/ready")
def health_ready(session: SessionDep, response: Response) -> dict[str, str]:
    try:
        session.exec(select(1)).one()
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}


@birds_router.get("", response_model=BirdPage)
def get_birds(session: SessionDep, query: Annotated[BirdPageQuery, Query()]) -> BirdPage:
    birds, total = get_bird_page(session, query)
    return BirdPage(items=[build_bird_public(bird) for bird in birds], total=total, offset=query.offset, limit=query.limit)


def found_or_404[T](item: T | None) -> T:
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bird not found")
    return item


def etag_matches(if_none_match: str, etag: str) -> bool:
    tags = [tag.strip().removeprefix("W/") for tag in if_none_match.split(",")]
    return "*" in tags or etag in tags


@birds_router.get("/{bird_id}", response_model=BirdPublic)
def read_bird(bird_id: UUID, session: SessionDep) -> BirdPublic:
    return build_bird_public(found_or_404(get_bird(session, bird_id)))


@birds_router.get(
    "/{bird_id}/image",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"description": "The bird's image", "content": {"image/jpeg": {}, "image/png": {}}},
        status.HTTP_304_NOT_MODIFIED: {"description": "The image matches the If-None-Match ETag"},
    },
)
def read_bird_image(bird_id: UUID, session: SessionDep, if_none_match: Annotated[str, Header()] = "") -> Response:
    image = found_or_404(get_bird_image(session, bird_id))
    headers = {"ETag": f'"{image.sha256}"', "Cache-Control": IMAGE_CACHE_CONTROL}
    if etag_matches(if_none_match, headers["ETag"]):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=image.data, media_type=image.media_type, headers=headers)


@birds_router.post("", response_model=BirdPublic, status_code=status.HTTP_201_CREATED)
def post_bird(bird: BirdCreate, session: SessionDep) -> BirdPublic:
    try:
        return build_bird_public(create_bird(session, bird))
    except DuplicateBirdError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A bird with this binomial_name already exists",
        ) from error


app.include_router(health_router)
app.include_router(birds_router)
