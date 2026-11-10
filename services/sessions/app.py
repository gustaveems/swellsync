"""Session Tracker service (domain 2). Owns the `sessions` table in its own database.

Endpoints:
    GET    /health                    own database only; 200 ok / 503 otherwise
    GET    /sessions?spot=&sort=&epic= list, with spot names from the spots service
    POST   /sessions                  create (checks the spot exists over HTTP)
    GET    /sessions/<id>             read one
    PUT    /sessions/<id>             update (checks the spot exists over HTTP)
    DELETE /sessions/<id>             delete
    GET    /sessions/export.csv       CSV of the same filtered list
    GET    /stats?spot=               aggregate stats and rating distribution

Cross-seam behaviour, both bounded by SPOTS_TIMEOUT_S:
  * list: if the spots service does not answer, sessions are returned with
    spot_name null and a "notice" explaining why. The list still works.
  * create/update: if the spots service does not answer, the write is refused
    with 503. We never store a spot_id we could not verify.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pymssql
from flask import Flask, Response, g, jsonify, request

import db as dbmod
import domain_logic

SEED_FILE = Path(__file__).with_name("seed.json")
VERSION = os.environ.get("APP_VERSION", "dev")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:8080")
SPOTS_URL = os.environ.get("SPOTS_URL", "http://spots:8000")
SPOTS_TIMEOUT_S = float(os.environ.get("SPOTS_TIMEOUT_S", "2"))

NOTICE_SPOTS_DOWN = (
    "Spot names are unavailable: the spots service did not answer, so spot names are blank."
)

SESSION_ORDER = {
    "date": "session_date DESC, id DESC",
    "oldest": "session_date ASC, id ASC",
    "duration": "duration_mins DESC, session_date DESC",
    "rating": "wave_or_wind_rating DESC, session_date DESC",
}

logging.basicConfig(
    stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("sessions")


class UpstreamUnavailable(Exception):
    """The spots service did not answer within its timeout."""


def _spots_get(path: str):
    """GET a JSON document from the spots service. Returns (status, body)."""
    req = urllib.request.Request(f"{SPOTS_URL}{path}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=SPOTS_TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpstreamUnavailable(str(exc)) from exc


def fetch_spot_names() -> tuple[dict, str | None]:
    """Return ({spot_id: name}, notice). The notice is None when the call worked."""
    try:
        _, body = _spots_get("/spots")
    except UpstreamUnavailable as exc:
        log.warning("spot names unavailable: %s", exc)
        return {}, NOTICE_SPOTS_DOWN
    return {spot["id"]: spot["name"] for spot in (body or {}).get("spots", [])}, None


def spot_exists(spot_id: int) -> bool:
    status, _ = _spots_get(f"/spots/{int(spot_id)}")
    return status == 200


def _session_out(row: dict, names: dict) -> dict:
    return {
        "id": row["id"],
        "spot_id": row["spot_id"],
        "spot_name": names.get(row["spot_id"]),
        "date": row["session_date"].isoformat(),
        "duration_mins": row["duration_mins"],
        "wave_or_wind_rating": row["wave_or_wind_rating"],
        "gear_used": row["gear_used"],
        "notes": row["notes"],
    }


def _session_values(data: dict) -> tuple:
    return (
        int(data["spot_id"]),
        date.fromisoformat(str(data["date"]).strip()),
        int(data["duration_mins"]),
        int(data["wave_or_wind_rating"]),
        domain_logic._text_or_empty(data.get("gear_used")) or None,
        domain_logic._text_or_empty(data.get("notes")) or None,
    )


def _prepare_session(data: dict) -> dict:
    """Default a blank date to today, as the monolith did."""
    prepared = dict(data)
    if not str(prepared.get("date") or "").strip():
        prepared["date"] = date.today().isoformat()
    return prepared


def create_app() -> Flask:
    app = Flask(__name__)
    database_url = os.environ["DATABASE_URL"]

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
    # Seed rows name spots by their position (1..4), which matches the identity
    # values the spots service assigns on its own first boot.
    boot = dbmod.connect(database_url)
    try:
        dbmod.migrate(boot)
        cur = boot.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM sessions")
        if cur.fetchone()["c"] == 0 and SEED_FILE.exists():
            seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))["sessions"]
            for item in seed:
                cur.execute(
                    "INSERT INTO sessions (spot_id, session_date, duration_mins,"
                    " wave_or_wind_rating, gear_used, notes) VALUES (%s, %s, %s, %s, %s, %s)",
                    (item["spot"], date.fromisoformat(item["date"]), item["duration_mins"],
                     item["wave_or_wind_rating"], item.get("gear_used"), item.get("notes")),
                )
            boot.commit()
            log.info("seeded %d sessions", len(seed))
    finally:
        boot.close()

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
        except Exception as exc:
            log.warning("health check failed: %s", exc)
            body, status = {"status": "error", "db": "unreachable", "version": VERSION}, 503
        return jsonify(body), status

    def _filtered_rows(spot_filter, sort_key, epic_only):
        cur = get_db().cursor()
        if spot_filter:
            cur.execute(
                "SELECT * FROM sessions WHERE spot_id = %s ORDER BY " + SESSION_ORDER[sort_key],
                (spot_filter,),
            )
        else:
            cur.execute("SELECT * FROM sessions ORDER BY " + SESSION_ORDER[sort_key])
        rows = cur.fetchall()
        if epic_only:
            rows = domain_logic.filter_ideal_sessions(rows)
        return rows

    @app.get("/sessions")
    def list_sessions():
        spot_filter = request.args.get("spot", type=int)
        sort_key = request.args.get("sort") if request.args.get("sort") in SESSION_ORDER else "date"
        epic_only = bool(request.args.get("epic"))
        rows = _filtered_rows(spot_filter, sort_key, epic_only)
        names, notice = fetch_spot_names()
        return jsonify({
            "sessions": [_session_out(r, names) for r in rows],
            "notice": notice,
        })

    @app.post("/sessions")
    def create_session():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error(400, "expected a JSON object")
        data = _prepare_session(data)
        errors = domain_logic.validate_session_data(data)
        if errors:
            return error(422, "invalid session", errors=errors)
        try:
            if not spot_exists(data["spot_id"]):
                return error(422, "invalid session", errors={"spot_id": "Unknown spot."})
        except UpstreamUnavailable as exc:
            log.warning("cannot verify spot before write: %s", exc)
            return error(503, "spots service unavailable, session not saved; try again shortly")
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO sessions (spot_id, session_date, duration_mins, wave_or_wind_rating,"
            " gear_used, notes) OUTPUT INSERTED.* VALUES (%s, %s, %s, %s, %s, %s)",
            _session_values(data),
        )
        row = cur.fetchone()
        db.commit()
        names, _ = fetch_spot_names()
        return jsonify(_session_out(row, names)), 201

    @app.get("/sessions/<int:session_id>")
    def read_session(session_id: int):
        cur = get_db().cursor()
        cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
        if row is None:
            return error(404, "session not found")
        return jsonify(_session_out(row, {}))

    @app.put("/sessions/<int:session_id>")
    def update_session(session_id: int):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error(400, "expected a JSON object")
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id FROM sessions WHERE id = %s", (session_id,))
        if cur.fetchone() is None:
            return error(404, "session not found")
        data = _prepare_session(data)
        errors = domain_logic.validate_session_data(data)
        if errors:
            return error(422, "invalid session", errors=errors)
        try:
            if not spot_exists(data["spot_id"]):
                return error(422, "invalid session", errors={"spot_id": "Unknown spot."})
        except UpstreamUnavailable as exc:
            log.warning("cannot verify spot before write: %s", exc)
            return error(503, "spots service unavailable, session not saved; try again shortly")
        cur.execute(
            "UPDATE sessions SET spot_id = %s, session_date = %s, duration_mins = %s,"
            " wave_or_wind_rating = %s, gear_used = %s, notes = %s WHERE id = %s",
            (*_session_values(data), session_id),
        )
        cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
        db.commit()
        names, _ = fetch_spot_names()
        return jsonify(_session_out(row, names))

    @app.delete("/sessions/<int:session_id>")
    def delete_session(session_id: int):
        db = get_db()
        cur = db.cursor()
        cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        deleted = cur.rowcount
        db.commit()
        if not deleted:
            return error(404, "session not found")
        return "", 204

    @app.get("/sessions/export.csv")
    def export_sessions_csv():
        spot_filter = request.args.get("spot", type=int)
        sort_key = request.args.get("sort") if request.args.get("sort") in SESSION_ORDER else "date"
        epic_only = bool(request.args.get("epic"))
        rows = _filtered_rows(spot_filter, sort_key, epic_only)
        names, _ = fetch_spot_names()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["date", "spot", "duration_mins", "rating", "gear_used", "notes"])
        for row in rows:
            s = _session_out(row, names)
            writer.writerow([s["date"], s["spot_name"] or "", s["duration_mins"],
                             s["wave_or_wind_rating"], s["gear_used"] or "", s["notes"] or ""])
        filename = "swellsync-sessions"
        if spot_filter:
            filename += f"-spot-{spot_filter}"
        if epic_only:
            filename += "-epic"
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )

    @app.get("/stats")
    def stats():
        spot_filter = request.args.get("spot", type=int)
        rows = _filtered_rows(spot_filter, "date", False)
        return jsonify({
            "stats": domain_logic.calculate_spot_stats(rows),
            "distribution": domain_logic.rating_distribution(rows),
        })

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
