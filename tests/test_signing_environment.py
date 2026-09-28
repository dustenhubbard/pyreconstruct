"""The signing secrets reach only v* tag builds.

The five macOS signing secrets live in the `release` GitHub environment, which
accepts only v* tags. build-installers.yml's build job asks for that
environment only on a v* tag ref, so a manual dispatch on a branch gets no
secrets and builds the unsigned app (the signing step's documented fallback).
A later edit that dropped the condition would ask every ref for the
environment, and a branch run would then fail its deployment instead of
building; one that dropped the environment would stop signing entirely. Both
fail here by name.
"""
import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "build-installers.yml"
SECRETS = ("MACOS_CERT_P12", "MACOS_CERT_PASSWORD", "APPLE_ID", "APPLE_APP_PASSWORD", "APPLE_TEAM_ID")


def _build_job() -> str:
    text = WORKFLOW.read_text()
    start = text.index("\n  build:\n")
    end = text.index("\n  release:\n", start)
    return text[start:end]


def test_build_job_uses_the_release_environment_only_on_v_tags():
    job = _build_job()
    lines = [l.strip() for l in job.splitlines() if re.match(r"\s{4}environment:", l)]
    assert lines == [
        "environment: ${{ startsWith(github.ref, 'refs/tags/v') && 'release' || '' }}"
    ], lines


def test_every_signing_secret_is_read_only_inside_the_build_job():
    text = WORKFLOW.read_text()
    job = _build_job()
    for name in SECRETS:
        uses = text.count(f"secrets.{name}")
        assert uses >= 1, f"{name} is no longer used; update this test with the workflow"
        assert job.count(f"secrets.{name}") == uses, (
            f"{name} is read outside the build job, which has no release environment"
        )


def test_nightly_tags_are_v_tags():
    """The nightly signs only because its tag starts with v."""
    nightly = (WORKFLOW.parent / "nightly.yml").read_text()
    assert "NIGHTLY_RE='^v[0-9]" in nightly
