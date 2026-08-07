import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Union

from PyReconstruct.modules.gui.utils import notifyConfirm, notify as note


## Some optional modules are thin Python wrappers around a *native* library
## that they dlopen at import time. On those, a failed import raises OSError
## rather than ModuleNotFoundError, and reinstalling the Python package cannot
## fix it -- the remedy is a system package manager. Keyed by module name;
## the value is the human name of the library and the per-platform remedy.
NATIVE_LIBRARY_REMEDIES: Dict[str, Tuple[str, str]] = {
    "cairosvg": (
        "Cairo",
        "Debian/Ubuntu:  sudo apt-get install libcairo2\n"
        "macOS:          brew install cairo, then set "
        "DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib\n"
        "Windows:        put a Cairo DLL (libcairo-2.dll) on PATH"
    ),
}


def native_library_message(unloadable: Dict[str, OSError]) -> str:
    """Compose the notice shown when a module's native library will not load.

    Deliberately not a yes/no install prompt: `pip install` cannot supply a
    system library, so offering it would send the user down a path that cannot
    work.
    """
    lines = [
        "This feature needs a system library that is not installed (or not on "
        "the library search path). The Python package is installed correctly; "
        "reinstalling it will not help.\n"
    ]

    for module, exc in unloadable.items():

        library, remedy = NATIVE_LIBRARY_REMEDIES.get(module, ("", ""))
        heading = f"{module} could not load"
        if library:
            heading += f" the native {library} library"

        ## First line only: cairocffi reports every dlopen candidate it tried,
        ## which is a dozen paths of no use to a user in a modal dialog.
        detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__

        lines.append(f"{heading}:\n{detail}\n")

        if remedy:
            lines.append(f"{remedy}\n")

    return "\n".join(lines).rstrip()


def module_path(module: str) -> Path:
    """Return path to a module."""

    mod = __import__(module)
    mod_init = mod.__file__
    
    if not mod_init:
        
        _, submod = module.split(".")
        mod_init = getattr(mod, submod).__file__

    return Path(mod_init).parent
        

def modules_available(modules: Union[str, List[str]], notify: bool=True) -> bool:
    """Check if module available."""

    if not isinstance(modules, list):
        modules = [modules]

    unavailable = []

    ## Modules whose Python package is present but whose native library is
    ## not loadable. A separate bucket because it has a separate remedy.
    unloadable: Dict[str, OSError] = {}

    ## Test if modules unavailable
    for module in modules:

        try:

            __import__(module)

        except ModuleNotFoundError:

            unavailable.append(module)

        except OSError as e:

            ## e.g. `import cairosvg` -> cairocffi dlopens libcairo and
            ## raises OSError('no library called "cairo-2" was found').
            ## Uncaught, this reaches customExcepthook as a crash report.
            unloadable[module] = e

    if not unavailable and not unloadable:  # all modules available

        return True

    if notify:

        if unloadable:

            note(native_library_message(unloadable))

        if unavailable:

            unavail_str = ", ".join(unavailable)

            response = notifyConfirm(
                f"This feature requires additional Python packages to work ({unavail_str}). "
                "Would you like to install them into your current environment?",
                yn=True
            )

            if response == True:

                ## Catch modules with different names on pip install
                mod_pip_names = {
                    "cloudvolume": "cloud-volume",
                    "dask": "dask==2024.12.1"
                }

                for mod, pip_install_name in mod_pip_names.items():
                    if mod in unavailable:
                        index = unavailable.index(mod)
                        unavailable[index] = (mod, pip_install_name)

                pip_outcomes = map(install_module, unavailable)

                ## A successful pip install still does not make the feature
                ## usable if a native library is missing alongside it. Two
                ## cases, and they need separate handling: a *different* module
                ## in this same call already went into the unloadable bucket
                ## (`not unloadable`), or the just-installed module is itself
                ## the native wrapper, which `install_module` finds when it
                ## imports the module to report where it landed and reports
                ## by returning False.
                return all(list(pip_outcomes)) and not unloadable

    return False


def pip_is_reachable() -> bool:
    """Whether a pip exists that `install_module`'s command could have run.

    Both routes are checked, because both are used: the install command is a
    shell `pip install`, which resolves `pip` on PATH, and `sys.executable -m
    pip` reaches the interpreter's own copy. True if either exists -- the
    caller only uses this to decide whether "pip failed" can be explained by
    there being no pip at all, and that claim should only be made when neither
    route can supply one.
    """

    if importlib.util.find_spec("pip") is not None:

        return True

    return shutil.which("pip") is not None


def uv_created_environment() -> bool:
    """Whether the running interpreter's environment was created by uv.

    uv stamps `uv = <version>` into the environment's `pyvenv.cfg`. Neither the
    stdlib's `venv` nor `virtualenv` writes that key, so its presence is a
    direct answer rather than an inference. Read in preference to the directory
    name: a uv environment is not always called `.venv` (UV_PROJECT_ENVIRONMENT
    renames it), and a directory called `.venv` was not necessarily made by uv.

    A frozen build has no `pyvenv.cfg` and answers False, which is correct --
    nothing there is uv-managed.
    """

    config = Path(sys.prefix) / "pyvenv.cfg"

    try:

        contents = config.read_text(encoding="utf-8", errors="replace")

    except OSError:

        ## No pyvenv.cfg (a system interpreter, a frozen build), or it is
        ## unreadable. Either way there is no uv marker to find.
        return False

    for line in contents.splitlines():

        key, separator, _ = line.partition("=")

        if separator and key.strip() == "uv":

            return True

    return False


