"""The signing secrets reach only v* tag builds.

The five macOS signing secrets and UPDATE_SIGNING_KEY live in the `release`
GitHub environment, which accepts only v* tags. build-installers.yml's build
job (macOS signing) and sign job (SHA256SUMS signing) ask for that
environment only on a v* tag ref, so a manual dispatch on a branch gets no
secrets and builds the unsigned app (the macOS signing step's documented
fallback; the sign job runs only on v* tags, and fails there without the
key rather than publish unsigned).
A later edit that dropped the condition would ask every ref for the
environment, and a branch run would then fail its deployment instead of
building; one that dropped the environment would stop signing entirely. Both
fail here by name.

Each secret is read only in the job that needs it, and UPDATE_SIGNING_KEY only
in the one step that signs, which runs no action. That step has a job of its
own: a step can set environment variables for the later steps of its job
(GITHUB_ENV, so BASH_ENV or LD_PRELOAD too), so the job with the key runs no
checkout and no package install, and gets SHA256SUMS and nothing else.
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


def test_sign_job_uses_the_release_environment_only_on_v_tags():
    job = _jobs()["sign"]
    lines = [l.strip() for l in job.splitlines() if re.match(r"\s{4}environment:", l)]
    assert lines == [ENVIRONMENT], lines


def test_no_other_job_asks_for_an_environment():
    jobs = _jobs()
    assert {"build", "release", "sign", "publish"} <= set(jobs), sorted(jobs)
    asking = sorted(n for n, job in jobs.items() if re.search(r"^\s+environment:", job, re.M))
    assert asking == ["build", "sign"]


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
    steps = _steps(_jobs()["sign"])
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


def _uses(job: str) -> list:
    return re.findall(r"^\s+(?:- )?uses: (\S+)", job, re.M)


def _with(step: str) -> dict:
    block = step.split("\n        with:\n", 1)[1]
    pairs = re.findall(r"^          ([\w-]+): (.*)$", block, re.M)
    return {k: v.split("  #", 1)[0].strip() for k, v in pairs}


def _step(job: str, name: str) -> str:
    [step] = [s for s in _steps(_jobs()[job]) if s.startswith(f"      - name: {name}\n")]
    return step


def test_the_key_job_gets_sha256sums_and_nothing_else():
    """No checkout, no package index, and no action but the two artifact ones."""
    job = _jobs()["sign"]
    names = [s.split("- name: ", 1)[1].split("\n", 1)[0] for s in _steps(job)]
    assert names == ["Get SHA256SUMS", "Install minisign", SIGN_STEP,
                     "Hand the signature to the publish job"]
    uses = _uses(job)
    assert [u.split("@", 1)[0] for u in uses] == ["actions/download-artifact",
                                                   "actions/upload-artifact"]
    for use in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", use), use
    code = "\n".join(l.split("  # ", 1)[0] for l in job.splitlines()
                     if not l.lstrip().startswith("#"))
    for word in ("checkout", "pip install", "uv ", "npm", "python", "git "):
        assert word not in code, word
    assert "    permissions: {}\n" in job
    assert "    needs: release\n" in job

    get = _with(_step("sign", "Get SHA256SUMS"))
    assert get == {"name": "sha256sums", "path": "dist"}
    hand = _with(_step("release", "Hand SHA256SUMS to the sign job"))
    assert hand["name"] == "sha256sums" and hand["path"] == "dist/SHA256SUMS"
    # Only the release job uploads that name, so nothing else can ride along.
    text = WORKFLOW.read_text()
    assert text.count("name: sha256sums\n") == 2


def test_the_signature_reaches_the_publish_job():
    hand = _with(_step("sign", "Hand the signature to the publish job"))
    assert hand["name"] == "sha256sums-signature"
    assert hand["path"] == "dist/SHA256SUMS.minisig"
    assert hand["if-no-files-found"] == "error"
    publish = _jobs()["publish"]
    assert "    needs: [release, sign]\n" in publish
    assert "needs.sign.result == 'success'" in publish
    assert _with(_step("publish", "Get the release files")) == {"name": "release-files", "path": "dist"}
    assert _with(_step("publish", "Get the signature")) == {"name": "sha256sums-signature", "path": "dist"}
    assert "files: dist/*" in publish


def test_the_jobs_around_the_key_never_name_it():
    jobs = _jobs()
    for name in ("release", "publish"):
        assert UPDATE_KEY not in jobs[name], name
        assert "environment:" not in jobs[name], name


def test_no_other_workflow_names_the_update_key():
    for path in WORKFLOW.parent.glob("*.y*ml"):
        if path != WORKFLOW:
            assert UPDATE_KEY not in path.read_text(), path.name


def test_nightly_tags_are_v_tags():
    """The nightly signs only because its tag starts with v."""
    nightly = (WORKFLOW.parent / "nightly.yml").read_text()
    assert "NIGHTLY_RE='^v[0-9]" in nightly
