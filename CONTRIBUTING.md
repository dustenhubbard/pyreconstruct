# Contributing to PyReconstruct

Thanks for helping out. Bug reports, fixes, docs, and screenshots are all welcome.

This is my distribution of [SynapseWeb/PyReconstruct](https://github.com/SynapseWeb/PyReconstruct),
the tracing and 3D reconstruction app from the Kristen Harris Lab at The University
of Texas at Austin. Issues and pull requests for this build go here, not to SynapseWeb.

By contributing, you agree that your work is licensed under
[GPL-3.0-or-later](LICENSE.md).

## Reporting a bug

Open an [issue](https://github.com/dustenhubbard/PyReconstruct/issues). PyReconstruct
links there from **Help ▸ Report a bug...** and **Help ▸ Request a feature...**, and
fills in your version and OS for you.

Tell me what you did, what you expected, and what happened instead. The log from
**View log file** usually saves a round trip. If you would rather write than file an
issue, **Help ▸ Email developers** reaches me too, and **Copy diagnostic report**
gives me your version and OS in one paste.

If you can share the `.jser`, that helps most of all.

For a feature request, tell me the problem you're trying to solve, not only the fix
you have in mind.

For a security problem, don't open a public issue. See [SECURITY.md](SECURITY.md).

## Setup

PyReconstruct runs on Python 3.11 and 3.12 with PySide6 6.9.3. I use [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/dustenhubbard/PyReconstruct
cd PyReconstruct
uv sync
uv run PyReconstruct
```

`uv sync` builds `.venv` from the committed `uv.lock`, so you get the same packages
I do. [docs/DEV_UV.md](docs/DEV_UV.md) has the rest.

If you prefer conda, run `make env` in `dev/`, activate `pyrecon_dev`, and start
the app with `python PyReconstruct/run.py`.

## Running the tests

This is what CI runs:

```bash
QT_QPA_PLATFORM=offscreen uv run --frozen --no-default-groups --extra test python -m pytest
uvx ruff@0.15.20 check .
```

In a conda env, the tests run with
`QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" python -m pytest`.

If you fix a bug, add a test for it, and check that the test fails without your fix
before you push.

Keep logic in `backend/`, `datatypes/`, and `calc/` where you can. Those import
without a window, so they're easy to test. `gui/` should mostly be presentation.

## Pull requests

Please keep each PR to one change. It's easier to review and easier to revert.

PRs are squash merged, so the title becomes the commit. Write it as a
[Conventional Commit](https://www.conventionalcommits.org/) header, like
`fix: the scale bar keeps its width after Cancel`. Branches follow the same types:
`fix/`, `feat/`, `docs/`, `perf/`, `refactor/`, `test/`, `build/`, `ci/`, `chore/`.

The body is a short paragraph. Say what someone using the app will do and see
differently, and why. Name code only when the sentence needs it.

If it changes anything on screen, add before and after screenshots. If it depends on
timing or motion, add a short video. That's the fastest way for me to see what
changed.

### Check every place it shows up

Most commands live in more than one spot. If you add or change one, check:

- the menubar
- the right-click menus on the field and in each list
- the shortcuts dialog, if it has a shortcut
- the Options dialog, if it has a setting
- macOS and Windows. Test on the one you have and say which in the PR.

### Changelog

If your PR changes anything under `PyReconstruct/`, add a changelog entry:

```bash
python3 scripts/changelog_fragments.py new fixed
```

The category is `added`, `changed`, `fixed`, or `removed`. Write the bullet in the
file it creates and commit it with your change. Don't edit `CHANGELOG.md`.
[changelog.d/README.md](changelog.d/README.md) shows what a good entry looks like.

If there's nothing to record, start a line in the PR body with this:

```
No changelog entry: internal refactor, nothing a user would notice
```

A missing entry only gets a warning and never blocks the merge. Changes that only
touch `tests/` or `.github/` don't need one.

## Credits

PyReconstruct was created in the Kristen Harris Lab by Michael A. Chirillo,
Julian N. Falco, Michael D. Musslewhite, Larry F. Lindsey, and Kristen M. Harris,
and introduced in *PNAS* (2025). The [README](README.md) has citation details.
