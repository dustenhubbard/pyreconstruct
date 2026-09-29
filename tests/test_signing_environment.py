"""The signing secrets reach only v* tag builds.

The five macOS signing secrets and UPDATE_SIGNING_KEY live in the `release`
GitHub environment, which accepts only v* tags. build-installers.yml's build
job (macOS signing) and release job (SHA256SUMS signing) ask for that
environment only on a v* tag ref, so a manual dispatch on a branch gets no
secrets and builds the unsigned app (the signing steps' documented fallback).
A later edit that dropped the condition would ask every ref for the
environment, and a branch run would then fail its deployment instead of
building; one that dropped the environment would stop signing entirely. Both
fail here by name.

Each secret is read only in the job that needs it, and UPDATE_SIGNING_KEY only
in the one step that signs, which runs no action.
"""
import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "build-installers.yml"
SECRETS = ("MACOS_CERT_P12", "MACOS_CERT_PASSWORD", "APPLE_ID", "APPLE_APP_PASSWORD", "APPLE_TEAM_ID")
UPDATE_KEY = "UPDATE_SIGNING_KEY"
SIGN_STEP = "Sign SHA256SUMS"
ENVIRONMENT = "environment: ${{ startsWith(github.ref, 'refs/tags/v') && 'release' || '' }}"


def _jobs() -> dict:
    """Each job's text, keyed by name, from the two-space job keys under `jobs:`."""
    text = WORKFLOW.read_text()
    body = text[text.index("\njobs:\n") + len("\njobs:\n"):]
    starts = [(m.group(1), m.start()) for m in re.finditer(r"^  ([\w-]+):\n", body, re.M)]
    return {name: body[start:(starts[i + 1][1] if i + 1 < len(starts) else len(body))]
            for i, (name, start) in enumerate(starts)}


def _build_job() -> str:
    return _jobs()["build"]


def _steps(job: str) -> list:
    return re.split(r"\n(?=      - )", job)[1:]


def test_build_job_uses_the_release_environment_only_on_v_tags():
    job = _build_job()
    lines = [l.strip() for l in job.splitlines() if re.match(r"\s{4}environment:", l)]
    assert lines == [ENVIRONMENT], lines


def test_release_job_uses_the_release_environment_only_on_v_tags():
    job = _jobs()["release"]
    lines = [l.strip() for l in job.splitlines() if re.match(r"\s{4}environment:", l)]
    assert lines == [ENVIRONMENT], lines


def test_no_other_job_asks_for_an_environment():
    jobs = _jobs()
    assert {"build", "release", "readme-bump"} <= set(jobs), sorted(jobs)
    asking = sorted(n for n, job in jobs.items() if re.search(r"^\s+environment:", job, re.M))
    assert asking == ["build", "release"]


def test_every_signing_secret_is_read_only_inside_the_build_job():
    text = WORKFLOW.read_text()
    job = _build_job()
    for name in SECRETS:
        uses = text.count(f"secrets.{name}")
        assert uses >= 1, f"{name} is no longer used; update this test with the workflow"
        assert job.count(f"secrets.{name}") == uses, (
            f"{name} is read outside the build job, which has no release environment"
        )


def test_the_update_key_is_read_only_by_the_signing_step():
    text = WORKFLOW.read_text()
    assert text.count(f"secrets.{UPDATE_KEY}") == 1, "read once, in one step"
    steps = _steps(_jobs()["release"])
    reading = [i for i, s in enumerate(steps) if f"secrets.{UPDATE_KEY}" in s]
    assert len(reading) == 1
    step = steps[reading[0]]
    assert step.startswith(f"      - name: {SIGN_STEP}\n"), step.splitlines()[0]
    # Mapped into the step's env for its own shell, never handed to an action.
    assert f"          {UPDATE_KEY}: ${{{{ secrets.{UPDATE_KEY} }}}}\n" in step
    assert not re.search(r"^\s+uses:", step, re.M)
    assert not re.search(r"^\s+with:", step, re.M)
    assert "secrets: inherit" not in text
    # The steps after it cannot see it either: no step but this one names it.
    others = [s.splitlines()[0] for i, s in enumerate(steps) if UPDATE_KEY in s and i != reading[0]]
    assert others == []


def test_no_other_workflow_names_the_update_key():
    for path in WORKFLOW.parent.glob("*.y*ml"):
        if path != WORKFLOW:
            assert UPDATE_KEY not in path.read_text(), path.name


def test_nightly_tags_are_v_tags():
    """The nightly signs only because its tag starts with v."""
    nightly = (WORKFLOW.parent / "nightly.yml").read_text()
    assert "NIGHTLY_RE='^v[0-9]" in nightly
