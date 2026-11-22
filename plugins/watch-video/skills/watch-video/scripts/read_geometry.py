"""Measure a reference picture's camera and 3D layout with MoGe-2 (microsoft/moge): horizontal and vertical field of
view, a metric point map, the camera's height over the ground below it, the horizon line, and the distance and
height of any frame points you name.

MoGe's package pulls flex-gemm, which pins torch, so the source is cloned once to ~/.cache/moge-src/MoGe
(git clone --depth 1 https://github.com/microsoft/MoGe.git) and only the inference needs are installed:

uv run --no-project --python 3.12 --with "torch==2.15.0+cu132" --with "torchvision==0.29.1+cu132" \
  --with "git+https://github.com/EasternJournalist/utils3d-moge.git@62f09d58509485564e24d5d9f6aac9ee9ebc0c37" \
  --with opencv-python-headless --with scipy --with trimesh --with huggingface-hub --with tqdm --with pillow \
  --index https://download.pytorch.org/whl/cu132 --index-strategy unsafe-best-match \
  python -I read_geometry.py <image> <out folder> [name=x,y ...]

Writes <out>/<image stem>.geometry.json and <stem>.depth.png (near is bright). Points are in metres, camera at the
origin, x right, y up, z forward (converted from MoGe's OpenCV frame, where y points down).
"""
import json
import math
import sys
from pathlib import Path

import numpy
import torch
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MOGE_SOURCE = Path.home() / ".cache" / "moge-src" / "MoGe"
sys.path.insert(0, str(MOGE_SOURCE))


def main():
    image_path = Path(sys.argv[1])
    output_folder = Path(sys.argv[2])
    output_folder.mkdir(parents=True, exist_ok=True)
    named_points = {}
    for argument in sys.argv[3:]:
        name, coordinates = argument.split("=")
        named_points[name] = [float(value) for value in coordinates.split(",")]

    from moge.model.v2 import MoGeModel

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MoGeModel.from_pretrained("Ruicheng/moge-2-vitl-normal").to(device).eval()
    picture = numpy.asarray(Image.open(image_path).convert("RGB"), dtype=numpy.float32) / 255
    tensor = torch.tensor(picture, device=device).permute(2, 0, 1)
    with torch.no_grad():
        result = model.infer(tensor)
    points = result["points"].cpu().numpy()  # H x W x 3, OpenCV camera frame
    mask = result["mask"].cpu().numpy().astype(bool)
    intrinsics = result["intrinsics"].cpu().numpy()
    height, width = mask.shape
    focal_x = intrinsics[0, 0]
    focal_y = intrinsics[1, 1]
    fov_x = math.degrees(2 * math.atan(0.5 / focal_x))
    fov_y = math.degrees(2 * math.atan(0.5 / focal_y))

    # Convert to y up.
    points_up = points * numpy.array([1, -1, 1], dtype=numpy.float32)
    distance = numpy.linalg.norm(points_up[..., [0, 2]], axis=-1)

    # Ground plane from the lowest quarter of the frame's valid points: fit y = a x + b z + c.
    rows = numpy.arange(height)[:, None].repeat(width, axis=1)
    ground_mask = mask & (rows > height * 0.75) & (distance < numpy.percentile(distance[mask], 60))
    ground = points_up[ground_mask]
    fit_matrix = numpy.c_[ground[:, 0], ground[:, 2], numpy.ones(len(ground))]
    (slope_x, slope_z, offset), *_ = numpy.linalg.lstsq(fit_matrix, ground[:, 1], rcond=None)
    camera_height_over_near_ground = float(-offset)

    # Camera pitch from the principal ray: points with the same height as the camera lie on the horizon.
    center_x, center_y = intrinsics[0, 2], intrinsics[1, 2]
    report = {
        "image": image_path.name,
        "size": [width, height],
        "fov_x_degrees": round(fov_x, 2),
        "fov_y_degrees": round(fov_y, 2),
        "principal_point": [round(float(center_x), 4), round(float(center_y), 4)],
        "camera_height_over_near_ground_m": round(camera_height_over_near_ground, 2),
        "near_ground_slope": [round(float(slope_x), 3), round(float(slope_z), 3)],
        "points": {},
    }
    for name, (frame_x, frame_y) in named_points.items():
        column = min(width - 1, int(frame_x * width))
        row = min(height - 1, int(frame_y * height))
        window = points_up[max(0, row - 2):row + 3, max(0, column - 2):column + 3].reshape(-1, 3)
        valid = mask[max(0, row - 2):row + 3, max(0, column - 2):column + 3].reshape(-1)
        if not valid.any():
            report["points"][name] = None
            continue
        point = numpy.median(window[valid], axis=0)
        report["points"][name] = {
            "frame": [frame_x, frame_y],
            "xyz_m": [round(float(value), 2) for value in point],
            "horizontal_distance_m": round(float(math.hypot(point[0], point[2])), 2),
        }
    (output_folder / f"{image_path.stem}.geometry.json").write_text(json.dumps(report, indent=1))
    depth = numpy.where(mask, distance, numpy.nan)
    finite = depth[numpy.isfinite(depth)]
    near, far = numpy.percentile(finite, 2), numpy.percentile(finite, 98)
    shade = 1 - numpy.clip((numpy.log(numpy.nan_to_num(depth, nan=far)) - math.log(near)) / (math.log(far) - math.log(near)), 0, 1)
    Image.fromarray((shade * 255).astype(numpy.uint8)).save(output_folder / f"{image_path.stem}.depth.png")
    numpy.save(output_folder / f"{image_path.stem}.points.npy", points_up.astype(numpy.float16))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
