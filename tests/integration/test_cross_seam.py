"""Cross-seam tests: the real spots and sessions apps, talking over real HTTP.

Each app runs its real code and makes real urllib calls. Only the databases
are faked. The other service is a StubService server: scripted for the
failure cases, and forwarding into the other real app for the round trip.
"""

import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.support.fakes import FakeSessionsDatabase, FakeSpotsDatabase, StubService, unused_url
from tests.support.services import build_app, load_service

TIMEOUT_S = 0.3
SPOT_NAMES = {1: "Ocean Beach North", 2: "Mavericks", 3: "Ho'okipa", 4: "Newport Harbor"}
SESSION = {
    "spot_id": 2,
    "date": "2026-11-01",
    "duration_mins": 50,
    "wave_or_wind_rating": 4,
    "gear_used": "5'10 Fish",
    "notes": "Clean.",
}


def scripted_spots(method, path):
    """What the spots service answers for the sessions service's calls."""
    if path == "/spots":
        return 200, {"spots": [{"id": i, "name": n} for i, n in SPOT_NAMES.items()]}
    spot_id = int(path.rsplit("/", 1)[1])
    if spot_id in SPOT_NAMES:
        return 200, {"id": spot_id, "name": SPOT_NAMES[spot_id]}
    return 404, None


def forward(client, method, path):
    """Answer an HTTP call by running it through another real app's test client."""
    response = client.open(path, method=method)
    return response.status_code, response.get_json(silent=True)


@pytest.fixture(scope="module")
def modules():
    return (
        load_service("spots", FakeSpotsDatabase()),
        load_service("sessions", FakeSessionsDatabase()),
    )


@pytest.fixture
def apps(modules, monkeypatch):
    spots_mod, sessions_mod = modules
    spots_stub, sessions_stub = StubService(), StubService()
    spots_stub.responder = scripted_spots
    try:
        monkeypatch.setattr(sessions_mod, "SPOTS_URL", spots_stub.url)
        monkeypatch.setattr(sessions_mod, "SPOTS_TIMEOUT_S", TIMEOUT_S)
        monkeypatch.setattr(spots_mod, "SESSIONS_URL", sessions_stub.url)
        monkeypatch.setattr(spots_mod, "SESSIONS_TIMEOUT_S", TIMEOUT_S)

        spots_db, sessions_db = FakeSpotsDatabase(), FakeSessionsDatabase()
        spots = build_app(spots_mod, spots_db, monkeypatch).test_client()
        sessions = build_app(sessions_mod, sessions_db, monkeypatch).test_client()
        yield SimpleNamespace(
            spots=spots, sessions=sessions, spots_db=spots_db, sessions_db=sessions_db,
            spots_stub=spots_stub, sessions_stub=sessions_stub,
            spots_mod=spots_mod, sessions_mod=sessions_mod,
        )
    finally:
        spots_stub.close()
        sessions_stub.close()


# -- sessions reading and writing against spots -----------------------------------

def test_list_takes_spot_names_from_the_spots_service(apps):
    body = apps.sessions.get("/sessions").get_json()
    assert body["notice"] is None
    names = {s["spot_id"]: s["spot_name"] for s in body["sessions"]}
    assert names[1] == "Ocean Beach North"
    assert ("GET", "/spots") in apps.spots_stub.calls


def test_list_degrades_with_a_notice_when_spots_is_unreachable(apps, monkeypatch):
    monkeypatch.setattr(apps.sessions_mod, "SPOTS_URL", unused_url())
    body = apps.sessions.get("/sessions").get_json()
    assert len(body["sessions"]) == 6
    assert all(s["spot_name"] is None for s in body["sessions"])
    assert body["notice"]


def test_list_gives_up_on_a_slow_spots_within_the_timeout(apps):
    apps.spots_stub.delay = 2.0
    started = time.monotonic()
    response = apps.sessions.get("/sessions")
    elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert response.get_json()["notice"]
    assert elapsed < 1.5, f"the call should stop at the {TIMEOUT_S}s timeout, took {elapsed:.2f}s"


