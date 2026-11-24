"""The workflow files of the repository, read as data (spec 008, contracts/workflows.md, SC-005).

They are not run here: the rules that keep a workflow that may one day hold write access safe, and the shape
that makes CI and the release run one definition of the checks, are asserted on the parsed YAML. The tests
read every file under `.github/workflows/`, so a file added later is held to the same rules.

Section 1: the rules for every file, `wheel.yml` and `python.yml`.
Section 2: `release.yml`, the one job that may write and what it may not hold.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from release_fixtures import REPO

WORKFLOWS = REPO / ".github" / "workflows"
SHA_USE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
USE_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
VERSION_COMMENT = re.compile(r"^\s+#\s*v\d+\.\d+\.\d+\s*$")
LOCAL_USE = "./.github/workflows/"


def workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def workflow(name: str) -> dict[str, Any]:
    path = WORKFLOWS / name
    if not path.is_file():
        pytest.fail(f"{path} is missing; run the tests from a repository checkout", pytrace=False)
    return load(path)


def triggers(doc: dict[str, Any]) -> dict[str, Any]:
    """PyYAML reads the key `on:` as the boolean True."""
    found = doc["on"] if "on" in doc else doc[True]
    return found if isinstance(found, dict) else {name: None for name in ([found] if isinstance(found, str) else found)}


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def runs(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in steps(job) if "run" in step]


def uses(job: dict[str, Any]) -> list[str]:
    found = [step["uses"] for step in steps(job) if "uses" in step]
    return found + ([job["uses"]] if "uses" in job else [])


def walk(node: Any) -> Iterator[tuple[str, Any]]:
    """Every (key, value) of a parsed document, however deep."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


@pytest.fixture(scope="module")
def files() -> list[Path]:
    found = workflow_files()
    if not found:
        pytest.fail(f"no workflow files under {WORKFLOWS}; run the tests from a repository checkout", pytrace=False)
    return found


# --- rules for every file under .github/workflows/ ---------------------------------------------------------


def each_file(test):
    return pytest.mark.parametrize("path", workflow_files() or [WORKFLOWS / "missing.yml"], ids=lambda p: p.name)(test)


@each_file
def test_the_top_level_permission_is_contents_read(path: Path) -> None:
    assert load(path).get("permissions") == {"contents": "read"}


@each_file
def test_every_action_is_a_full_sha_with_a_version_comment_or_a_local_workflow(path: Path) -> None:
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        match = USE_LINE.match(line)
        if not match:
            continue
        ref = match["ref"]
        if ref.startswith(LOCAL_USE):
            continue
        assert SHA_USE.match(ref), f"{path.name}:{number} {ref} is not pinned to a 40-hex commit"
        assert VERSION_COMMENT.match(match["rest"]), f"{path.name}:{number} has no '# vX.Y.Z' comment"


@each_file
def test_checkout_keeps_no_credentials_and_setup_uv_keeps_no_cache(path: Path) -> None:
    for job in load(path)["jobs"].values():
        for step in steps(job):
            action = step.get("uses", "").split("@")[0]
            if action == "actions/checkout":
                assert step.get("with", {}).get("persist-credentials") is False, step
            if action == "astral-sh/setup-uv":
                assert step.get("with", {}).get("enable-cache") is False, step


@each_file
def test_no_run_script_holds_an_expression(path: Path) -> None:
    for job_id, job in load(path)["jobs"].items():
        for script in runs(job):
            assert "${{" not in script, f"{path.name} job {job_id}: values go through env:, not into run:"


@each_file
def test_no_run_script_writes_the_environment_files(path: Path) -> None:
    for job in load(path)["jobs"].values():
        for script in runs(job):
            assert "GITHUB_ENV" not in script and "GITHUB_PATH" not in script


@each_file
def test_no_secret_no_token_for_another_service_and_no_wide_permission(path: Path) -> None:
    text = path.read_text()
    assert "secrets" not in text, "no secrets context and no `secrets: inherit`"
    doc = load(path)
    for key, value in walk(doc):
        if key == "permissions" and isinstance(value, dict):
            assert set(value) <= {"contents"}, f"{path.name}: only `contents` is ever granted, got {sorted(value)}"
            assert value["contents"] in {"read", "write"}


@each_file
def test_no_dangerous_trigger(path: Path) -> None:
    names = set(triggers(load(path)))
    assert not names & {"pull_request_target", "workflow_run"}, names


