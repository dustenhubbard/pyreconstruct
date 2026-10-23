"""pyreconstruct.org follows the system theme and carries the brand kit.

The palette's first entry follows the visitor's system theme, so a first visit
opens in light or dark to match the computer. The header logo, favicons,
home-screen icon and link-preview image the theme and the head template name
are all in docs/, and the link previews use absolute URLs from site_url. The
light-theme keyboard focus outline keeps 3:1 contrast against the page.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MKDOCS = ROOT / "mkdocs.yml"
DOCS = ROOT / "docs"
HEAD = DOCS / "overrides" / "main.html"
CSS = DOCS / "stylesheets" / "extra.css"


def _palette_entries() -> list[str]:
    text = MKDOCS.read_text()
    block = text[text.index("\n  palette:\n") + len("\n  palette:\n"):]
    block = block[:block.index("\n\n")]
    return block.split("\n    - ")


def _scheme_block(scheme: str) -> str:
    css = CSS.read_text()
    start = css.index(f'[data-md-color-scheme="{scheme}"] {{')
    return css[start:css.index("\n}", start)]


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_palette_follows_system_theme_first():
    entries = _palette_entries()
    assert entries[0].lstrip("- ").startswith('media: "(prefers-color-scheme)"')
    assert 'media: "(prefers-color-scheme: light)"' in entries[1]
    assert "scheme: default" in entries[1]
    assert 'media: "(prefers-color-scheme: dark)"' in entries[2]
    assert "scheme: slate" in entries[2]


def test_brand_images_exist():
    text = MKDOCS.read_text()
    named = re.findall(r"^  (?:logo|favicon): (\S+)$", text, re.M)
    named += re.findall(r"'(assets/images/[^']+)'", HEAD.read_text())
    assert len(named) >= 5
    for path in named:
        assert (DOCS / path).is_file(), path


def test_link_previews_use_absolute_urls():
    head = HEAD.read_text()
    assert "config.site_url" in head
    for tag in ("og:image", "twitter:image", "og:url"):
        assert f'"{tag}" content="{{{{' in head, tag
    assert re.search(r"^site_url: https://", MKDOCS.read_text(), re.M)


def test_light_focus_outline_contrast():
    light = _scheme_block("default")
    focus = re.search(r"--pr-focus: (#[0-9a-fA-F]{6});", light).group(1)
    card = re.search(r"--pr-card: (#[0-9a-fA-F]{6});", light).group(1)
    assert "outline: 3px solid var(--pr-focus)" in CSS.read_text()
    assert _contrast(focus, card) >= 3.0
