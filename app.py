"""
SwellSync — Surf & Sail Session Logger (app.py)
===============================================

Single-process Flask monolith with SQLite persistence (Assignment 1).

Layout of this file:
  1. Configuration & schema        (PORT / DATA_DIR / SCHEMA_SQL)
  2. Shared DB plumbing            (connect / init / per-request handle)
  3. Application factory           (create_app — used by `python app.py` and tests)
  4. Composition views             (dashboard, spot detail: cross-domain reads)
  5. Domain 1 — Spot Directory     (CRUD on `spots` only; never queries `sessions`)
  6. Domain 2 — Session Tracker    (CRUD on `sessions`; spots referenced by spot_id)

All cross-domain math lives in domain_logic.py (pure functions, no Flask).

Run:
    python app.py

Environment:
    PORT         server port, default 8000 (binds 0.0.0.0)
    DATA_DIR     directory for swellsync.db, default ./data
    SECRET_KEY   flash-message signing key (dev default provided)
    FLASK_DEBUG  set to 1 for the Werkzeug reloader
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

import domain_logic

DEFAULT_PORT = 8000
DEFAULT_DATA_DIR = "./data"
DB_FILENAME = "swellsync.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    location         TEXT NOT NULL,
    ideal_wind_dir   TEXT,
    ideal_swell_ft   REAL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id             INTEGER NOT NULL,
    date                TEXT NOT NULL,
    duration_mins       INTEGER NOT NULL CHECK (duration_mins > 0),
    wave_or_wind_rating INTEGER CHECK (wave_or_wind_rating BETWEEN 1 AND 5),
    gear_used           TEXT,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (spot_id) REFERENCES spots (id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_spot_id ON sessions (spot_id);
CREATE INDEX IF NOT EXISTS idx_sessions_date    ON sessions (date);
"""

SQL_SESSIONS_WITH_SPOT = (
    "SELECT s.*, sp.name AS spot_name "
    "FROM sessions s JOIN spots sp ON sp.id = s.spot_id"
)


# ---------------------------------------------------------------------------
# 2. Shared DB plumbing — infrastructure, owned by neither domain
# ---------------------------------------------------------------------------

