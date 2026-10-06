import os
import sys
import time
import uuid
import shutil
import multiprocessing.spawn
from multiprocessing import Pool, freeze_support

# Frozen-build (PyInstaller) fix for Windows. This script is executed via runpy
# as the program's __main__, but on a frozen win32 executable multiprocessing's
# spawn does NOT re-establish __main__ in worker processes: its WINEXE path
# assumes __main__ is the frozen entry point (run.py), not a runpy'd script. The
# workers then can't find the worker function defined here and die unpickling the
# first task, which hangs the Pool right after the zarr skeleton is created.
# macOS/Linux are unaffected (that path is gated on sys.platform == 'win32').
# Clearing WINEXE makes multiprocessing send this script's path to the workers
# (init_main_from_path) so they re-execute it and find the worker function --
# exactly as already happens off Windows.
multiprocessing.spawn.WINEXE = False

# Cap the native (C-level) thread pools of the imaging/compression libraries to
# one thread PER PROCESS *before* importing them. OpenCV and numpy/BLAS read
# these on import; a fresh value here would otherwise be too late. This process
# is the dedicated conversion subprocess (spawned by the GUI just for this job),
# so limiting threads here never touches the main application (3D meshing,
# imports, etc.). Parallelism comes from the worker Pool below -- see
# _limit_worker_threads for the full rationale. setdefault() respects a value a
# user deliberately exported.
for _thread_var in (
    "OMP_NUM_THREADS",        # OpenMP (OpenCV/numpy backends)
    "OPENBLAS_NUM_THREADS",   # OpenBLAS
    "MKL_NUM_THREADS",        # Intel MKL
    "NUMEXPR_NUM_THREADS",    # numexpr
    "VECLIB_MAXIMUM_THREADS", # Apple Accelerate / vecLib
):
    os.environ.setdefault(_thread_var, "1")

import cv2
import zarr

os.environ["OPENCV_LOG_LEVEL"] = "FATAL"
os.environ["OPENCV_IO_MAX_IMAGE_PIXELS"] = "18500000000"  # Go big or go home?


def _limit_worker_threads():
    """Pin this process's runtime thread pools to a single thread.

    Each conversion worker runs OpenCV (``cv2.imread``/``cv2.resize``) and
    compresses with blosc when it writes its arrays to the zarr.
    By default BOTH libraries spawn one thread per CPU core, so a Pool of N
    workers would fan out to roughly N x (all cores) threads and peg every CPU
    no matter how few workers the user selected in Settings -- the historical
    cause of a 4-worker job saturating an 8-thread laptop. Capping each process
    to one native thread makes N workers cost ~N CPU threads, so the Settings
    slider actually bounds CPU use.

    This runs at import time -- which covers the ``fork`` start method
    (Linux default), where workers inherit this already-applied state -- and is
    also passed as the Pool ``initializer`` so it re-runs inside each worker
    under the ``spawn`` start method (Windows/macOS default), where every
    worker re-imports this module in a fresh interpreter.

    macOS caveat: ``cv2.setNumThreads()`` is a no-op there because OpenCV's
    macOS wheels build against Apple's Grand Central Dispatch
    (``getBuildInformation()`` reports ``Parallel framework: GCD``), and no
    environment variable above reaches GCD either. Measured on opencv-python
    4.8.1 / macOS 27 arm64 / M4 10-core, that costs us nothing in practice:
    the only two cv2 calls this script makes are single threaded in that build
    regardless of the cap (``cv2.imread`` of an 8192^2 TIFF 0.97 CPU-cores,
    each ``cv2.resize`` pyramid step 1.00, never above 2 OS threads), so the
    worker count still bounds CPU. ``blosc.set_nthreads`` does work on macOS.
    See tests/test_zarr_worker_cpu_bound.py for the platform xfail this earns.
    """
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass
    try:
        from numcodecs import blosc
        blosc.set_nthreads(1)
    except Exception:
        pass


# apply to this (main) process, and -- under fork -- to inherited workers
_limit_worker_threads()

IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
MIN_DOWNSAMPLED_PIXELS = 1024**2

