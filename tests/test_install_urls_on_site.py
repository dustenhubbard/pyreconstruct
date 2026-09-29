"""The short Linux install URLs on pyreconstruct.org serve the real scripts.

The curl commands in the docs and in the AppImage installer's own messages use
pyreconstruct.org/install.sh and pyreconstruct.org/install-from-source.sh. The
docs workflow copies the two scripts into the built site, and it reruns when
either script changes, so the site never serves an old copy. A rename of either
script, a dropped copy step, or a dropped path trigger fails here by name.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"
PUBLISHED = {
    "packaging/linux/install-appimage.sh": "site/install.sh",
    "packaging/linux/install.sh": "site/install-from-source.sh",
}


def _trigger_paths(event: str) -> list[str]:
    text = DOCS_WORKFLOW.read_text()
    block = text[text.index(f"\n  {event}:\n"):]
    block = block[block.index("paths:\n") + len("paths:\n"):]
    paths = []
    for line in block.splitlines():
        if not line.startswith("      - "):
            break
        paths.append(line.strip()[2:])
    return paths


def test_docs_build_copies_each_script_into_the_site():
    text = DOCS_WORKFLOW.read_text()
    for source, target in PUBLISHED.items():
        assert (ROOT / source).is_file(), f"{source} is gone; update docs.yml and this test"
        assert f"cp {source} {target}" in text, f"docs.yml no longer publishes {source} as {target}"


def test_a_script_change_redeploys_the_site():
    for event in ("push", "pull_request"):
        paths = _trigger_paths(event)
        for source in PUBLISHED:
            assert source in paths, f"docs.yml {event} does not rerun when {source} changes"


def test_appimage_installer_names_its_short_url():
    script = (ROOT / "packaging/linux/install-appimage.sh").read_text()
    assert 'INSTALLER_URL="https://pyreconstruct.org/install.sh"' in script
    assert "raw.githubusercontent.com" not in script
