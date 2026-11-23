"""Targeted probes that compare a render with its reference still, region by region, in numbers you can act on.

uv run --no-project --with numpy --with pillow --with scipy python -I probe_still.py <probe> <reference> <render> [options]

Probes (all coordinates are frame fractions, 0-1, x right, y down; images are resized to 960x540):
  edges     Per-cell edge misalignment (6x4 grid): mean distance from each reference edge pixel to the nearest render
            edge pixel, and the integer shift that would close it. A cell whose best shift is large is a placement
            error; a cell whose distance stays high after the shift is a missing or extra shape.
  columns   Luminance down columns: --x 0.2,0.5 --y 0.1,0.5. Finds skyline and ridge rows (the step where sky
            ends), and whether a slope is lighter or darker. Use it before trusting a box mean: a box that straddles a
            skyline mixes sky and ground and gives a false gap.
  colours   Mean RGB of 11x11 patches on a grid: --x 0.1,0.3,0.5 --y 0.05,0.15. Red minus blue shows warmth; the
            sky near a sun and haze colour are read here.
  bands     Mean RGB of horizontal bands: --bands 0,0.3,0.5,0.7,1. Quick global tone and warmth check per depth band.
  mask      Inside a reference mask (--mask <png>), per 0.05 cell: share of pixels darker than --dark (default 100)
            in reference and render. Shows whether a crown, a cliff or a crowd fills the reference outline.
  regions   Per class mask (--mask <folder of class_*.png>): mean RGB, lightness spread and fine texture energy.
            Tells a flat, smooth surface (low texture) from a detailed one, and a colour cast per region.
  glow      Brightest smoothed spot and its column and row profiles: is the sun glow where and as bright as the
            reference's.

Each probe prints both images side by side so one run gives the gap. Pair every probe with a look at the overlay
(overlay_reference.py): the probe tells how much, the eye tells what.
"""
import argparse
import sys
from pathlib import Path

import numpy
from PIL import Image
from scipy import ndimage

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WIDTH, HEIGHT = 960, 540


def load(path, mode="L"):
    return numpy.asarray(Image.open(path).convert(mode).resize((WIDTH, HEIGHT)), dtype=numpy.float32)


def fractions(text):
    return [float(value) for value in text.split(",")]


def edge_map(picture, fraction=0.12, cells=(6, 4)):
    """Strongest `fraction` of gradients in each grid cell. One threshold for the whole frame was unstable: a road
    that became a little more contrasty (mean frame change 1.6/255) pushed the soft foreground edges out of the top
    12% and moved the overall score from 6.7 to 8.7 px with no visible change."""
    magnitude = numpy.hypot(ndimage.sobel(picture, 1), ndimage.sobel(picture, 0))
    edges = numpy.zeros(magnitude.shape, bool)
    columns, rows = cells
    cell_width, cell_height = WIDTH // columns, HEIGHT // rows
    for row in range(rows):
        for column in range(columns):
            block = magnitude[row * cell_height:(row + 1) * cell_height, column * cell_width:(column + 1) * cell_width]
            edges[row * cell_height:(row + 1) * cell_height, column * cell_width:(column + 1) * cell_width] = block > numpy.quantile(block, 1 - fraction)
    return edges


def probe_edges(arguments):
    reference_edges = edge_map(load(arguments.reference))
    distance_to_render = ndimage.distance_transform_edt(~edge_map(load(arguments.render)))
    columns, rows = 6, 4
    cell_width, cell_height = WIDTH // columns, HEIGHT // rows
    means = []
    print("cell centre x,y   mean px   best shift   mean after shift")
    for row in range(rows):
        for column in range(columns):
            top, left = row * cell_height, column * cell_width
            cell = reference_edges[top:top + cell_height, left:left + cell_width]
            if cell.sum() < 30:
                continue
            mean = distance_to_render[top:top + cell_height, left:left + cell_width][cell].mean()
            best = (mean, 0, 0)
            for shift_y in range(-12, 13, 2):
                for shift_x in range(-12, 13, 2):
                    shifted = numpy.roll(numpy.roll(distance_to_render, -shift_y, 0), -shift_x, 1)
                    value = shifted[top:top + cell_height, left:left + cell_width][cell].mean()
                    if value < best[0]:
                        best = (value, shift_x, shift_y)
            means.append(mean)
            centre_x = (left + cell_width / 2) / WIDTH
            centre_y = (top + cell_height / 2) / HEIGHT
            print(f"  {centre_x:.2f},{centre_y:.2f}      {mean:6.1f}    ({best[1]:+3d},{best[2]:+3d})     {best[0]:6.1f}")
    print(f"overall mean {numpy.mean(means):.2f} px")


def probe_columns(arguments):
    y_from, y_to = fractions(arguments.y)
    for label, path in (("reference", arguments.reference), ("render", arguments.render)):
        picture = load(path)
        print(label, f"(rows y {y_from}-{y_to} step 0.01)")
        for frame_x in fractions(arguments.x):
            column = int(frame_x * (WIDTH - 1))
            values = [int(picture[int(frame_y * (HEIGHT - 1)), max(0, column - 2):column + 3].mean()) for frame_y in numpy.arange(y_from, y_to + 1e-6, 0.01)]
            print(f"  x {frame_x:.2f}:", " ".join(f"{value:3d}" for value in values))


