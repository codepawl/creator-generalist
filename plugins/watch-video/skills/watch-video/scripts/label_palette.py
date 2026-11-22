"""One fixed colour per label and one fixed depth scale, shared by every reading of a reference still
(segment_still.py, compare_detectors.py, measure_look.py), so the same colour means the same thing in every picture.

Labels: the classes a scene rebuild cares about. Model labels are mapped onto them by LABEL_ALIASES (OneFormer's
ADE20K names, the text prompts), so "mountain" near the camera can become "rock" once depth splits it.
Depth: turbo colour map on log distance from 1 m (red) to 2000 m (dark blue), sky black, with a legend bar in metres.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LABEL_COLOURS = {
    "sky": (120, 170, 235),
    "far mountain": (110, 90, 150),
    "rock": (200, 60, 50),
    "ground": (170, 130, 80),
    "road": (245, 200, 60),
    "tree": (40, 150, 60),
    "pine tree": (20, 90, 40),
    "bush": (150, 210, 70),
    "sea": (30, 90, 200),
    "building": (230, 120, 200),
    "pier": (255, 140, 0),
    "fence": (0, 220, 220),
    "utility pole": (255, 255, 255),
    "wire": (255, 60, 60),
    "car": (255, 40, 160),
    "person": (255, 0, 0),
    "bird": (255, 240, 0),
    "contrail": (190, 240, 255),
    "other": (128, 128, 128),
}

LABEL_ALIASES = {
    "mountain": "far mountain", "hill": "far mountain", "rock": "rock", "stone": "rock", "earth": "ground",
    "land": "ground", "grass": "ground", "field": "ground", "sand": "ground", "dirt track": "road", "road": "road",
    "path": "road", "tree": "tree", "palm": "tree", "pine tree": "pine tree", "plant": "bush", "bush": "bush",
    "flower": "bush", "sea": "sea", "water": "sea", "lake": "sea", "river": "sea", "fence": "fence",
    "railing": "fence", "pole": "utility pole", "utility pole": "utility pole", "car": "car", "truck": "car",
    "van": "car", "person": "person", "bird": "bird", "sky": "sky", "pier": "pier", "dock": "pier",
    "house": "building", "building": "building", "wall": "building", "contrail": "contrail", "wire": "wire",
}

DEPTH_NEAR = 1.0
DEPTH_FAR = 2000.0


def canonical(label):
    """Map a model's label (also a prompt phrase such as 'pine tree bush') onto one of LABEL_COLOURS."""
    text = label.strip().lower()
    if text in LABEL_ALIASES:
        return LABEL_ALIASES[text]
    for alias in sorted(LABEL_ALIASES, key=len, reverse=True):
        if alias in text:
            return LABEL_ALIASES[alias]
    return "other"


def colour_of(label):
    return LABEL_COLOURS[canonical(label)]


def turbo(values):
    """Google's turbo colour map, polynomial fit, values 0..1 to RGB 0..255."""
    x = np.clip(values, 0, 1)
    red = 0.13572138 + x * (4.61539260 + x * (-42.66032258 + x * (132.13108234 + x * (-152.94239396 + x * 59.28637943))))
    green = 0.09140261 + x * (2.19418839 + x * (4.84296658 + x * (-14.18503333 + x * (4.27729857 + x * 2.82956604))))
    blue = 0.10667330 + x * (12.64194608 + x * (-60.58204836 + x * (110.36276771 + x * (-89.90310912 + x * 27.34824973))))
    return (np.clip(np.stack([red, green, blue], -1), 0, 1) * 255).astype(np.uint8)


def depth_picture(depth, sky_mask=None):
    """Depth in metres to a fixed-scale picture: 1 m red, 2000 m dark blue, sky black, with a legend bar."""
    depth = np.asarray(depth, dtype=np.float32)
    position = (np.log(np.clip(depth, DEPTH_NEAR, DEPTH_FAR)) - math.log(DEPTH_NEAR)) / (math.log(DEPTH_FAR) - math.log(DEPTH_NEAR))
    picture = turbo(1 - position)
    invalid = ~np.isfinite(depth) | (depth > DEPTH_FAR * 5)
    if sky_mask is not None:
        invalid |= sky_mask
    picture[invalid] = 0
    return add_depth_legend(Image.fromarray(picture))


def add_depth_legend(picture):
    width, height = picture.size
    bar_width = max(200, width // 3)
    bar_height = max(12, height // 45)
    left = width - bar_width - 20
    top = height - bar_height - 40
    ramp = turbo(1 - np.linspace(0, 1, bar_width))[None].repeat(bar_height, 0)
    picture.paste(Image.fromarray(ramp), (left, top))
    draw = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=max(12, height // 50))
    for metres in (1, 10, 30, 100, 300, 1000):
        offset = (math.log(metres) - math.log(DEPTH_NEAR)) / (math.log(DEPTH_FAR) - math.log(DEPTH_NEAR)) * bar_width
        draw.text((left + offset, top + bar_height + 2), f"{metres} m", fill=(255, 255, 255), font=font,
                  stroke_width=2, stroke_fill=(0, 0, 0), anchor="ma")
    return picture


def legend_picture(labels, height=None):
    """A key of the labels present, one swatch per row."""
    font = ImageFont.load_default(size=18)
    rows = sorted(set(canonical(label) for label in labels), key=list(LABEL_COLOURS).index)
    picture = Image.new("RGB", (220, height or 30 * len(rows) + 10), (20, 20, 20))
    draw = ImageDraw.Draw(picture)
    for index, name in enumerate(rows):
        top = 8 + index * 30
        draw.rectangle([10, top, 34, top + 22], fill=LABEL_COLOURS[name])
        draw.text((44, top + 2), name, fill=(240, 240, 240), font=font)
    return picture


def with_legend(picture, labels):
    legend = legend_picture(labels, picture.size[1])
    combined = Image.new("RGB", (picture.size[0] + legend.size[0], picture.size[1]), (20, 20, 20))
    combined.paste(picture, (0, 0))
    combined.paste(legend, (picture.size[0], 0))
    return combined
