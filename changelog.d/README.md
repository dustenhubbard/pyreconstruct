# Changelog fragments

One file per change. Nothing in this directory shares a file with anything else,
so two pull requests landing near each other cannot conflict here, and nothing is
filed under a release until someone assembles the release.

`CHANGELOG.md` is still the record. This directory is the staging area for the
part of it that has not been cut yet.

## Adding one

```sh
python3 scripts/changelog_fragments.py new fixed
```

That prints a path such as `changelog.d/stale-color-render-9c1f04.fixed.md` and
writes a template into it. Edit the file, commit it with the code change, and
stop. Do not touch `CHANGELOG.md`.

The category is the argument: `added`, `changed`, `fixed`, `removed`. These are
the four headings `CHANGELOG.md` uses, in the order it uses them. Pick the one
matching the heading the entry would have gone under.

Run `python3 scripts/changelog_fragments.py list` to see what is waiting.

## What goes in the file

The markdown bullet itself, exactly as it will appear in `CHANGELOG.md`. There
is no metadata, no front matter and no reformatting step: the assembler
concatenates fragments, it does not rewrite them. What you write is what ships.

The house style is a bold lead sentence naming the user-visible effect, then the
mechanism, then the resolution, in full prose. Hard-wrap at 80 columns and indent
continuation lines by two spaces. This is a real entry, from
`## [1.21.0-beta-6]`:

```markdown
- **Renaming or deleting the brightness/contrast profile currently on screen no
  longer raises.** `Series > Brightness/contrast profiles...` rewrote every
  section's profiles and then reloaded the field before switching profiles, so a
  rename left `series.bc_profile` naming a key that no longer existed.
  `Section.brightness` indexes `bc_profiles` by that name and the reload reads it
  through the brightness/contrast palette, giving `KeyError: '<old name>'` on the
  forward path, with no undo involved. The displayed profile now follows the
  rename, and deleting it falls back to `default`.
```

A fragment can run to several paragraphs. Indent the blank line's neighbors by
two spaces and the bullet stays one list item:

```markdown
- **The lead sentence.** The first paragraph.

  The second paragraph, indented by two spaces like everything else under the
  bullet.
```

A fragment can also hold more than one bullet, when one change genuinely
produces two entries in the same category. Write both bullets in the one file.

## Naming

`<slug>.<category>.md`. Only the category is read; the slug is an identifier and
nothing parses it.

`new` builds the slug from the current branch name and appends six random hex
characters. The branch name alone would almost always be unique, since two open
pull requests cannot come from the same branch of the same repository, but two
people working from separate clones can pick the same branch name for the same
bug. The random suffix closes that, and it is generated rather than typed, so
there is nothing for two authors to coordinate on.

A hand-written name works too. It only has to end in `.<category>.md`. A name the
assembler cannot read is an error rather than a skipped file, because a fragment
quietly ignored is a change that disappears from the record.

## Assembling a release

```sh
python3 scripts/changelog_fragments.py assemble 1.21.0-beta-7
```

That collates every fragment under a new `## [1.21.0-beta-7] - <today>` heading
in `CHANGELOG.md`, in the file's heading order, together with anything sitting
under `## [Unreleased]`, and deletes the fragments it consumed. Add `--dry-run`
to print the section and change nothing, and `--date` to set the date by hand.

The version is an argument and the script never reads `git tag`, so the section
can be written and reviewed before the tag exists. Writing entries before a tag
and then merging them after it is exactly how eight entries ended up filed under
`v1.21.0-beta-6`, a build that does not contain them.

`WHATS_NEW.md` is curated per release, not per pull request, and is untouched by
any of this.
