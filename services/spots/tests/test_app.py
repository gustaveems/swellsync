"""Route tests for the spots service, with the database faked and sessions stubbed."""

import pytest

from tests.support.fakes import FakeSpotsDatabase, StubService
from tests.support.services import build_app

VALID_SPOT = {
    "name": "Thurso East",
    "location": "Caithness, Scotland",
    "ideal_wind_dir": "S offshore",
    "ideal_swell_ft": 6.5,
}


@pytest.fixture
def sessions_stub(spots_module, monkeypatch):
    stub = StubService()
    monkeypatch.setattr(spots_module, "SESSIONS_URL", stub.url)
    yield stub
    stub.close()


def names(response):
    return [spot["name"] for spot in response.get_json()["spots"]]


# -- boot ---------------------------------------------------------------------

def test_boot_seeds_an_empty_database_once(spots_module, monkeypatch):
    database = FakeSpotsDatabase()
    build_app(spots_module, database, monkeypatch)
    assert len(database.spots) == 4

    build_app(spots_module, database, monkeypatch)
    assert len(database.spots) == 4, "a second boot must not seed again"


# -- health -------------------------------------------------------------------

def test_health_reports_ok_when_own_database_answers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "db": "ok", "version": "dev"}


def test_health_is_503_when_own_database_is_down(client, database):
    database.down = True
    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json()["db"] == "unreachable"


# -- list and search ----------------------------------------------------------

def test_list_returns_all_spots_ordered_by_name(client):
    response = client.get("/spots")
    assert response.status_code == 200
    assert names(response) == sorted(names(response))
    assert len(names(response)) == 4


def test_search_matches_name_or_location_ignoring_case(client):
    assert names(client.get("/spots?q=maverick")) == ["Mavericks"]
    assert names(client.get("/spots?q=MAUI")) == ["Ho'okipa"]


def test_search_treats_percent_and_underscore_literally(client):
    assert names(client.get("/spots?q=%25")) == []
    assert names(client.get("/spots?q=_")) == []


def test_list_is_503_when_database_is_down(client, database):
    database.down = True
    response = client.get("/spots")
    assert response.status_code == 503
    assert "database unavailable" in response.get_json()["error"]


# -- create -------------------------------------------------------------------

def test_create_stores_the_spot_and_returns_201(client, database):
    response = client.post("/spots", json=VALID_SPOT)
    assert response.status_code == 201
    body = response.get_json()
    assert body["id"] == 5
    assert body["name"] == "Thurso East"
    assert body["ideal_swell_ft"] == 6.5
    assert len(database.spots) == 5
    assert database.commits >= 1


def test_create_accepts_blank_optional_fields_as_null(client):
    response = client.post("/spots", json={**VALID_SPOT, "ideal_wind_dir": " ", "ideal_swell_ft": ""})
    assert response.status_code == 201
    assert response.get_json()["ideal_wind_dir"] is None
    assert response.get_json()["ideal_swell_ft"] is None


def test_create_rejects_a_body_that_is_not_an_object(client):
    assert client.post("/spots", data="[1, 2]", content_type="application/json").status_code == 400
    assert client.post("/spots").status_code == 400


def test_create_reports_each_invalid_field_with_422(client, database):
    response = client.post("/spots", json={"name": "", "location": "", "ideal_swell_ft": -1})
    assert response.status_code == 422
    errors = response.get_json()["errors"]
    assert set(errors) == {"name", "location", "ideal_swell_ft"}
    assert len(database.spots) == 4


def test_create_is_503_when_database_is_down(client, database):
    database.down = True
    response = client.post("/spots", json=VALID_SPOT)
    assert response.status_code == 503
    assert len(database.spots) == 4


# -- read and update ----------------------------------------------------------

def test_read_one_spot(client):
    response = client.get("/spots/1")
    assert response.status_code == 200
    assert response.get_json()["id"] == 1


def test_read_unknown_spot_is_404(client):
    response = client.get("/spots/999")
    assert response.status_code == 404
    assert response.get_json() == {"error": "spot not found"}


def test_update_replaces_the_fields(client, database):
    response = client.put("/spots/1", json={**VALID_SPOT, "name": "Ocean Beach South"})
    assert response.status_code == 200
    assert response.get_json()["name"] == "Ocean Beach South"
    assert next(s for s in database.spots if s["id"] == 1)["name"] == "Ocean Beach South"


def test_update_checks_existence_before_validation(client):
    assert client.put("/spots/999", json=VALID_SPOT).status_code == 404
    assert client.put("/spots/1", json={"name": ""}).status_code == 422
    assert client.put("/spots/1", data="7", content_type="application/json").status_code == 400


# -- delete and the seam ------------------------------------------------------

def test_delete_without_sessions_removes_the_spot(client, database, sessions_stub):
    sessions_stub.responder = lambda method, path: (200, {"sessions": []})
    assert client.delete("/spots/2").status_code == 204
    assert all(s["id"] != 2 for s in database.spots)
    assert ("GET", "/sessions?spot=2") in sessions_stub.calls


def test_delete_with_sessions_is_409_and_keeps_the_spot(client, database, sessions_stub):
    sessions_stub.responder = lambda method, path: (200, {"sessions": [{"id": 1}]})
    assert client.delete("/spots/2").status_code == 409
    assert any(s["id"] == 2 for s in database.spots)


def test_delete_is_503_when_sessions_is_unreachable(client, database):
    response = client.delete("/spots/2")
    assert response.status_code == 503
    assert "sessions service unavailable" in response.get_json()["error"]
    assert any(s["id"] == 2 for s in database.spots)


def test_delete_is_503_when_sessions_answers_with_an_error(client, database, sessions_stub):
    sessions_stub.responder = lambda method, path: (500, {"error": "boom"})
    assert client.delete("/spots/2").status_code == 503
    assert any(s["id"] == 2 for s in database.spots)


def test_delete_unknown_spot_is_404_without_calling_sessions(client, sessions_stub):
    assert client.delete("/spots/999").status_code == 404
    assert sessions_stub.calls == []


# -- routing, CORS -------------------------------------------------------------

def test_unknown_route_and_wrong_method_return_json(client):
    assert client.get("/nope").get_json() == {"error": "not found"}
    response = client.put("/health")
    assert response.status_code == 405
    assert response.get_json() == {"error": "method not allowed"}


def test_cors_is_granted_only_to_the_allowed_origin(client, spots_module):
    allowed = client.get("/spots", headers={"Origin": spots_module.ALLOWED_ORIGIN})
    assert allowed.headers["Access-Control-Allow-Origin"] == spots_module.ALLOWED_ORIGIN
    other = client.get("/spots", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in other.headers