# Cap concurrency: each worker holds a full-resolution tile in memory, and a
# large worker count multiplies filesystem/metadata pressure for little gain
# (the work is I/O bound). Bounded well below typical core counts on purpose.
#
# 5, not 8: past this the extra workers are a pessimization, not a plateau.
# Measured 2026-07-28 on a 10-core M4 (synthetic 8192^2 grayscale TIFFs), 8
# workers ran 8% SLOWER than 5 while burning 19% more CPU (14.16 vs 11.93
# CPU-seconds). Callers inside the GUI clamp to the same number before they get
# here, via `modules.backend.func.utils.MAX_ZARR_WORKERS`, so the worker count
# the Settings slider shows is the one that starts; this clamp is what keeps the
# guarantee when the script is run directly. The two constants must agree --
# tests/test_zarr_worker_cpu_bound.py asserts it.
MAX_WORKERS = 5

# Require a little more free space than estimated before starting.
DISK_SAFETY_FACTOR = 1.15

# Folder inside the zarr where an array is built before it is renamed into
# place (see write_array).
UNFINISHED_DIR = ".unfinished"

def clean_windows_path(path):

    if not sys.platform.startswith('win'):
        return path

    # Remove surrounding quotes if present
    if (path.startswith('"') and path.endswith('"')) or (path.startswith("'") and path.endswith("'")):
        path = path[1:-1]

    # Handle paths with nested quotes
    path = path.replace('""', '"').replace("''", "'")

    # Replace forward slashes with backslashes for Windows
    path = path.replace('/', '\\')

    return path

cores = int(sys.argv[1])  # number of cores to use

if len(sys.argv) == 4:

    img_dir = clean_windows_path(sys.argv[2])
    zarr_fp = clean_windows_path(sys.argv[3])
    create_new = True

elif len(sys.argv) == 3:

    zarr_fp = clean_windows_path(sys.argv[2])
    create_new = False

else:

    print("Please provide arguments", flush=True)
    exit()


def open_zarr_with_retry(fp, mode=None, attempts=5, delay=0.2):
    """Open a zarr store, retrying briefly on transient filesystem errors.

    Network/synced drives (e.g. OneDrive) can momentarily fail to serve a
    freshly written metadata file; a short backoff absorbs those hiccups
    instead of crashing.
    """
    last_err = None
    for attempt in range(attempts):
        try:
            return zarr.open(fp) if mode is None else zarr.open(fp, mode=mode)
        except (KeyError, OSError, zarr.errors.GroupNotFoundError) as e:
            last_err = e
            time.sleep(delay * (attempt + 1))
    raise last_err


def image_filenames(img_dir):
    images = []
    skipped = []

    for filename in sorted(os.listdir(img_dir)):
        img_fp = os.path.join(img_dir, filename)
        ext = os.path.splitext(filename)[1].lower()

        if not os.path.isfile(img_fp) or ext not in IMAGE_EXTENSIONS:
            skipped.append(filename)
            continue

        images.append(filename)

    if skipped:
        print(
            "Skipping non-image entries: " + ", ".join(skipped),
            flush=True
        )

    if not images:
        raise Exception(f"No image files found in {img_dir}.")

    return images


def scale_names_for_shape(shape):
    h, w = shape
    exp = 0
    scale_names = ["scale_1"]

    while h * w >= MIN_DOWNSAMPLED_PIXELS:
        h = round(h / 2)
        w = round(w / 2)
        exp += 1
        scale_names.append(f"scale_{2**exp}")

    return scale_names


def ensure_scale_groups(zg, images):
    if create_new:
        img_fp = os.path.join(img_dir, images[0])
        cvim = cv2.imread(img_fp, cv2.IMREAD_GRAYSCALE)
        if cvim is None:
            raise Exception(f"{images[0]} is not an image file.")
        scale_names = scale_names_for_shape(cvim.shape)
    else:
        first_image = images[0]
        scale_names = scale_names_for_shape(zg["scale_1"][first_image].shape)

    for scale_group in scale_names:
        if scale_group not in zg:
            zg.create_group(scale_group)


