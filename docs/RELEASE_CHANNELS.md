# Release channels

PyReconstruct's in-app updater (frozen/installed builds) serves two channels.
Users choose one in **Options → Updates → Update channel**; the default is
`release`.

| Channel      | Serves                                   | For                                  |
| ------------ | ---------------------------------------- | ------------------------------------ |
| `release`    | the newest **stable** release (e.g. `v1.20.0`) | everyone (default, recommended) |
| `prerelease` | the newest release of **any** kind, including pre-releases (e.g. `v1.30.0-alpha.1`) | people who want to try upcoming features early |

The updater reads GitHub Releases from the repo in
`PyReconstruct/modules/backend/updater/updater.py` (`GITHUB_REPO`). The
`release` channel only ever offers GitHub releases that are **not** marked
pre-release; the `prerelease` channel offers everything and picks the highest
version.

> Switched to `prerelease`, want out? Switch back to `release` any time. The
> updater never auto-installs anything. If you're already running a pre-release
> that is newer than the current stable build, the next check tells you the
> stable build (e.g. `v1.20.0`) is *older* than what you have and asks whether to
> install it anyway (a downgrade); the prompt defaults to "No". Decline it to keep
> your pre-release until a stable release catches up to or passes your version —
> once `v1.30.0` final ships, both channels offer it and the prompt goes away.

## Version convention: alpha → beta → rc → stable

The stable line is **`v1.20.0`** (the current performance release). The UI
overhaul ships as the next minor, **`v1.30.0`**, delivered first as a sequence
of [semver](https://semver.org/) pre-releases:

```
v1.30.0-alpha.1  →  v1.30.0-alpha.N  →  v1.30.0-beta.1  →  …  →  v1.30.0-rc.1  →  v1.30.0
```

These order exactly as you'd expect, because the updater parses each tag with
[PEP 440](https://peps.python.org/pep-0440/) semantics:

```
1.30.0-alpha.1 < 1.30.0-alpha.2 < 1.30.0-beta.1 < 1.30.0-rc.1 < 1.30.0
```

(`alpha`/`beta`/`rc` normalize to `a`/`b`/`rc`; a final release with no
pre-release suffix outranks every pre-release of the same version.) Ordering is
by parsed version, **not** by the order GitHub lists releases in, so an
out-of-order or re-published tag can't mis-select an update.

A `prerelease` user is always offered the newest of these. A `release` user is
offered only `v1.20.0` until `v1.30.0` final ships, at which point it promotes to
the `release` channel automatically (it's published with `prerelease: false`).

## How a release maps to a GitHub Release

`.github/workflows/build-installers.yml` builds the per-platform installers and
publishes them:

| You push…                         | The workflow publishes…                              |
| --------------------------------- | ---------------------------------------------------- |
| a final tag `vX.Y.Z`              | a **stable** GitHub Release (`prerelease: false`)    |
| a pre-release tag `vX.Y.Z-…`      | a **GitHub pre-release** (`prerelease: true`)        |
| a commit to `main`                | the rolling `prerelease` build (legacy edge channel) |

The stable-vs-pre-release decision is made purely from the tag: a semver
pre-release tag carries a hyphen after the version (`v1.30.0-alpha.1`), a final
release does not (`v1.30.0`).

## Cutting a pre-release (maintainer runbook)

Pre-releases of the UI overhaul are tagged on the held UI line
(`feat/ui-v1-lists-panel`), **not** `main`. To cut the first alpha:

```bash
# on the commit you want to ship, from the UI overhaul branch:
git checkout feat/ui-v1-lists-panel
git tag v1.30.0-alpha.1
git push fork v1.30.0-alpha.1        # 'fork' = dustenhubbard/PyReconstruct
```

Pushing the tag triggers `build-installers`: it builds the Windows/macOS
installers, generates checksums, and publishes them as a GitHub **pre-release**
(`prerelease: true`). Within a minute or two, every user on the `prerelease`
channel is offered `v1.30.0-alpha.1` from inside the app.

Cut the rest the same way, advancing the suffix:

```bash
git tag v1.30.0-alpha.2 && git push fork v1.30.0-alpha.2
git tag v1.30.0-beta.1  && git push fork v1.30.0-beta.1
git tag v1.30.0-rc.1    && git push fork v1.30.0-rc.1
```

When the overhaul is ready for everyone, tag the **final** release (no suffix):

```bash
git tag v1.30.0 && git push fork v1.30.0
```

That publishes a stable GitHub Release, so the `release` channel offers `v1.30.0`
to everyone — no further updater changes needed.

Notes:

- The tag string is what the updater orders on. The readable dotted spelling
  (`v1.30.0-alpha.1`) and the PEP 440 spelling (`v1.30.0a1`) parse identically,
  so either works; the dotted form is preferred for readability.
- `setuptools-scm` derives the build's embedded version from the tag, so the tag
  must point at the exact commit you intend to ship.
- The PyPI publish workflow (`publish-pypi.yml`) never touches PyPI for a
  pre-release, on two counts: it is guarded to the canonical upstream repo (a
  no-op on the fork) **and** it skips any tag with a pre-release suffix. Cutting
  `v1.30.0-alpha.1` ships installers via GitHub Releases only; PyPI sees nothing
  until the final `v1.30.0` tag.