def no_pip_message(pip_install_name: str) -> str:
    """Compose the notice shown when the install failed because pip is absent.

    The generic "try pip installing it in a terminal yourself" advice is wrong
    in this case, and wrong in a way that costs the user the whole afternoon:
    it names the one command that has already been established not to exist.

    Names the *pip install* name rather than the import name, because that is
    what the user has to type -- `cloudvolume` is installed as `cloud-volume`.

    For the same reason the non-uv branch spells its commands
    `"{sys.executable}" -m ...` rather than bare `python`/`pip`. This branch
    only fires when no pip is reachable, which means PATH has none for *this*
    interpreter; a bare token would therefore resolve to a different
    interpreter, and the user would add pip to, and install the package into,
    an environment that is not the one the notice just named. Quoted because
    an interpreter path can contain spaces.
    """

    if uv_created_environment():

        ## The project's documented from-source setup is `uv sync`, and uv does
        ## not put pip inside the environment it creates; it installs packages
        ## itself. So this is the expected state of a source install, not a
        ## broken one, and the remedy is a uv command.
        return (
            f"{pip_install_name} could not be installed: this environment has "
            "no pip in it, so there was no pip command to run.\n\n"
            "That is normal here. This environment was created by uv, which "
            "installs packages itself and does not put pip inside it. Install "
            "the package with uv instead, from a terminal in the "
            "PyReconstruct source directory:\n\n"
            f"    uv add {pip_install_name}\n"
            "        adds it to pyproject.toml and uv.lock, so it survives "
            "later syncs\n\n"
            f"    uv pip install {pip_install_name}\n"
            "        installs it into this environment only, without "
            "recording it, so the next `uv sync` removes it again\n\n"
            "Then restart PyReconstruct."
        )

    return (
        f"{pip_install_name} could not be installed: pip is not available in "
        "this Python environment, so there was no pip command to run.\n\n"
        f"The environment is:\n\n    {sys.executable}\n\n"
        "Add pip to it from a terminal and then install the package. Both "
        "lines name that interpreter on purpose -- a bare `python` or `pip` "
        "would be whichever one your PATH finds, which is not this one:\n\n"
        f'    "{sys.executable}" -m ensurepip --upgrade\n'
        f'    "{sys.executable}" -m pip install {pip_install_name}\n\n'
        "If something else manages this environment, use its own install "
        f"command instead -- for a uv environment, `uv pip install "
        f"{pip_install_name}`; for conda, `conda install "
        f"{pip_install_name}`.\n\n"
        "Then restart PyReconstruct."
    )


def install_module(module: Union[str, Tuple[str, str]]) -> bool:
    """Interactively install a pip module."""

    if isinstance(module, tuple):
        
        module, pip_install_name = module
        
    else:
        
        pip_install_name = module

    output = subprocess.run(
        f"pip install {pip_install_name}",
        capture_output=True,
        text=True,
        shell=True
    )

    if output.returncode == 0:

        try:

            installed_to = module_path(module)

        except OSError as e:

            ## pip succeeded but the package wraps a native library that will
            ## not load, so `module_path`'s own `__import__` raises the OSError
            ## `modules_available`'s probe already handles. Uncaught here it
            ## reaches customExcepthook as a crash report. Report the real
            ## remedy and count the install as failed: the feature is still
            ## unusable, and re-offering pip cannot supply a system library.
            note(native_library_message({module: e}))

            return False

        note(
            f"{module} successfully installed to:\n\n{installed_to}"
        )

        return True

    else:

        ## Why the reason is established by probing rather than by reading the
        ## subprocess output: the two ways this environment reports a missing
        ## pip look nothing alike. A shell `pip install` exits 127 with
        ## "pip: command not found"; `sys.executable -m pip` exits 1 with "No
        ## module named pip". Matching either string would pin this branch to
        ## one spelling of the install command. Asking whether a pip exists at
        ## all answers the same question and survives the command changing.
        ##
        ## Deliberately not extended to the other install failures. A network
        ## timeout and a package that does not exist on the index both leave
        ## pip reachable, and both keep the generic message, which is at least
        ## true advice for them: retrying `pip install` in a terminal is what
        ## they need.
        if not pip_is_reachable():

            note(no_pip_message(pip_install_name))

            return False

        note(
            "Something went wrong. "
            f"Please try pip installing {module} in a terminal."
        )

        return False


def is_conda_package_installed(package_name: str) -> bool:
    """Check if conda package installed"""

    try:
        
        result = subprocess.run(
            ['conda', 'list', package_name], capture_output=True, text=True, check=True
        )

        results = result.stdout.strip().split("\n")
        
        results = [line for line in results if not line.startswith("#")]
        
        if not results:
            
            return False
        
        else:
            
            return True
    
    except subprocess.CalledProcessError:
        
        return False

