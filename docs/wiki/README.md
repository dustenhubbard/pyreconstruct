# PyReconstruct Wiki source

This directory is the **versioned source** for the project's GitHub Wiki. Edit the
pages here, in the code repository, and sync them to the wiki so history and review
live alongside the rest of the project.

## How the files map to wiki pages

GitHub Wiki treats each Markdown file as a page named by its filename, with hyphens
rendered as spaces. A few filenames are special:

- `Home.md` -> the wiki landing page.
- `_Sidebar.md` -> the navigation sidebar shown on every page.
- `_Footer.md` -> the footer shown on every page.
- Every other `*.md` (e.g. `The-Tool-Palette.md`) -> a page of that name
  (`The Tool Palette`). Inter-page links use the hyphenated name, e.g. `[The Tool
  Palette](The-Tool-Palette)`.

`README.md` (this file) is **not** a wiki page. It stays in the code repo and is not
pushed to the wiki.

## Pushing to the wiki

The wiki is its own git repository at
`https://github.com/dustenhubbard/PyReconstruct.wiki.git`. To publish, copy every
`*.md` in this directory **except `README.md`** into a clone of that repo, then commit
and push:

```
git clone https://github.com/dustenhubbard/PyReconstruct.wiki.git /tmp/pr-wiki
rsync -a --exclude README.md docs/wiki/ /tmp/pr-wiki/
cd /tmp/pr-wiki && git add -A && git commit -m "Sync wiki from docs/wiki" && git push
```