@each_file
def test_everything_has_a_name(path: Path) -> None:
    doc = load(path)
    assert doc.get("name"), f"{path.name} has no name"
    for job_id, job in doc["jobs"].items():
        assert job.get("name"), f"{path.name} job {job_id} has no name"
        for step in steps(job):
            assert step.get("name"), f"{path.name} job {job_id} has an unnamed step: {step}"


@each_file
def test_a_job_that_runs_on_a_runner_names_the_runner_image(path: Path) -> None:
    for job in load(path)["jobs"].values():
        if "runs-on" in job:
            assert job["runs-on"] == "ubuntu-24.04"


@pytest.mark.parametrize("name", ["python.yml", "release.yml"])
def test_only_wheel_yml_builds_tests_and_holds_the_matrix(name: str) -> None:
    path = WORKFLOWS / name
    if not path.is_file():
        pytest.skip(f"{name} does not exist yet")  # release.yml is written in a later phase
    doc = load(path)
    for job_id, job in doc["jobs"].items():
        for script in runs(job):
            assert "uv build" not in script and "pytest" not in script and "_only.py" not in script, (name, job_id)
        assert "strategy" not in job, f"{name} job {job_id} has its own matrix; the matrix is in wheel.yml only"


# --- wheel.yml: the one definition of the checks --------------------------------------------------------------


def test_wheel_yml_is_a_reusable_workflow_with_no_inputs_secrets_or_outputs() -> None:
    call = triggers(workflow("wheel.yml"))
    assert set(call) == {"workflow_call"}
    assert not call["workflow_call"], "workflow_call takes no inputs, no secrets and no outputs"


def test_wheel_yml_has_the_three_jobs_and_runs_from_python() -> None:
    doc = workflow("wheel.yml")
    assert set(doc["jobs"]) == {"build", "checks", "inspect"}
    assert doc["defaults"]["run"]["working-directory"] == "python"
    assert doc["jobs"]["checks"]["needs"] == "build" and doc["jobs"]["inspect"]["needs"] == "build"
    assert "needs" not in doc["jobs"]["build"]


def test_the_matrix_is_three_versions_and_does_not_stop_at_the_first_failure() -> None:
    strategy = workflow("wheel.yml")["jobs"]["checks"]["strategy"]
    assert strategy["fail-fast"] is False
    assert strategy["matrix"] == {"python": ["3.11", "3.12", "3.13"]}


def test_only_the_build_job_builds_and_it_builds_once() -> None:
    jobs = workflow("wheel.yml")["jobs"]
    assert sum(script.count("uv build") for script in runs(jobs["build"])) == 1
    for job_id in ("checks", "inspect"):
        assert not any("uv build" in script for script in runs(jobs[job_id])), job_id


