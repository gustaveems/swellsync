"""Spot Directory service (domain 1). Owns the `spots` table in its own database.

Endpoints:
    GET    /health            own database only; 200 ok / 503 otherwise
    GET    /spots?q=          list (search name or location)
    POST   /spots             create
    GET    /spots/<id>        read one
    PUT    /spots/<id>        update
    DELETE /spots/<id>        delete; 409 if sessions still reference it

The only outbound call is DELETE's check against the sessions service (the
seam's other side), bounded by SESSIONS_TIMEOUT_S. Nothing here reads `sessions`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pymssql
from flask import Flask, g, jsonify, request

import db as dbmod
import domain_logic

SEED_FILE = Path(__file__).with_name("seed.json")
VERSION = os.environ.get("APP_VERSION", "dev")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:8080")
SESSIONS_URL = os.environ.get("SESSIONS_URL", "http://sessions:8000")
SESSIONS_TIMEOUT_S = float(os.environ.get("SESSIONS_TIMEOUT_S", "2"))

logging.basicConfig(
    stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("spots")


class UpstreamUnavailable(Exception):
    """The sessions service did not answer within its timeout."""


def _like_pattern(term: str) -> str:
    escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"


def _spot_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "location": row["location"],
        "ideal_wind_dir": row["ideal_wind_dir"],
        "ideal_swell_ft": row["ideal_swell_ft"],
    }


def _spot_values(data: dict) -> tuple:
    swell = data.get("ideal_swell_ft")
    swell_value = None
    if not (swell is None or (isinstance(swell, str) and not swell.strip())):
        swell_value = domain_logic._to_float(swell)
    return (
        domain_logic._text_or_empty(data.get("name")),
        domain_logic._text_or_empty(data.get("location")),
        domain_logic._text_or_empty(data.get("ideal_wind_dir")) or None,
        swell_value,
    )


def _sessions_count_for_spot(spot_id: int) -> int:
    """Ask the sessions service how many sessions reference this spot."""
    url = f"{SESSIONS_URL}/sessions?{urllib.parse.urlencode({'spot': spot_id})}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=SESSIONS_TIMEOUT_S) as resp:
            body = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise UpstreamUnavailable(f"sessions answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpstreamUnavailable(str(exc)) from exc
    return len(body.get("sessions", []))


def create_app() -> Flask:
    app = Flask(__name__)
    database_url = os.environ["DATABASE_URL"]

    # -- database ----------------------------------------------------------

    def get_db():
        if "db" not in g:
            g.db = dbmod.connect(database_url)
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    # Boot: apply pending migrations, then seed once if the table is empty.
    boot = dbmod.connect(database_url)
    try:
        dbmod.migrate(boot)
        cur = boot.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM spots")
        if cur.fetchone()["c"] == 0 and SEED_FILE.exists():
            for spot in json.loads(SEED_FILE.read_text(encoding="utf-8"))["spots"]:
                cur.execute(
                    "INSERT INTO spots (name, location, ideal_wind_dir, ideal_swell_ft)"
                    " VALUES (%s, %s, %s, %s)",
                    (spot["name"], spot["location"], spot.get("ideal_wind_dir"),
                     spot.get("ideal_swell_ft")),
                )
            boot.commit()
            log.info("seeded %d spots", len(json.loads(SEED_FILE.read_text())["spots"]))
    finally:
        boot.close()

    # -- logging and CORS ----------------------------------------------------

    @app.before_request
    def _start_timer():
        g.started = time.perf_counter()

    @app.after_request
    def _log_and_cors(response):
        started = g.get("started")
        duration_ms = (time.perf_counter() - started) * 1000 if started else 0.0
        log.info("%s %s %s %.1fms", request.method, request.path, response.status_code, duration_ms)
        if request.headers.get("Origin") == ALLOWED_ORIGIN:
            response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Vary"] = "Origin"
        return response

    # -- errors ---------------------------------------------------------------

    def error(status: int, message: str, **extra):
        return jsonify({"error": message, **extra}), status

    @app.errorhandler(pymssql.Error)
    def database_error(exc):
        log.error("database error: %s", exc)
        return error(503, "database unavailable, try again shortly")

    @app.errorhandler(404)
    def not_found(_exc):
        return error(404, "not found")

    @app.errorhandler(405)
    def wrong_method(_exc):
        return error(405, "method not allowed")

    # -- health -----------------------------------------------------------------

    @app.get("/health")
    def health():
        try:
            conn = dbmod.connect(database_url, attempts=1)
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
            finally:
                conn.close()
            body, status = {"status": "ok", "db": "ok", "version": VERSION}, 200
        except Exception as exc:  # any failure to use our own database is a 503
            log.warning("health check failed: %s", exc)
            body, status = {"status": "error", "db": "unreachable", "version": VERSION}, 503
        return jsonify(body), status

    # -- spots ----------------------------------------------------------------

    @app.get("/spots")
    def list_spots():
        db = get_db()
        query = request.args.get("q", "").strip()
        cur = db.cursor()
        if query:
            pattern = _like_pattern(query)
            cur.execute(
                "SELECT * FROM spots WHERE (name LIKE %s ESCAPE '!' OR location LIKE %s ESCAPE '!')"
                " ORDER BY name",
                (pattern, pattern),
            )
        else:
            cur.execute("SELECT * FROM spots ORDER BY name")
        return jsonify({"spots": [_spot_out(r) for r in cur.fetchall()]})

    @app.post("/spots")
    def create_spot():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error(400, "expected a JSON object")
        errors = domain_logic.validate_spot_data(data)
        if errors:
            return error(422, "invalid spot", errors=errors)
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO spots (name, location, ideal_wind_dir, ideal_swell_ft)"
            " OUTPUT INSERTED.* VALUES (%s, %s, %s, %s)",
            _spot_values(data),
        )
        row = cur.fetchone()
        db.commit()
        return jsonify(_spot_out(row)), 201

    @app.get("/spots/<int:spot_id>")
    def read_spot(spot_id: int):
        cur = get_db().cursor()
        cur.execute("SELECT * FROM spots WHERE id = %s", (spot_id,))
        row = cur.fetchone()
        if row is None:
            return error(404, "spot not found")
        return jsonify(_spot_out(row))

    @app.put("/spots/<int:spot_id>")
    def update_spot(spot_id: int):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error(400, "expected a JSON object")
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id FROM spots WHERE id = %s", (spot_id,))
        if cur.fetchone() is None:
            return error(404, "spot not found")
        errors = domain_logic.validate_spot_data(data)
        if errors:
            return error(422, "invalid spot", errors=errors)
        cur.execute(
            "UPDATE spots SET name = %s, location = %s, ideal_wind_dir = %s, ideal_swell_ft = %s"
            " WHERE id = %s",
            (*_spot_values(data), spot_id),
        )
        cur.execute("SELECT * FROM spots WHERE id = %s", (spot_id,))
        row = cur.fetchone()
        db.commit()
        return jsonify(_spot_out(row))

    @app.delete("/spots/<int:spot_id>")
    def delete_spot(spot_id: int):
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id FROM spots WHERE id = %s", (spot_id,))
        if cur.fetchone() is None:
            return error(404, "spot not found")
        # Referential integrity crosses the seam: the spot's sessions live in
        # another database, so the check is a call, not a foreign key.
        try:
            session_count = _sessions_count_for_spot(spot_id)
        except UpstreamUnavailable as exc:
            log.warning("cannot verify sessions before delete: %s", exc)
            return error(503, "sessions service unavailable, cannot verify the spot has no sessions")
        if session_count:
            return error(409, "this spot still has logged sessions; delete or move those first")
        cur.execute("DELETE FROM spots WHERE id = %s", (spot_id,))
        db.commit()
        return "", 204

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