def _dir_size(path):
    """Total size of all files under path (metadata-only walk)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def estimate_required_bytes(images):
    """Rough estimate of the additional disk space the scales will need.

    Each halving stores 1/4 the pixels, so the downsampled levels sum to
    ~1/3 of scale_1 (1/4 + 1/16 + ...). For an existing zarr we measure
    scale_1's on-disk (compressed) size; for a new zarr we approximate
    scale_1 from the source image file sizes.
    """
    if create_new:
        src_total = 0
        for filename in images:
            try:
                src_total += os.path.getsize(os.path.join(img_dir, filename))
            except OSError:
                pass
        # new scale_1 (~ source size) plus downscales (~1/3 of scale_1)
        return int(src_total * (1 + 1 / 3))

    scale1_size = _dir_size(os.path.join(zarr_fp, "scale_1"))
    # only the downscales are new (~1/3 of scale_1)
    return int(scale1_size / 3)


def check_disk_space(images):
    """Abort up front if the target volume can't hold the new scales."""
    required = int(estimate_required_bytes(images) * DISK_SAFETY_FACTOR)
    target = os.path.dirname(os.path.abspath(zarr_fp)) or "."
    free = shutil.disk_usage(target).free
    gb = 1024 ** 3

    print(
        f"Estimated additional space needed: ~{required / gb:.2f} GB; "
        f"free on target volume: {free / gb:.2f} GB",
        flush=True,
    )

    if free < required:
        raise SystemExit(
            "Not enough free disk space to generate scaled images.\n"
            f"  Estimated need (with margin): ~{required / gb:.2f} GB\n"
            f"  Available on target volume:   {free / gb:.2f} GB\n"
            "Free up space or choose an output location with more room, "
            "then try again."
        )


def validate_zarr(zg, images):
    missing = []

    for filename in images:
        if filename not in zg["scale_1"]:
            missing.append(f"scale_1/{filename}")
            continue

        for scale_group in scale_names_for_shape(zg["scale_1"][filename].shape)[1:]:
            if scale_group not in zg or filename not in zg[scale_group]:
                missing.append(f"{scale_group}/{filename}")

    if missing:
        preview = "\n".join(missing[:20])
        remaining = len(missing) - 20
        if remaining > 0:
            preview += f"\n... and {remaining} more"
        raise Exception(f"Zarr conversion incomplete:\n{preview}")


def require_scale_group(zg, scale_group):
    """Return the scale group, creating it if it does not exist yet.

    The main process makes the groups the first image needs before the Pool
    starts. A larger image can need one more, and two workers can try to make
    it at the same time; the one that loses gets ContainsGroupError and opens
    the group the other one made.
    """
    try:
        return zg.require_group(scale_group)
    except zarr.errors.ContainsGroupError:
        return zg[scale_group]


def unfinished_dir(zarr_fp):
    """Folder inside the zarr where workers build arrays before publishing.

    It has no .zgroup, so zarr does not list it as a group, and its name
    starts with a dot, so PyReconstruct skips it when listing scales.
    """
    return os.path.join(zarr_fp, UNFINISHED_DIR)


def publish(src, dst, attempts=5, delay=0.2):
    """Rename a finished array folder into place, retrying briefly.

    On Windows a virus scanner or a sync client (e.g. OneDrive) can hold a
    file it just saw for a moment, and the rename fails with PermissionError.
    """
    for attempt in range(attempts):
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def write_array(zarr_fp, scale_group, filename, arr):
    """Write one array so that it only appears in the zarr once complete.

    zarr writes an array's .zarray before its chunks, so an array written in
    place is listed as soon as it is started. If the run stops partway (a
    worker fails and the Pool terminates the others, or the processes are
    killed), that half-written array would look finished: an update skips
    arrays that exist and validate_zarr only checks names. So the array is
    written to its own folder under UNFINISHED_DIR and renamed into place
    after its last chunk. A rename on the same volume is a single step, so
    scale_N/filename is either absent or complete.
    """
    staging = os.path.join(unfinished_dir(zarr_fp), uuid.uuid4().hex)
    os.makedirs(staging)
    # same call group.create_dataset makes, with the array at the store root
    zarr.array(arr, store=zarr.DirectoryStore(staging))
    publish(staging, os.path.join(zarr_fp, scale_group, filename))


