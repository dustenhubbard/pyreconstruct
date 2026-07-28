"""Suite-wide pytest configuration.

Two jobs, both deliberately small:

1. Default the Qt platform to ``offscreen`` so the suite runs headless without
   the caller having to remember an environment variable. The datatypes import
   PySide6 transitively, so a handful of modules had grown their own
   module-scope ``os.environ.setdefault`` for this; hoisting it here makes it
   uniform and makes a bare ``uv run pytest`` behave the way CI does. It is a
   *setdefault*, so an explicit ``QT_QPA_PLATFORM`` in the environment still
   wins, and tests that deliberately strip the variable from a subprocess
   environment (``test_qt_free_core.py``) are unaffected.

2. Register the suite's custom markers. Registration is what makes
   ``pytest --markers`` self-documenting and what stops a typo'd marker from
   being silently ignored under ``--strict-markers``.

Note on (2): the markers below are **scaffolding, and nothing carries them
yet**. That is intentional. The suite currently has no test that depends on an
external corpus or on a second interpreter, so there is nothing to mark today.
Registering the vocabulary now costs three lines; retrofitting it across 4,000+
tests later does not. The collection-time gating hooks that will consume these
markers (resolving a corpus path, probing a reference interpreter) belong with
the work that introduces the first test needing them, not here -- a hook that
gates on nothing is harder to review and easier to get wrong than one written
against a real first caller.
"""

import os

# Must run before any test module imports PySide6, which conftest collection
# guarantees: pytest imports this file before it imports any test module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure(config):
    """Register the suite's custom markers."""
    for marker in (
        "needs_data: requires an external image/series corpus that is not in "
        "the repository. Not run in CI; gated on a corpus path supplied by the "
        "environment.",
        "needs_pr2: requires a separate reference interpreter with the "
        "pyrecon2 package installed. Cannot be an importorskip -- this project "
        "pins python <3.12 and pyrecon2 requires >=3.12, so the two never share "
        "a process and availability is an external-resource fact, not an "
        "import fact.",
        "slow: takes long enough that it should be skippable in the tight "
        "edit/test loop. Excluded by `make fast`, included by `make test`.",
    ):
        config.addinivalue_line("markers", marker)