def resolve_db_path(data_dir: str | None = None) -> Path:
    """SQLite file lives at $DATA_DIR/swellsync.db (arg wins, then env, then default)."""
    base = data_dir if data_dir is not None else os.environ.get("DATA_DIR", DEFAULT_DATA_DIR)
    return (Path(base) / DB_FILENAME).resolve()


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # SQLite ships with FK enforcement OFF; turn it on for every connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    """Idempotently create tables + indexes. No prompts, no migration steps."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_db(db_path)) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect_db(Path(current_app.config["DB_PATH"]))
    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _safe_next(target: str | None, fallback: str) -> str:
    """Accept only site-relative redirect targets (open-redirect guard)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return fallback


def _flash_field_errors(errors: dict) -> None:
    for field, message in errors.items():
        flash(f"{field.replace('_', ' ').capitalize()}: {message}", "error")


def _optional_text(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value or None


def _swell_or_none(raw: str | None) -> float | None:
    return float(raw.strip()) if raw and raw.strip() else None


def _session_write_values(form: dict) -> tuple:
    return (
        int(form["spot_id"]),
        form["date"].strip(),
        int(form["duration_mins"]),
        int(form["wave_or_wind_rating"]),
        _optional_text(form.get("gear_used")),
        _optional_text(form.get("notes")),
    )


# ---------------------------------------------------------------------------
# 3. Application factory
# ---------------------------------------------------------------------------

def create_app(data_dir: str | None = None) -> Flask:
    """Build the app. ``data_dir`` overrides $DATA_DIR (used by the test suite)."""
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "swellsync-dev-secret"),
        DB_PATH=str(resolve_db_path(data_dir)),
    )
    init_db(Path(app.config["DB_PATH"]))
    app.teardown_appcontext(close_db)

    # -- 4. Composition views (read across the domain seam) ------------------

    @app.route("/")
    def dashboard():
        db = get_db()
        spots = db.execute(
            "SELECT id, name, location FROM spots ORDER BY name COLLATE NOCASE"
        ).fetchall()
        recent = db.execute(
            SQL_SESSIONS_WITH_SPOT + " ORDER BY s.date DESC, s.id DESC LIMIT 8"
        ).fetchall()
        every_session = [dict(row) for row in db.execute("SELECT * FROM sessions")]
        overall = domain_logic.calculate_spot_stats(every_session)
        return render_template(
            "index.html", spots=spots, recent_sessions=recent, overall=overall
        )

    @app.route("/spots/<int:spot_id>")
    def spot_detail_page(spot_id):
        db = get_db()
        spot = db.execute("SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
        if spot is None:
            abort(404)
        sessions = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM sessions WHERE spot_id = ? ORDER BY date DESC, id DESC",
                (spot_id,),
            )
        ]
        stats = domain_logic.calculate_spot_stats(sessions)
        ideal = domain_logic.filter_ideal_sessions(sessions)
        return render_template(
            "spot_detail.html",
            spot=spot,
            sessions=sessions,
            stats=stats,
            ideal_sessions=ideal,
            today=date.today().isoformat(),
        )

    # -- 5. Domain 1 — Spot Directory (only the `spots` table) ----------------

    @app.route("/spots", methods=["GET", "POST"])
    def spots_page():
        db = get_db()
        form = request.form.to_dict()
        if request.method == "POST":
            errors = domain_logic.validate_spot_data(form)
            if errors:
                _flash_field_errors(errors)
                return _render_spots_page(db, form, errors)
            db.execute(
                "INSERT INTO spots (name, location, ideal_wind_dir, ideal_swell_ft)"
                " VALUES (?, ?, ?, ?)",
                (
                    form["name"].strip(),
                    form["location"].strip(),
                    _optional_text(form.get("ideal_wind_dir")),
                    _swell_or_none(form.get("ideal_swell_ft")),
                ),
            )
            db.commit()
            flash(f"Spot “{form['name'].strip()}” added to the directory.", "success")
            return redirect(url_for("spots_page"))
        return _render_spots_page(db, {}, {})

    def _render_spots_page(db, form, errors):
        spots = db.execute("SELECT * FROM spots ORDER BY name COLLATE NOCASE").fetchall()
        status = 422 if errors else 200
        return render_template("spots.html", spots=spots, form=form, errors=errors), status

    @app.route("/spots/<int:spot_id>/edit", methods=["GET", "POST"])
    def spot_edit_page(spot_id):
        db = get_db()
        spot = db.execute("SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
        if spot is None:
            abort(404)
        if request.method == "POST":
            form = request.form.to_dict()
            errors = domain_logic.validate_spot_data(form)
            if errors:
                _flash_field_errors(errors)
                return render_template(
                    "spot_edit.html", spot=spot, form=form, errors=errors
                ), 422
            db.execute(
                "UPDATE spots SET name = ?, location = ?, ideal_wind_dir = ?,"
                " ideal_swell_ft = ? WHERE id = ?",
                (
                    form["name"].strip(),
                    form["location"].strip(),
                    _optional_text(form.get("ideal_wind_dir")),
                    _swell_or_none(form.get("ideal_swell_ft")),
                    spot_id,
                ),
            )
            db.commit()
            flash("Spot updated.", "success")
            return redirect(url_for("spot_detail_page", spot_id=spot_id))
        form = {
            "name": spot["name"],
            "location": spot["location"],
            "ideal_wind_dir": spot["ideal_wind_dir"] or "",
            "ideal_swell_ft": "" if spot["ideal_swell_ft"] is None else spot["ideal_swell_ft"],
        }
        return render_template("spot_edit.html", spot=spot, form=form, errors={})

    @app.route("/spots/<int:spot_id>/delete", methods=["POST"])
    def spot_delete_page(spot_id):
        db = get_db()
        # Domain 1 never queries `sessions`: referential integrity is the
        # database's job. A spot that still has sessions raises IntegrityError.
        try:
            cursor = db.execute("DELETE FROM spots WHERE id = ?", (spot_id,))
        except sqlite3.IntegrityError:
            db.rollback()
            flash(
                "This spot still has logged sessions — delete or move those first.",
                "error",
            )
            return redirect(url_for("spot_detail_page", spot_id=spot_id))
        db.commit()
        if cursor.rowcount == 0:
            abort(404)
        flash("Spot deleted.", "success")
        return redirect(url_for("spots_page"))

    # -- 6. Domain 2 — Session Tracker (`sessions`; spots referenced by id) ---

    @app.route("/sessions", methods=["GET", "POST"])
    def sessions_page():
        db = get_db()
        spots = db.execute(
            "SELECT id, name FROM spots ORDER BY name COLLATE NOCASE"
        ).fetchall()
        if request.method == "POST":
            form = request.form.to_dict()
            if not form.get("date", "").strip():
                form["date"] = date.today().isoformat()
            errors = domain_logic.validate_session_data(form)
            if errors:
                _flash_field_errors(errors)
                return _render_sessions_page(db, spots, form, errors)
            try:
                db.execute(
                    "INSERT INTO sessions (spot_id, date, duration_mins,"
                    " wave_or_wind_rating, gear_used, notes) VALUES (?, ?, ?, ?, ?, ?)",
                    _session_write_values(form),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                flash("That spot is not in the directory — pick one from the list.", "error")
                return _render_sessions_page(db, spots, form, {"spot_id": "Unknown spot."})
            flash("Session logged. 🤙", "success")
            return redirect(url_for("sessions_page"))
        return _render_sessions_page(db, spots, {}, {})

    def _render_sessions_page(db, spots, form, errors):
        spot_filter = request.args.get("spot", type=int)
        if spot_filter:
            sessions = db.execute(
                SQL_SESSIONS_WITH_SPOT
                + " WHERE s.spot_id = ? ORDER BY s.date DESC, s.id DESC",
                (spot_filter,),
            ).fetchall()
        else:
            sessions = db.execute(
                SQL_SESSIONS_WITH_SPOT + " ORDER BY s.date DESC, s.id DESC"
            ).fetchall()
        status = 422 if errors else 200
        return render_template(
            "sessions.html",
            sessions=sessions,
            spots=spots,
            form=form,
            errors=errors,
            spot_filter=spot_filter,
            today=date.today().isoformat(),
        ), status

    @app.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
    def session_edit_page(session_id):
        db = get_db()
        session_row = db.execute(
            SQL_SESSIONS_WITH_SPOT + " WHERE s.id = ?", (session_id,)
        ).fetchone()
        if session_row is None:
            abort(404)
        spots = db.execute(
            "SELECT id, name FROM spots ORDER BY name COLLATE NOCASE"
        ).fetchall()
        if request.method == "POST":
            form = request.form.to_dict()
            if not form.get("date", "").strip():
                form["date"] = date.today().isoformat()
            errors = domain_logic.validate_session_data(form)
            if errors:
                _flash_field_errors(errors)
                return render_template(
                    "session_edit.html",
                    session_row=session_row,
                    spots=spots,
                    form=form,
                    errors=errors,
                ), 422
            try:
                db.execute(
                    "UPDATE sessions SET spot_id = ?, date = ?, duration_mins = ?,"
                    " wave_or_wind_rating = ?, gear_used = ?, notes = ? WHERE id = ?",
                    (*_session_write_values(form), session_id),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                flash("That spot is not in the directory.", "error")
                return render_template(
                    "session_edit.html",
                    session_row=session_row,
                    spots=spots,
                    form=form,
                    errors={"spot_id": "Unknown spot."},
                ), 422
            flash("Session updated.", "success")
            return redirect(url_for("sessions_page"))
        form = {
            key: "" if session_row[key] is None else session_row[key]
            for key in (
                "spot_id",
                "date",
                "duration_mins",
                "wave_or_wind_rating",
                "gear_used",
                "notes",
            )
        }
        return render_template(
            "session_edit.html",
            session_row=session_row,
            spots=spots,
            form=form,
            errors={},
        )

    @app.route("/sessions/<int:session_id>/delete", methods=["POST"])
    def session_delete_page(session_id):
        db = get_db()
        cursor = db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        db.commit()
        if cursor.rowcount == 0:
            abort(404)
        flash("Session deleted.", "success")
        return redirect(_safe_next(request.form.get("next"), url_for("sessions_page")))

    @app.errorhandler(404)
    def page_not_found(_error):
        return render_template("404.html"), 404

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    create_app().run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
