"""
SwellSync test suite (test_app.py)
==================================

Two tiers, matching ADR-004:

  1. Pure business logic — domain_logic.py exercised with plain dicts.
     No Flask, no database. This is the tier the assignment's >= 70%
     coverage requirement points at (pytest --cov=domain_logic test_app.py).
  2. SQLite CRUD — exercised end-to-end through the Flask test client
     against a throwaway DATA_DIR, with rows verified straight through
     sqlite3 so the assertions do not depend on rendered HTML.

Run:
    pytest --cov=domain_logic test_app.py
"""

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import sqlite3

import pytest

import domain_logic
from app import DB_FILENAME, connect_db, create_app, load_reference_data


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(tmp_path):
    application = create_app(data_dir=str(tmp_path))
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_path(app):
    return app.config["DB_PATH"]


def fetch_all(path, sql, params=()):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def add_spot(client, name="Pacifica Bluff", location="Pacifica, CA",
             wind="Offshore", swell="4.5"):
    return client.post(
        "/spots",
        data={
            "name": name,
            "location": location,
            "ideal_wind_dir": wind,
            "ideal_swell_ft": swell,
        },
        follow_redirects=False,
    )


def add_session(client, spot_id=1, day=None, duration=90, rating=4,
                gear="9'0 Longboard", notes="Glassy morning"):
    return client.post(
        "/sessions",
        data={
            "spot_id": str(spot_id),
            "date": day if day is not None else date.today().isoformat(),
            "duration_mins": str(duration),
            "wave_or_wind_rating": str(rating),
            "gear_used": gear,
            "notes": notes,
        },
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# domain_logic.calculate_spot_stats
# ---------------------------------------------------------------------------

class TestCalculateSpotStats:
    def test_empty_list_returns_zeroed_stats(self):
        assert domain_logic.calculate_spot_stats([]) == {
            "session_count": 0,
            "total_duration_mins": 0,
            "average_duration_mins": None,
            "average_rating": None,
        }

    def test_single_session(self):
        stats = domain_logic.calculate_spot_stats(
            [{"duration_mins": 60, "wave_or_wind_rating": 5}]
        )
        assert stats["session_count"] == 1
        assert stats["total_duration_mins"] == 60
        assert stats["average_duration_mins"] == 60.0
        assert stats["average_rating"] == 5.0

    def test_multiple_sessions_totals_and_averages(self):
        sessions = [
            {"duration_mins": 60, "wave_or_wind_rating": 5},
            {"duration_mins": 90, "wave_or_wind_rating": 3},
            {"duration_mins": 30, "wave_or_wind_rating": 4},
        ]
        stats = domain_logic.calculate_spot_stats(sessions)
        assert stats["session_count"] == 3
        assert stats["total_duration_mins"] == 180
        assert stats["average_duration_mins"] == 60.0
        assert stats["average_rating"] == 4.0

    def test_unrated_sessions_do_not_poison_the_rating_average(self):
        sessions = [
            {"duration_mins": 60, "wave_or_wind_rating": None},
            {"duration_mins": 45, "wave_or_wind_rating": 4},
        ]
        stats = domain_logic.calculate_spot_stats(sessions)
        assert stats["session_count"] == 2
        assert stats["total_duration_mins"] == 105
        assert stats["average_rating"] == 4.0

    def test_accepts_numeric_strings_and_generators(self):
        sessions = (
            {"duration_mins": "75", "wave_or_wind_rating": "3"} for _ in range(2)
        )
        stats = domain_logic.calculate_spot_stats(sessions)
        assert stats["session_count"] == 2
        assert stats["total_duration_mins"] == 150
        assert stats["average_duration_mins"] == 75.0
        assert stats["average_rating"] == 3.0

    def test_recurring_decimal_is_rounded_to_two_places(self):
        stats = domain_logic.calculate_spot_stats(
            [
                {"duration_mins": 100, "wave_or_wind_rating": 5},
                {"duration_mins": 100, "wave_or_wind_rating": 5},
                {"duration_mins": 100, "wave_or_wind_rating": 4},
            ]
        )
        assert stats["average_rating"] == 4.67


# ---------------------------------------------------------------------------
# domain_logic.filter_ideal_sessions
# ---------------------------------------------------------------------------

class TestFilterIdealSessions:
    def test_keeps_sessions_at_or_above_default_threshold(self):
        sessions = [
            {"wave_or_wind_rating": 5},
            {"wave_or_wind_rating": 4},
            {"wave_or_wind_rating": 3},
        ]
        assert len(domain_logic.filter_ideal_sessions(sessions)) == 2

    def test_boundary_rating_four_is_included(self):
        sessions = [{"wave_or_wind_rating": 4}]
        assert domain_logic.filter_ideal_sessions(sessions) == sessions

    def test_custom_threshold(self):
        sessions = [
            {"wave_or_wind_rating": 4},
            {"wave_or_wind_rating": 5},
        ]
        assert domain_logic.filter_ideal_sessions(sessions, min_rating=5) == [
            {"wave_or_wind_rating": 5}
        ]

    def test_missing_or_invalid_ratings_are_excluded(self):
        sessions = [
            {"wave_or_wind_rating": None},
            {},
            {"wave_or_wind_rating": "4"},
        ]
        assert domain_logic.filter_ideal_sessions(sessions) == [
            {"wave_or_wind_rating": "4"}
        ]

    def test_empty_input(self):
        assert domain_logic.filter_ideal_sessions([]) == []

    def test_input_order_is_preserved(self):
        sessions = [
            {"wave_or_wind_rating": 5, "tag": "first"},
            {"wave_or_wind_rating": 3, "tag": "second"},
            {"wave_or_wind_rating": 4, "tag": "third"},
        ]
        kept = domain_logic.filter_ideal_sessions(sessions)
        assert [s["tag"] for s in kept] == ["first", "third"]


# ---------------------------------------------------------------------------
# domain_logic.validate_session_data
# ---------------------------------------------------------------------------

class TestValidateSessionData:
    def valid_payload(self, **overrides):
        payload = {
            "spot_id": "1",
            "date": "2026-07-04",
            "duration_mins": "90",
            "wave_or_wind_rating": "4",
            "gear_used": "6'2 Shortboard",
            "notes": "Offshore and punchy.",
        }
        payload.update(overrides)
        return payload

    def test_valid_string_payload_passes(self):
        assert domain_logic.validate_session_data(self.valid_payload()) == {}

    def test_valid_int_payload_passes(self):
        payload = self.valid_payload(spot_id=2, duration_mins=45,
                                     wave_or_wind_rating=5)
        assert domain_logic.validate_session_data(payload) == {}

    def test_integral_float_duration_passes(self):
        payload = self.valid_payload(duration_mins=90.0)
        assert domain_logic.validate_session_data(payload) == {}

    def test_date_object_passes(self):
        payload = self.valid_payload(date=date(2026, 7, 4))
        assert domain_logic.validate_session_data(payload) == {}

    def test_missing_or_bad_spot_id(self):
        for bad in ("", None, "abc", "0", "-3", True):
            errors = domain_logic.validate_session_data(
                self.valid_payload(spot_id=bad))
            assert "spot_id" in errors, bad

    def test_duration_must_be_positive(self):
        for bad in ("0", "-30", "ninety", "", 4.5):
            errors = domain_logic.validate_session_data(
                self.valid_payload(duration_mins=bad))
            assert "duration_mins" in errors, bad

    def test_rating_bounds(self):
        for bad in ("0", "6", "", None, "3.5"):
            errors = domain_logic.validate_session_data(
                self.valid_payload(wave_or_wind_rating=bad))
            assert "wave_or_wind_rating" in errors, bad
        assert domain_logic.validate_session_data(
            self.valid_payload(wave_or_wind_rating="1")) == {}
        assert domain_logic.validate_session_data(
            self.valid_payload(wave_or_wind_rating="5")) == {}

    def test_date_must_be_iso_shaped(self):
        for bad in ("", "07/04/2026", "4-7-2026", "2026-7-4", "not-a-date",
                    "20260704"):
            errors = domain_logic.validate_session_data(
                self.valid_payload(date=bad))
            assert "date" in errors, bad

    def test_date_must_be_a_real_calendar_date(self):
        for bad in ("2026-02-30", "2026-13-01", "2023-02-29"):
            errors = domain_logic.validate_session_data(
                self.valid_payload(date=bad))
            assert "date" in errors, bad

    def test_leap_day_is_valid(self):
        assert domain_logic.validate_session_data(
            self.valid_payload(date="2024-02-29")) == {}

    def test_today_is_a_valid_date(self):
        errors = domain_logic.validate_session_data(
            self.valid_payload(date=date.today().isoformat()))
        assert errors == {}

    def test_future_dates_are_rejected(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        for bad in (tomorrow, "2999-12-31"):
            errors = domain_logic.validate_session_data(
                self.valid_payload(date=bad))
            assert "date" in errors, bad

    def test_non_string_date_is_rejected(self):
        errors = domain_logic.validate_session_data(self.valid_payload(date=None))
        assert "date" in errors

    def test_non_string_optional_fields_are_tolerated(self):
        payload = self.valid_payload(gear_used=4113, notes=7)
        assert domain_logic.validate_session_data(payload) == {}

    def test_optional_fields_have_length_caps(self):
        assert "gear_used" in domain_logic.validate_session_data(
            self.valid_payload(gear_used="x" * 121))
        assert "notes" in domain_logic.validate_session_data(
            self.valid_payload(notes="y" * 2001))
        assert domain_logic.validate_session_data(
            self.valid_payload(gear_used="x" * 120, notes="y" * 2000)) == {}


# ---------------------------------------------------------------------------
# domain_logic.validate_spot_data
# ---------------------------------------------------------------------------

class TestValidateSpotData:
    def valid_payload(self, **overrides):
        payload = {
            "name": "Pacifica Bluff",
            "location": "Pacifica, CA",
            "ideal_wind_dir": "Offshore",
            "ideal_swell_ft": "4.5",
        }
        payload.update(overrides)
        return payload

    def test_valid_string_payload_passes(self):
        assert domain_logic.validate_spot_data(self.valid_payload()) == {}

    def test_valid_numeric_swell_passes(self):
        payload = self.valid_payload(ideal_swell_ft=6.2)
        assert domain_logic.validate_spot_data(payload) == {}

    def test_blank_optional_fields_are_fine(self):
        payload = self.valid_payload(ideal_wind_dir="", ideal_swell_ft="")
        assert domain_logic.validate_spot_data(payload) == {}

    def test_name_and_location_required(self):
        errors = domain_logic.validate_spot_data(
            self.valid_payload(name="   ", location=""))
        assert set(errors) == {"name", "location"}

    def test_spot_field_length_caps(self):
        errors = domain_logic.validate_spot_data(
            self.valid_payload(
                name="x" * 101, location="y" * 151, ideal_wind_dir="z" * 61
            )
        )
        assert set(errors) == {"name", "location", "ideal_wind_dir"}

    def test_boolean_swell_is_rejected(self):
        assert "ideal_swell_ft" in domain_logic.validate_spot_data(
            self.valid_payload(ideal_swell_ft=True))

    def test_swell_must_be_a_non_negative_number(self):
        assert "ideal_swell_ft" in domain_logic.validate_spot_data(
            self.valid_payload(ideal_swell_ft="huge"))
        assert "ideal_swell_ft" in domain_logic.validate_spot_data(
            self.valid_payload(ideal_swell_ft="-1"))
        assert domain_logic.validate_spot_data(
            self.valid_payload(ideal_swell_ft="6")) == {}


# ---------------------------------------------------------------------------
# domain_logic.rating_distribution
# ---------------------------------------------------------------------------

class TestRatingDistribution:
    def test_empty_input_returns_all_zero_counts(self):
        assert domain_logic.rating_distribution([]) == {
            1: 0, 2: 0, 3: 0, 4: 0, 5: 0
        }

    def test_counts_each_rating(self):
        sessions = [{"wave_or_wind_rating": r} for r in (5, 5, 4, 1)]
        assert domain_logic.rating_distribution(sessions) == {
            1: 1, 2: 0, 3: 0, 4: 1, 5: 2
        }

    def test_missing_or_unusable_ratings_are_ignored(self):
        sessions = [
            {"wave_or_wind_rating": None},
            {},
            {"wave_or_wind_rating": "3"},
        ]
        assert domain_logic.rating_distribution(sessions) == {
            1: 0, 2: 0, 3: 1, 4: 0, 5: 0
        }

    def test_out_of_range_ratings_are_ignored(self):
        assert domain_logic.rating_distribution(
            [{"wave_or_wind_rating": 9}]) == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}


# ---------------------------------------------------------------------------
# SQLite schema & engine-level guarantees
# ---------------------------------------------------------------------------

class TestDatabaseBootstrap:
    def test_database_file_created_inside_data_dir(self, app, db_path, tmp_path):
        assert Path(db_path) == (tmp_path / DB_FILENAME).resolve()
        assert Path(db_path).exists()

    def test_data_dir_env_variable_is_respected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        application = create_app()
        assert Path(application.config["DB_PATH"]) == (tmp_path / DB_FILENAME).resolve()
        assert (tmp_path / DB_FILENAME).exists()

    def test_schema_creates_both_tables(self, db_path):
        tables = {
            row["name"]
            for row in fetch_all(
                db_path, "SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"spots", "sessions"} <= tables

    def test_foreign_keys_enforced_at_engine_level(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            with closing(connect_db(Path(db_path))) as conn:
                conn.execute(
                    "INSERT INTO sessions (spot_id, date, duration_mins)"
                    " VALUES (999, '2026-07-04', 60)"
                )

    def test_rating_check_constraint(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("INSERT INTO spots (name, location) VALUES ('X', 'Y')")
                conn.execute(
                    "INSERT INTO sessions (spot_id, date, duration_mins,"
                    " wave_or_wind_rating) VALUES (1, '2026-07-04', 60, 9)"
                )


# ---------------------------------------------------------------------------
# Domain 1 CRUD — Spot Directory (through the Flask test client)
# ---------------------------------------------------------------------------

class TestSpotCrud:
    def test_create_spot_persists_row(self, client, db_path):
        response = add_spot(client, name="Ocean Beach",
                            location="San Francisco, CA", wind="NW", swell="6.0")
        assert response.status_code == 302
        rows = fetch_all(db_path, "SELECT * FROM spots")
        assert len(rows) == 1
        row = rows[0]
        assert row["name"] == "Ocean Beach"
        assert row["location"] == "San Francisco, CA"
        assert row["ideal_wind_dir"] == "NW"
        assert row["ideal_swell_ft"] == 6.0
        assert row["created_at"] is not None

    def test_create_spot_missing_name_rejected(self, client, db_path):
        response = client.post("/spots", data={"name": "", "location": "Somewhere"})
        assert response.status_code == 422
        assert fetch_all(db_path, "SELECT * FROM spots") == []

    def test_spot_list_renders(self, client):
        add_spot(client)
        response = client.get("/spots")
        assert response.status_code == 200
        assert b"Pacifica Bluff" in response.data

    def test_read_spot_detail(self, client):
        add_spot(client)
        response = client.get("/spots/1")
        assert response.status_code == 200
        assert b"Pacifica Bluff" in response.data

    def test_missing_spot_404(self, client):
        assert client.get("/spots/999").status_code == 404

    def test_update_spot(self, client, db_path):
        add_spot(client)
        response = client.post(
            "/spots/1/edit",
            data={
                "name": "Pacifica Bluff (South)",
                "location": "Pacifica, CA",
                "ideal_wind_dir": "SW",
                "ideal_swell_ft": "3.2",
            },
        )
        assert response.status_code == 302
        row = fetch_all(db_path, "SELECT * FROM spots")[0]
        assert row["name"] == "Pacifica Bluff (South)"
        assert row["ideal_wind_dir"] == "SW"
        assert row["ideal_swell_ft"] == 3.2

    def test_update_spot_invalid_data_rejected(self, client, db_path):
        add_spot(client)
        response = client.post(
            "/spots/1/edit",
            data={"name": "", "location": "Pacifica, CA"},
        )
        assert response.status_code == 422
        assert fetch_all(db_path, "SELECT name FROM spots")[0]["name"] == "Pacifica Bluff"

    def test_delete_spot_without_sessions(self, client, db_path):
        add_spot(client)
        assert client.post("/spots/1/delete").status_code == 302
        assert fetch_all(db_path, "SELECT * FROM spots") == []

    def test_delete_spot_with_sessions_is_blocked_by_fk(self, client, db_path):
        add_spot(client)
        add_session(client, spot_id=1)
        response = client.post("/spots/1/delete", follow_redirects=True)
        assert response.status_code == 200
        assert b"still has" in response.data
        assert len(fetch_all(db_path, "SELECT * FROM spots")) == 1


# ---------------------------------------------------------------------------
# Spot Directory search (?q= on /spots)
# ---------------------------------------------------------------------------

class TestSpotSearch:
    @staticmethod
    def table(html):
        """Just the <tbody> of the results table.

        Asserting on the whole page is unreliable: a flash banner left over
        from the preceding POST names the spot we expect to be filtered out,
        and the add-spot form's placeholders name real beaches.
        """
        return html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]

    def test_no_query_lists_every_spot(self, client):
        add_spot(client, name="Alpha Point", location="North Coast")
        add_spot(client, name="Beta Point", location="South Coast")
        rows = self.table(client.get("/spots").get_data(as_text=True))
        assert "Alpha Point" in rows
        assert "Beta Point" in rows

    def test_search_matches_name_case_insensitively(self, client):
        add_spot(client, name="Hookipa", location="Maui, HI")
        add_spot(client, name="Trestles", location="Laguna Beach, CA")
        rows = self.table(client.get("/spots?q=HOOK").get_data(as_text=True))
        assert "Hookipa" in rows
        assert "Trestles" not in rows

    def test_search_matches_location_not_just_name(self, client):
        add_spot(client, name="Hookipa", location="Maui, HI")
        add_spot(client, name="Trestles", location="Laguna Beach, CA")
        rows = self.table(client.get("/spots?q=laguna").get_data(as_text=True))
        assert "Trestles" in rows
        assert "Hookipa" not in rows

    def test_search_treats_percent_as_a_literal(self, client):
        # '%' and '_' are LIKE wildcards: they must be escaped, or a query of
        # "%" would match every row.
        add_spot(client, name="Fifty Percent Reef", location="Has a 50% rule")
        add_spot(client, name="Glass Cliff", location="No symbols here")
        rows = self.table(client.get("/spots?q=%25").get_data(as_text=True))  # "%"
        assert "Fifty Percent Reef" in rows
        assert "Glass Cliff" not in rows

    def test_underscore_is_literal_too(self, client):
        add_spot(client, name="North_Slab", location="Cold country")
        add_spot(client, name="North Slab Two", location="Warm country")
        rows = self.table(client.get("/spots?q=_").get_data(as_text=True))
        assert "North_Slab" in rows
        assert "North Slab Two" not in rows

    def test_query_echoed_and_no_match_state(self, client):
        add_spot(client, name="Hookipa", location="Maui, HI")
        response = client.get("/spots?q=noway")
        text = response.get_data(as_text=True)
        assert "No spot matches" in self.table(text)
        assert "Hookipa" not in self.table(text)
        assert 'value="noway"' in text  # the box keeps what you typed


# ---------------------------------------------------------------------------
# Domain 2 CRUD — Session Tracker (through the Flask test client)
# ---------------------------------------------------------------------------

class TestSessionCrud:
    def test_create_session_persists_row(self, client, db_path):
        add_spot(client)
        response = add_session(client, spot_id=1, duration=75, rating=5)
        assert response.status_code == 302
        rows = fetch_all(db_path, "SELECT * FROM sessions")
        assert len(rows) == 1
        row = rows[0]
        assert row["spot_id"] == 1
        assert row["date"] == date.today().isoformat()
        assert row["duration_mins"] == 75
        assert row["wave_or_wind_rating"] == 5
        assert row["gear_used"] == "9'0 Longboard"
        assert row["notes"] == "Glassy morning"
        assert row["created_at"] is not None

    def test_blank_date_defaults_to_today(self, client, db_path):
        add_spot(client)
        client.post(
            "/sessions",
            data={
                "spot_id": "1",
                "date": "",
                "duration_mins": "60",
                "wave_or_wind_rating": "3",
            },
        )
        rows = fetch_all(db_path, "SELECT date FROM sessions")
        assert rows[0]["date"] == date.today().isoformat()

    def test_invalid_session_rejected(self, client, db_path):
        add_spot(client)
        response = client.post(
            "/sessions",
            data={
                "spot_id": "1",
                "date": "2026-07-04",
                "duration_mins": "0",
                "wave_or_wind_rating": "9",
            },
        )
        assert response.status_code == 422
        assert fetch_all(db_path, "SELECT * FROM sessions") == []

    def test_session_for_missing_spot_rejected_via_fk(self, client, db_path):
        response = add_session(client, spot_id=999)
        assert response.status_code == 422
        assert fetch_all(db_path, "SELECT * FROM sessions") == []

    def test_future_dated_session_rejected_at_route_level(self, client, db_path):
        add_spot(client)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        response = client.post(
            "/sessions",
            data={
                "spot_id": "1",
                "date": tomorrow,
                "duration_mins": "60",
                "wave_or_wind_rating": "3",
            },
        )
        assert response.status_code == 422
        assert fetch_all(db_path, "SELECT * FROM sessions") == []

    def test_update_session(self, client, db_path):
        add_spot(client)
        add_session(client, spot_id=1, duration=60, rating=2)
        response = client.post(
            "/sessions/1/edit",
            data={
                "spot_id": "1",
                "date": date.today().isoformat(),
                "duration_mins": "120",
                "wave_or_wind_rating": "5",
                "gear_used": "Laser",
                "notes": "Nuclear breeze.",
            },
        )
        assert response.status_code == 302
        row = fetch_all(db_path, "SELECT * FROM sessions")[0]
        assert row["duration_mins"] == 120
        assert row["wave_or_wind_rating"] == 5
        assert row["gear_used"] == "Laser"

    def test_delete_session(self, client, db_path):
        add_spot(client)
        add_session(client, spot_id=1)
        assert client.post("/sessions/1/delete").status_code == 302
        assert fetch_all(db_path, "SELECT * FROM sessions") == []

    def test_sessions_page_lists_entries_with_spot_name(self, client):
        add_spot(client)
        add_session(client, spot_id=1, rating=4)
        response = client.get("/sessions")
        assert response.status_code == 200
        assert b"Pacifica Bluff" in response.data
        assert date.today().isoformat().encode() in response.data


# ---------------------------------------------------------------------------
# Composition views (dashboard / spot detail) + error pages
# ---------------------------------------------------------------------------

class TestViewsAndStats:
    def test_dashboard_empty_state(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"Water time, logged." in response.data

    def test_dashboard_shows_cross_domain_stats(self, client):
        add_spot(client, name="Hookipa", location="Maui, HI")
        add_session(client, spot_id=1, duration=120, rating=5)
        add_session(client, spot_id=1, duration=60, rating=3)
        response = client.get("/")
        assert response.status_code == 200
        assert b"Hookipa" in response.data
        assert b"3.0h" in response.data  # (120 + 60) minutes of water time

    def test_spot_detail_renders_domain_logic_stats(self, client):
        add_spot(client, name="Hookipa", location="Maui, HI")
        add_session(client, spot_id=1, duration=60, rating=5)
        add_session(client, spot_id=1, duration=90, rating=3)
        response = client.get("/spots/1")
        assert response.status_code == 200
        assert b"4.0" in response.data     # average rating (5 + 3) / 2
        assert b"2h 30m" in response.data  # total water time
        assert b"1h 15m" in response.data  # average duration
        assert "★".encode() in response.data

    def test_spot_detail_ideal_sessions_section(self, client):
        add_spot(client)
        add_session(client, spot_id=1, rating=2, notes="mushy")
        add_session(client, spot_id=1, rating=5, notes="all-time")
        response = client.get("/spots/1")
        assert b"all-time" in response.data
        assert b"mushy" in response.data  # all sessions table shows both

    def test_spot_detail_shows_rating_distribution(self, client):
        add_spot(client)
        add_session(client, spot_id=1, rating=5)
        add_session(client, spot_id=1, rating=3)
        response = client.get("/spots/1")
        assert response.status_code == 200
        assert b"dist-fill" in response.data

    def test_unknown_route_returns_custom_404(self, client):
        response = client.get("/no/such/page")
        assert response.status_code == 404
        assert b"drifted" in response.data


# ---------------------------------------------------------------------------
# Reference-data seeding (§7.11): loads on empty, never re-seeds
# ---------------------------------------------------------------------------

class TestReferenceSeeding:
    def test_seed_does_not_run_by_default(self, app, db_path):
        # The test fixture builds the app without seed=True, so a fresh
        # database stays empty — that is what keeps the CRUD tests isolated.
        assert fetch_all(db_path, "SELECT * FROM spots") == []

    def test_seed_populates_directory_on_empty_db(self, tmp_path):
        data_dir = tmp_path / "seeded"
        create_app(data_dir=str(data_dir), seed=True)
        db_file = str(data_dir / DB_FILENAME)
        spots = fetch_all(db_file, "SELECT * FROM spots")
        assert len(spots) > 0
        assert all(s["name"] and s["location"] for s in spots)
        sessions = fetch_all(db_file, "SELECT * FROM sessions")
        assert len(sessions) > 0
        # Seeded sessions reference real seeded spots (the FK is enforced).
        spot_ids = {s["id"] for s in spots}
        assert all(sess["spot_id"] in spot_ids for sess in sessions)

    def test_seed_is_idempotent_across_restarts(self, tmp_path):
        data_dir = tmp_path / "twice"
        db_file = str(data_dir / DB_FILENAME)
        create_app(data_dir=str(data_dir), seed=True)
        first_spots = fetch_all(db_file, "SELECT id, name FROM spots ORDER BY id")
        first_sessions = fetch_all(db_file, "SELECT * FROM sessions")

        # Second boot on the same volume: the count guard must skip re-seed.
        create_app(data_dir=str(data_dir), seed=True)
        assert fetch_all(db_file, "SELECT id, name FROM spots ORDER BY id") == first_spots
        assert len(fetch_all(db_file, "SELECT * FROM sessions")) == len(first_sessions)

    def test_load_reference_data_reports_zero_when_populated(self, tmp_path):
        create_app(data_dir=str(tmp_path))  # creates the schema, no seed
        db_file = tmp_path / DB_FILENAME
        assert load_reference_data(db_file) > 0
        assert load_reference_data(db_file) == 0

    def test_missing_seed_file_is_a_no_op(self, tmp_path):
        count = load_reference_data(
            tmp_path / "x.db", seed_file=Path("/nonexistent/seed.json"))
        assert count == 0


# ---------------------------------------------------------------------------
# Epic-only session filter (sessions page query param)
# ---------------------------------------------------------------------------

class TestEpicSessionFilter:
    def test_epic_only_hides_low_rated_sessions(self, client):
        add_spot(client)
        add_session(client, spot_id=1, rating=2, notes="mushy")
        add_session(client, spot_id=1, rating=5, notes="all-time")
        response = client.get("/sessions?epic=1")
        assert response.status_code == 200
        assert b"all-time" in response.data
        assert b"mushy" not in response.data

    def test_epic_filter_combines_with_spot_filter(self, client):
        add_spot(client, name="Spot One", location="A")
        add_spot(client, name="Spot Two", location="B")
        add_session(client, spot_id=1, rating=5, notes="one epic")
        add_session(client, spot_id=1, rating=2, notes="one mush")
        add_session(client, spot_id=2, rating=5, notes="two epic")
        response = client.get("/sessions?epic=1&spot=1")
        assert response.status_code == 200
        assert b"one epic" in response.data
        assert b"one mush" not in response.data
        assert b"two epic" not in response.data


# ---------------------------------------------------------------------------
# Infrastructure: /healthz deployment liveness probe
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_healthz_reports_ok(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.is_json
        data = response.get_json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"

    def test_healthz_counts_entities(self, client):
        add_spot(client)
        add_session(client, spot_id=1)
        data = client.get("/healthz").get_json()
        assert data["spots"] == 1
        assert data["sessions"] == 1


# ---------------------------------------------------------------------------
# CSV export of the session log (Domain 2 read across the seam)
# ---------------------------------------------------------------------------

class TestCsvExport:
    def test_export_headers_and_empty_body(self, client):
        response = client.get("/sessions/export.csv")
        assert response.status_code == 200
        assert response.mimetype == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        assert "swellsync-sessions.csv" in response.headers["Content-Disposition"]
        text = response.get_data(as_text=True)
        assert text.splitlines() == ["date,spot,duration_mins,rating,gear_used,notes"]

    def test_export_rows_in_newest_first_order(self, client):
        add_spot(client, name="Cove")
        add_session(client, spot_id=1, day="2026-01-01", duration=60, rating=3,
                    gear="Longboard", notes="old")
        add_session(client, spot_id=1, day="2026-02-02", duration=90, rating=5,
                    gear="Shortboard", notes="new")
        lines = client.get("/sessions/export.csv").get_data(as_text=True).splitlines()
        assert lines[0] == "date,spot,duration_mins,rating,gear_used,notes"
        assert lines[1].startswith("2026-02-02")   # newest first
        assert lines[2].startswith("2026-01-01")
        assert "Cove" in lines[1]

    def test_export_respects_spot_and_epic_filters(self, client):
        add_spot(client, name="Spot One")
        add_spot(client, name="Spot Two")
        add_session(client, spot_id=1, rating=5, notes="one epic")
        add_session(client, spot_id=1, rating=2, notes="one mush")
        add_session(client, spot_id=2, rating=5, notes="two epic")

        spot_only = client.get("/sessions/export.csv?spot=1")
        assert "spot-1" in spot_only.headers["Content-Disposition"]
        text = spot_only.get_data(as_text=True)
        assert "one epic" in text      # both spot-1 rows present...
        assert "one mush" in text      # ...rating is NOT filtered here
        assert "two epic" not in text  # spot 2 excluded by the spot filter

        epic_all = client.get("/sessions/export.csv?epic=1")
        assert "epic" in epic_all.headers["Content-Disposition"]
        epic_text = epic_all.get_data(as_text=True)
        assert "one epic" in epic_text
        assert "two epic" in epic_text
        assert "one mush" not in epic_text  # rating 2 dropped by epic filter

        both = client.get("/sessions/export.csv?spot=1&epic=1")
        both_text = both.get_data(as_text=True)
        assert "one epic" in both_text      # spot 1 AND rating >= 4
        assert "one mush" not in both_text  # fails epic
        assert "two epic" not in both_text  # fails spot

    def test_export_quotes_commas_in_notes(self, client):
        add_spot(client)
        add_session(client, spot_id=1, notes="Offshore, punchy, crowded")
        row = client.get("/sessions/export.csv").get_data(as_text=True).splitlines()[1]
        assert '"Offshore, punchy, crowded"' in row  # proper CSV quoting


# ---------------------------------------------------------------------------
# Infrastructure: security headers
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_hardening_headers_on_html_pages(self, client):
        response = client.get("/")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "camera=()" in response.headers["Permissions-Policy"]

    def test_headers_on_error_page_too(self, client):
        response = client.get("/no/such/page")
        assert response.status_code == 404
        assert response.headers["X-Content-Type-Options"] == "nosniff"
