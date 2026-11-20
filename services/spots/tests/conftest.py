"""Shared fixtures for the spots service tests.

The app is loaded once per session with a throwaway database. Each test then
builds its own app against a fresh fake database, so tests cannot leak state.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "spots"))  # so `import db` finds this service

from tests.support.fakes import FakeSpotsDatabase, unused_url  # noqa: E402
from tests.support.services import build_app, load_service  # noqa: E402


@pytest.fixture(scope="session")
def spots_module():
    return load_service("spots", FakeSpotsDatabase())


@pytest.fixture(autouse=True)
def _sessions_unreachable_by_default(spots_module, monkeypatch):
    """Point the sessions URL at nothing unless a test sets it up."""
    monkeypatch.setattr(spots_module, "SESSIONS_URL", unused_url())
    monkeypatch.setattr(spots_module, "SESSIONS_TIMEOUT_S", 0.5)


@pytest.fixture
def database():
    """A fresh database. Building an app seeds it with the four seed spots."""
    return FakeSpotsDatabase()


@pytest.fixture
def client(spots_module, database, monkeypatch):
    return build_app(spots_module, database, monkeypatch).test_client()
