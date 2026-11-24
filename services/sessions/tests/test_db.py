"""The boot lock in the sessions copy of db.py (the spots copy has the same tests)."""

import pymssql
import pytest

import db as dbmod


# -- boot_lock --------------------------------------------------------------------

class LockConnection:
    """Answers sp_getapplock with `code` and records every statement."""

    def __init__(self, code=0, release_fails=False):
        self.code = code
        self.release_fails = release_fails
        self.statements: list[str] = []
        self._row = None

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.statements.append(sql)
        self._row = {"r": self.code} if "sp_getapplock" in sql else None
        if "sp_releaseapplock" in sql and self.release_fails:
            raise pymssql.Error("connection lost")

    def fetchone(self):
        return self._row


def test_boot_lock_is_taken_before_the_block_and_released_after():
    conn = LockConnection(code=0)
    with dbmod.boot_lock(conn):
        conn.execute("WORK")
    assert ["sp_getapplock" in conn.statements[0], conn.statements[1],
            "sp_releaseapplock" in conn.statements[2]] == [True, "WORK", True]


def test_boot_lock_accepts_a_lock_granted_after_waiting():
    conn = LockConnection(code=1)  # 1 means granted after another session released it
    with dbmod.boot_lock(conn):
        pass
    assert "sp_releaseapplock" in conn.statements[-1]


@pytest.mark.parametrize("code", [-1, -2, -3, -999])
def test_boot_lock_refuses_to_boot_when_the_lock_is_not_granted(code):
    conn = LockConnection(code=code)
    with pytest.raises(RuntimeError, match=str(code)):
        with dbmod.boot_lock(conn):
            raise AssertionError("the block must not run")


def test_boot_lock_is_released_when_the_block_fails():
    conn = LockConnection(code=0)
    with pytest.raises(ValueError):
        with dbmod.boot_lock(conn):
            raise ValueError("migration failed")
    assert "sp_releaseapplock" in conn.statements[-1]


def test_a_failed_release_does_not_hide_the_boot(caplog):
    conn = LockConnection(code=0, release_fails=True)
    with caplog.at_level("WARNING", logger="db"):
        with dbmod.boot_lock(conn):
            pass
    assert "could not release the boot lock" in caplog.text
