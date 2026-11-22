"""Lay a reference still over a render so the two can be judged in one picture: what moved, what is missing, what
hangs in the air. Numbers (DreamSim, region means) can call a render close while a tree floats over the sea; the
overlay shows it at once.

  uv run --no-project --with numpy --with pillow --with scipy python -I overlay_reference.py <reference> <render> <out folder> [--crop x0,y0,x1,y1] [--zoom 3]

Writes into <out folder>:
  overlay_blend.png   50/50 blend of reference and render.
  overlay_edges.png   the render with the reference's edges drawn on it in cyan, and the render's own edges in magenta:
                      cyan with no magenta beside it is something the render lacks or put elsewhere.
  overlay_flip.gif    the two pictures alternating every 0.6 s, the fastest way for an eye to see a shift.
  overlay_strip.png   reference | render | blend | edges in one row, for a reader or the user.
--crop takes frame fractions and --zoom enlarges that region in every output.
"""
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def option(name, default):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def edges(picture, fraction=0.12):
    """Strong luminance edges: the top `fraction` of Sobel magnitude, thinned by one dilation step."""
    gray = np.asarray(picture.convert("L")).astype(np.float32)
    gray = ndimage.gaussian_filter(gray, 1.2)
    magnitude = np.hypot(ndimage.sobel(gray, axis=0), ndimage.sobel(gray, axis=1))
    return magnitude > np.quantile(magnitude, 1 - fraction)


def main():
    reference_path, render_path, output_folder = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(output_folder, exist_ok=True)
    reference = Image.open(reference_path).convert("RGB")
    render = Image.open(render_path).convert("RGB").resize(reference.size, Image.LANCZOS)
    crop = option("--crop", None)
    zoom = float(option("--zoom", "1"))
    if crop:
        x0, y0, x1, y1 = [float(value) for value in crop.split(",")]
        width, height = reference.size
        box = (int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height))
        reference, render = reference.crop(box), render.crop(box)
    if zoom != 1:
        size = (int(reference.width * zoom), int(reference.height * zoom))
        reference, render = reference.resize(size, Image.LANCZOS), render.resize(size, Image.LANCZOS)
    blend = Image.blend(reference, render, 0.5)
    drawn = np.asarray(render).astype(np.float32) * 0.75
    drawn[edges(render)] = (255, 0, 255)
    drawn[edges(reference)] = (0, 255, 255)
    edge_picture = Image.fromarray(drawn.astype(np.uint8))
    blend.save(os.path.join(output_folder, "overlay_blend.png"))
    edge_picture.save(os.path.join(output_folder, "overlay_edges.png"))
    reference.save(os.path.join(output_folder, "overlay_flip.gif"), save_all=True, append_images=[render], duration=600, loop=0)
    strip = Image.new("RGB", (reference.width * 2, reference.height * 2))
    for index, picture in enumerate([reference, render, blend, edge_picture]):
        strip.paste(picture, ((index % 2) * reference.width, (index // 2) * reference.height))
    strip.save(os.path.join(output_folder, "overlay_strip.png"))
    print("wrote overlay_blend.png overlay_edges.png overlay_flip.gif overlay_strip.png in", output_folder)


if __name__ == "__main__":
    main()
