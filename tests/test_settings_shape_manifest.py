"""A stored setting never changes shape: a shape change is a new key name.

PyReconstruct and PyReconstruct Dev share one settings store, and a nightly
runs against values the stable build also reads. `Series.getOption` coerces a
stored value with the type of ITS OWN default (``type(defaults[name])``, and
``json.loads`` for a list or dict), so a nightly that changed a key's type
would raise inside the stable app at read time, on a machine that never ran
the nightly's code.

The rule, from the design (hub specs/settings-sync-two-apps-2026-09-27.md):
a key's type never changes and a key is never removed. Want a different
shape? Add a new key, leave the old one, and let the stable app keep reading
it. ``tests/settings_manifest.json`` pins the type name of every default and
this test fails the moment one moves.

Adding a key is fine and expected: add it to the manifest in the same PR.
"""

import json
from pathlib import Path

from PyReconstruct.modules.datatypes.default_settings import (
    default_series_settings,
    default_settings,
)

MANIFEST = Path(__file__).with_name("settings_manifest.json")

RULE = (
    "A stored setting never changes shape. The stable app coerces every value "
    "with the type of its own default, so a changed type raises inside the "
    "stable app on a machine that never ran this code. Use a NEW KEY NAME, "
    "never a shape change, and never remove a key; the old one stays and "
    "stable keeps reading it."
)

LIVE = {
    "default_settings": default_settings,
    "default_series_settings": default_series_settings,
}


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_manifest_covers_both_default_tables():
    assert set(_manifest()) == set(LIVE)


def test_no_key_changed_type():
    changed = {}
    for table, pinned in _manifest().items():
        for key, type_name in pinned.items():
            if key in LIVE[table] and type(LIVE[table][key]).__name__ != type_name:
                changed[f"{table}[{key!r}]"] = (type_name, type(LIVE[table][key]).__name__)
    assert not changed, f"type changed (pinned, now): {changed}\n{RULE}"


def test_no_key_disappeared():
    gone = [
        f"{table}[{key!r}]"
        for table, pinned in _manifest().items()
        for key in pinned
        if key not in LIVE[table]
    ]
    assert not gone, f"keys removed from the defaults: {gone}\n{RULE}"


def test_every_default_is_in_the_manifest():
    """The manifest must stay complete, or a key added today is a key whose
    shape nobody is watching tomorrow. Add the new key with its type name."""
    missing = {
        f"{table}[{key!r}]": type(value).__name__
        for table, live in LIVE.items()
        for key, value in live.items()
        if key not in _manifest()[table]
    }
    assert not missing, (
        f"defaults missing from tests/settings_manifest.json: {missing}. "
        "Add each with its type name; adding a key is fine, changing one is not."
    )


def test_container_defaults_are_json_shaped():
    """Lists and dicts are stored as JSON strings and parsed on read; a
    default that cannot round-trip through json would fail every read of it."""
    for table, live in LIVE.items():
        for key, value in live.items():
            if isinstance(value, (list, dict, tuple)):
                assert json.loads(json.dumps(value)) == (
                    list(value) if isinstance(value, tuple) else value
                ), f"{table}[{key!r}]"
