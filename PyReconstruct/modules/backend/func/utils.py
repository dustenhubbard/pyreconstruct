import os
import uuid
from contextlib import redirect_stdout


def make_unique_id() -> int:
    """Return a uuid."""

    return uuid.uuid4().int


# The practical ceiling on image-to-zarr conversion workers, as an absolute
# worker count rather than a share of the cores.
#
# Measured 2026-07-28 on a 10-core M4 (synthetic 8192^2 grayscale TIFFs): 5
# workers is the wall-clock optimum. Going higher is a pessimization, not just a
# plateau -- 8 workers ran 8% SLOWER than 5 while burning 19% more CPU (14.16 vs
# 11.93 CPU-seconds). The work is I/O bound, and past this point the extra
# workers only add filesystem/metadata pressure and full-resolution tiles held in
# memory. So the ceiling is deliberately well below typical core counts, and
# raising it should be driven by a new measurement rather than by core count.
MAX_ZARR_WORKERS = 5


def determine_cpus(percent_usage: int) -> int:
    """Determine max numbers of cores to use.

    A pure share of the machine's cores, floored at 1. This is the slider's
    percentage translated into cores; it is deliberately NOT capped, so that
    ``zarr_worker_count`` below is the single place the conversion ceiling
    lives.
    """

    cpus = int((os.cpu_count() or 1) * (percent_usage / 100))

    return cpus or 1


def zarr_worker_count(percent_usage: int) -> int:
    """Workers the image-to-zarr converter will actually launch at a setting.

    The ``cpu_max`` slider is a share of the cores, so the same percentage buys
    a different number of workers on different machines -- but the useful
    ceiling is an absolute worker count, not a share (see ``MAX_ZARR_WORKERS``).
    Both the Settings readout and the converter launch resolve through here, so
    the number shown to the user is the number that starts.
    """

    return min(determine_cpus(percent_usage), MAX_ZARR_WORKERS)


def stdout_to_devnull(func):
    """Silence stdout by redirecting to devnull.

    Use as @stdout_to_devnull decorator or as stdout_to_devnull(func)(args)
    """

    def wrapper(*args, **kwargs):
        
        with open(os.devnull, 'w') as devnull:
            with redirect_stdout(devnull):
                return func(*args, **kwargs)
            
    return wrapper
