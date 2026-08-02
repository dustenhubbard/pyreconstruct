import argparse
import subprocess
import sys
from pathlib import Path


def _version_string():
    """Best-effort version string, without importing the heavy constants package."""
    try:
        from PyReconstruct._version import version
        return version
    except Exception:
        pass
    try:
        from importlib.metadata import version as _v
        return _v("PyReconstruct")
    except Exception:
        return "unknown"


def _repo_info():
    """Branch/commit (or version) info; imported lazily — it does git/dist-info I/O.

    Catch broadly: importing the constants package pulls PySide6.QtCore, which
    raises a plain ImportError (not ModuleNotFoundError) if Qt is present but
    can't load (e.g. missing libGL on a headless box).
    """
    try:
        from PyReconstruct.modules.constants import repo_info
        return repo_info
    except Exception:
        return {"branch": "unknown", "commit": "unknown"}


def _github_repo():
    """The 'owner/name' GitHub repo updates come from — shared with the frozen updater."""
    # stdlib-only module (no Qt), safe to import from the CLI
    from PyReconstruct.modules.backend.updater.updater import GITHUB_REPO
    return GITHUB_REPO


def main():

    parser = argparse.ArgumentParser(description='Open a jser file in PyReconstruct')

    parser.add_argument('path', nargs='?', metavar='file.jser', default=None, help='The jser file to open')
    parser.add_argument('-f', '--filename', type=str, required=False, default=None, help='The file path for the jser')
    parser.add_argument('-u', '--update', action='store_true', help='Update PyReconstruct')
    parser.add_argument('-b', '--branch', action='store_true', help='Show current branch')
    parser.add_argument('-c', '--commit', action='store_true', help='Show current commit')
    parser.add_argument('-s', '--switch', type=str, required=False, default=None, help='Switch PyReconstruct branch')
    parser.add_argument('-V', '--version', action='store_true', help='Show version and exit')

    args = parser.parse_args()

    if args.version:

        print(_version_string())

    elif args.update:

        _run_update()

    elif args.branch:

        print(_repo_info().get("branch"))

    elif args.commit:

        print(_repo_info().get("commit"))

    elif args.switch:

        _run_update(args.switch)

    else:

        open_file(resolve_jser_path(parser, args))

def resolve_jser_path(parser, args):
    """The jser to open, from the positional argument or from -f/--filename.

    The positional form is what a shell user types and what a desktop entry's
    %f produces, so it is the one the app should answer to. -f came first and
    stays: the Linux installer writes a launcher that translates a single
    non-flag argument into -f, and every already-installed copy of that
    launcher keeps working until its owner re-runs the installer.

    Naming the same file both ways is accepted. Naming two different files is a
    mistake, and picking one of them silently would open the wrong series.
    """
    positional, flag = args.path, args.filename

    if positional is not None and flag is not None and Path(positional) != Path(flag):
        parser.error("give the jser path once, either positionally or with -f/--filename")

    return positional if positional is not None else flag

def open_file(filename):
    # A path that does not exist reaches MainWindow, which falls back to the
    # welcome series without a word (main_window.py: `if filename and
    # Path(filename).exists()`). For a mistyped argument that means a launched
    # app, no series, and no explanation of why. Say so here instead, while
    # there is still a console to say it on and before Qt starts.
    if filename is not None and not Path(filename).exists():
        print(f"File not found: {filename}")
        sys.exit(1)
    try:
        from PyReconstruct.run import runPyReconstruct
        runPyReconstruct(filename)
    except FileNotFoundError:
        print(f"File not found: {filename}")

def _run_update(requested_branch=None):
    """CLI wrapper around update(): print refusals cleanly instead of tracebacks."""
    try:
        update(requested_branch)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

def validate_branch(requested_branch):

    repo_url = f"https://github.com/{_github_repo()}"
    output = subprocess.run(
        ["git", "ls-remote", "--heads", repo_url, f"refs/heads/{requested_branch}"],
        capture_output=True, text=True,
    )

    return bool(output.stdout.strip())

def update(requested_branch=None):
    """Reinstall PyReconstruct from GitHub via pip (source/pip installs only).

    Raises RuntimeError — without having touched the existing install — when the
    update can't or shouldn't proceed; both the CLI (_run_update) and the in-app
    source-update path surface the message.
    """

    if getattr(sys, "frozen", False):
        print("This is a packaged build; use Help > Check for updates in the app.")
        return

    # The Linux .sh installer owns its venv (ownership marker at the app root);
    # its update path is re-running the installer, not an in-place pip.
    if (Path(sys.prefix).parent / ".pyreconstruct-install").exists():
        raise RuntimeError(
            "This install is managed by the PyReconstruct Linux installer.\n"
            "To update, re-run the installer:\n"
            f"  curl -fsSL https://raw.githubusercontent.com/{_github_repo()}"
            "/main/packaging/linux/install.sh | bash"
        )

    if not requested_branch:

        requested_branch = _repo_info().get("branch")  # current branch, if known

        # Non-branch fallbacks from repo_info: plain pip installs report the
        # package name, detached checkouts report no branch — default to main.
        if requested_branch in (None, "unknown", "PyReconstruct", "detached head"):
            requested_branch = "main"

    # Validate the ref BEFORE touching the install, whether it was requested
    # explicitly or detected — a bad ref must leave the install untouched.
    if not validate_branch(requested_branch):
        raise RuntimeError(
            f"Branch '{requested_branch}' was not found on {_github_repo()}; "
            "nothing was changed."
        )

    link = f"git+https://github.com/{_github_repo()}@{requested_branch}"

    # One idempotent pip call, with THIS interpreter's pip: --force-reinstall
    # replaces the install (picking up new/changed dependencies) but never
    # uninstalls first, so a failure (offline, bad ref) leaves the existing
    # install intact.
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", link]
    )
    if result.returncode != 0:
        raise RuntimeError(
            "pip could not complete the update; the existing install was left in place."
        )

if __name__ == '__main__':
    main()