def create2D(args):
    """Worker: read one image, resize it and write its levels to the zarr.

    Each worker opens the store and writes its own arrays, so the compression
    and the disk writes run in parallel across the Pool. No two workers write
    the same file: every array is its own directory in the DirectoryStore and
    each image goes to exactly one worker. The only shared writes are the
    scale groups, handled by require_scale_group. Arrays are published whole
    by write_array.

    Only the filename and the time taken go back to the main process. An
    exception here (e.g. a full disk) is raised again in the main process by
    Pool.imap and fails the run.
    """
    filename, create_new, img_dir, zarr_fp = args

    print(f"Working on {filename}...", flush=True)

    t_start = time.perf_counter()

    zg = open_zarr_with_retry(zarr_fp, mode="a")

    scales = {}

    if create_new:
        img_fp = os.path.join(img_dir, filename)
        cvim = cv2.imread(img_fp, cv2.IMREAD_GRAYSCALE)
        if cvim is None:
            raise Exception(f"{filename} is not an image file.")
        scales["scale_1"] = cvim
    else:
        cvim = zg["scale_1"][filename][:]

    # keep downsampling by 2 until below MIN_DOWNSAMPLED_PIXELS
    h, w = cvim.shape
    exp = 0
    while h * w >= MIN_DOWNSAMPLED_PIXELS:
        h = round(h / 2)
        w = round(w / 2)
        exp += 1
        scales[f"scale_{2**exp}"] = cv2.resize(cvim, (w, h))

    for scale_group, arr in scales.items():
        group = require_scale_group(zg, scale_group)
        # an array already there is left alone: when updating scales,
        # scale_1 is the source and any existing level is kept
        if filename not in group:
            write_array(zarr_fp, scale_group, filename, arr)

    return filename, time.perf_counter() - t_start


if __name__ == "__main__":

    freeze_support()

    if create_new:

        zg = zarr.group(zarr_fp, overwrite=True)
        zg.create_group("scale_1")
        message = "Converting to zarr now..."

    else:

        zg = open_zarr_with_retry(zarr_fp, mode="a")
        message = "Updating zarr scales now..."

    print(message, flush=True)

    if create_new:
        images = image_filenames(img_dir)
    else:
        images = sorted(list(zg["scale_1"]))
        if not images:
            raise Exception(f"No scale_1 images found in {zarr_fp}.")

    # fail fast if the target volume cannot hold the new scales
    check_disk_space(images)

    # make the scale groups the first image needs; a worker adds any group a
    # larger image needs (see require_scale_group)
    ensure_scale_groups(zg, images)

    processes = max(1, min(cores, MAX_WORKERS))
    print(f"Converting with {processes} worker process(es)...", flush=True)

    total = len(images)
    # machine-readable progress markers consumed by the converter window
    # (start_process.py) to drive the progress bar / ETA.
    print(f"@@PROGRESS@@ TOTAL {total}", flush=True)

    t_all_start = time.perf_counter()

    # plain, picklable args only -- never the zarr group itself
    args = [
        (filename, create_new, img_dir if create_new else None, zarr_fp)
        for filename in images
    ]

    done = 0
    # initializer re-applies the per-process thread cap in every worker so the
    # spawn start method (Windows/macOS) is covered as well as fork.
    try:
        with Pool(processes, initializer=_limit_worker_threads) as p:

            # workers write their own arrays; imap (ordered) reports them here
            # in input order and re-raises a worker's exception
            for filename, duration in p.imap(create2D, args):
                done += 1
                print(f"Time for conversion {filename}: {round(duration, 2)} s", flush=True)
                print(f"@@PROGRESS@@ STEP {done} {total}", flush=True)
    finally:
        # leaving the Pool stops every worker, so what is left here is
        # unfinished arrays from a failed run (or an earlier closed one)
        shutil.rmtree(unfinished_dir(zarr_fp), ignore_errors=True)

    print(f"All tasks completed: {round(time.perf_counter() - t_all_start, 2)} s", flush=True)

    validate_zarr(zg, images)
    print("Zarr validation complete.", flush=True)
