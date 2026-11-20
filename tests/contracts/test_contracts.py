"""Contract checks: the OpenAPI documents, the running apps and system.yaml must agree.

A route added to an app without a document entry, or a call that the other
side does not document, fails here before it reaches a deployment.
"""

import re

import pytest
import yaml
from openapi_spec_validator import validate

from tests.support.fakes import FakeSessionsDatabase, FakeSpotsDatabase
from tests.support.services import ROOT, build_app, load_service

SERVICES = ("spots", "sessions")
HTTP_METHODS = {"get", "put", "post", "delete", "patch"}
DATABASES = {"spots": FakeSpotsDatabase, "sessions": FakeSessionsDatabase}


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def openapi_of(name):
    return read_yaml(ROOT / "services" / name / "openapi.yaml")


def documented_operations(spec):
    return {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }


def routed_operations(app):
    operations = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule)
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            operations.add((method, path))
    return operations


@pytest.mark.parametrize("name", SERVICES)
def test_openapi_document_is_valid(name):
    validate(openapi_of(name))


@pytest.mark.parametrize("name", SERVICES)
def test_the_running_app_serves_exactly_the_documented_operations(name, monkeypatch):
    module = load_service(name, DATABASES[name]())
    app = build_app(module, DATABASES[name](), monkeypatch)
    assert routed_operations(app) == documented_operations(openapi_of(name))


@pytest.mark.parametrize("name", SERVICES)
def test_every_service_documents_its_health_endpoint(name):
    assert ("GET", "/health") in documented_operations(openapi_of(name))


# -- system.yaml ----------------------------------------------------------------

@pytest.fixture(scope="module")
def system():
    return read_yaml(ROOT / "system.yaml")


def test_system_yaml_lists_both_services_with_matching_documents(system):
    assert set(system["services"]) == set(SERVICES)
    for name, service in system["services"].items():
        assert service["health"] == "/health"
        assert (ROOT / service["openapi"]).is_file(), f"{name}: openapi file is missing"
        assert (ROOT / service["path"]).is_dir(), f"{name}: service path is missing"


def test_every_call_is_documented_by_the_service_it_calls(system):
    for name, service in system["services"].items():
        for call in service.get("calls", []):
            documented = documented_operations(openapi_of(call["service"]))
            for endpoint in call["endpoints"]:
                method, path = endpoint.split(" ", 1)
                assert (method, path) in documented, (
                    f"{name} calls {endpoint}, which {call['service']} does not document"
                )


def test_every_call_url_is_an_env_var_the_caller_declares(system):
    for name, service in system["services"].items():
        for call in service.get("calls", []):
            assert call["url_env"] in service["env"], f"{name} does not declare {call['url_env']}"


def test_azure_names_share_the_student_prefix(system):
    prefix = system["prefix"]
    assert system["student"].replace(".", "-") == prefix
    assert system["ui"]["static_web_app"].startswith(prefix)
    for name, service in system["services"].items():
        assert service["azure"]["container_app"].startswith(prefix), name
        assert service["azure"]["sql_database"].startswith(prefix), name


def test_system_yaml_matches_the_course_schema_when_it_is_present(system):
    schema_path = ROOT / "system.schema.json"
    if not schema_path.exists():
        pytest.skip("system.schema.json is not in the repo yet (course file pending)")
    import json

    import jsonschema

    jsonschema.validate(system, json.loads(schema_path.read_text(encoding="utf-8")))
