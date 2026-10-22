# Class site: first-time setup

Run once, in this order. The Worker gets its passwords before its first deploy, so the
class pages are never open while it is being set up. `CURRENT_TERM` is not a secret: it
lives in `worker/wrangler.jsonc` and changes with the term's pull request.

1. Make the Cloudflare API token for GitHub Actions. In the Cloudflare dashboard, open
   the [Account API tokens](https://dash.cloudflare.com/?to=/:account/api-tokens) page,
   then Create Token, then a custom token. Name it `pyreconstruct-class deploy` and give it these permissions and nothing else:

   - Account, Workers Scripts, Edit (to upload the Worker and its files)
   - Zone, Workers Routes, Edit, on the zone `pyreconstruct.org` only (to keep the route)
   - Zone, Zone, Read, on the zone `pyreconstruct.org` only (wrangler looks up the zone
     by name)

   A good result: the token is shown once. Keep the page open for step 8.

2. Check out the `class` branch where wrangler can run.

   ```
   git -C ~/Code/pyreconstruct fetch origin && git -C ~/Code/pyreconstruct wt class-setup --detach origin/class
   ```

   A good result: `HEAD is now at` and a commit on `class`.

3. Install wrangler for the Worker.

   ```
   cd ~/Code/.worktrees/pyreconstruct/class-setup/class/worker && npm ci
   ```

   A good result: `added ... packages` and no errors.

4. Log wrangler in to Cloudflare.

   ```
   cd ~/Code/.worktrees/pyreconstruct/class-setup/class/worker && npx wrangler login
   ```

   A good result: the browser asks you to allow access, and the terminal says
   `Successfully logged in`.

5. Set the student password. Wrangler asks whether to create the Worker
   `pyreconstruct-class`; answer `y`. Then type the password.

   ```
   cd ~/Code/.worktrees/pyreconstruct/class-setup/class/worker && npx wrangler secret put STUDENT_PASSWORD
   ```

   A good result: `Success! Uploaded secret STUDENT_PASSWORD`.

6. Set the teaching-team password. Make it different from the student one.

   ```
   cd ~/Code/.worktrees/pyreconstruct/class-setup/class/worker && npx wrangler secret put STAFF_PASSWORD
   ```

   A good result: `Success! Uploaded secret STAFF_PASSWORD`.

7. Copy the account ID. The dashboard shows it on the Workers & Pages overview and on the
   account home page, labeled Account ID.

8. Add the token to the fork's Actions secrets. Paste the token from step 1 when asked.

   ```
   gh secret set CLOUDFLARE_API_TOKEN -R dustenhubbard/pyreconstruct
   ```

   A good result: `Set Actions secret CLOUDFLARE_API_TOKEN for dustenhubbard/pyreconstruct`.

9. Add the account ID. Paste the ID from step 7 when asked.

   ```
   gh secret set CLOUDFLARE_ACCOUNT_ID -R dustenhubbard/pyreconstruct
   ```

   A good result: `Set Actions secret CLOUDFLARE_ACCOUNT_ID for dustenhubbard/pyreconstruct`.

10. Run the first deploy.

    ```
    gh workflow run class-site.yml -R dustenhubbard/pyreconstruct --ref class
    ```

    A good result: `Created workflow_dispatch event for class-site.yml at class`.

11. Wait for it to finish.

    ```
    gh run list -R dustenhubbard/pyreconstruct --workflow class-site.yml --limit 1
    ```

    A good result, after two or three minutes: `completed  success`.

12. Check that the Worker now answers `/class/`, not GitHub Pages.

    ```
    curl -sI https://pyreconstruct.org/class/
    ```

    A good result: `HTTP/2 401` and `www-authenticate: Basic realm="PyReconstruct class"`.

13. Check that a wrong password is refused on a clip, not just on a page.

    ```
    curl -s -o /dev/null -w '%{http_code}\n' -u student:wrong https://pyreconstruct.org/class/2026-fall/videos/lab-1-1/group-filter.mp4
    ```

    A good result: `401`.

14. Check that the rest of the site is untouched.

    ```
    curl -s -o /dev/null -w '%{http_code}\n' https://pyreconstruct.org/USER_GUIDE/
    ```

    A good result: `200`.

15. Check that the Worker has no other address. In the dashboard, open Workers & Pages,
    then `pyreconstruct-class`, then Settings, then Domains & Routes. A good result: the
    route `pyreconstruct.org/class*` is listed, `workers.dev` says Disabled, and Preview
    URLs says Disabled.

16. Open [pyreconstruct.org/class/](https://pyreconstruct.org/class/) in a private window,
    sign in with the student password, and play a clip on a lab page. A good result: you
    land on the 2026 Fall page and the clip plays. Then try `/class/staff/teaching-notes/`
    with the same window: it says the page is for the teaching team.

## After the gate is live

Main still publishes its own copy of the class pages to GitHub Pages under
`docs/class/`. The Worker answers every request that starts with `/class`, so that copy is
out of reach at the normal address. A request spelled another way, like `//class/` or
`/%63lass/`, may still reach GitHub's copy, depending on how Cloudflare normalizes URLs.
The fix is a separate pull request into `main` that removes `docs/class/`,
`docs/stylesheets/class.css`, the `class.css` line and the `not_in_nav` block in
`mkdocs.yml`, and the class note in `docs/overrides/main.html`. Make it once steps 12 and 13
pass.
