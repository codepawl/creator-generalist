"""Cut a reference picture into overlapping zoomed tiles with frame coordinates drawn on them, so a reader can
name every small object and give its position in whole-frame units (0-1) instead of guessing from a small view.

uv run --no-project --with pillow python zoom_tiles.py <image> <out folder> [--grid 4x3] [--zoom 2] [--overlap 0.15]

Writes <out>/overview.png (the whole frame with the tile grid and labels) and one tile_<row><column>.png per cell,
each scaled up by --zoom with a 0.05 grid in frame units printed on its edges. A tile list is written to tiles.json.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_font(size):
    for candidate in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_label(draw, position, text, font):
    left, top = position
    box = draw.textbbox((left, top), text, font=font)
    draw.rectangle((box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1), fill=(0, 0, 0))
    draw.text((left, top), text, fill=(255, 235, 0), font=font)


def frame_grid_lines(start, end, step):
    first = int(start / step + 0.999) * step
    value = first
    lines = []
    while value <= end + 1e-9:
        lines.append(round(value, 3))
        value += step
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("output")
    parser.add_argument("--grid", default="4x3", help="columns x rows")
    parser.add_argument("--zoom", type=float, default=2.0)
    parser.add_argument("--overlap", type=float, default=0.15, help="share of a cell added on each side")
    parser.add_argument("--step", type=float, default=0.05, help="frame-unit spacing of the printed grid")
    arguments = parser.parse_args()

    picture = Image.open(arguments.image).convert("RGB")
    width, height = picture.size
    columns, rows = (int(value) for value in arguments.grid.lower().split("x"))
    output_folder = Path(arguments.output)
    output_folder.mkdir(parents=True, exist_ok=True)
    font = load_font(max(14, int(height / 50)))
    small_font = load_font(14)

    overview = picture.copy()
    overview_draw = ImageDraw.Draw(overview)
    tiles = []
    for row in range(rows):
        for column in range(columns):
            name = f"{chr(65 + row)}{column + 1}"
            left = max(0.0, (column - arguments.overlap) / columns)
            right = min(1.0, (column + 1 + arguments.overlap) / columns)
            top = max(0.0, (row - arguments.overlap) / rows)
            bottom = min(1.0, (row + 1 + arguments.overlap) / rows)
            crop = picture.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
            crop = crop.resize((int(crop.width * arguments.zoom), int(crop.height * arguments.zoom)), Image.LANCZOS)
            tile_draw = ImageDraw.Draw(crop)
            for frame_x in frame_grid_lines(left, right, arguments.step):
                pixel_x = (frame_x - left) / (right - left) * crop.width
                tile_draw.line((pixel_x, 0, pixel_x, crop.height), fill=(255, 235, 0), width=1)
                draw_label(tile_draw, (pixel_x + 2, 2), f"{frame_x:.2f}", small_font)
            for frame_y in frame_grid_lines(top, bottom, arguments.step):
                pixel_y = (frame_y - top) / (bottom - top) * crop.height
                tile_draw.line((0, pixel_y, crop.width, pixel_y), fill=(255, 235, 0), width=1)
                draw_label(tile_draw, (2, pixel_y + 2), f"{frame_y:.2f}", small_font)
            draw_label(tile_draw, (crop.width - 60, crop.height - 30), name, font)
            tile_path = output_folder / f"tile_{name}.png"
            crop.save(tile_path)
            tiles.append({"name": name, "file": tile_path.name, "frame_box": [round(left, 3), round(top, 3), round(right, 3), round(bottom, 3)]})
            cell_left = column / columns * width
            cell_top = row / rows * height
            overview_draw.rectangle((cell_left, cell_top, (column + 1) / columns * width, (row + 1) / rows * height), outline=(255, 235, 0), width=2)
            draw_label(overview_draw, (cell_left + 6, cell_top + 6), name, font)
    overview.save(output_folder / "overview.png")
    (output_folder / "tiles.json").write_text(json.dumps({"image": Path(arguments.image).name, "grid": [columns, rows], "tiles": tiles}, indent=1))
    print(f"{len(tiles)} tiles in {output_folder}")


if __name__ == "__main__":
    main()
