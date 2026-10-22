"""Write the terminal commands into a frozen PyReconstruct build.

    python packaging/make_cli_shims.py "dist/PyReconstruct.app"
    python packaging/make_cli_shims.py "dist/PyReconstruct Dev" --version 1.25.0.dev202610211200
    python packaging/make_cli_shims.py --check "dist/PyReconstruct.app"

The stable app gets ``pyrecon`` and ``pyreconstruct``; PyReconstruct Dev gets
``pyrecon-dev`` and ``pyreconstruct-dev``, so the two install side by side.
``<command> file.jser`` opens that series in that flavor's installed app and
returns at once; with no argument the command just starts the app.

* macOS: ``<app>.app/Contents/Resources/bin/<long name>``, a POSIX sh script,
  and ``<short name>`` beside it as a relative symlink. The script finds its
  own bundle by following symlinks, so a link to it from ~/.local/bin works,
  and hands the file to ``open -a <bundle>``. Written before signing, so the
  scripts are sealed with the bundle's resources.
* Windows: ``<app folder>\\bin\\<name>.cmd`` for both names. The installer puts
  only that ``bin`` folder on the user's PATH.

Linux needs nothing in the build: install-appimage.sh writes the launcher and
its short-name link in ~/.local/bin.

The flavor comes from the bundle or folder name (``PyReconstruct Dev``), the
same name the spec gives it. ``--check`` runs each command with ``--version``
and fails unless it prints the app name and the version.
"""

import argparse
import os
import plistlib
import re
import stat
import subprocess
import sys
from pathlib import Path

STABLE_APP = "PyReconstruct"
DEV_APP = "PyReconstruct Dev"


def app_name(flavor):
    """The app's name for ``flavor`` (``stable`` or ``dev``)."""
    if flavor not in ("stable", "dev"):
        raise ValueError(f"unknown flavor: {flavor!r}")
    return DEV_APP if flavor == "dev" else STABLE_APP


def command_names(flavor):
    """(short, long) command names for ``flavor``."""
    if app_name(flavor) == DEV_APP:
        return ("pyrecon-dev", "pyreconstruct-dev")
    return ("pyrecon", "pyreconstruct")


def flavor_of(path):
    """``dev`` or ``stable`` from a frozen build's folder or bundle name."""
    name = Path(path).name
    if name.endswith(".app"):
        name = name[: -len(".app")]
    if name == DEV_APP:
        return "dev"
    if name == STABLE_APP:
        return "stable"
    raise ValueError(f"not a PyReconstruct build: {path}")


MACOS_SHIM = r"""#!/bin/sh
# @COMMAND@: open a series in @APP@ from the terminal.
#   @COMMAND@ [file.jser]
# Part of the app bundle; a link to this file from a folder on PATH works too.
set -u

cmd='@COMMAND@'
app='@APP@'

usage() {
  echo "usage: $cmd [file.jser]"
  echo "Opens the series in $app. With no file, starts $app."
}

# Follow links (one in ~/.local/bin, one beside this file) to the script itself.
self=$0
hops=0
while [ -L "$self" ]; do
  hops=$((hops + 1))
  if [ "$hops" -gt 40 ]; then
    echo "$cmd: too many symbolic links from $0" >&2
    exit 1
  fi
  link=$(readlink "$self") || break
  case $link in
    /*) self=$link ;;
    *) self=$(dirname "$self")/$link ;;
  esac
done
bin_dir=$(cd "$(dirname "$self")" 2>/dev/null && pwd -P) || {
  echo "$cmd: cannot find the folder of $self" >&2
  exit 1
}
bundle=${bin_dir%/Contents/Resources/bin}
case $bundle in
  "$bin_dir" | "") bundle="" ;;
  *.app) ;;
  *) bundle="" ;;
esac
if [ -z "$bundle" ] || [ ! -f "$bundle/Contents/Info.plist" ]; then
  echo "$cmd: cannot find $app around $bin_dir" >&2
  exit 1
fi

case ${1-} in
  -h | --help)
    usage
    exit 0
    ;;
  --version)
    version=$(/usr/libexec/PlistBuddy -c "Print :PyReconstructVersion" "$bundle/Contents/Info.plist" 2>/dev/null) || {
      echo "$cmd: cannot read the version of $bundle" >&2
      exit 1
    }
    echo "$app $version"
    exit 0
    ;;
  --)
    shift
    ;;
  -*)
    echo "$cmd: unknown option: $1" >&2
    usage >&2
    exit 2
    ;;
esac

if [ "$#" -eq 0 ]; then
  exec open -a "$bundle"
fi
if [ "$#" -gt 1 ]; then
  echo "$cmd: give one series file" >&2
  usage >&2
  exit 2
fi

file=$1
if [ ! -f "$file" ]; then
  echo "$cmd: no such file: $file" >&2
  exit 1
fi
# open runs the app with / as its folder, so the path must be absolute.
dir=$(cd "$(dirname "$file")" 2>/dev/null && pwd) || {
  echo "$cmd: cannot read the folder of $file" >&2
  exit 1
}
exec open -a "$bundle" "$dir/$(basename "$file")"
"""


