"""The SQL users script must name the databases system.yaml deploys, and stay narrow.

The script itself is proved against SQL Server 2022 (docs/evidence/boot-lock-and-sql-users.md).
These checks keep it in step with system.yaml without a database.
"""

import importlib.util

import pytest
import yaml

from tests.support.services import ROOT


def load_script():
    path = ROOT / "scripts" / "azure" / "create_sql_users.py"
    spec = importlib.util.spec_from_file_location("create_sql_users", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return load_script()


def test_the_script_covers_exactly_the_services_in_system_yaml(script):
    system = yaml.safe_load((ROOT / "system.yaml").read_text(encoding="utf-8"))
    assert set(script.SERVICES) == set(system["services"])
    for name, service in system["services"].items():
        assert f"{system['prefix']}-{name}-db" == service["azure"]["sql_database"]


def test_each_user_gets_only_the_roles_the_service_needs(script):
    assert script.ROLES == ("db_ddladmin", "db_datareader", "db_datawriter")
    create, *grants = script.statements("spots_app")
    assert "CREATE USER [spots_app] WITH PASSWORD = %s" in create
    assert "ALTER USER [spots_app] WITH PASSWORD = %s" in create, "a second run rotates the password"
    assert grants == [f"ALTER ROLE {role} ADD MEMBER [spots_app]" for role in script.ROLES]


@pytest.mark.parametrize("bad", ["spots]; DROP TABLE spots;--", "a b", ""])
def test_names_that_could_break_out_of_brackets_are_refused(script, bad):
    with pytest.raises(ValueError):
        script.statements(bad)


def test_missing_passwords_stop_the_script_before_it_connects(script, monkeypatch, capsys):
    for name in ("SQL_ADMIN_PASSWORD", "SPOTS_DB_PASSWORD", "SESSIONS_DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(script.pymssql, "connect", lambda **kw: pytest.fail("must not connect"))
    assert script.main(["--server", "s", "--admin", "a"]) == 2
    assert "SQL_ADMIN_PASSWORD" in capsys.readouterr().err