def test_create_checks_the_spot_over_http_before_storing(apps):
    response = apps.sessions.post("/sessions", json=SESSION)
    assert response.status_code == 201
    assert response.get_json()["spot_name"] == "Mavericks"
    assert ("GET", "/spots/2") in apps.spots_stub.calls
    assert len(apps.sessions_db.sessions) == 7


def test_create_refuses_a_spot_the_spots_service_does_not_know(apps):
    response = apps.sessions.post("/sessions", json={**SESSION, "spot_id": 99})
    assert response.status_code == 422
    assert len(apps.sessions_db.sessions) == 6


def test_create_is_503_and_stores_nothing_when_spots_is_unreachable(apps, monkeypatch):
    monkeypatch.setattr(apps.sessions_mod, "SPOTS_URL", unused_url())
    response = apps.sessions.post("/sessions", json=SESSION)
    assert response.status_code == 503
    assert len(apps.sessions_db.sessions) == 6


def test_update_is_503_within_the_timeout_when_spots_is_slow(apps):
    apps.spots_stub.delay = 2.0
    started = time.monotonic()
    response = apps.sessions.put("/sessions/1", json={**SESSION, "wave_or_wind_rating": 1})
    elapsed = time.monotonic() - started
    assert response.status_code == 503
    assert elapsed < 1.5
    assert next(r for r in apps.sessions_db.sessions if r["id"] == 1)["wave_or_wind_rating"] == 5


# -- spots deleting against sessions ------------------------------------------------

def test_spot_delete_is_409_when_sessions_still_reference_it(apps):
    apps.sessions_stub.responder = lambda method, path: (200, {"sessions": [{"id": 1}]})
    assert apps.spots.delete("/spots/2").status_code == 409
    assert any(s["id"] == 2 for s in apps.spots_db.spots)
    assert ("GET", "/sessions?spot=2") in apps.sessions_stub.calls


def test_spot_delete_succeeds_when_sessions_has_none(apps):
    apps.sessions_stub.responder = lambda method, path: (200, {"sessions": []})
    assert apps.spots.delete("/spots/2").status_code == 204
    assert all(s["id"] != 2 for s in apps.spots_db.spots)


def test_spot_delete_is_503_when_sessions_is_unreachable(apps, monkeypatch):
    monkeypatch.setattr(apps.spots_mod, "SESSIONS_URL", unused_url())
    assert apps.spots.delete("/spots/2").status_code == 503
    assert any(s["id"] == 2 for s in apps.spots_db.spots)


def test_spot_delete_is_503_within_the_timeout_when_sessions_is_slow(apps):
    apps.sessions_stub.delay = 2.0
    started = time.monotonic()
    response = apps.spots.delete("/spots/2")
    elapsed = time.monotonic() - started
    assert response.status_code == 503
    assert elapsed < 1.5
    assert any(s["id"] == 2 for s in apps.spots_db.spots)


# -- the round trip: both real apps, each calling the other ----------------------------

def test_a_spot_can_only_be_deleted_once_its_sessions_are_gone(apps):
    apps.spots_stub.responder = lambda method, path: forward(apps.spots, method, path)

    def sessions_answer(method, path):
        return forward(apps.sessions, method, path)

    apps.sessions_stub.responder = sessions_answer

    created = apps.sessions.post("/sessions", json={**SESSION, "spot_id": 4})
    assert created.status_code == 201
    session_id = created.get_json()["id"]

    assert apps.spots.delete("/spots/4").status_code == 409

    # Spot 4 also has a seeded session, so clear every session at it first.
    at_spot = apps.sessions.get("/sessions?spot=4").get_json()["sessions"]
    assert session_id in {s["id"] for s in at_spot}
    for session in at_spot:
        assert apps.sessions.delete(f"/sessions/{session['id']}").status_code == 204

    assert apps.spots.delete("/spots/4").status_code == 204
    assert all(s["id"] != 4 for s in apps.spots_db.spots)

    query = parse_qs(urlsplit(apps.sessions_stub.calls[-1][1]).query)
    assert query == {"spot": ["4"]}
