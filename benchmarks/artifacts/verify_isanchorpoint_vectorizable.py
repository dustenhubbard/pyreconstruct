"""Verify the claim that Grid.isAnchorPoint's 8-neighbour test is exactly a
3x3 convolution, i.e. addressable by batching into numpy/OpenCV.
Not a proposed patch -- evidence for the Phase 2 gate decision only."""
import numpy as np, cv2, time, sys
sys.path.insert(0, ".")
from PyReconstruct.modules.calc.grid import Grid

rng = np.random.default_rng(7)
mismatches = 0
for trial in range(30):
    h, w = rng.integers(40, 260), rng.integers(40, 260)
    grid = np.zeros((h, w), dtype=int)
    # sprinkle values like _drawGridLine does (1s, with some >1 overlaps)
    idx = rng.integers(0, h * w, size=(h * w) // 4)
    flat = grid.ravel()
    for i in idx:
        flat[i] += 1

    g = Grid.__new__(Grid)
    g.grid = grid

    # reference: the shipped scalar implementation
    pts = [(int(x), int(y)) for y in range(1, h - 1) for x in range(1, w - 1)]
    ref = np.array([g.isAnchorPoint(x, y) for x, y in pts])

    # vectorised: >1 OR (>=3 nonzero 8-neighbours)
    nz = (grid > 0).astype(np.uint8)
    k = np.ones((3, 3), np.uint8); k[1, 1] = 0
    nbr = cv2.filter2D(nz, cv2.CV_16S, k, borderType=cv2.BORDER_CONSTANT)
    vec_grid = (grid > 1) | (nbr >= 3)
    vec = np.array([vec_grid[y, x] for x, y in pts])

    if not np.array_equal(ref, vec):
        mismatches += 1
        print("MISMATCH trial", trial, (ref != vec).sum(), "of", len(ref))

print(f"trials=30 mismatches={mismatches}")

# speed comparison on one representative grid
h = w = 700
grid8 = np.zeros((h, w), dtype=np.uint8)
cv2.circle(grid8, (350, 350), 300, 1, 2)
grid = grid8.astype(int)
g = Grid.__new__(Grid); g.grid = grid
contour = cv2.findContours(grid.astype(np.uint8), cv2.RETR_EXTERNAL,
                           cv2.CHAIN_APPROX_NONE)[0][0][:, 0, :]
t0 = time.perf_counter()
_ = [g.isAnchorPoint(*p) for p in contour]
t_scalar = time.perf_counter() - t0

t0 = time.perf_counter()
nz = (grid > 0).astype(np.uint8)
k = np.ones((3, 3), np.uint8); k[1, 1] = 0
nbr = cv2.filter2D(nz, cv2.CV_16S, k, borderType=cv2.BORDER_CONSTANT)
mask = (grid > 1) | (nbr >= 3)
_ = contour[mask[contour[:, 1], contour[:, 0]]]
t_vec = time.perf_counter() - t0
print(f"contour points={len(contour)}  scalar={t_scalar*1000:.2f}ms  "
      f"vectorised={t_vec*1000:.2f}ms  speedup={t_scalar/t_vec:.1f}x")
