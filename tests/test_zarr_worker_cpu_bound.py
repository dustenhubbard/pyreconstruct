"""The zarr-conversion worker slider must actually bound CPU use.

Background: the "CPU usage" slider (series option ``cpu_max``) is a percentage
of cores that becomes the number of ``multiprocessing`` workers in the
image-to-zarr converter (``assets/scripts/convert_zarr/zarree-2.py``). Each
worker runs OpenCV (``cv2.resize``) and the main process compresses with blosc;
both libraries default to one thread PER CORE, so historically N workers fanned
out to N x (all cores) threads and pegged every CPU regardless of the slider.

These tests lock in the plumbing that keeps N workers costing ~N CPU threads:

  * the converter caps per-process native thread pools on import and exposes
    ``_limit_worker_threads`` for the Pool initializer (verified in a clean
    subprocess so the check mirrors a real worker and pollutes nothing);
  * the Pool is actually created with that initializer;
  * ``determine_cpus`` maps the percentage slider to a sane core count and the
    default leaves headroom on limited hardware.
"""
import os
import sys
import subprocess
import textwrap
from pathlib import Path

import PyReconstruct
from PyReconstruct.modules.backend.func.utils import determine_cpus
from PyReconstruct.modules.datatypes.default_settings import default_settings

CONVERTER = (
    Path(PyReconstruct.__file__).parent
    / "assets" / "scripts" / "convert_zarr" / "zarree-2.py"
)

THREAD_ENV_VARS = [
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
]


def test_converter_file_exists():
    assert CONVERTER.is_file(), CONVERTER


def test_importing_converter_pins_native_thread_pools(tmp_path):
    """A fresh interpreter that loads the converter (as a worker does under the
    spawn start method) must end up with cv2 and blosc pinned to one thread and
    the BLAS/OpenMP env vars set to 1."""
    out = tmp_path / "x.zarr"
    code = textwrap.dedent(f"""
        import os, sys, importlib.util
        # start from a clean env so setdefault() is observable
        for v in {THREAD_ENV_VARS!r}:
            os.environ.pop(v, None)
        # the module parses sys.argv at import; give it a benign valid form
        sys.argv = ["zarree-2.py", "4", {str(tmp_path)!r}, {str(out)!r}]
        spec = importlib.util.spec_from_file_location("zarree_under_test", {str(CONVERTER)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        import cv2
        from numcodecs import blosc

        # module import alone must have pinned this process
        assert cv2.getNumThreads() == 1, cv2.getNumThreads()
        assert blosc.get_nthreads() == 1, blosc.get_nthreads()
        for v in {THREAD_ENV_VARS!r}:
            assert os.environ.get(v) == "1", (v, os.environ.get(v))

        # the cap helper the Pool uses as its initializer exists and is idempotent
        assert hasattr(mod, "_limit_worker_threads")
        mod._limit_worker_threads()
        assert cv2.getNumThreads() == 1
        assert blosc.get_nthreads() == 1
        print("OK")
    """)
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stdout.strip().endswith("OK"), r.stdout


def test_pool_is_created_with_thread_cap_initializer():
    """Guard the wiring: the worker Pool must pass the cap function as its
    initializer, otherwise spawn-start-method workers would not be pinned."""
    src = CONVERTER.read_text()
    assert "initializer=_limit_worker_threads" in src, (
        "the multiprocessing Pool must be created with "
        "initializer=_limit_worker_threads so spawned workers are thread-capped"
    )


def test_determine_cpus_full_uses_all_cores():
    assert determine_cpus(100) == os.cpu_count()


def test_determine_cpus_half_is_about_half():
    # independent behavioural check: half should be bounded by full, and on any
    # multi-core machine strictly fewer than full and within rounding of full/2.
    full = determine_cpus(100)
    half = determine_cpus(50)
    assert 1 <= half <= full
    if full >= 2:
        assert half < full
        assert abs(half - full / 2) <= 1


def test_determine_cpus_floors_at_one():
    # a 0% (or a percentage that rounds to zero cores) must still yield >=1
    assert determine_cpus(0) == 1
    assert determine_cpus(1) >= 1


def test_default_cpu_max_leaves_headroom():
    """The shipped default should be a bounded share (not 100%) so a limited
    laptop stays usable during conversion. The maintainer may tune this."""
    d = default_settings["cpu_max"]
    assert isinstance(d, int)
    assert 0 < d < 100, d
    assert d == 50  # ~half the cores; documents the chosen default
    assert 1 <= determine_cpus(d) <= os.cpu_count()
