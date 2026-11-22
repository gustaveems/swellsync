"""Load a service's app module for tests.

Both services ship a module named `app`, `db` and `domain_logic`, so each load
unloads those names first. Loaded modules keep their own references, so two
services can be loaded in the same test session.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_SERVICE_MODULES = ("app", "db", "domain_logic")


def load_service(name: str, database) -> ModuleType:
    """Import services/<name>/app.py. `database` serves the boot step only.

    The module builds its app at import time, which runs migrate and seed.
    Both are pointed at `database` for that import and restored afterwards.
    """
    service_dir = str(ROOT / "services" / name)
    for module_name in _SERVICE_MODULES:
        sys.modules.pop(module_name, None)
    os.environ["DATABASE_URL"] = f"mssql://{name}_app:test-only@localhost:1433/{name}_db"
    sys.path.insert(0, service_dir)
    try:
        dbmod = importlib.import_module("db")
        with mock.patch.object(dbmod, "connect", database.connect), \
                mock.patch.object(dbmod, "migrate", lambda conn: []):
            return importlib.import_module("app")
    finally:
        sys.path.remove(service_dir)


def build_app(module: ModuleType, database, monkeypatch):
    """Build a fresh Flask app for one test, bound to `database`."""
    monkeypatch.setattr(module.dbmod, "connect", database.connect)
    monkeypatch.setattr(module.dbmod, "migrate", lambda conn: [])
    app = module.create_app()
    app.testing = True
    return app
