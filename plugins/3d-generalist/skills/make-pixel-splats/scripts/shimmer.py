"""Shimmer of a slow turn: the share of object pixels that change colour between neighbouring frames.

Usage: uv run --no-project --with numpy --with pillow --with scipy python -I shimmer.py <internal_size> <frames_dir> [<frames_dir> ...]
Frames are read back at the internal (drawn) size with nearest neighbour, so each sample is one drawn pixel. A pixel
counts as object when it differs from the corner (background) colour in either frame. Lower is steadier. Compare
runs only at the same internal size, turn step and elevation.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(path: Path, size: int) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB").resize((size, size), Image.NEAREST)).astype(np.int16)


def shimmer(frames_dir: Path, size: int) -> tuple:
    """Mean share of object pixels that change per frame, and mean share of the filled silhouette that is a hole."""
    files = sorted(frames_dir.glob("*.png"))
    shares = []
    holes = []
    for earlier, later in zip(files, files[1:]):
        first, second = load(earlier, size), load(later, size)
        background = first[0, 0]
        first_object = np.any(first != background, -1)
        object_pixels = first_object | np.any(second != background, -1)
        changed = np.any(np.abs(first - second) > 12, -1) & object_pixels
        shares.append(changed.sum() / max(object_pixels.sum(), 1))
        filled = ndimage.binary_fill_holes(first_object)
        holes.append((filled & ~first_object).sum() / max(filled.sum(), 1))
    return float(np.mean(shares)), float(np.mean(holes)), len(files)


def main() -> None:
    size = int(sys.argv[1])
    for folder in sys.argv[2:]:
        share, hole_share, count = shimmer(Path(folder), size)
        print(f"{folder}: shimmer {share:.3f} of object pixels per frame, holes {hole_share:.4f} of silhouette, {count} frames")


if __name__ == "__main__":
    main()
