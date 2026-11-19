"""Connection retry and the migration runner, tested against a recording connection."""

import pymssql
import pytest

import db as dbmod


class RecordingConnection:
    """Records statements. Migration bookkeeping is answered from `applied`."""

    def __init__(self, applied=(), fail_on=None):
        self.applied = set(applied)
        self.fail_on = fail_on
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self._rows: list = []

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.statements.append(sql)
        self._rows = []
        if sql.startswith("SELECT version FROM schema_migrations"):
            self._rows = [{"version": v} for v in sorted(self.applied)]
        elif sql.startswith("INSERT INTO schema_migrations"):
            self.applied.add(params[0])
        elif self.fail_on and self.fail_on in sql:
            raise pymssql.Error("statement failed")

    def fetchall(self):
        return list(self._rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# -- parse_database_url --------------------------------------------------------

def test_parse_database_url_reads_every_part_and_decodes_the_password():
    params = dbmod.parse_database_url("mssql://spots_app:p%40ss%2Fw@db.example:1500/spots_db")
    assert params == {
        "server": "db.example",
        "port": 1500,
        "user": "spots_app",
        "password": "p@ss/w",
        "database": "spots_db",
    }


def test_parse_database_url_defaults_the_port_to_1433():
    assert dbmod.parse_database_url("mssql://u:p@host/db")["port"] == 1433


def test_parse_database_url_rejects_other_schemes():
    with pytest.raises(ValueError):
        dbmod.parse_database_url("postgres://u:p@host/db")


# -- connect --------------------------------------------------------------------

def test_connect_retries_then_succeeds(monkeypatch):
    sleeps = []
    outcomes = [pymssql.Error("warming up"), pymssql.Error("warming up"), "connection"]

    def fake_connect(**kwargs):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(dbmod.pymssql, "connect", fake_connect)
    monkeypatch.setattr(dbmod.time, "sleep", sleeps.append)
    assert dbmod.connect("mssql://u:p@host/db") == "connection"
    assert sleeps == [1.0, 2.0]


def test_connect_gives_up_after_the_last_attempt_with_capped_backoff(monkeypatch):
    sleeps = []

    def always_fails(**kwargs):
        raise pymssql.Error("down")

    monkeypatch.setattr(dbmod.pymssql, "connect", always_fails)
    monkeypatch.setattr(dbmod.time, "sleep", sleeps.append)
    with pytest.raises(pymssql.Error):
        dbmod.connect("mssql://u:p@host/db", attempts=6)
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 8.0], "backoff doubles and stops at 8 seconds"


# -- migrate ----------------------------------------------------------------------

def test_migrate_applies_the_shipped_migration_once(monkeypatch):
    conn = RecordingConnection()
    assert dbmod.migrate(conn) == ["001_init.sql"]
    assert conn.commits >= 2, "bookkeeping table commit, then one commit per migration"
    assert "001_init.sql" in conn.applied

    assert dbmod.migrate(conn) == [], "a second run applies nothing"


def test_migrate_splits_on_go_and_runs_each_batch(monkeypatch):
    conn = RecordingConnection()
    text = (dbmod.MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8")
    expected_batches = [b for b in dbmod._GO_RE.split(text) if b.strip()]
    dbmod.migrate(conn)
    batch_statements = [s for s in conn.statements
                        if not s.startswith(("IF OBJECT_ID", "SELECT version", "INSERT INTO schema"))]
    assert len(batch_statements) == len(expected_batches)


def test_migrate_runs_files_in_order_and_stops_on_a_failure(tmp_path, monkeypatch):
    (tmp_path / "001_first.sql").write_text("CREATE TABLE a (x INT)\nGO\nCREATE TABLE b (y INT)")
    (tmp_path / "002_broken.sql").write_text("BROKEN STATEMENT")
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", tmp_path)

    conn = RecordingConnection(fail_on="BROKEN")
    with pytest.raises(pymssql.Error):
        dbmod.migrate(conn)
    assert conn.rollbacks == 1
    assert conn.applied == {"001_first.sql"}, "the failed file is not recorded"


def test_migrate_logs_when_nothing_is_pending(monkeypatch, caplog):
    conn = RecordingConnection(applied={"001_init.sql"})
    with caplog.at_level("INFO", logger="db"):
        assert dbmod.migrate(conn) == []
    assert "nothing to apply" in caplog.text