def test_build_records_the_sums_and_uploads_one_artifact_named_dist() -> None:
    build = workflow("wheel.yml")["jobs"]["build"]
    scripts = "\n".join(runs(build))
    assert "cmp LICENSE ../LICENSE" in scripts
    assert "sums.py write --dir dist --summary" in scripts
    assert scripts.index("uv build") < scripts.index("sums.py write")
    upload = next(step for step in steps(build) if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["name"] == "dist"
    assert upload["with"]["if-no-files-found"] == "error"
    paths = str(upload["with"]["path"])
    assert "*.whl" in paths and "*.tar.gz" in paths and "SHA256SUMS" in paths


@pytest.mark.parametrize("job_id", ["checks", "inspect"])
def test_the_other_jobs_download_that_artifact_and_check_the_sums_first(job_id: str) -> None:
    job = workflow("wheel.yml")["jobs"][job_id]
    download = next(step for step in steps(job) if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"]["name"] == "dist" and download["with"]["path"] == "python/dist"
    scripts = runs(job)
    assert "sums.py check --dir dist" in scripts[0]


def test_checks_runs_the_suite_the_four_single_extra_scripts_and_the_adopters_path_in_that_order() -> None:
    scripts = "\n".join(runs(workflow("wheel.yml")["jobs"]["checks"]))
    order = [
        "sums.py check",
        "--group dev",
        "pytest",
        "core_only.py",
        "a2a_only.py",
        "mcp_only.py",
        "langgraph_only.py",
        "adopter_path.py",
    ]
    positions = [scripts.find(token) for token in order]
    assert all(p >= 0 for p in positions), dict(zip(order, positions, strict=True))
    assert positions == sorted(positions)


def test_the_python_version_reaches_a_run_script_only_through_the_environment() -> None:
    checks = workflow("wheel.yml")["jobs"]["checks"]
    assert any(step.get("env", {}).get("PYTHON") == "${{ matrix.python }}" for step in steps(checks))
    for step in steps(checks):
        if "run" in step and "--python" in step["run"]:
            assert '--python "$PYTHON"' in step["run"] and "env" in step, step["name"]
            assert step["env"]["PYTHON"] == "${{ matrix.python }}"


def test_the_adopters_path_installs_the_three_extras_and_uvicorn_and_no_dev_group() -> None:
    steps_ = workflow("wheel.yml")["jobs"]["checks"]["steps"]
    adopter = next(step for step in steps_ if "adopter_path.py" in step.get("run", ""))
    script = adopter["run"]
    assert ".adopter-venv" in script
    assert "[a2a,mcp,langgraph]" in script and "uvicorn" in script
    assert "--group" not in script and "pytest" not in script
    assert "-I tests/adopter_path.py" in script


def test_inspect_checks_the_content_and_scans_both_archives() -> None:
    scripts = "\n".join(runs(workflow("wheel.yml")["jobs"]["inspect"]))
    assert "content.py --dir dist" in scripts
    assert "scan.py dist/*.whl dist/*.tar.gz" in scripts


def test_no_job_of_wheel_yml_asks_for_more_than_read() -> None:
    for job in workflow("wheel.yml")["jobs"].values():
        assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}


# --- python.yml: CI only calls it -----------------------------------------------------------------------------


def test_ci_keeps_its_triggers() -> None:
    assert triggers(workflow("python.yml")) == {"push": {"branches": ["main"]}, "pull_request": None}


def test_ci_is_one_job_that_calls_wheel_yml_and_nothing_else() -> None:
    doc = workflow("python.yml")
    assert list(doc["jobs"]) == ["wheel"]
    job = doc["jobs"]["wheel"]
    assert job["uses"] == "./.github/workflows/wheel.yml"
    assert set(job) <= {"name", "uses", "permissions"}
    assert job["permissions"] == {"contents": "read"}


# --- release.yml: the job that may write (section 2) ----------------------------------------------------------

ENV_VALUES = {
    "EVENT": "${{ github.event_name }}",
    "REF_TYPE": "${{ github.ref_type }}",
    "TAG": "${{ github.ref_name }}",
    "SHA": "${{ github.sha }}",
    "REPOSITORY": "${{ github.repository }}",
}
NOT_IN_THE_WRITING_JOB = [r"setup-uv", r"\bpip\b", r"\buv\b", r"python3?\s+-m\b", r"python3?\s+-c\b", r"\bimport\b", r"\binstall\b"]


def release_jobs() -> dict[str, Any]:
    return workflow("release.yml")["jobs"]


def needs(job: dict[str, Any]) -> list[str]:
    found = job.get("needs", [])
    return [found] if isinstance(found, str) else sorted(found)


def script_of(job: dict[str, Any], marker: str) -> str:
    return next(script for script in runs(job) if marker in script)


def test_release_yml_starts_on_a_tag_push_or_a_manual_start_and_on_nothing_else() -> None:
    assert triggers(workflow("release.yml")) == {"push": {"tags": ["v*"]}, "workflow_dispatch": None}


def test_the_four_jobs_and_what_each_waits_for() -> None:
    jobs = release_jobs()
    assert list(jobs) == ["preflight", "wheel", "publish", "verify"]
    assert [needs(jobs[j]) for j in jobs] == [[], ["preflight"], ["preflight", "wheel"], ["publish"]]


def test_publish_and_verify_run_for_a_tag_push_and_never_for_a_manual_start() -> None:
    jobs = release_jobs()
    for job_id in ("publish", "verify"):
        assert jobs[job_id]["if"] == "github.event_name == 'push'", job_id
    for job_id in ("preflight", "wheel"):
        assert "if" not in jobs[job_id], f"{job_id} runs on a manual start too"


def test_a_release_is_never_cancelled_by_another_run() -> None:
    assert workflow("release.yml")["concurrency"] == {"group": "release-${{ github.ref }}", "cancel-in-progress": False}


def test_exactly_one_job_may_write_and_it_is_publish() -> None:
    jobs = release_jobs()
    assert [j for j, job in jobs.items() if job.get("permissions", {}).get("contents") == "write"] == ["publish"]
    assert workflow_text("release.yml").count("contents: write") == 1
    for job_id in ("preflight", "wheel", "verify"):
        assert jobs[job_id]["permissions"] == {"contents": "read"}, job_id


def workflow_text(name: str) -> str:
    return (WORKFLOWS / name).read_text()


def test_the_writing_job_installs_nothing_and_runs_only_the_publishing_script() -> None:
    publish = release_jobs()["publish"]
    everything = yaml.safe_dump(publish["steps"])
    for pattern in NOT_IN_THE_WRITING_JOB:
        assert not re.search(pattern, everything), f"publish must not hold {pattern!r}"
    assert len(runs(publish)) == 1 and runs(publish)[0].startswith("python3 scripts/release/publish.py")
    assert not re.search(r"python3?\s+\S*dist", runs(publish)[0]), "no file of the build is passed to an interpreter"
    actions = [step["uses"].split("@")[0] for step in steps(publish) if "uses" in step]
    assert actions == ["actions/checkout", "actions/download-artifact", "actions/download-artifact"]
    downloaded = {step["with"]["name"] for step in steps(publish) if step.get("uses", "").startswith("actions/download-artifact@")}
    assert downloaded == {"dist", "release-notes"}


def test_publish_gets_the_values_it_needs_through_env_and_calls_the_script_with_them() -> None:
    script = runs(release_jobs()["publish"])[0]
    assert script.strip() == (
        'python3 scripts/release/publish.py --tag "$TAG" --repository "$REPOSITORY" '
        "--dir dist --notes release-notes/RELEASE_NOTES.md"
    )


def test_the_token_is_the_workflows_own_and_reaches_only_preflight_and_publish() -> None:
    jobs = release_jobs()
    for job_id in ("preflight", "publish"):
        assert any(step.get("env", {}).get("GH_TOKEN") == "${{ github.token }}" for step in steps(jobs[job_id])), job_id
    for job_id in ("wheel", "verify"):
        assert "GH_TOKEN" not in yaml.safe_dump(jobs[job_id]), f"{job_id} must not hold a token"
    for key, value in walk(workflow("release.yml")):
        if "TOKEN" in key.upper():
            assert value == "${{ github.token }}", key


def test_each_value_comes_from_the_github_context_through_env_only() -> None:
    seen = set()
    for key, value in walk(workflow("release.yml")):
        if key in ENV_VALUES:
            assert value == ENV_VALUES[key], key
            seen.add(key)
    assert seen == set(ENV_VALUES)


def test_preflight_runs_first_with_the_whole_history_then_writes_and_uploads_the_notes() -> None:
    preflight = release_jobs()["preflight"]
    checkout = next(step for step in steps(preflight) if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    gate = script_of(preflight, "preflight.py")
    assert gate.strip() == (
        'python3 scripts/release/preflight.py --event "$EVENT" --ref-type "$REF_TYPE" --tag "$TAG" '
        '--sha "$SHA" --repository "$REPOSITORY"'
    )
    scripts = "\n".join(runs(preflight))
    assert scripts.index("preflight.py") < scripts.index("notes.py")
    assert 'notes.py --repository "$REPOSITORY" --out release-notes/RELEASE_NOTES.md' in scripts
    assert "$GITHUB_STEP_SUMMARY" in scripts
    upload = next(step for step in steps(preflight) if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["name"] == "release-notes" and upload["with"]["if-no-files-found"] == "error"


def test_the_release_runs_the_one_definition_of_the_checks() -> None:
    wheel = release_jobs()["wheel"]
    assert wheel["uses"] == "./.github/workflows/wheel.yml"
    assert set(wheel) <= {"name", "uses", "needs", "permissions"}


def test_verify_reads_the_public_files_without_a_token_and_installs_the_address_in_a_clean_venv() -> None:
    verify = release_jobs()["verify"]
    scripts = "\n".join(runs(verify))
    assert 'verify.py --tag "$TAG" --repository "$REPOSITORY" --dir public' in scripts
    assert "uv venv" in scripts and "ext-r2c[a2a,mcp,langgraph] @ $ADDRESS" in scripts
    assert "ext_r2c.__version__" in scripts and "from ext_r2c import Remote" in scripts
    assert scripts.index("verify.py") < scripts.index("uv pip install")
