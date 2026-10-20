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

A note tells someone using PyReconstruct what they see now, briefly, in plain
words:

- One bold claim of about 12 words, ending in a period, and at most one short
  plain sentence after it. Two sentences in all.
- Say what the user sees, not how the code works. Leave out timers, parsers,
  layouts, exceptions and names from the code. If the cause matters to the
  user, say it in their words.
- A fix says what works now, with no "Before, ..." sentence. When the old
  behavior helps someone recognize the bug, put it in the claim as "no
  longer ...".
- A bug that never reached a stable release gets no `fixed` fragment. Fold it
  into the fragment of the feature it belongs to, or leave it out.
- Plain words. Write "PyReconstruct", never "the app", and no playful verbs.
  Give a number only when the number is the point, such as a speed-up.
- Write a menu path one way: Series ▸ Options ▸ View, with the ▸ sign, no
  backticks and no "...".
- One topic, one fragment. If a fragment for the same feature is already
  waiting here, edit it instead of adding a new one.

Hard-wrap at 80 columns and indent continuation lines by two spaces. This is a
real entry:

```markdown
- **When a Save at close fails, the window and the series stay open.** Free
  space or fix the file, then save or close again.
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
