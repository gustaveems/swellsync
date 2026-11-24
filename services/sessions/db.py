"""Database plumbing for the spots service: connection with retry, and migrations.

Azure SQL serverless pauses when idle. The first connection after a pause fails
with error 40613 for up to about a minute, so connects retry with backoff.
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

import pymssql

log = logging.getLogger("db")

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
# T-SQL batch separator; migration files may split statements with GO lines.
_GO_RE = re.compile(r"^\s*GO\s*$", re.MULTILINE)
# Name of the SQL Server application lock held while a replica migrates and seeds.
BOOT_LOCK = "swellsync_boot"


def parse_database_url(url: str) -> dict:
    """mssql://user:password@host:port/database -> pymssql keyword arguments."""
    parts = urlparse(url)
    if parts.scheme not in ("mssql", "mssql+pymssql"):
        raise ValueError("DATABASE_URL must start with mssql://")
    return {
        "server": parts.hostname,
        "port": parts.port or 1433,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": parts.path.lstrip("/"),
    }


def connect(url: str, attempts: int = 8):
    """Open a connection, retrying with capped backoff (about 1 minute total)."""
    params = parse_database_url(url)
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return pymssql.connect(
                login_timeout=10, timeout=10, as_dict=True, autocommit=False, **params
            )
        except pymssql.Error as exc:
            if attempt == attempts:
                raise
            log.warning("database not ready (attempt %d/%d): %s", attempt, attempts, exc)
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
    raise RuntimeError("unreachable")


@contextmanager
def boot_lock(conn, timeout_ms: int = 120_000):
    """Hold an exclusive SQL Server application lock while migrating and seeding.

    Without it, two replicas booting at once could both see a migration as
    pending, or both see an empty table and seed it twice. The second replica
    waits here until the first is done, then finds nothing left to do. The lock
    belongs to the session, so closing the connection also releases it.
    """
    cur = conn.cursor()
    cur.execute(
        "SET NOCOUNT ON; DECLARE @r INT; EXEC @r = sp_getapplock @Resource = %s,"
        " @LockMode = 'Exclusive', @LockOwner = 'Session', @LockTimeout = %s; SELECT @r AS r",
        (BOOT_LOCK, timeout_ms),
    )
    row = cur.fetchone()
    if row is None or row["r"] < 0:
        code = None if row is None else row["r"]
        raise RuntimeError(f"could not take the boot lock (sp_getapplock returned {code})")
    log.info("boot lock taken")
    try:
        yield
    finally:
        try:
            cur.execute("EXEC sp_releaseapplock @Resource = %s, @LockOwner = 'Session'", (BOOT_LOCK,))
        except pymssql.Error as exc:  # the connection is closed next, which releases it too
            log.warning("could not release the boot lock: %s", exc)


def migrate(conn) -> list[str]:
    """Apply every migrations/*.sql file not yet recorded, in filename order.

    Each file runs in its own transaction and is recorded in schema_migrations,
    so a second boot applies nothing. Returns the names applied on this boot.
    """
    cur = conn.cursor()
    cur.execute(
        "IF OBJECT_ID('schema_migrations', 'U') IS NULL "
        "CREATE TABLE schema_migrations ("
        " version NVARCHAR(100) NOT NULL PRIMARY KEY,"
        " applied_at DATETIME2 NOT NULL CONSTRAINT df_schema_migrations_applied"
        " DEFAULT SYSUTCDATETIME())"
    )
    conn.commit()
    cur.execute("SELECT version FROM schema_migrations")
    applied = {row["version"] for row in cur.fetchall()}

    done_now: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        try:
            for batch in _GO_RE.split(path.read_text(encoding="utf-8")):
                if batch.strip():
                    cur.execute(batch)
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        log.info("migration applied: %s", path.name)
        done_now.append(path.name)
    if not done_now:
        log.info("migrations: nothing to apply")
    return done_now
