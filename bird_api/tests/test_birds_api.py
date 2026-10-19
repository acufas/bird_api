import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from app.models import Bird, build_bird_public
from tests.factories import (
    CARDINAL_ID,
    CONSERVATION_STATUSES,
    GIF_IMAGE,
    IMAGE,
    MEDIA_TYPES,
    PNG_IMAGE,
    TEXT_FIELDS,
    add_bird,
    bird_payload,
    encode,
    sha256,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ATTRIBUTION_FIELDS = ["image_alt_text", "image_credit", "image_license", "image_source_url"]
PUBLIC_IMAGE_FIELDS = ["image_url", "image_media_type", "image_size", *ATTRIBUTION_FIELDS]
IMAGE_DATA_COLUMN = re.compile(r"\.data\b")


@pytest.fixture
def sql_statements(session):
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    yield statements
    event.remove(engine, "before_cursor_execute", record)


def statements_for_request(client, session, sql_statements, path):
    session.expunge_all()
    sql_statements.clear()
    response = client.get(path)
    assert response.status_code == 200
    return list(sql_statements)


def listed(response, field):
    return [bird[field] for bird in response.json()["items"]]


def bird_image_count(session):
    return session.connection().exec_driver_sql("SELECT COUNT(*) FROM bird_images").scalar()


def expected_public_image_fields(bird_id):
    return {
        "image_url": f"/api/v1/birds/{bird_id}/image",
        "image_media_type": "image/jpeg",
        "image_size": len(IMAGE),
        **{field: bird_payload()[field] for field in ATTRIBUTION_FIELDS},
    }


def errors_for(response, field):
    return [error for error in response.json()["detail"] if error["loc"] == ["body", field]]


def error_types(response, field):
    return [error["type"] for error in errors_for(response, field)]


def body_error_messages(response):
    return [error["msg"] for error in response.json()["detail"] if error["loc"] == ["body"]]


def test_list_birds_returns_birds_with_image_url_instead_of_image(client, session):
    add_bird(session, bird_id=CARDINAL_ID)

    response = client.get("/api/v1/birds")

    assert response.status_code == 200
    [bird] = response.json()["items"]
    assert bird["id"] == str(CARDINAL_ID)
    assert bird["class"] == "Aves"
    assert "image" not in bird
    assert "image_sha256" not in bird
    assert {field: bird[field] for field in PUBLIC_IMAGE_FIELDS} == expected_public_image_fields(CARDINAL_ID)


def test_list_birds_returns_empty_page_when_no_birds(client):
    response = client.get("/api/v1/birds")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 100}


