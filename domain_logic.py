"""
SwellSync domain logic (domain_logic.py)
========================================

Pure business logic for both feature domains — no Flask, no SQL, no I/O.

Why this module exists (the domain seam):
  * Domain 1 (Spot Directory) contributes spot-form validation.
  * Domain 2 (Session Tracker) contributes session validation + quality filter.
  * Cross-domain statistics (sessions aggregated for a spot / the whole log)
    live here so neither the routes nor the database know the math.

Because every function is deterministic and side-effect free, the required
">= 70% business logic coverage" is reachable with plain pytest tests over
dictionaries — no web server, no database.

Public API:
    calculate_spot_stats(sessions)
    filter_ideal_sessions(sessions, min_rating=4)
    validate_session_data(data)   -> dict of field -> error (empty = valid)
    validate_spot_data(data)      -> dict of field -> error (empty = valid)
"""

from __future__ import annotations

import re
from datetime import date

RATING_MIN = 1
RATING_MAX = 5
DEFAULT_MIN_RATING = 4

MAX_NAME_LENGTH = 100
MAX_LOCATION_LENGTH = 150
MAX_WIND_DIR_LENGTH = 60
MAX_GEAR_LENGTH = 120
MAX_NOTES_LENGTH = 2000

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


def _to_int(value):
    """Best-effort integer coercion; returns None when the value is not integral.

    Accepts ints, integral floats, and numeric strings (form posts arrive as
    strings). Booleans are rejected on purpose — True is not a duration.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if _INT_RE.fullmatch(stripped):
            return int(stripped)
    return None


def _to_float(value):
    """Best-effort float coercion; returns None when the value is not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if _FLOAT_RE.fullmatch(stripped):
            return float(stripped)
    return None


def _text_or_empty(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def calculate_spot_stats(sessions):
    """Aggregate sessions (any iterable of mappings) into summary metrics.

    Works for one spot's sessions or the whole log. Reads the
    ``duration_mins`` / ``wave_or_wind_rating`` keys stored by the Session
    Tracker; numeric strings (straight from forms) are tolerated.

    Returns a dict:
        session_count          int    number of sessions
        total_duration_mins    int    summed water time in minutes
        average_duration_mins  float  total / count, rounded to 2 dp (None if no sessions)
        average_rating         float  mean rating, rounded to 2 dp (None if none rated)
    """
    rows = list(sessions)
    session_count = len(rows)
    total_duration_mins = 0
    rating_total = 0
    ratings_seen = 0

    for row in rows:
        duration = _to_int(row.get("duration_mins"))
        if duration is not None and duration > 0:
            total_duration_mins += duration
        rating = _to_int(row.get("wave_or_wind_rating"))
        if rating is not None:
            rating_total += rating
            ratings_seen += 1

    if session_count == 0:
        return {
            "session_count": 0,
            "total_duration_mins": 0,
            "average_duration_mins": None,
            "average_rating": None,
        }

    return {
        "session_count": session_count,
        "total_duration_mins": total_duration_mins,
        "average_duration_mins": round(total_duration_mins / session_count, 2),
        "average_rating": round(rating_total / ratings_seen, 2) if ratings_seen else None,
    }


def filter_ideal_sessions(sessions, min_rating=DEFAULT_MIN_RATING):
    """Return the sessions rated at or above ``min_rating`` (default 4).

    Input order is preserved; sessions without a usable rating never qualify.
    """
    ideal = []
    for row in sessions:
        rating = _to_int(row.get("wave_or_wind_rating"))
        if rating is not None and rating >= min_rating:
            ideal.append(row)
    return ideal


def validate_session_data(data):
    """Validate a session payload. Values may be strings (form posts) or ints.

    Returns a dict mapping field name -> human-readable error; an empty dict
    means the payload is valid. Referential integrity (does spot_id exist?)
    is deliberately NOT checked here — that is the SQLite foreign key's job,
    which keeps this function pure and database-free.
    """
    errors = {}

    spot_id = _to_int(data.get("spot_id"))
    if spot_id is None or spot_id <= 0:
        errors["spot_id"] = "Pick a spot from the directory."

    duration = _to_int(data.get("duration_mins"))
    if duration is None:
        errors["duration_mins"] = "Duration must be a whole number of minutes."
    elif duration <= 0:
        errors["duration_mins"] = "Duration must be greater than zero minutes."

    rating = _to_int(data.get("wave_or_wind_rating"))
    if rating is None or not RATING_MIN <= rating <= RATING_MAX:
        errors["wave_or_wind_rating"] = (
            f"Rating must be a whole number from {RATING_MIN} to {RATING_MAX}."
        )

    raw_date = data.get("date")
    if isinstance(raw_date, date):
        date_str = raw_date.isoformat()
    elif isinstance(raw_date, str):
        date_str = raw_date.strip()
    else:
        date_str = ""
    if not date_str:
        errors["date"] = "Date is required (YYYY-MM-DD)."
    elif not _ISO_DATE_RE.fullmatch(date_str):
        errors["date"] = "Date must look like YYYY-MM-DD."
    else:
        try:
            date.fromisoformat(date_str)
        except ValueError:
            errors["date"] = "That is not a real calendar date."

    if len(_text_or_empty(data.get("gear_used"))) > MAX_GEAR_LENGTH:
        errors["gear_used"] = f"Gear must be {MAX_GEAR_LENGTH} characters or fewer."
    if len(_text_or_empty(data.get("notes"))) > MAX_NOTES_LENGTH:
        errors["notes"] = f"Notes must be {MAX_NOTES_LENGTH} characters or fewer."

    return errors


def validate_spot_data(data):
    """Validate a spot payload. Empty dict means valid.

    Optional fields (wind direction, swell) may be blank; swell, when given,
    must be a non-negative number.
    """
    errors = {}

    name = _text_or_empty(data.get("name"))
    if not name:
        errors["name"] = "Name is required."
    elif len(name) > MAX_NAME_LENGTH:
        errors["name"] = f"Name must be {MAX_NAME_LENGTH} characters or fewer."

    location = _text_or_empty(data.get("location"))
    if not location:
        errors["location"] = "Location is required."
    elif len(location) > MAX_LOCATION_LENGTH:
        errors["location"] = f"Location must be {MAX_LOCATION_LENGTH} characters or fewer."

    if len(_text_or_empty(data.get("ideal_wind_dir"))) > MAX_WIND_DIR_LENGTH:
        errors["ideal_wind_dir"] = (
            f"Ideal wind direction must be {MAX_WIND_DIR_LENGTH} characters or fewer."
        )

    raw_swell = data.get("ideal_swell_ft")
    is_blank = raw_swell is None or (isinstance(raw_swell, str) and not raw_swell.strip())
    if not is_blank:
        swell = _to_float(raw_swell)
        if swell is None:
            errors["ideal_swell_ft"] = "Ideal swell must be a number, e.g. 4.5."
        elif swell < 0:
            errors["ideal_swell_ft"] = "Ideal swell cannot be negative."

    return errors
