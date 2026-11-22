"""Route tests for the sessions service. The database is faked, spots is a SpotsDirectory."""

import csv
import io
from datetime import date

import pytest

from tests.support.fakes import FakeSessionsDatabase
from tests.support.services import build_app

VALID = {
    "spot_id": 2,
    "date": "2026-11-01",
    "duration_mins": 50,
    "wave_or_wind_rating": 4,
    "gear_used": "5'10 Fish",
    "notes": "Clean and small.",
}


def ids(response):
    return [s["id"] for s in response.get_json()["sessions"]]


# -- boot and health -------------------------------------------------------------

def test_boot_seeds_six_sessions_once(sessions_module, monkeypatch):
    database = FakeSessionsDatabase()
    build_app(sessions_module, database, monkeypatch)
    assert len(database.sessions) == 6
    build_app(sessions_module, database, monkeypatch)
    assert len(database.sessions) == 6, "a second boot must not seed again"


def test_health_reports_ok_when_own_database_answers(client):
    assert client.get("/health").get_json() == {"status": "ok", "db": "ok", "version": "dev"}


def test_health_is_503_when_own_database_is_down(client, database):
    database.down = True
    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json()["status"] == "error"


# -- list, sort, filter ---------------------------------------------------------------

def test_list_is_newest_first_by_default(client, spots):
    response = client.get("/sessions")
    assert response.status_code == 200
    assert ids(response) == [6, 5, 4, 3, 2, 1]
    assert response.get_json()["notice"] is None


@pytest.mark.parametrize(("sort", "expected"), [
    ("oldest", [1, 2, 3, 4, 5, 6]),
    ("duration", [3, 4, 1, 5, 2, 6]),
    ("rating", [3, 1, 6, 4, 5, 2]),
    ("bogus", [6, 5, 4, 3, 2, 1]),
])
def test_list_sorts_by_the_requested_order(client, spots, sort, expected):
    assert ids(client.get(f"/sessions?sort={sort}")) == expected


def test_list_filters_by_spot(client, spots):
    assert ids(client.get("/sessions?spot=3")) == [4, 3]
    assert ids(client.get("/sessions?spot=99")) == []


def test_epic_keeps_sessions_rated_four_or_higher(client, spots):
    assert ids(client.get("/sessions?epic=1")) == [6, 4, 3, 1]


def test_blank_epic_means_no_filter(client, spots):
    assert len(ids(client.get("/sessions?epic="))) == 6


def test_list_carries_spot_names_when_spots_answers(client, spots):
    sessions = client.get("/sessions").get_json()["sessions"]
    by_id = {s["id"]: s for s in sessions}
    assert by_id[6]["spot_name"] == "Mavericks"
    assert by_id[5]["spot_name"] == "Newport Harbor"


def test_list_degrades_with_a_notice_when_spots_is_down(client, spots):
    spots.down = True
    body = client.get("/sessions").get_json()
    assert len(body["sessions"]) == 6, "the list still works"
    assert all(s["spot_name"] is None for s in body["sessions"])
    assert "spot names are unavailable" in body["notice"].lower()


def test_list_is_503_when_database_is_down(client, database):
    database.down = True
    response = client.get("/sessions")
    assert response.status_code == 503
    assert "database unavailable" in response.get_json()["error"]


# -- read one ------------------------------------------------------------------------

def test_read_one_session_has_no_spot_name(client):
    response = client.get("/sessions/3")
    assert response.status_code == 200
    body = response.get_json()
    assert body["spot_id"] == 3 and body["spot_name"] is None
    assert body["date"] == "2026-10-02"


def test_read_unknown_session_is_404(client):
    assert client.get("/sessions/999").status_code == 404


# -- create ------------------------------------------------------------------------------

def test_create_stores_the_session_and_returns_201(client, database, spots):
    response = client.post("/sessions", json=VALID)
    assert response.status_code == 201
    body = response.get_json()
    assert body["id"] == 7
    assert body["spot_name"] == "Mavericks"
    assert body["date"] == "2026-11-01"
    assert len(database.sessions) == 7
    assert database.commits >= 1
    assert "/spots/2" in spots.paths


def test_create_defaults_a_blank_date_to_today(client, spots):
    response = client.post("/sessions", json={**VALID, "date": "  "})
    assert response.status_code == 201
    assert response.get_json()["date"] == date.today().isoformat()


def test_create_refuses_a_spot_the_directory_does_not_know(client, database, spots):
    response = client.post("/sessions", json={**VALID, "spot_id": 99})
    assert response.status_code == 422
    assert response.get_json()["errors"] == {"spot_id": "Unknown spot."}
    assert len(database.sessions) == 6


def test_create_is_503_and_stores_nothing_when_spots_is_down(client, database, spots):
    spots.down = True
    response = client.post("/sessions", json=VALID)
    assert response.status_code == 503
    assert "session not saved" in response.get_json()["error"]
    assert len(database.sessions) == 6


def test_create_validates_before_asking_spots(client, spots):
    response = client.post("/sessions", json={**VALID, "duration_mins": 0, "wave_or_wind_rating": 9})
    assert response.status_code == 422
    errors = response.get_json()["errors"]
    assert set(errors) == {"duration_mins", "wave_or_wind_rating"}
    assert spots.paths == []


