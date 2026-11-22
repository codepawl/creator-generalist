"""Find thin lines no detector labels: dark wires (a few pixels wide, dark against sky or land) and pale contrails
(wider, brighter than the sky around them). Uses a top-hat filter to keep only thin structure, then a probabilistic
Hough transform for straight runs, merged into lines. Writes thin_lines.png (wires in the shared wire colour,
contrails in the contrail colour) and thin_lines.json (frame coordinates 0-1, length, mean brightness step).

  uv run --no-project --with numpy --with pillow --with scipy --with scikit-image python -I find_thin_lines.py <image> <out folder> --sky-mask class_sky.png [--tree-mask class_tree.png]

A line is kept only where at least 85% of it stays 15 px clear of trees, and a contrail must also run over sky: on the
GTA V still the unfiltered pass found 926 "wires", nearly all of them branches of the big tree. A wire must also cross
smooth background on both sides (texture below the frame's 35th percentile), which drops cracks in rock. Lines at the
same angle (within 3 degrees) and offset (within 1% of the width) are merged into the longest one.
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage.transform import probabilistic_hough_line

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from label_palette import LABEL_COLOURS  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def thin_mask(gray, dark, width, step):
    """Pixels on structures thinner than `width` that differ from their surroundings by more than `step` (0..1)."""
    footprint = np.ones((width, width))
    if dark:
        response = ndimage.grey_closing(gray, footprint=footprint) - gray
    else:
        response = gray - ndimage.grey_opening(gray, footprint=footprint)
    return response > step, response


def lines_of(mask, response, minimum_length, gap, width, height, kind):
    segments = probabilistic_hough_line(mask, threshold=12, line_length=minimum_length, line_gap=gap, rng=0)
    found = []
    for (x0, y0), (x1, y1) in segments:
        length = math.hypot(x1 - x0, y1 - y0)
        samples = np.linspace(0, 1, max(2, int(length)))
        columns = np.clip((x0 + (x1 - x0) * samples).astype(int), 0, width - 1)
        rows = np.clip((y0 + (y1 - y0) * samples).astype(int), 0, height - 1)
        found.append({"kind": kind, "from": [round(x0 / width, 3), round(y0 / height, 3)],
                      "to": [round(x1 / width, 3), round(y1 / height, 3)], "length": round(length / width, 3),
                      "step": round(float(response[rows, columns].mean()), 3)})
    return found


def keep_over_sky(lines, open_sky, width, height):
    kept = []
    for line in lines:
        samples = np.linspace(0, 1, 50)
        columns = np.clip(((line["from"][0] + (line["to"][0] - line["from"][0]) * samples) * width).astype(int), 0, width - 1)
        rows = np.clip(((line["from"][1] + (line["to"][1] - line["from"][1]) * samples) * height).astype(int), 0, height - 1)
        if open_sky[rows, columns].mean() >= 0.85:
            kept.append(line)
    return kept


def background_texture(line, texture, width, height, offset=9):
    """Mean texture on both sides of the line, `offset` px away: a wire crosses smooth sky, haze or road, a crack in
    rock or a twig sits in busy texture."""
    x0, y0 = line["from"][0] * width, line["from"][1] * height
    x1, y1 = line["to"][0] * width, line["to"][1] * height
    length = math.hypot(x1 - x0, y1 - y0) or 1
    normal_x, normal_y = -(y1 - y0) / length, (x1 - x0) / length
    samples = np.linspace(0, 1, 40)
    values = []
    for side in (-1, 1):
        columns = np.clip((x0 + (x1 - x0) * samples + side * offset * normal_x).astype(int), 0, width - 1)
        rows = np.clip((y0 + (y1 - y0) * samples + side * offset * normal_y).astype(int), 0, height - 1)
        values.append(texture[rows, columns])
    return float(np.mean(values))


def distance_to_point(line, point_x, point_y):
    """Shortest distance from a frame point to the line segment, in frame widths (both axes in 0-1 frame units)."""
    x0, y0 = line["from"]
    x1, y1 = line["to"]
    run_x, run_y = x1 - x0, y1 - y0
    span = run_x * run_x + run_y * run_y or 1e-9
    along = max(0.0, min(1.0, ((point_x - x0) * run_x + (point_y - y0) * run_y) / span))
    return math.hypot(x0 + along * run_x - point_x, y0 + along * run_y - point_y)


def sky_on_both_sides(line, sky, width, height, offset=12):
    x0, y0 = line["from"][0] * width, line["from"][1] * height
    x1, y1 = line["to"][0] * width, line["to"][1] * height
    length = math.hypot(x1 - x0, y1 - y0) or 1
    normal_x, normal_y = -(y1 - y0) / length, (x1 - x0) / length
    samples = np.linspace(0, 1, 40)
    shares = []
    for side in (-1, 1):
        columns = (x0 + (x1 - x0) * samples + side * offset * normal_x).astype(int)
        rows = (y0 + (y1 - y0) * samples + side * offset * normal_y).astype(int)
        inside = (columns >= 0) & (columns < width) & (rows >= 0) & (rows < height)
        # Off the top edge of the frame counts as sky: contrails often run along it.
        values = np.ones(len(samples), dtype=bool)
        values[inside] = sky[rows[inside], columns[inside]]
        shares.append(values.mean())
    return min(shares) >= 0.9


def merge_parallel(lines, width, height):
    """Keep the longest of each group of lines with nearly the same angle and offset."""
    kept = []
    for line in sorted(lines, key=lambda item: -item["length"]):
        x0, y0 = line["from"][0] * width, line["from"][1] * height
        x1, y1 = line["to"][0] * width, line["to"][1] * height
        angle = math.atan2(y1 - y0, x1 - x0) % math.pi
        duplicate = False
        for other in kept:
            ox0, oy0 = other["from"][0] * width, other["from"][1] * height
            ox1, oy1 = other["to"][0] * width, other["to"][1] * height
            other_angle = math.atan2(oy1 - oy0, ox1 - ox0) % math.pi
            angle_difference = min(abs(angle - other_angle), math.pi - abs(angle - other_angle))
            length = math.hypot(ox1 - ox0, oy1 - oy0) or 1
            middle_x, middle_y = (x0 + x1) / 2, (y0 + y1) / 2
            offset = abs((ox1 - ox0) * (oy0 - middle_y) - (ox0 - middle_x) * (oy1 - oy0)) / length
            if angle_difference < math.radians(3) and offset < 0.01 * width:
                duplicate = True
                break
        if not duplicate:
            kept.append(line)
    return kept


def main():
    image_path, output_folder = sys.argv[1], sys.argv[2]
    os.makedirs(output_folder, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    gray = np.asarray(image.convert("L")).astype(np.float32) / 255
    sky = None
    if "--sky-mask" in sys.argv:
        sky_path = sys.argv[sys.argv.index("--sky-mask") + 1]
        sky = np.asarray(Image.open(sky_path).convert("L").resize(image.size, Image.NEAREST)) > 127
    wire_mask, wire_response = thin_mask(gray, dark=True, width=7, step=0.06)
    padded = np.pad(ndimage.gaussian_filter(gray, 1.5), 30, mode="reflect")
    trail_mask, trail_response = thin_mask(padded, dark=False, width=25, step=0.015)
    trail_mask, trail_response = trail_mask[30:-30, 30:-30], trail_response[30:-30, 30:-30]
    wires = lines_of(wire_mask, wire_response, minimum_length=width // 12, gap=6, width=width, height=height, kind="wire")
    trails = lines_of(trail_mask, trail_response, minimum_length=width // 14, gap=12, width=width, height=height, kind="contrail")
    away_from_trees = np.ones_like(gray, dtype=bool)
    if "--tree-mask" in sys.argv:
        tree_path = sys.argv[sys.argv.index("--tree-mask") + 1]
        tree = np.asarray(Image.open(tree_path).convert("L").resize(image.size, Image.NEAREST)) > 127
        away_from_trees = ~ndimage.binary_dilation(tree, iterations=15)
    # Wires also hang in front of hills and roads, so they only need to stay clear of tree crowns.
    wires = keep_over_sky(wires, away_from_trees, width, height)
    texture = ndimage.gaussian_filter(np.abs(gray - ndimage.gaussian_filter(gray, 2)), 4)
    smooth_limit = float(np.percentile(texture, 35))
    wires = [line for line in wires if background_texture(line, texture, width, height) < smooth_limit]
    if sky is not None:
        # A contrail has sky on both sides; a ridge line or a cloud edge has sky on one side only. Contrails may cross
        # the sky seen between branches, so only the sky mask is used here, not the distance from trees.
        trails = keep_over_sky(trails, sky, width, height)
        trails = [line for line in trails if sky_on_both_sides(line, sky, width, height)]
        # Glow rays fan out of the sun and pass the same tests, so lines that come within 12% of the width of the
        # brightest spot are dropped (on the GTA V still 6 of 16 candidates were rays from the sun).
        smooth = ndimage.gaussian_filter(gray, 4)
        sun_row, sun_column = np.unravel_index(np.argmax(np.where(sky, smooth, 0)), smooth.shape)
        trails = [line for line in trails if distance_to_point(line, sun_column / width, sun_row / height) > 0.12]
    wires = merge_parallel(wires, width, height)
    trails = merge_parallel(trails, width, height)
    picture = image.copy()
    draw = ImageDraw.Draw(picture)
    for line in wires + trails:
        draw.line([line["from"][0] * width, line["from"][1] * height, line["to"][0] * width, line["to"][1] * height],
                  fill=LABEL_COLOURS[line["kind"]], width=3)
    picture.save(os.path.join(output_folder, "thin_lines.png"))
    with open(os.path.join(output_folder, "thin_lines.json"), "w", encoding="utf-8") as handle:
        json.dump(wires + trails, handle, indent=1)
    print("wires", len(wires), "contrails", len(trails))
    for line in sorted(wires + trails, key=lambda item: -item["length"])[:20]:
        print(line)


if __name__ == "__main__":
    main()
