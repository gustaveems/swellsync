"""Migration 002 on the sessions table: order, batches, and no data loss.

These tests read the real migration files and run them through db.migrate with
a connection that records the statements. The SQL itself is proved against SQL
Server by the compose stack (see docs/evidence/migration-002.md).
"""

import db

MIGRATION_002 = "002_sessions_updated_at.sql"


class RecordingConnection:
    def __init__(self, applied=()):
        self.applied = set(applied)
        self.statements: list[str] = []
        self.commits = 0
        self._rows: list = []

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.statements.append(sql.strip())
        self._rows = []
        if sql.startswith("SELECT version FROM schema_migrations"):
            self._rows = [{"version": v} for v in sorted(self.applied)]
        elif sql.startswith("INSERT INTO schema_migrations"):
            self.applied.add(params[0])

    def fetchall(self):
        return list(self._rows)

    def commit(self):
        self.commits += 1

    def rollback(self):  # pragma: no cover - no statement fails here
        raise AssertionError("no migration should roll back")


def test_migrations_are_numbered_and_002_follows_001():
    names = sorted(p.name for p in db.MIGRATIONS_DIR.glob("*.sql"))
    assert names == ["001_init.sql", MIGRATION_002]


def test_a_database_at_001_applies_only_002():
    conn = RecordingConnection(applied={"001_init.sql"})
    assert db.migrate(conn) == [MIGRATION_002]
    assert MIGRATION_002 in conn.applied


def test_002_backfills_every_row_before_the_column_becomes_not_null():
    conn = RecordingConnection(applied={"001_init.sql"})
    db.migrate(conn)
    batches = [s for s in conn.statements if "updated_at" in s]
    assert [b.split()[0:3] for b in batches] == [
        ["--", "002:", "record"],  # the first batch carries the header comment
        ["UPDATE", "sessions", "SET"],
        ["ALTER", "TABLE", "sessions"],
        ["ALTER", "TABLE", "sessions"],
    ]
    assert "ADD updated_at DATETIME2 NULL" in batches[0]
    assert "SET updated_at = created_at WHERE updated_at IS NULL" in batches[1]
    assert "ALTER COLUMN updated_at DATETIME2 NOT NULL" in batches[2]
    assert "DEFAULT SYSUTCDATETIME() FOR updated_at" in batches[3]


def test_002_never_deletes_or_drops_anything():
    text = (db.MIGRATIONS_DIR / MIGRATION_002).read_text(encoding="utf-8").upper()
    for word in ("DELETE ", "DROP ", "TRUNCATE "):
        assert word not in text


def test_a_second_boot_applies_nothing():
    conn = RecordingConnection(applied={"001_init.sql", MIGRATION_002})
    assert db.migrate(conn) == []
