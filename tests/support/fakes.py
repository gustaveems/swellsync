"""In-memory stand-ins for the two service databases, plus a small HTTP stub.

The fakes understand only the SQL these services send. Any other statement
raises AssertionError, so a new query shows up as a failing test instead of a
silent pass. The HTTP stub is a real server on 127.0.0.1, so timeouts and
connection errors behave the way they do between containers.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymssql

# Orders used by the sessions service, mapped to (sort key, reverse).
SESSION_ORDERINGS = {
    "session_date DESC, id DESC": (lambda r: (r["session_date"], r["id"]), True),
    "session_date ASC, id ASC": (lambda r: (r["session_date"], r["id"]), False),
    "duration_mins DESC, session_date DESC": (lambda r: (r["duration_mins"], r["session_date"]), True),
    "wave_or_wind_rating DESC, session_date DESC": (
        lambda r: (r["wave_or_wind_rating"], r["session_date"]),
        True,
    ),
}


def like_match(pattern: str, text: str) -> bool:
    """Match a SQL LIKE pattern that uses ESCAPE '!', case-insensitively."""
    regex = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "!" and i + 1 < len(pattern):
            regex.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        regex.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.fullmatch("".join(regex), text, re.IGNORECASE | re.DOTALL) is not None


class _Cursor:
    def __init__(self, db: "FakeDatabase"):
        self._db = db
        self._rows: list = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        if self._db.down:
            raise pymssql.Error("server unreachable")
        normalised = " ".join(sql.split())
        self._rows, self.rowcount = self._db.run(normalised, tuple(params))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, db: "FakeDatabase"):
        self._db = db

    def cursor(self):
        return _Cursor(self._db)

    def commit(self):
        self._db.commits += 1

    def rollback(self):
        self._db.rollbacks += 1

    def close(self):
        self._db.closed += 1


class FakeDatabase:
    """One service database. Set `down` to make connect and every statement fail."""

    def __init__(self):
        self.down = False
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def connect(self, url, attempts=8):
        if self.down:
            raise pymssql.Error("server unreachable")
        return _Connection(self)

    def run(self, sql, params):  # pragma: no cover - overridden by each service fake
        raise NotImplementedError


class FakeSpotsDatabase(FakeDatabase):
    def __init__(self, spots=None):
        super().__init__()
        self.spots = [dict(s) for s in (spots or [])]
        self.next_id = max((s["id"] for s in self.spots), default=0) + 1

    def run(self, sql, params):
        if sql == "SELECT 1 AS ok":
            return [{"ok": 1}], 0
        if sql == "SELECT COUNT(*) AS c FROM spots":
            return [{"c": len(self.spots)}], 0
        if sql.startswith("SELECT * FROM spots WHERE (name LIKE"):
            pattern = params[0]
            hits = [s for s in self.spots
                    if like_match(pattern, s["name"]) or like_match(pattern, s["location"])]
            return [dict(s) for s in sorted(hits, key=lambda s: s["name"])], 0
        if sql == "SELECT * FROM spots ORDER BY name":
            return [dict(s) for s in sorted(self.spots, key=lambda s: s["name"])], 0
        if sql.startswith("INSERT INTO spots"):
            row = {
                "id": self.next_id,
                "name": params[0],
                "location": params[1],
                "ideal_wind_dir": params[2],
                "ideal_swell_ft": params[3],
            }
            self.next_id += 1
            self.spots.append(row)
            return ([dict(row)] if "OUTPUT INSERTED" in sql else []), 1
        if sql == "SELECT * FROM spots WHERE id = %s":
            return [dict(s) for s in self.spots if s["id"] == params[0]], 0
        if sql == "SELECT id FROM spots WHERE id = %s":
            return [{"id": s["id"]} for s in self.spots if s["id"] == params[0]], 0
        if sql.startswith("UPDATE spots SET"):
            name, location, wind, swell, spot_id = params
            for s in self.spots:
                if s["id"] == spot_id:
                    s.update(name=name, location=location, ideal_wind_dir=wind, ideal_swell_ft=swell)
                    return [], 1
            return [], 0
        if sql == "DELETE FROM spots WHERE id = %s":
            before = len(self.spots)
            self.spots = [s for s in self.spots if s["id"] != params[0]]
            return [], before - len(self.spots)
        raise AssertionError(f"FakeSpotsDatabase does not know this SQL: {sql}")


class FakeSessionsDatabase(FakeDatabase):
    def __init__(self, sessions=None):
        super().__init__()
        self.sessions = [dict(s) for s in (sessions or [])]
        self.next_id = max((s["id"] for s in self.sessions), default=0) + 1
        # Counts updates that set updated_at (migration 002).
        self.updates_stamped = 0

    def run(self, sql, params):
        if sql == "SELECT 1 AS ok":
            return [{"ok": 1}], 0
        if sql == "SELECT COUNT(*) AS c FROM sessions":
            return [{"c": len(self.sessions)}], 0
        if sql == "SELECT * FROM sessions WHERE id = %s":
            return [dict(r) for r in self.sessions if r["id"] == params[0]], 0
        if sql == "SELECT id FROM sessions WHERE id = %s":
            return [{"id": r["id"]} for r in self.sessions if r["id"] == params[0]], 0
        if sql.startswith("SELECT * FROM sessions") and "ORDER BY" in sql:
            rows = self.sessions
            if "WHERE spot_id = %s" in sql:
                rows = [r for r in rows if r["spot_id"] == params[0]]
            key, reverse = SESSION_ORDERINGS[sql.split("ORDER BY ", 1)[1]]
            return [dict(r) for r in sorted(rows, key=key, reverse=reverse)], 0
        if sql.startswith("INSERT INTO sessions"):
            row = {
                "id": self.next_id,
                "spot_id": params[0],
                "session_date": params[1],
                "duration_mins": params[2],
                "wave_or_wind_rating": params[3],
                "gear_used": params[4],
                "notes": params[5],
            }
            self.next_id += 1
            self.sessions.append(row)
            return ([dict(row)] if "OUTPUT INSERTED" in sql else []), 1
        if sql.startswith("UPDATE sessions SET"):
            spot_id, session_date, duration, rating, gear, notes, row_id = params
            for r in self.sessions:
                if r["id"] == row_id:
                    r.update(spot_id=spot_id, session_date=session_date, duration_mins=duration,
                             wave_or_wind_rating=rating, gear_used=gear, notes=notes)
                    if "updated_at = SYSUTCDATETIME()" in sql:
                        self.updates_stamped += 1
                    return [], 1
            return [], 0
        if sql == "DELETE FROM sessions WHERE id = %s":
            before = len(self.sessions)
            self.sessions = [r for r in self.sessions if r["id"] != params[0]]
            return [], before - len(self.sessions)
        raise AssertionError(f"FakeSessionsDatabase does not know this SQL: {sql}")


class StubService:
    """A real HTTP server on 127.0.0.1 standing in for the other service.

    `responder(method, path)` returns (status, json_body); a body of None sends
    an empty reply. `delay` makes every reply late by that many seconds.
    `calls` records each (method, path) received.
    """

    def __init__(self):
        self.responder = lambda method, path: (200, {})
        self.delay = 0.0
        self.calls: list[tuple[str, str]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                stub.calls.append((self.command, self.path))
                if stub.delay:
                    time.sleep(stub.delay)
                status, body = stub.responder(self.command, self.path)
                payload = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_DELETE = _answer

            def log_message(self, *args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


def unused_url() -> str:
    """A URL with nothing listening, so a call fails at once with connection refused."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"
