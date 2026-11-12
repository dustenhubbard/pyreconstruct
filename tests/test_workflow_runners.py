"""Jobs must not use macOS 14 images retired by GitHub on 2026-11-02."""

from pathlib import Path
import re

import pytest
import yaml


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_jobs_do_not_request_retired_macos_14_images(path):
    workflow = yaml.safe_load(path.read_text())
    for name, job in workflow["jobs"].items():
        runners = list(_strings(job.get("runs-on")))
        runners.extend(_strings(job.get("strategy", {}).get("matrix")))
        retired = [runner for runner in runners if re.fullmatch(r"macos-14(?:-.*)?", runner)]
        assert not retired, f"{path.name}:{name} requests retired runners: {retired}"
