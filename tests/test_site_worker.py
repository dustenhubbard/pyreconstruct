"""pyreconstruct.org is served by the Cloudflare Worker in site-worker/.

The site moved off GitHub Pages on 2026-11-05. Cloudflare proxies the domain,
so GitHub could not renew its certificate for it, and the site answered with
Cloudflare error 526. docs.yml now builds the site and deploys it with
wrangler. These tests pin the parts that keep the site and its neighbors up:
the routes, the www redirect, the 404 page, and a deploy that only main runs.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "site-worker"
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"


def _wrangler_config() -> dict:
    # wrangler.jsonc allows // comments; none of its strings contain "//"
    # except the route patterns, which have no "//" in them.
    text = (WORKER_DIR / "wrangler.jsonc").read_text()
    return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))


def test_routes_cover_the_domain_and_leave_narrower_routes_alone():
    config = _wrangler_config()
    patterns = {route["pattern"] for route in config["routes"]}
    assert patterns == {"pyreconstruct.org/*", "www.pyreconstruct.org/*"}
    # /class* and /companion/* belong to other Workers on the zone. Cloudflare
    # picks the most specific route, so this Worker must not claim them.
    assert not any("class" in p or "companion" in p for p in patterns)
    assert config["workers_dev"] is False


def test_assets_serve_the_built_site_with_its_404_page():
    assets = _wrangler_config()["assets"]
    assert (WORKER_DIR / assets["directory"]).resolve() == ROOT / "site"
    assert assets["not_found_handling"] == "404-page"
    # The Worker has to run before the asset lookup, or www would serve pages
    # instead of redirecting.
    assert assets["run_worker_first"] is True


def _run_worker(url: str) -> dict:
    script = f"""
    const worker = (await import({json.dumps((WORKER_DIR / "worker.js").as_uri())})).default;
    const env = {{ ASSETS: {{ fetch: (r) => new Response("asset " + new URL(r.url).pathname) }} }};
    const res = await worker.fetch(new Request({json.dumps(url)}), env);
    console.log(JSON.stringify({{
      status: res.status,
      location: res.headers.get("location"),
      body: res.status === 200 ? await res.text() : null,
    }}));
    """
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_www_redirects_to_the_bare_domain_keeping_path_and_query():
    res = _run_worker("https://www.pyreconstruct.org/USER_GUIDE/?x=1")
    assert res["status"] == 301
    assert res["location"] == "https://pyreconstruct.org/USER_GUIDE/?x=1"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_bare_domain_is_served_from_the_assets():
    res = _run_worker("https://pyreconstruct.org/install.sh")
    assert res == {"status": 200, "location": None, "body": "asset /install.sh"}


def test_only_main_deploys_and_only_the_deploy_job_sees_the_token():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    deploy = workflow["jobs"]["deploy"]
    assert "github.ref == 'refs/heads/main'" in deploy["if"]
    assert "pull_request" in deploy["if"]
    steps = deploy["steps"]
    wrangler = [s for s in steps if s.get("uses", "").startswith("cloudflare/wrangler-action@")]
    assert len(wrangler) == 1
    assert wrangler[0]["with"]["workingDirectory"] == "site-worker"
    # The build job runs third-party docs tooling, so it must never see the secrets.
    assert "secrets." not in yaml.safe_dump(workflow["jobs"]["build"])
    assert workflow["permissions"] == {"contents": "read"}
