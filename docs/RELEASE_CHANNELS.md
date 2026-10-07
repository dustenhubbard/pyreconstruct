# Release channels

Two apps install side by side, each with its own update feed:

| App | Channel | Serves |
| --- | --- | --- |
| PyReconstruct | Stable | the newest published stable release |
| PyReconstruct Dev | Nightly | the newest published pre-release |

The channel follows the app. It is not a per-series choice. Use
the **Help** menu's download link to install the other app. Installing Dev
keeps the stable app available for everyday work.

The updater reads GitHub Releases from the repository named in `GITHUB_REPO`
(`PyReconstruct/modules/backend/updater/updater.py`). Both feeds skip drafts.
Nightly also excludes the retired rolling release tagged `prerelease`.
Neither feed offers a release from the other channel. If no pre-release is
published, Dev reports that no Nightly update is available.

Selection follows GitHub's release order: `pick_release` takes the first
release matching the channel. It then compares that release's version with
the installed version using PEP 440 ordering:

```text
1.23.0 < 1.24.0.dev20260927 < 1.24.0
```

Windows and macOS installers must also match the app's flavor. Dev assets
carry `-Dev`; the stable app never offers those assets.

## Tags and versions

| Channel | Tag | Example |
| --- | --- | --- |
| Stable | `vX.Y.Z` | `v1.23.0` |
| Nightly | `vX.Y.Z.devYYYYMMDD` | `v1.24.0.dev20260927` |

The nightly base defaults to the next minor release after the newest stable.
The date is UTC. `setuptools-scm` derives the embedded version from the tag,
and the build checks that they agree. Asset names use the version without
the leading `v`.

## The nightly build

`.github/workflows/nightly.yml` checks `main` daily at 06:00 UTC. If there are
new commits since the last release on either channel, it tags `main` and
explicitly dispatches `build-installers.yml` on that tag. The explicit
workflow dispatch is necessary because a tag pushed with `GITHUB_TOKEN`
does not trigger another workflow through a push event.

To run it by hand:

```bash
gh workflow run nightly.yml --repo dustenhubbard/pyreconstruct --ref main
```

An optional `version` input sets a different base version, such as a planned
major release. A rerun on the same UTC date skips if that day's tag already
exists. A day without new commits also skips.

Under the default draft policy, a successful nightly publishes immediately
as a GitHub pre-release and never becomes Latest. Its release body opens
with the changes since the newest stable, assembled from the `changelog.d`
fragments on `main` by the same script a stable release uses, as a dry run
that writes and removes nothing. Below that is GitHub's generated change
list, compared with the previous nightly, or with the newest stable for the
first nightly. Nightlies do not require a `WHATS_NEW.md` section and skip the
in-app What's New popup. `Help` > `What's new` in the Dev app shows the newest
stable section at or below the nightly's base version, with a line above it
that links the nightly's own release page as the live changelog.

A failed build leaves its tag in place. If `main` has not changed, the next
scheduled run skips too. Recover by rerunning the installer workflow on the
existing tag, replacing the example below with the failed tag:

```bash
gh workflow run build-installers.yml --repo dustenhubbard/pyreconstruct \
  --ref v1.24.0.dev20260927
```

## Stable releases

A clean `vX.Y.Z` tag on `main` builds the stable app. Prepare and approve the
matching `WHATS_NEW.md` section before tagging. For example, for the next
stable release:

```bash
git checkout main
git pull --ff-only
# Confirm WHATS_NEW.md has the approved ## [1.24.0] section.
git tag v1.24.0
git push origin v1.24.0
```

`build-installers.yml` uses `STAGE_RELEASE_AS_DRAFT` to decide when a release
becomes public:

| Value | Effect |
| --- | --- |
| unset or `auto` | stage Stable as a draft; publish Nightly immediately |
| `true` | always stage a draft |
| `false` | publish immediately |

Under `auto`, inspect the stable draft before publishing:

1. Confirm all eight assets: Windows Setup, both macOS architectures, the
   Linux installer tarball, and a SHA-256 file for each.
2. Check the notes against the matching `WHATS_NEW.md` section and confirm
   the compare link.
3. Publish the draft as Latest.
4. Update the stable download links and version text in `README.md`,
   `docs/index.md`, and the installation section of `docs/USER_GUIDE.md`.

The PyPI workflow is separate and runs only by manual dispatch. An installer
release does not publish to PyPI.

## Retention

`prune-nightlies.yml` runs after a release is published. Installer builds
also dispatch it explicitly, because a publish performed with the workflow
token does not trigger the release event workflow.

The retention helper removes published nightlies whose base version has
been overtaken by Stable. Of the remaining nightlies, it keeps the newest
seven. It also recognizes the retired `vX.Y.Z-beta-N` tags for cleanup of
releases overtaken by Stable. Drafts and stable releases are excluded.
This cleanup deletes releases and assets but retains Git tags.

The installer workflow has a separate same-version cleanup for stable
releases published directly rather than staged as drafts. That path also retains
Git tags. Publishing a staged stable instead triggers `prune-nightlies.yml`.

Pruning does not move Dev users onto Stable. The apps keep their own feeds;
open the stable app to use a stable release.

## Build checks

- Release jobs fetch full history and tags so version discovery works.
- The Linux installer pins its source to the release tag.
- Build concurrency is scoped per platform and ref, so one matrix leg does
  not cancel the others.
