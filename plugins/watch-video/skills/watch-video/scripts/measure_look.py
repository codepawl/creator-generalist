"""Scorecard of a render against its reference, region by region and for the whole frame, so colour, texture, haze
and lens effects are compared as numbers instead of by eye.

  uv run --no-project --with numpy --with pillow --with scipy python -I measure_look.py <reference> <render> <mask folder> [depth.npz]

The mask folder is the output of segment_still.py (class_*.png, one per region). Per region, for both pictures:
- colour: median sRGB, median of the lit part (top 20% luminance) and of the shade (bottom 20%), and their ratio,
  which is the light contrast the material has to show;
- texture: detail energy (spread of a 3 px high-pass, in luminance) and the dominant feature size in pixels (where
  the band-pass energy peaks), so "too smooth" or "pattern too big" shows up as a ratio;
Whole frame: grain (high-pass spread in the flattest sky patch), vignette (corner against centre luminance), bloom
(how far the glow around the brightest point falls to half), sharpness (high-pass energy), and, with a depth map,
haze: the colour the frame fades to and the fade rate, fitted from luminance against distance.
Colour, in CIELAB so lightness, warmth (b) and tint (a) read apart: per region the mean L, a, b and chroma; for the
whole frame the tone curve (luminance percentiles 2 to 98, so crushed blacks and clipped highlights show), the five
dominant colours (k-means) matched pair by pair, and with depth, warmth and saturation in near, middle and far bands
(how the haze tints with distance). Layout: structural similarity of the luminance at 1/8 size (0 to 1), a single
number for "are the big shapes in the same place", independent of colour.
Prints a table; the last column is render over reference (1.0 is a match), with a mark where it is off by over 25%.
"""
import glob
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(path, size=None):
    picture = Image.open(path).convert("RGB")
    if size and picture.size != size:
        picture = picture.resize(size, Image.LANCZOS)
    return np.asarray(picture).astype(np.float32) / 255.0


def luminance(pixels):
    return pixels[..., 0] * 0.2126 + pixels[..., 1] * 0.7152 + pixels[..., 2] * 0.0722


def high_pass(gray, radius):
    return gray - ndimage.gaussian_filter(gray, radius)


def to_lab(pixels):
    """sRGB 0..1 to CIELAB (D65)."""
    linear = np.where(pixels <= 0.04045, pixels / 12.92, ((pixels + 0.055) / 1.055) ** 2.4)
    matrix = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = linear @ matrix.T / np.array([0.95047, 1.0, 1.08883])
    curved = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    lightness = 116 * curved[..., 1] - 16
    green_red = 500 * (curved[..., 0] - curved[..., 1])
    blue_yellow = 200 * (curved[..., 1] - curved[..., 2])
    return np.stack([lightness, green_red, blue_yellow], -1)


def dominant_colours(pixels, count=5, seed=0):
    """k-means on a sample of LAB pixels; returns centres sorted by lightness and their shares."""
    lab = to_lab(pixels).reshape(-1, 3)
    generator = np.random.default_rng(seed)
    sample = lab[generator.choice(len(lab), min(40000, len(lab)), replace=False)]
    centres = sample[generator.choice(len(sample), count, replace=False)]
    for _ in range(25):
        nearest = np.argmin(((sample[:, None] - centres[None]) ** 2).sum(-1), axis=1)
        centres = np.array([sample[nearest == index].mean(0) if (nearest == index).any() else centres[index] for index in range(count)])
    shares = np.bincount(nearest, minlength=count) / len(sample)
    order = np.argsort(centres[:, 0])
    return centres[order], shares[order]


def structural_similarity(first, second):
    """SSIM of two luminance pictures (same size), Gaussian window, constants for 0..1 values."""
    blur = lambda values: ndimage.gaussian_filter(values, 1.5)
    mean_first, mean_second = blur(first), blur(second)
    variance_first = blur(first * first) - mean_first ** 2
    variance_second = blur(second * second) - mean_second ** 2
    covariance = blur(first * second) - mean_first * mean_second
    constant_one, constant_two = 0.01 ** 2, 0.03 ** 2
    score = ((2 * mean_first * mean_second + constant_one) * (2 * covariance + constant_two)) / (
        (mean_first ** 2 + mean_second ** 2 + constant_one) * (variance_first + variance_second + constant_two))
    return float(score.mean())