def test_list_birds_returns_page_envelope(client, session):
    add_bird(session, bird_id=CARDINAL_ID)

    response = client.get("/api/v1/birds", params={"offset": 0, "limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "offset", "limit"}
    assert [bird["id"] for bird in body["items"]] == [str(CARDINAL_ID)]
    assert (body["total"], body["offset"], body["limit"]) == (1, 0, 10)


def test_list_birds_orders_by_common_name(client, session):
    add_bird(session, common_name="Northern cardinal")
    add_bird(session, common_name="American robin", binomial_name="Turdus migratorius")

    response = client.get("/api/v1/birds")

    assert listed(response, "common_name") == ["American robin", "Northern cardinal"]


def test_list_birds_paginates_with_offset_and_limit(client, session):
    for name in ["Alpha", "Bravo", "Charlie"]:
        add_bird(session, common_name=name, binomial_name=f"{name} species")

    response = client.get("/api/v1/birds", params={"offset": 1, "limit": 1})

    assert response.status_code == 200
    assert listed(response, "common_name") == ["Bravo"]
    assert (response.json()["total"], response.json()["offset"], response.json()["limit"]) == (3, 1, 1)


def test_list_birds_total_ignores_offset_and_limit(client, session):
    for name in ["Alpha", "Bravo", "Charlie"]:
        add_bird(session, common_name=name, binomial_name=f"{name} species")

    for params in [{}, {"offset": 2}, {"limit": 1}, {"offset": 5, "limit": 2}]:
        assert client.get("/api/v1/birds", params=params).json()["total"] == 3


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_birds_rejects_invalid_pagination(client, params):
    response = client.get("/api/v1/birds", params=params)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("parameter", "field", "match", "other"),
    [
        ("conservation_status", "conservation_status", "Endangered", "Least Concern"),
        ("kingdom", "kingdom", "Animalia", "Plantae"),
        ("phylum", "phylum", "Chordata", "Arthropoda"),
        ("class", "class", "Aves", "Reptilia"),
        ("order", "order", "Passeriformes", "Strigiformes"),
        ("family", "family", "Cardinalidae", "Turdidae"),
        ("genus", "genus", "Cardinalis", "Turdus"),
    ],
)
def test_list_birds_filters_by_exact_value(client, session, parameter, field, match, other):
    add_bird(session, bird_id=CARDINAL_ID, **{field: match})
    add_bird(session, binomial_name="Turdus migratorius", **{field: other})

    response = client.get("/api/v1/birds", params={parameter: match})

    assert response.status_code == 200
    assert listed(response, "id") == [str(CARDINAL_ID)]
    assert response.json()["total"] == 1


@pytest.mark.parametrize(
    ("parameter", "value"),
    [("kingdom", "animalia"), ("class", "AVES"), ("order", "Passeri"), ("family", "Cardinalidae "), ("genus", "cardinalis")],
)
def test_list_birds_filters_are_exact_and_case_sensitive(client, session, parameter, value):
    add_bird(session)

    response = client.get("/api/v1/birds", params={parameter: value})

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 100}


def test_list_birds_combines_filters_with_and(client, session):
    add_bird(session, bird_id=CARDINAL_ID, family="Alpha", genus="Xenus")
    add_bird(session, binomial_name="Two species", family="Alpha", genus="Yenus")
    add_bird(session, binomial_name="Three species", family="Bravo", genus="Xenus")

    response = client.get("/api/v1/birds", params={"family": "Alpha", "genus": "Xenus"})

    assert listed(response, "id") == [str(CARDINAL_ID)]
    assert response.json()["total"] == 1


def test_list_birds_total_counts_filtered_birds_independent_of_offset_and_limit(client, session):
    for name in ["Alpha", "Bravo", "Charlie"]:
        add_bird(session, common_name=name, binomial_name=f"{name} species", family="Alpha")
    add_bird(session, common_name="Delta", binomial_name="Delta species", family="Bravo")

    response = client.get("/api/v1/birds", params={"family": "Alpha", "offset": 1, "limit": 1})

    assert response.json()["total"] == 3
    assert listed(response, "common_name") == ["Bravo"]


@pytest.mark.parametrize("conservation_status", ["least concern", "LEAST_CONCERN", "LC", "Mostly Harmless", ""])
def test_list_birds_rejects_unknown_conservation_status_filter(client, conservation_status):
    response = client.get("/api/v1/birds", params={"conservation_status": conservation_status})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert (error["loc"], error["type"]) == (["query", "conservation_status"], "enum")


SORT_VALUES = {
    "common_name": ["Alpha", "Bravo", "Charlie"],
    "binomial_name": ["Aa aa", "Bb bb", "Cc cc"],
    "conservation_status": ["Endangered", "Least Concern", "Vulnerable"],
    "family": ["Alpha", "Bravo", "Charlie"],
    "genus": ["Alpha", "Bravo", "Charlie"],
}


def add_birds_for_sort(session, field):
    common_names = ["Name B", "Name C", "Name A"]
    for index in [1, 2, 0]:
        overrides = {"common_name": common_names[index], "binomial_name": f"Binomial {index}"}
        add_bird(session, **{**overrides, field: SORT_VALUES[field][index]})


