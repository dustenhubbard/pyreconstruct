# Class site

The NEU466G handouts live here, on the `class` branch, and are served at
[pyreconstruct.org/class/](https://pyreconstruct.org/class/) behind a password. They use the
same theme as the rest of pyreconstruct.org, so they look the same and the clips play the
same way.

There are two passwords. The browser asks for a user name too; type anything there.

- **Student password**: opens the current term, `pyreconstruct.org/class/<term>/`. Going to
  `pyreconstruct.org/class/` with it takes a student straight to the current term.
- **Teaching-team password**: opens everything under `/class/`, including past terms and the
  teaching notes.

Pushing to the `class` branch builds the site and deploys it (`.github/workflows/class-site.yml`).
The first-time Cloudflare setup is in [SETUP.md](SETUP.md).

## Layout

```
class/
  mkdocs.yml               site settings
  pages/
    index.md               /class/: teaching-team home
    2026-fall/             one folder per term; students see only the current one
      index.md             the term's list of handouts
      *.md                 the handouts
      img/  videos/        stills and clips for that term
    staff/
      archive.md           past terms
      teaching-notes.md    notes for the teaching team
    stylesheets/  javascripts/  assets/
                           class.css, plus links to the public site's extra.css,
                           clips.js and logo
  worker/                  the Cloudflare Worker that checks the password
```

`2026-fall` is a placeholder name for the current term. Name terms `YYYY-season`
(`2027-spring`, `2027-fall`) so the folders sort by date.

## Cut a new term from the last one

1. Copy the last term's folder: `cp -R class/pages/2026-fall class/pages/2027-spring`.
2. In the new folder, update the term index and the handouts: dates, assigned object
   names, series names. Retake only the screenshots and clips that changed.
3. In `class/worker/wrangler.jsonc`, set `CURRENT_TERM` to the new folder name.
4. In `class/pages/index.md`, point "Current term" at the new folder. Add the old term to
   `class/pages/staff/archive.md`.
5. Open a pull request into `class`. Once it merges, the site deploys.
6. Change the student password (below) and give the new one to the class.

To preview before pushing:

```
cd class
uv run --no-project --with-requirements ../docs/requirements.txt mkdocs serve
```

## Retire a term

Changing `CURRENT_TERM` retires the old term: students can no longer open it, and the
teaching team still can, from Past terms. It stays as it was taught, so it still matches
that semester's version of PyReconstruct. To take a term off the site for good, delete its
folder and its line in `archive.md`; the git history keeps it.

## Change a password

This needs a Cloudflare login on the account that runs the site. From `class/worker`:

```
npm ci
npx wrangler secret put STUDENT_PASSWORD
```

Use `STAFF_PASSWORD` for the teaching-team password. The change takes effect in a few
seconds, with no deploy. Anyone still using the old password is asked for the new one.
Keep the two passwords different.

## Worker tests

```
cd class/worker
npm ci
npm test
```