def test_create_rejects_future_and_impossible_dates(client, spots):
    future = client.post("/sessions", json={**VALID, "date": "2099-01-01"})
    assert "cannot be in the future" in future.get_json()["errors"]["date"]
    impossible = client.post("/sessions", json={**VALID, "date": "2026-02-30"})
    assert "not a real calendar date" in impossible.get_json()["errors"]["date"]


def test_create_rejects_a_body_that_is_not_an_object(client):
    assert client.post("/sessions", data="[]", content_type="application/json").status_code == 400


def test_create_is_503_when_database_is_down(client, database, spots):
    database.down = True
    assert client.post("/sessions", json=VALID).status_code == 503


# -- update and delete -------------------------------------------------------------------

def test_update_replaces_the_fields(client, database, spots):
    response = client.put("/sessions/1", json={**VALID, "wave_or_wind_rating": 3})
    assert response.status_code == 200
    assert response.get_json()["wave_or_wind_rating"] == 3
    assert response.get_json()["spot_name"] == "Mavericks"
    assert next(r for r in database.sessions if r["id"] == 1)["wave_or_wind_rating"] == 3


def test_update_records_when_the_session_changed(client, database, spots):
    # Migration 002 added updated_at; every edit sets it on the server's clock.
    assert client.put("/sessions/1", json=VALID).status_code == 200
    assert database.updates_stamped == 1


def test_update_checks_existence_before_anything_else(client, spots):
    assert client.put("/sessions/999", json=VALID).status_code == 404
    assert client.put("/sessions/1", data="[]", content_type="application/json").status_code == 400
    assert client.put("/sessions/1", json={**VALID, "spot_id": 99}).status_code == 422


def test_update_is_503_and_changes_nothing_when_spots_is_down(client, database, spots):
    spots.down = True
    response = client.put("/sessions/1", json={**VALID, "wave_or_wind_rating": 1})
    assert response.status_code == 503
    assert next(r for r in database.sessions if r["id"] == 1)["wave_or_wind_rating"] == 5


def test_delete_removes_the_session(client, database):
    assert client.delete("/sessions/1").status_code == 204
    assert all(r["id"] != 1 for r in database.sessions)
    assert client.delete("/sessions/1").status_code == 404


# -- export and stats -----------------------------------------------------------------

def test_csv_export_has_a_header_and_every_row(client, spots):
    response = client.get("/sessions/export.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert response.headers["Content-Disposition"] == 'attachment; filename="swellsync-sessions.csv"'
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert rows[0] == ["date", "spot", "duration_mins", "rating", "gear_used", "notes"]
    assert len(rows) == 7
    assert rows[1][:2] == ["2026-10-06", "Mavericks"]


def test_csv_filename_names_the_filters(client, spots):
    response = client.get("/sessions/export.csv?spot=3&epic=1")
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="swellsync-sessions-spot-3-epic.csv"'
    )


def test_csv_spot_column_is_blank_when_spots_is_down(client, spots):
    spots.down = True
    rows = list(csv.reader(io.StringIO(client.get("/sessions/export.csv").get_data(as_text=True))))
    assert all(row[1] == "" for row in rows[1:])


def test_stats_summarise_all_sessions(client):
    body = client.get("/stats").get_json()
    assert body["stats"] == {
        "session_count": 6,
        "total_duration_mins": 420,
        "average_duration_mins": 70.0,
        "average_rating": 3.83,
    }
    assert body["distribution"] == {"1": 0, "2": 1, "3": 1, "4": 2, "5": 2}


def test_stats_for_one_spot(client):
    body = client.get("/stats?spot=3").get_json()
    assert body["stats"]["session_count"] == 2
    assert body["stats"]["average_rating"] == 4.5
    assert body["distribution"]["5"] == 1


def test_stats_for_a_spot_with_no_sessions_has_no_averages(client):
    body = client.get("/stats?spot=99").get_json()
    assert body["stats"] == {
        "session_count": 0,
        "total_duration_mins": 0,
        "average_duration_mins": None,
        "average_rating": None,
    }


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/sessions"),
    ("get", "/sessions/1"),
    ("get", "/sessions/export.csv"),
    ("get", "/stats"),
    ("delete", "/sessions/1"),
])
def test_every_database_route_is_503_when_the_database_is_down(client, database, method, path):
    database.down = True
    assert getattr(client, method)(path).status_code == 503


# -- routing and CORS --------------------------------------------------------------------

def test_unknown_route_and_wrong_method_return_json(client):
    assert client.get("/nope").get_json() == {"error": "not found"}
    response = client.put("/health")
    assert response.status_code == 405
    assert response.get_json() == {"error": "method not allowed"}


def test_cors_is_granted_only_to_the_allowed_origin(client, sessions_module):
    allowed = client.get("/stats", headers={"Origin": sessions_module.ALLOWED_ORIGIN})
    assert allowed.headers["Access-Control-Allow-Origin"] == sessions_module.ALLOWED_ORIGIN
    other = client.get("/stats", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in other.headers