@pytest.mark.parametrize("field", SORT_VALUES)
def test_list_birds_sorts_ascending_by_field(client, session, field):
    add_birds_for_sort(session, field)

    response = client.get("/api/v1/birds", params={"sort": field})

    assert response.status_code == 200
    assert listed(response, field) == SORT_VALUES[field]


@pytest.mark.parametrize("field", SORT_VALUES)
def test_list_birds_sorts_descending_by_field(client, session, field):
    add_birds_for_sort(session, field)

    response = client.get("/api/v1/birds", params={"sort": f"-{field}"})

    assert response.status_code == 200
    assert listed(response, field) == SORT_VALUES[field][::-1]


def test_list_birds_sorts_by_common_name_by_default(client, session):
    add_birds_for_sort(session, "family")

    response = client.get("/api/v1/birds")

    assert listed(response, "common_name") == ["Name A", "Name B", "Name C"]


@pytest.mark.parametrize("sort", ["common_name", "-common_name", "family", "-family"])
def test_list_birds_breaks_sort_ties_by_ascending_id(client, session, sort):
    ids = [UUID(int=value) for value in [3, 1, 2]]
    for index, bird_id in enumerate(ids):
        add_bird(session, bird_id=bird_id, binomial_name=f"Binomial {index}")

    response = client.get("/api/v1/birds", params={"sort": sort})

    assert listed(response, "id") == [str(bird_id) for bird_id in sorted(ids)]


@pytest.mark.parametrize("sort", ["species", "id", "image_size", "+common_name", "--common_name", "common_name,genus", ""])
def test_list_birds_rejects_unknown_sort(client, sort):
    response = client.get("/api/v1/birds", params={"sort": sort})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert (error["loc"], error["type"]) == (["query", "sort"], "enum")


def list_parameters(client):
    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/api/v1/birds"]["get"]["parameters"]
    return schema, {parameter["name"]: parameter for parameter in parameters}


def resolve_enum(schema, parameter_schema):
    options = parameter_schema.get("anyOf", [parameter_schema])
    [reference] = [option["$ref"] for option in options if "$ref" in option]
    return schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]["enum"]


def test_openapi_documents_list_filter_and_sort_parameters(client):
    schema, parameters = list_parameters(client)

    assert set(parameters) == {
        "offset",
        "limit",
        "sort",
        "conservation_status",
        "kingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
    }
    assert all(parameter["in"] == "query" and not parameter.get("required") for parameter in parameters.values())
    assert resolve_enum(schema, parameters["conservation_status"]["schema"]) == CONSERVATION_STATUSES
    assert resolve_enum(schema, parameters["sort"]["schema"]) == [prefix + field for field in SORT_VALUES for prefix in ["", "-"]]
    assert parameters["sort"]["schema"]["default"] == "common_name"


def test_openapi_documents_bird_page_schema(client):
    bird_page = client.get("/openapi.json").json()["components"]["schemas"]["BirdPage"]

    assert bird_page["properties"]["items"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/BirdPublic"},
        "title": "Items",
    }
    assert {field: bird_page["properties"][field]["type"] for field in ["total", "offset", "limit"]} == {
        "total": "integer",
        "offset": "integer",
        "limit": "integer",
    }
    assert set(bird_page["required"]) == {"items", "total", "offset", "limit"}


def test_get_bird_returns_bird(client, session):
    add_bird(session, bird_id=CARDINAL_ID)

    response = client.get(f"/api/v1/birds/{CARDINAL_ID}")

    assert response.status_code == 200
    assert response.json()["common_name"] == "Northern cardinal"


def test_get_bird_returns_image_url_and_metadata_without_image(client, session):
    add_bird(session, bird_id=CARDINAL_ID)

    bird = client.get(f"/api/v1/birds/{CARDINAL_ID}").json()

    assert "image" not in bird
    assert "image_sha256" not in bird
    assert {field: bird[field] for field in PUBLIC_IMAGE_FIELDS} == expected_public_image_fields(CARDINAL_ID)


