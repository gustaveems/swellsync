"""The required checks on main must match the job names in ci.yml.

The `Main` ruleset on GitHub requires each check by its display name. A job
renamed in ci.yml without a matching change to the ruleset would leave the
ruleset waiting for a check that never reports, so the merge stays blocked.
This test fails first, in the same pull request, when the two drift apart.
"""

import yaml

from tests.support.services import ROOT

# Keep in step with the required status checks on the `Main` ruleset.
REQUIRED_CHECKS = {
    "lint",
    "unit tests spots",
    "unit tests sessions",
    "cross-seam integration",
    "contracts (OpenAPI and system.yaml)",
}


def ci_check_names():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    names = set()
    for job in workflow["jobs"].values():
        name = job.get("name", "")
        matrix = job.get("strategy", {}).get("matrix", {})
        if "${{ matrix.service }}" in name:
            names.update(name.replace("${{ matrix.service }}", svc) for svc in matrix["service"])
        else:
            names.add(name)
    return names


def test_every_required_check_is_a_job_in_ci():
    assert REQUIRED_CHECKS <= ci_check_names()


def test_ci_has_no_check_the_ruleset_does_not_require():
    # A new job should be added to REQUIRED_CHECKS on purpose, not left out.
    assert ci_check_names() == REQUIRED_CHECKS