WINDOWS_SHIM = r"""@echo off
rem @COMMAND@: open a series in @APP@ from the terminal.
rem   @COMMAND@ [file.jser]
setlocal
set "APP_EXE=%~dp0..\@APP@.exe"
if "%~1"=="" goto start_app
if /i "%~1"=="--version" goto version
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage
if not "%~2"=="" goto too_many
if not exist "%~f1" goto missing
if exist "%~f1\" goto missing
start "" "%APP_EXE%" "%~f1"
exit /b 0

:start_app
start "" "%APP_EXE%"
exit /b 0

:version
echo @APP@ @VERSION@
exit /b 0

:usage
echo usage: @COMMAND@ [file.jser]
echo Opens the series in @APP@. With no file, starts @APP@.
exit /b 0

:too_many
>&2 echo @COMMAND@: give one series file
exit /b 2

:missing
>&2 echo @COMMAND@: no such file: "%~f1"
exit /b 1
"""

# Characters cmd.exe would read as syntax in an echo or a set line.
_CMD_UNSAFE = re.compile(r'[%^&|<>()"!\r\n]')


def _fill(template, **values):
    text = template
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    leftover = re.findall(r"@[A-Z]+@", text)
    if leftover:
        raise ValueError(f"unfilled placeholders: {leftover}")
    return text


def macos_shim(flavor, command):
    return _fill(MACOS_SHIM, COMMAND=command, APP=app_name(flavor))


def windows_shim(flavor, command, version):
    if not version or _CMD_UNSAFE.search(version):
        raise ValueError(f"not a version a .cmd file can echo: {version!r}")
    text = _fill(WINDOWS_SHIM, COMMAND=command, APP=app_name(flavor), VERSION=version)
    # cmd.exe misreads labels in a file with bare LF line ends
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def _bin_dir(build, platform):
    build = Path(build)
    if platform == "macos":
        return build / "Contents" / "Resources" / "bin"
    return build / "bin"


def write_shims(build, platform, version=None):
    """Write both commands into ``build``. Returns the paths written."""
    build = Path(build)
    flavor = flavor_of(build)
    short, long_ = command_names(flavor)
    if not build.is_dir():
        raise FileNotFoundError(f"no frozen build at {build}")
    bin_dir = _bin_dir(build, platform)
    if bin_dir.exists() and any(bin_dir.iterdir()):
        raise FileExistsError(f"{bin_dir} already holds files")
    bin_dir.mkdir(parents=True, exist_ok=True)
    written = []
    if platform == "macos":
        target = bin_dir / long_
        target.write_text(macos_shim(flavor, long_), encoding="utf-8", newline="\n")
        target.chmod(0o755)
        os.symlink(long_, bin_dir / short)
        written = [target, bin_dir / short]
    elif platform == "windows":
        for name in (short, long_):
            path = bin_dir / f"{name}.cmd"
            path.write_bytes(windows_shim(flavor, name, version).encode("ascii"))
            written.append(path)
    else:
        raise ValueError(f"unknown platform: {platform!r}")
    return written


def _expected_version(build, platform, version):
    if platform == "macos":
        with open(Path(build) / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f)["PyReconstructVersion"]
    return version


def check_shims(build, platform, version=None):
    """Run each command with --version; return a list of problems (empty is good)."""
    flavor = flavor_of(build)
    bin_dir = _bin_dir(build, platform)
    expected = f"{app_name(flavor)} {_expected_version(build, platform, version)}"
    problems = []
    for name in command_names(flavor):
        path = bin_dir / (f"{name}.cmd" if platform == "windows" else name)
        if not path.exists():
            problems.append(f"{path} is missing")
            continue
        if platform == "macos" and not os.stat(path).st_mode & stat.S_IXUSR:
            problems.append(f"{path} is not executable")
            continue
        done = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=60)
        out = done.stdout.strip()
        if done.returncode != 0 or out != expected:
            problems.append(f"{path} --version: exit {done.returncode}, printed {out!r}, wanted {expected!r}"
                            + (f"; stderr {done.stderr.strip()!r}" if done.stderr.strip() else ""))
        else:
            print(f"{path} --version: {out}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=Path, help="the frozen .app (macOS) or app folder (Windows)")
    ap.add_argument("--platform", choices=("macos", "windows"),
                    default="macos" if sys.platform == "darwin" else "windows")
    ap.add_argument("--version", help="the version the Windows commands print (macOS reads Info.plist)")
    ap.add_argument("--check", action="store_true", help="run each command with --version instead of writing")
    args = ap.parse_args(argv)
    if args.platform == "windows" and not args.version:
        ap.error("--version is required for the Windows commands")
    if args.check:
        problems = check_shims(args.build, args.platform, args.version)
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return 1 if problems else 0
    for path in write_shims(args.build, args.platform, args.version):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