@pytest.mark.parametrize("image", [IMAGE, PNG_IMAGE])
def test_get_bird_image_returns_image_bytes_with_media_type_and_cache_headers(client, session, image):
    add_bird(session, bird_id=CARDINAL_ID, image=image)

    response = client.get(f"/api/v1/birds/{CARDINAL_ID}/image")

    assert response.status_code == 200
    assert response.content == image
    assert response.headers["Content-Type"] == MEDIA_TYPES[image]
    assert response.headers["ETag"] == f'"{sha256(image)}"'
    assert response.headers["Cache-Control"] == "public, max-age=86400"


def test_get_bird_image_returns_304_when_if_none_match_matches_etag(client, session):
    add_bird(session, bird_id=CARDINAL_ID)
    etag = f'"{sha256(IMAGE)}"'

    response = client.get(f"/api/v1/birds/{CARDINAL_ID}/image", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["ETag"] == etag


@pytest.mark.parametrize("if_none_match", ['W/"{sha}"', '"other", "{sha}"', "*"])
def test_get_bird_image_returns_304_for_weak_listed_and_wildcard_if_none_match(client, session, if_none_match):
    add_bird(session, bird_id=CARDINAL_ID)

    response = client.get(
        f"/api/v1/birds/{CARDINAL_ID}/image", headers={"If-None-Match": if_none_match.format(sha=sha256(IMAGE))}
    )

    assert response.status_code == 304


@pytest.mark.parametrize("if_none_match", ['"other"', sha256(IMAGE), ""])
def test_get_bird_image_returns_200_when_if_none_match_does_not_match(client, session, if_none_match):
    add_bird(session, bird_id=CARDINAL_ID)

    response = client.get(f"/api/v1/birds/{CARDINAL_ID}/image", headers={"If-None-Match": if_none_match})

    assert response.status_code == 200
    assert response.content == IMAGE


def test_get_bird_image_returns_404_for_unknown_id(client):
    response = client.get(f"/api/v1/birds/{uuid4()}/image")

    assert response.status_code == 404
    assert response.json() == {"detail": "Bird not found"}


def test_get_bird_image_rejects_invalid_uuid(client):
    response = client.get("/api/v1/birds/not-a-uuid/image")

    assert response.status_code == 422


def test_openapi_documents_bird_image_media_types(client):
    responses = client.get("/openapi.json").json()["paths"]["/api/v1/birds/{bird_id}/image"]["get"]["responses"]

    assert set(responses["200"]["content"]) == {"image/jpeg", "image/png"}
    assert "304" in responses


@pytest.mark.parametrize("path", ["/api/v1/birds", f"/api/v1/birds/{CARDINAL_ID}"])
def test_bird_json_routes_read_image_metadata_without_image_data(client, session, sql_statements, path):
    add_bird(session, bird_id=CARDINAL_ID)

    statements = statements_for_request(client, session, sql_statements, path)

    assert any("bird_images" in statement for statement in statements)
    assert [statement for statement in statements if IMAGE_DATA_COLUMN.search(statement)] == []


def test_bird_image_route_reads_image_data(client, session, sql_statements):
    add_bird(session, bird_id=CARDINAL_ID)

    statements = statements_for_request(client, session, sql_statements, f"/api/v1/birds/{CARDINAL_ID}/image")

    assert any(IMAGE_DATA_COLUMN.search(statement) for statement in statements)


LIST_PATHS = ["/api/v1/birds", "/api/v1/birds?family=Cardinalidae&genus=Cardinalis&sort=-genus&offset=0&limit=5"]


@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_birds_uses_one_items_statement_and_one_count_statement_regardless_of_row_count(
    client, session, sql_statements, path
):
    add_bird(session, common_name="Alpha", binomial_name="Alpha species")
    one_bird = statements_for_request(client, session, sql_statements, path)
    for name in ["Bravo", "Charlie", "Delta", "Echo"]:
        add_bird(session, common_name=name, binomial_name=f"{name} species")

    five_birds = statements_for_request(client, session, sql_statements, path)

    assert len(client.get(path).json()["items"]) == 5
    for statements in [one_bird, five_birds]:
        counts = [statement for statement in statements if "count(" in statement.lower()]
        assert (len(statements), len(counts)) == (2, 1)


@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_birds_items_and_count_statements_join_bird_images_without_image_data(client, session, sql_statements, path):
    add_bird(session, bird_id=CARDINAL_ID)

    statements = statements_for_request(client, session, sql_statements, path)

    assert len(statements) == 2
    assert all("JOIN bird_images" in statement for statement in statements)
    assert [statement for statement in statements if IMAGE_DATA_COLUMN.search(statement)] == []


def test_list_birds_excludes_bird_without_image_row(client, session):
    add_bird(session, bird_id=CARDINAL_ID)
    add_bird(session, image=None, binomial_name="Turdus migratorius")

    response = client.get("/api/v1/birds")

    assert listed(response, "id") == [str(CARDINAL_ID)]
    assert response.json()["total"] == 1


def test_list_birds_total_excludes_filtered_bird_without_image_row(client, session):
    add_bird(session, bird_id=CARDINAL_ID)
    add_bird(session, image=None, binomial_name="Turdus migratorius")

    response = client.get("/api/v1/birds", params={"family": "Cardinalidae"})

    assert listed(response, "id") == [str(CARDINAL_ID)]
    assert response.json()["total"] == 1


@pytest.mark.parametrize("path", [f"/api/v1/birds/{CARDINAL_ID}", f"/api/v1/birds/{CARDINAL_ID}/image"])
def test_bird_without_image_row_returns_404(client, session, path):
    add_bird(session, bird_id=CARDINAL_ID, image=None)

    response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Bird not found"}


def test_get_bird_returns_404_for_unknown_id(client):
    response = client.get(f"/api/v1/birds/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Bird not found"}


def test_get_bird_rejects_invalid_uuid(client):
    response = client.get("/api/v1/birds/not-a-uuid")

    assert response.status_code == 422


def test_create_bird_returns_201_and_persists_bird(client, session):
    response = client.post("/api/v1/birds", json=bird_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["class"] == "Aves"
    assert "image" not in body
    assert "image_sha256" not in body
    assert body["image_url"] == f"/api/v1/birds/{body['id']}/image"
    stored = session.get(Bird, UUID(body["id"]))
    assert stored is not None
    assert stored.image.data == IMAGE


@pytest.mark.parametrize("image", [IMAGE, PNG_IMAGE])
def test_create_bird_computes_image_metadata_and_ignores_client_values(client, session, image):
    payload = bird_payload(image=encode(image), image_media_type="image/gif", image_sha256="0" * 64, image_size=1)

    response = client.post("/api/v1/birds", json=payload)

    assert response.status_code == 201
    assert response.json()["image_media_type"] == MEDIA_TYPES[image]
    assert response.json()["image_size"] == len(image)
    stored = session.get(Bird, UUID(response.json()["id"])).image
    assert (stored.media_type, stored.sha256, stored.size) == (MEDIA_TYPES[image], sha256(image), len(image))


def test_create_bird_returns_and_stores_image_attribution(client, session):
    response = client.post("/api/v1/birds", json=bird_payload())

    assert response.status_code == 201
    expected = {field: bird_payload()[field] for field in ATTRIBUTION_FIELDS}
    assert {field: response.json()[field] for field in ATTRIBUTION_FIELDS} == expected
    stored = session.get(Bird, UUID(response.json()["id"])).image
    assert [stored.alt_text, stored.credit, stored.license, stored.source_url] == list(expected.values())


def test_created_bird_image_is_served_by_image_url(client):
    image_url = client.post("/api/v1/birds", json=bird_payload(image=encode(PNG_IMAGE))).json()["image_url"]

    response = client.get(image_url)

    assert response.status_code == 200
    assert response.content == PNG_IMAGE
    assert response.headers["Content-Type"] == "image/png"


@pytest.mark.parametrize(
    "image_source_url",
    [
        "ftp://example.com/cardinal.jpg",
        "javascript:alert(1)",
        "example.com/cardinal.jpg",
        "not a url",
        "/relative/cardinal.jpg",
        "",
    ],
)
def test_create_bird_rejects_image_source_url_that_is_not_http_or_https(client, image_source_url):
    response = client.post("/api/v1/birds", json=bird_payload(image_source_url=image_source_url))

    assert response.status_code == 422
    assert errors_for(response, "image_source_url")


@pytest.mark.parametrize("image_source_url", ["http://example.com/cardinal.jpg", "https://example.com/cardinal.jpg"])
def test_create_bird_accepts_http_and_https_image_source_url(client, image_source_url):
    response = client.post("/api/v1/birds", json=bird_payload(image_source_url=image_source_url))

    assert response.status_code == 201
    assert response.json()["image_source_url"] == image_source_url


def test_create_bird_strips_whitespace_from_image_source_url(client):
    response = client.post("/api/v1/birds", json=bird_payload(image_source_url=" \thttps://example.com/cardinal.jpg\n "))

    assert response.status_code == 201
    assert response.json()["image_source_url"] == "https://example.com/cardinal.jpg"


def test_create_bird_accepts_2000_character_image_source_url(client):
    url = "https://example.com/" + "a" * 1980

    response = client.post("/api/v1/birds", json=bird_payload(image_source_url=url))

    assert response.status_code == 201
    assert response.json()["image_source_url"] == url


def test_create_bird_rejects_image_source_url_longer_than_2000_characters(client):
    response = client.post("/api/v1/birds", json=bird_payload(image_source_url="https://example.com/" + "a" * 1981))

    assert response.status_code == 422
    assert errors_for(response, "image_source_url")


def test_create_bird_generates_id_and_ignores_client_id(client):
    response = client.post("/api/v1/birds", json=bird_payload(id=str(CARDINAL_ID)))

    assert response.status_code == 201
    assert response.json()["id"] != str(CARDINAL_ID)


def test_create_bird_returns_409_for_duplicate_binomial_name(client, session):
    add_bird(session)

    response = client.post("/api/v1/birds", json=bird_payload(common_name="Another cardinal"))

    assert response.status_code == 409
    assert response.json() == {"detail": "A bird with this binomial_name already exists"}
    assert bird_image_count(session) == 1


def test_create_bird_inserts_one_image_row(client, session):
    bird_id = client.post("/api/v1/birds", json=bird_payload()).json()["id"]

    rows = session.connection().exec_driver_sql("SELECT bird_id, data FROM bird_images").all()
    assert rows == [(UUID(bird_id).hex, IMAGE)]


def test_create_bird_succeeds_after_duplicate_conflict(client, session):
    assert client.post("/api/v1/birds", json=bird_payload()).status_code == 201
    assert client.post("/api/v1/birds", json=bird_payload()).status_code == 409
    assert bird_image_count(session) == 1

    response = client.post(
        "/api/v1/birds",
        json=bird_payload(binomial_name="Turdus migratorius", genus="Turdus", species="migratorius"),
    )

    assert response.status_code == 201
    names = listed(client.get("/api/v1/birds"), "binomial_name")
    assert sorted(names) == ["Cardinalis cardinalis", "Turdus migratorius"]


@pytest.mark.parametrize("field", bird_payload().keys())
def test_create_bird_rejects_missing_field(client, field):
    payload = {key: value for key, value in bird_payload().items() if key != field}

    response = client.post("/api/v1/birds", json=payload)

    assert response.status_code == 422


def test_create_bird_rejects_invalid_base64_image(client):
    response = client.post("/api/v1/birds", json=bird_payload(image="not base64!"))

    assert response.status_code == 422


@pytest.mark.parametrize("conservation_status", CONSERVATION_STATUSES)
def test_create_bird_accepts_each_conservation_status(client, session, conservation_status):
    response = client.post("/api/v1/birds", json=bird_payload(conservation_status=conservation_status))

    assert response.status_code == 201
    assert response.json()["conservation_status"] == conservation_status
    stored = session.connection().exec_driver_sql("SELECT conservation_status FROM birds").scalars().all()
    assert stored == [conservation_status]


@pytest.mark.parametrize("conservation_status", ["Mostly Harmless", "least concern", "LEAST_CONCERN", "LC", ""])
def test_create_bird_rejects_unknown_conservation_status(client, conservation_status):
    response = client.post("/api/v1/birds", json=bird_payload(conservation_status=conservation_status))

    assert response.status_code == 422
    assert error_types(response, "conservation_status") == ["enum"]


@pytest.mark.parametrize("model", ["BirdCreate", "BirdPublic"])
def test_openapi_lists_conservation_statuses(client, model):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    reference = schemas[model]["properties"]["conservation_status"]["$ref"]

    assert schemas[reference.rsplit("/", 1)[-1]]["enum"] == CONSERVATION_STATUSES


@pytest.mark.parametrize("field", TEXT_FIELDS)
@pytest.mark.parametrize(
    ("value", "error_type"), [("", "string_too_short"), (" \t\n ", "string_too_short"), ("a" * 201, "string_too_long")]
)
def test_create_bird_rejects_empty_and_oversized_text(client, field, value, error_type):
    response = client.post("/api/v1/birds", json=bird_payload(**{field: value}))

    assert response.status_code == 422
    assert error_type in error_types(response, field)


@pytest.mark.parametrize(
    "field", ["common_name", "kingdom", "phylum", "class", "order", "family", "image_alt_text", "image_credit", "image_license"]
)
def test_create_bird_accepts_200_character_text(client, field):
    response = client.post("/api/v1/birds", json=bird_payload(**{field: "a" * 200}))

    assert response.status_code == 201
    assert response.json()[field] == "a" * 200


def test_create_bird_accepts_200_character_taxonomy_names(client):
    genus = "C" + "a" * 99
    species = "b" * 99
    payload = bird_payload(genus=genus, species=species, binomial_name=f"{genus} {species}")

    response = client.post("/api/v1/birds", json=payload)

    assert response.status_code == 201
    assert len(response.json()["binomial_name"]) == 200


def test_create_bird_strips_surrounding_whitespace_from_text(client, session):
    payload = bird_payload(**{field: f" \t{value}\n " for field, value in bird_payload().items() if field in TEXT_FIELDS})

    response = client.post("/api/v1/birds", json=payload)

    assert response.status_code == 201
    expected = {field: value for field, value in bird_payload().items() if field in TEXT_FIELDS}
    assert {field: response.json()[field] for field in TEXT_FIELDS} == expected
    stored = build_bird_public(session.get(Bird, UUID(response.json()["id"]))).model_dump(by_alias=True)
    assert {field: stored[field] for field in TEXT_FIELDS} == expected


@pytest.mark.parametrize(
    "binomial_name",
    ["Cardinalis sinuatus", "Pyrrhuloxia cardinalis", "Cardinalis  cardinalis", "Cardinaliscardinalis", "cardinalis cardinalis"],
)
def test_create_bird_rejects_binomial_name_that_does_not_match_genus_and_species(client, binomial_name):
    response = client.post("/api/v1/birds", json=bird_payload(binomial_name=binomial_name))

    assert response.status_code == 422
    [message] = body_error_messages(response)
    assert "binomial_name" in message
    assert "'Cardinalis cardinalis'" in message


@pytest.mark.parametrize("genus", ["cardinalis", "CARDINALIS", "CardinaLis", "Cardinalis2", "Cardi-nalis", "C"])
def test_create_bird_rejects_badly_cased_genus(client, genus):
    response = client.post("/api/v1/birds", json=bird_payload(genus=genus, binomial_name=f"{genus} cardinalis"))

    assert response.status_code == 422
    assert error_types(response, "genus") == ["string_pattern_mismatch"]


@pytest.mark.parametrize(
    "species", ["Cardinalis", "carDinalis", "cardinalis2", "-cardinalis", "cardinalis-", "novae--hollandiae", "novae hollandiae"]
)
def test_create_bird_rejects_badly_formed_species(client, species):
    response = client.post("/api/v1/birds", json=bird_payload(species=species, binomial_name=f"Cardinalis {species}"))

    assert response.status_code == 422
    assert error_types(response, "species") == ["string_pattern_mismatch"]


def test_create_bird_accepts_hyphenated_species(client):
    payload = bird_payload(genus="Dromaius", species="novae-hollandiae", binomial_name="Dromaius novae-hollandiae")

    response = client.post("/api/v1/birds", json=payload)

    assert response.status_code == 201
    assert response.json()["binomial_name"] == "Dromaius novae-hollandiae"


@pytest.mark.parametrize("image", [IMAGE, PNG_IMAGE])
def test_create_bird_accepts_jpeg_and_png_images(client, session, image):
    response = client.post("/api/v1/birds", json=bird_payload(image=encode(image)))

    assert response.status_code == 201
    assert session.get(Bird, UUID(response.json()["id"])).image.data == image


@pytest.mark.parametrize("image", [GIF_IMAGE, b"", b"\xff\xd8", b"\x89PNG", b"not an image", b"\x00" + IMAGE])
def test_create_bird_rejects_images_that_are_not_jpeg_or_png(client, image):
    response = client.post("/api/v1/birds", json=bird_payload(image=encode(image)))

    assert response.status_code == 422
    [error] = errors_for(response, "image")
    assert "JPEG or PNG" in error["msg"]


def test_create_bird_accepts_image_of_exactly_5_mib(client, session):
    image = IMAGE.ljust(MAX_IMAGE_BYTES, b"\x00")

    response = client.post("/api/v1/birds", json=bird_payload(image=encode(image)))

    assert response.status_code == 201
    assert len(session.get(Bird, UUID(response.json()["id"])).image.data) == MAX_IMAGE_BYTES


def test_create_bird_rejects_image_larger_than_5_mib(client):
    image = IMAGE.ljust(MAX_IMAGE_BYTES + 1, b"\x00")

    response = client.post("/api/v1/birds", json=bird_payload(image=encode(image)))

    assert response.status_code == 422
    [error] = errors_for(response, "image")
    assert "5 MiB" in error["msg"]


def test_bird_routes_respond_with_bird_public_schema(client):
    schema = client.get("/openapi.json").json()
    bird_public = {"$ref": "#/components/schemas/BirdPublic"}

    def response_schema(path, method, status):
        return schema["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]

    assert response_schema("/api/v1/birds", "get", "200") == {"$ref": "#/components/schemas/BirdPage"}
    assert response_schema("/api/v1/birds/{bird_id}", "get", "200") == bird_public
    assert response_schema("/api/v1/birds", "post", "201") == bird_public
    assert "Bird" not in schema["components"]["schemas"]


def test_bird_public_schema_has_image_url_and_metadata_but_no_image(client):
    bird_public = client.get("/openapi.json").json()["components"]["schemas"]["BirdPublic"]

    assert "image" not in bird_public["properties"]
    assert "image_sha256" not in bird_public["properties"]
    assert set(PUBLIC_IMAGE_FIELDS) <= set(bird_public["required"])


def test_unversioned_birds_route_is_removed(client):
    response = client.get("/birds")

    assert response.status_code == 404