def probe_colours(arguments):
    for label, path in (("reference", arguments.reference), ("render", arguments.render)):
        picture = load(path, "RGB")
        print(label)
        for frame_y in fractions(arguments.y):
            cells = []
            for frame_x in fractions(arguments.x):
                row, column = int(frame_y * (HEIGHT - 1)), int(frame_x * (WIDTH - 1))
                patch = picture[max(0, row - 5):row + 6, max(0, column - 5):column + 6].reshape(-1, 3).mean(axis=0)
                cells.append("%3d,%3d,%3d" % tuple(patch))
            print(f"  y {frame_y:.2f}: " + "  ".join(cells))


def probe_bands(arguments):
    edges = fractions(arguments.bands)
    for label, path in (("reference", arguments.reference), ("render", arguments.render)):
        picture = load(path, "RGB")
        parts = []
        for top, bottom in zip(edges, edges[1:]):
            mean = picture[int(top * HEIGHT):int(bottom * HEIGHT)].reshape(-1, 3).mean(axis=0).astype(int)
            parts.append(f"y{top:.1f}-{bottom:.1f} {mean}")
        print(f"{label:9s}", " | ".join(parts))


def probe_mask(arguments):
    mask = numpy.asarray(Image.open(arguments.mask).convert("L").resize((WIDTH, HEIGHT))) > 127
    reference, render = load(arguments.reference), load(arguments.render)
    print(f"dark share (<{arguments.dark}) inside the mask, reference/render, per 0.05 cell")
    rows, columns = numpy.nonzero(mask)
    for top in numpy.arange(rows.min() / HEIGHT // 0.05 * 0.05, rows.max() / HEIGHT, 0.05):
        cells = []
        for left in numpy.arange(columns.min() / WIDTH // 0.05 * 0.05, columns.max() / WIDTH, 0.05):
            row_slice = slice(int(top * HEIGHT), int((top + 0.05) * HEIGHT))
            column_slice = slice(int(left * WIDTH), int((left + 0.05) * WIDTH))
            inside = mask[row_slice, column_slice]
            if inside.mean() < 0.05:
                cells.append("   .   ")
                continue
            reference_dark = (reference[row_slice, column_slice][inside] < arguments.dark).mean() * 100
            render_dark = (render[row_slice, column_slice][inside] < arguments.dark).mean() * 100
            cells.append(f"{reference_dark:3.0f}/{render_dark:3.0f}")
        print(f"  y {top:.2f}", " ".join(cells))


def probe_regions(arguments):
    """Per mask file in --mask (a folder of class_*.png or one png): mean RGB, lightness spread and fine texture."""
    folder = Path(arguments.mask)
    mask_paths = sorted(folder.glob("class_*.png")) if folder.is_dir() else [folder]
    reference, render = load(arguments.reference, "RGB"), load(arguments.render, "RGB")
    print("region             share  reference rgb / std / texture     render rgb / std / texture")
    for mask_path in mask_paths:
        mask = numpy.asarray(Image.open(mask_path).convert("L").resize((WIDTH, HEIGHT))) > 127
        if mask.mean() < 0.005:
            continue
        cells = []
        for picture in (reference, render):
            lightness = picture.mean(axis=2)
            texture = numpy.abs(lightness - ndimage.gaussian_filter(lightness, 2))
            mean = picture[mask].mean(axis=0).astype(int)
            cells.append(f"{mean[0]:3d},{mean[1]:3d},{mean[2]:3d} / {lightness[mask].std():4.1f} / {texture[mask].mean():4.1f}")
        print(f"{mask_path.stem[:18]:18s} {mask.mean():5.2f}  {cells[0]}     {cells[1]}")


def probe_glow(arguments):
    for label, path in (("reference", arguments.reference), ("render", arguments.render)):
        picture = load(path)
        smooth = ndimage.gaussian_filter(picture, 6)
        row, column = numpy.unravel_index(numpy.argmax(smooth), smooth.shape)
        column_values = [int(picture[int(frame_y * (HEIGHT - 1)), column]) for frame_y in numpy.arange(0.2, 0.43, 0.02)]
        row_values = [int(picture[row, int(frame_x * (WIDTH - 1))]) for frame_x in numpy.arange(0.4, 0.67, 0.02)]
        print(f"{label}: glow centre ({column / WIDTH:.3f},{row / HEIGHT:.3f}) value {smooth[row, column]:.0f} raw max {picture.max():.0f}")
        print("  column through glow, y 0.20-0.42 step 0.02:", " ".join(map(str, column_values)))
        print("  row through glow, x 0.40-0.66 step 0.02:", " ".join(map(str, row_values)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("probe", choices=["edges", "columns", "colours", "bands", "mask", "regions", "glow"])
    parser.add_argument("reference")
    parser.add_argument("render")
    parser.add_argument("--x", default="0.1,0.3,0.5,0.7,0.9")
    parser.add_argument("--y", default="0.05,0.15,0.25,0.35")
    parser.add_argument("--bands", default="0,0.3,0.5,0.7,1")
    parser.add_argument("--mask")
    parser.add_argument("--dark", type=float, default=100)
    arguments = parser.parse_args()
    for path in (arguments.reference, arguments.render, arguments.mask):
        if path and not Path(path).exists():
            sys.exit(f"probe_still: no file at {path}. Check that the render finished (a failed render leaves no image).")
    if arguments.probe == "columns" and arguments.y == "0.05,0.15,0.25,0.35":
        arguments.y = "0.1,0.5"
    {"edges": probe_edges, "columns": probe_columns, "colours": probe_colours, "bands": probe_bands, "mask": probe_mask, "regions": probe_regions, "glow": probe_glow}[arguments.probe](arguments)


main()
