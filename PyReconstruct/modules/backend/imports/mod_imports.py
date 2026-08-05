import subprocess
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

