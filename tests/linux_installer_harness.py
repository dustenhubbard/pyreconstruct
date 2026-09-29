"""A stand-in for the GitHub releases API, for packaging/linux/install-appimage.sh.

Serves ``/repos/<owner>/<repo>/releases`` (newest first, like GitHub),
``/releases/latest`` (the newest release that is neither a draft nor a
pre-release, which is what GitHub's "latest" is for this repository) and the
asset bytes under ``/download/<tag>/<name>``, the same shape as a real
``browser_download_url``. Drafts are left out of the list, as they are for an
anonymous caller. Every request path is recorded in ``requests``.

Used two ways: imported by tests/test_install_appimage_script.py, and run as a
script by the AppImage test job in build-installers.yml to install the real
AppImage it just built:

    python3 tests/linux_installer_harness.py --appimage FILE --flavor dev \
        --version 1.24.0.dev20260928 --port-file port.txt
"""

import argparse
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API_PREFIX = "/repos/dustenhubbard/PyReconstruct"


def release(tag, *, prerelease=False, draft=False, assets=None, sha=True):
    """A release record. ``assets`` maps name -> bytes; ``sha`` adds .sha256 files."""
    files = dict(assets or {})
    if sha:
        for name, data in list(files.items()):
            digest = hashlib.sha256(data).hexdigest()
            files[name + ".sha256"] = f"{digest}  {name}\n".encode()
    return {"tag": tag, "prerelease": prerelease, "draft": draft, "files": files}


class FakeGitHub:
    def __init__(self, releases=(), pretty=False):
        self.releases = list(releases)   # newest first
        self.pretty = pretty
        self.requests = []
        self.fail_api = False
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                harness.requests.append(self.path)
                status, body, ctype = harness.respond(self.path)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.api = self.base + API_PREFIX
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    # --- the API ------------------------------------------------------------
    def _json(self, rel):
        # GitHub's own key order, with an author object ahead of tag_name and
        # a body that quotes the keys the installer greps for.
        return {
            "url": f"{self.api}/releases/1",
            "html_url": f"https://github.com/dustenhubbard/PyReconstruct/releases/tag/{rel['tag']}",
            "id": 1,
            "author": {"login": "someone", "type": "User"},
            "tag_name": rel["tag"],
            "target_commitish": "main",
            "name": rel["tag"],
            "draft": rel["draft"],
            "prerelease": rel["prerelease"],
            "assets": [
                {
                    "name": name,
                    "size": len(data),
                    "uploader": {"login": "github-actions[bot]"},
                    "browser_download_url": f"{self.base}/download/{rel['tag']}/{name}",
                }
                for name, data in rel["files"].items()
            ],
            "tarball_url": f"{self.api}/tarball/{rel['tag']}",
            "body": 'Notes that mention "prerelease": true and "tag_name": "v9.9.9".',
        }

    def _dump(self, obj):
        text = json.dumps(obj, indent=2 if self.pretty else None)
        return 200, text.encode(), "application/json"

    def respond(self, path):
        if self.fail_api and path.startswith(API_PREFIX):
            return 403, b'{"message": "API rate limit exceeded"}', "application/json"
        route = path.split("?", 1)[0]
        visible = [r for r in self.releases if not r["draft"]]
        if route == API_PREFIX + "/releases":
            return self._dump([self._json(r) for r in visible])
        if route == API_PREFIX + "/releases/latest":
            for r in visible:
                if not r["prerelease"]:
                    return self._dump(self._json(r))
            return 404, b'{"message": "Not Found"}', "application/json"
        if route.startswith("/download/"):
            parts = route.split("/")
            if len(parts) == 4:
                _, _, tag, name = parts
                for r in self.releases:
                    if r["tag"] == tag and name in r["files"]:
                        return 200, r["files"][name], "application/octet-stream"
        return 404, b"not found", "text/plain"


def asset_name(version, flavor):
    return f"PyReconstruct-{version}-linux-x86_64{'-Dev' if flavor == 'dev' else ''}.AppImage"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--appimage", required=True, type=Path)
    ap.add_argument("--flavor", choices=("stable", "dev"), required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--port-file", required=True, type=Path)
    args = ap.parse_args()
    data = args.appimage.read_bytes()
    name = asset_name(args.version, args.flavor)
    if args.flavor == "dev":
        rel = release(f"v{args.version}", prerelease=True, assets={name: data})
    else:
        rel = release(f"v{args.version}", assets={name: data})
    with FakeGitHub([rel]) as gh:
        args.port_file.write_text(gh.api + "\n")
        print(f"serving {name} at {gh.api}", flush=True)
        gh.thread.join()


if __name__ == "__main__":
    main()
