"""Shared fixtures for the sessions service tests.

The spots service is replaced by a directory object that the tests control.
Real HTTP to spots is covered by tests/integration, against a stub server.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.support.fakes import FakeSessionsDatabase, unused_url  # noqa: E402
from tests.support.services import build_app, load_service  # noqa: E402


@pytest.fixture(scope="session")
def sessions_module():
    return load_service("sessions", FakeSessionsDatabase())


@pytest.fixture(autouse=True)
def _spots_unreachable_by_default(sessions_module, monkeypatch):
    monkeypatch.setattr(sessions_module, "SPOTS_URL", unused_url())
    monkeypatch.setattr(sessions_module, "SPOTS_TIMEOUT_S", 0.5)


class SpotsDirectory:
    """Stands in for the spots service's HTTP answers. Set `down` to make it unreachable."""

    def __init__(self, module):
        self._module = module
        self.known = {1: "Ocean Beach North", 2: "Mavericks", 3: "Ho'okipa", 4: "Newport Harbor"}
        self.down = False
        self.paths: list[str] = []

    def get(self, path):
        self.paths.append(path)
        if self.down:
            raise self._module.UpstreamUnavailable("spots is down")
        if path == "/spots":
            return 200, {"spots": [{"id": i, "name": n} for i, n in self.known.items()]}
        spot_id = int(path.rsplit("/", 1)[1])
        if spot_id in self.known:
            return 200, {"id": spot_id, "name": self.known[spot_id]}
        return 404, None


@pytest.fixture
def spots(sessions_module, monkeypatch):
    directory = SpotsDirectory(sessions_module)
    monkeypatch.setattr(sessions_module, "_spots_get", directory.get)
    return directory


@pytest.fixture
def database():
    """A fresh database. Building an app seeds it with the six seed sessions."""
    return FakeSessionsDatabase()


@pytest.fixture
def client(sessions_module, database, monkeypatch):
    return build_app(sessions_module, database, monkeypatch).test_client()