def region_numbers(pixels, gray, mask):
    values = pixels[mask]
    light = gray[mask]
    if values.shape[0] < 50:
        return None
    lit_cut = np.percentile(light, 80)
    shade_cut = np.percentile(light, 20)
    lit = np.median(values[light >= lit_cut], axis=0)
    shade = np.median(values[light <= shade_cut], axis=0)
    detail = float(np.std(high_pass(gray, 3)[mask]))
    band_energy = []
    sizes = [2, 4, 8, 16, 32]
    for size in sizes:
        band = ndimage.gaussian_filter(gray, size / 2) - ndimage.gaussian_filter(gray, size)
        band_energy.append(float(np.std(band[mask])))
    lab = to_lab(values)
    return {
        "lab": lab.mean(axis=0),
        "chroma": float(np.hypot(lab[:, 1], lab[:, 2]).mean()),
        "median": np.median(values, axis=0) * 255,
        "lit": lit * 255,
        "shade": shade * 255,
        "contrast": float(luminance(lit[None])[0] / max(1e-3, luminance(shade[None])[0])),
        "detail": detail,
        "featureSize": sizes[int(np.argmax(band_energy))],
    }


def frame_numbers(pixels, gray, depth=None):
    height, width = gray.shape
    numbers = {}
    detail = np.abs(high_pass(gray, 1.5))
    # Grain: the flattest 32 px block in the top third (sky).
    best = None
    for row in range(0, height // 3 - 32, 16):
        for column in range(0, width - 32, 16):
            block = gray[row:row + 32, column:column + 32]
            spread = float(np.std(block - ndimage.gaussian_filter(block, 4)))
            if best is None or float(np.std(block)) < best[0]:
                best = (float(np.std(block)), spread)
    numbers["grain"] = best[1] if best else 0.0
    corner = np.concatenate([gray[:height // 8, :width // 8].ravel(), gray[:height // 8, -width // 8:].ravel(),
                             gray[-height // 8:, :width // 8].ravel(), gray[-height // 8:, -width // 8:].ravel()])
    centre = gray[height * 3 // 8:height * 5 // 8, width * 3 // 8:width * 5 // 8]
    numbers["vignette"] = float(np.mean(corner) / max(1e-3, np.mean(centre)))
    numbers["sharpness"] = float(np.mean(detail))
    smooth = ndimage.gaussian_filter(gray, 2)
    peak_row, peak_column = np.unravel_index(np.argmax(smooth), smooth.shape)
    peak = smooth[peak_row, peak_column]
    rows, columns = np.indices(gray.shape)
    radius = np.hypot(rows - peak_row, columns - peak_column)
    background = np.percentile(smooth, 50)
    half_radius = 0
    for ring in range(2, min(height, width) // 2, 2):
        ring_mask = (radius >= ring) & (radius < ring + 2)
        if ring_mask.any() and np.mean(smooth[ring_mask]) < background + (peak - background) / 2:
            half_radius = ring
            break
    numbers["bloomHalfRadius"] = half_radius / width
    numbers["sunFrame"] = (round(float(peak_column) / width, 3), round(float(peak_row) / height, 3))
    if depth is not None:
        depth = np.asarray(Image.fromarray(depth).resize((width, height), Image.NEAREST))
        valid = np.isfinite(depth) & (depth > 1) & (depth < 5000)
        far = valid & (depth > np.percentile(depth[valid], 90))
        near = valid & (depth < np.percentile(depth[valid], 30))
        numbers["hazeColour"] = tuple(int(value) for value in np.round(np.median(pixels[far], axis=0) * 255))
        near_luminance = np.median(gray[near])
        far_luminance = np.median(gray[far])
        numbers["hazeLift"] = float(far_luminance - near_luminance)
    return numbers


def ratio_mark(render_value, reference_value):
    if reference_value == 0:
        return "   -"
    ratio = render_value / reference_value
    return f"{ratio:5.2f}" + (" <<" if ratio < 0.75 else " >>" if ratio > 1.33 else "")


def main():
    reference_path, render_path, mask_folder = sys.argv[1:4]
    depth = np.load(sys.argv[4])["depth"].astype(np.float32) if len(sys.argv) > 4 else None
    reference = load(reference_path)
    size = (reference.shape[1], reference.shape[0])
    render = load(render_path, size)
    reference_gray = luminance(reference)
    render_gray = luminance(render)
    print(f"{'region':14s} {'what':12s} {'reference':>18s} {'render':>18s}  render/ref")
    for mask_path in sorted(glob.glob(os.path.join(mask_folder, "class_*.png"))):
        name = os.path.basename(mask_path)[9:-4]
        mask_picture = Image.open(mask_path).convert("L").resize(size, Image.NEAREST)
        mask = np.asarray(mask_picture) > 127
        if mask.mean() < 0.003:
            continue
        reference_numbers = region_numbers(reference, reference_gray, mask)
        render_numbers = region_numbers(render, render_gray, mask)
        if not reference_numbers or not render_numbers:
            continue
        label = f"{name} {mask.mean() * 100:.0f}%"
        for key in ("median", "lit", "shade"):
            reference_colour = reference_numbers[key]
            render_colour = render_numbers[key]
            reference_light = float(luminance(reference_colour[None] / 255)[0])
            render_light = float(luminance(render_colour[None] / 255)[0])
            print(f"{label:14s} {key + ' rgb':12s} {str(tuple(int(value) for value in np.round(reference_colour))):>18s} "
                  f"{str(tuple(int(value) for value in np.round(render_colour))):>18s}  {ratio_mark(render_light, reference_light)}")
            label = ""
        reference_lab = reference_numbers["lab"]
        render_lab = render_numbers["lab"]
        print(f"{label:14s} {'L a b':12s} {'%5.1f %5.1f %5.1f' % tuple(reference_lab):>18s} {'%5.1f %5.1f %5.1f' % tuple(render_lab):>18s}  "
              f"dL {render_lab[0] - reference_lab[0]:+.1f} warmth {render_lab[2] - reference_lab[2]:+.1f} tint {render_lab[1] - reference_lab[1]:+.1f}")
        for key in ("chroma", "contrast", "detail", "featureSize"):
            print(f"{label:14s} {key:12s} {reference_numbers[key]:18.3f} {render_numbers[key]:18.3f}  "
                  f"{ratio_mark(render_numbers[key], reference_numbers[key])}")
    print()
    small = (size[0] // 8, size[1] // 8)
    layout = structural_similarity(luminance(load(reference_path, small)), luminance(load(render_path, small)))
    print(f"{'frame':14s} {'layout SSIM 1/8':16s} {'1.000':>14s} {layout:18.3f}")
    reference_tone = np.percentile(reference_gray, [2, 10, 25, 50, 75, 90, 98]) * 255
    render_tone = np.percentile(render_gray, [2, 10, 25, 50, 75, 90, 98]) * 255
    print(f"{'frame':14s} {'tone p2..p98':16s} {' '.join('%3d' % value for value in reference_tone):>30s}")
    print(f"{'':14s} {'':16s} {' '.join('%3d' % value for value in render_tone):>30s}  (render)")
    reference_centres, reference_shares = dominant_colours(reference)
    render_centres, render_shares = dominant_colours(render)
    for index in range(len(reference_centres)):
        print(f"{'palette ' + str(index + 1):14s} {'L a b share':16s} {'%5.1f %5.1f %5.1f %3.0f%%' % (*reference_centres[index], reference_shares[index] * 100):>24s}"
              f" {'%5.1f %5.1f %5.1f %3.0f%%' % (*render_centres[index], render_shares[index] * 100):>24s}")
    if depth is not None:
        depth_resized = np.asarray(Image.fromarray(depth).resize(size, Image.NEAREST))
        reference_lab = to_lab(reference)
        render_lab = to_lab(render)
        for name, low, high in (("near <30 m", 0, 30), ("middle 30-150 m", 30, 150), ("far 150-1500 m", 150, 1500)):
            band = (depth_resized >= low) & (depth_resized < high)
            if band.mean() < 0.01:
                continue
            reference_band = reference_lab[band].mean(axis=0)
            render_band = render_lab[band].mean(axis=0)
            reference_chroma = np.hypot(reference_lab[band][:, 1], reference_lab[band][:, 2]).mean()
            render_chroma = np.hypot(render_lab[band][:, 1], render_lab[band][:, 2]).mean()
            print(f"{'depth ' + name:22s} L {reference_band[0]:5.1f}/{render_band[0]:5.1f}  warmth b {reference_band[2]:5.1f}/{render_band[2]:5.1f}"
                  f"  tint a {reference_band[1]:5.1f}/{render_band[1]:5.1f}  chroma {reference_chroma:5.1f}/{render_chroma:5.1f}")
    reference_frame = frame_numbers(reference, reference_gray, depth)
    render_frame = frame_numbers(render, render_gray, depth)
    print()
    for key in reference_frame:
        reference_value = reference_frame[key]
        render_value = render_frame[key]
        if isinstance(reference_value, float):
            print(f"{'frame':14s} {key:16s} {reference_value:14.3f} {render_value:18.3f}  {ratio_mark(render_value, reference_value)}")
        else:
            print(f"{'frame':14s} {key:16s} {str(reference_value):>14s} {str(render_value):>18s}")


if __name__ == "__main__":
    main()
