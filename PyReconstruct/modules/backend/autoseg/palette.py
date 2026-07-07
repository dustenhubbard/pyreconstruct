"""Curated color palette for autoseg-imported traces.

Autoseg import turns each segmentation label id into a trace/object. The color
those traces get needs to stand out against a grayscale EM image, and it needs
to be *stable*: the same label id spans many sections, so every section must
paint it the same color or a single object ends up multicolored.

Design (mirrors how neuroglancer keeps segment colors readable on gray):

* Colors are drawn from a small curated whitelist rather than an arbitrary RGB
  cube. Every entry is high-value and clearly chromatic, so it sits well off the
  achromatic ("gray") axis and away from near-black tones. That is exactly the
  region of color space a grayscale background cannot camouflage.

* The whitelist is also color-vision-deficiency (CVD) safe: the 12 colors stay
  mutually distinguishable under deuteranopia, protanopia, and tritanopia. See
  the palette comment below for the analysis; the tests assert a minimum
  perceptual separation (CIEDE2000) under each simulated deficiency.

* The label id is mapped to a palette entry *deterministically* by hashing the
  id (with an adjustable seed) and indexing into the palette. Determinism is not
  just nice-to-have here: import runs per-section, so a random pick would give
  the same label a different color on each section. Hashing guarantees one label
  id -> one color everywhere, reproducibly across sessions.

* The seed is a global "re-roll" knob (neuroglancer's color-seed idea): bump it
  and the whole id->color assignment shifts, which lets a user break up an
  unlucky case where two touching labels landed on similar colors.

The palette below is the shipped default and is meant to be easy to edit in one
place. It can also be overridden per computer/series via the
``autoseg_color_palette`` and ``autoseg_color_seed`` options (see
``modules/datatypes/default_settings.py``); an empty override falls back to this
default.
"""

# 12 CVD-safe, grayscale-visible colors. Each is high-value and clearly
# chromatic (never a shade of gray, never near-black), and the set stays
# mutually distinguishable under all three main color-vision deficiencies.
# Values are (R, G, B) integers in 0-255 -- the format Trace expects.
#
# Derivation: seeded with the seven non-black colors of the Okabe-Ito CVD-safe
# palette (Okabe & Ito 2008 -- the accessibility standard), then extended to 12
# by farthest-point selection under the worst case across normal vision plus
# simulated deuteranopia/protanopia/tritanopia (Machado et al. 2009 matrices),
# using CIEDE2000 as the perceptual distance. Ordered most-distinct-first so a
# future sequential-assignment mode would use the best-separated colors first
# (the current hash-based assignment draws from all 12, so order is cosmetic).
#
# Measured worst-case minimum pairwise CIEDE2000 separation:
#   normal 15.2, protanopia 12.3, deuteranopia 11.6, tritanopia 10.9
# CVD-safety forces the set toward the blue-yellow and lightness axes (the
# red-green axis collapses under deuteranopia/protanopia), which is why several
# blues appear -- this is the same reason the Okabe-Ito standard looks as it
# does. A wider spread of hues is not achievable without colors that merge
# under red-green deficiency.
DEFAULT_AUTOSEG_PALETTE = [
    (240, 228,  66),   # yellow
    (  0,   0, 178),   # blue
    (178,   0,   0),   # red
    ( 86, 180, 233),   # sky blue
    (  0, 114, 178),   # azure
    (213,  94,   0),   # vermillion
    ( 51, 255, 187),   # aqua
    (178,  36, 112),   # magenta
    (204, 121, 167),   # pink
    (  0, 158, 115),   # green
    ( 89, 133, 255),   # cornflower
    (230, 159,   0),   # orange
]


def _mix(value: int, seed: int) -> int:
    """Deterministically scramble an integer (splitmix64/Murmur3 finalizer).

    Good avalanche so consecutive label ids (1, 2, 3, ...) land on different
    palette entries. Uses only integer arithmetic, so it is independent of
    PYTHONHASHSEED and identical across processes and sessions.
    """
    mask = 0xFFFFFFFFFFFFFFFF
    h = (int(value) ^ int(seed)) & mask
    h = ((h ^ (h >> 33)) * 0xFF51AFD7ED558CCD) & mask
    h = ((h ^ (h >> 33)) * 0xC4CEB9FE1A85EC53) & mask
    h = h ^ (h >> 33)
    return h


def palette_color(label_id, palette=None, seed: int = 0) -> tuple:
    """Return a stable (R, G, B) color for a segmentation label id.

        Params:
            label_id: the segmentation label id (int-like)
            palette: list of (R, G, B) entries; falls back to the shipped
                default when None or empty
            seed (int): re-roll seed; the same id + seed always yields the same
                color, and changing the seed reshuffles the whole assignment
        Returns:
            (tuple): an (R, G, B) integer triple, 0-255, taken from the palette
    """
    if not palette:
        palette = DEFAULT_AUTOSEG_PALETTE
    index = _mix(int(label_id), seed) % len(palette)
    return tuple(int(c) for c in palette[index])


def palette_color_array(label_array, palette=None, seed: int = 0,
                        background=(0, 0, 0)):
    """Vectorized palette_color for a 2-D array of label ids.

    Used to render the live label overlay in the exact same colors the import
    would assign, so the preview matches the resulting traces. Returns an
    (H, W, 3) uint8 array.

        Params:
            label_array: 2-D array of integer label ids
            palette: see palette_color
            seed (int): see palette_color
            background: (R, G, B) for label id 0 (not a segment)
        Returns:
            an (H, W, 3) uint8 numpy array

    Colors are resolved once per *unique* id (few) via palette_color, then
    scattered back to every pixel. Doing it per-unique-id both reuses the exact
    scalar mapping and sidesteps 64-bit overflow that a fully vectorized hash
    would hit in numpy integer types.
    """
    import numpy as np

    arr = np.asarray(label_array)
    unique, inverse = np.unique(arr, return_inverse=True)
    lut = np.array(
        [background if int(u) == 0 else palette_color(u, palette, seed)
         for u in unique.tolist()],
        dtype=np.uint8,
    )
    return lut[inverse].reshape(arr.shape + (3,))
