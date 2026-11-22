"""Split a still into material colour (albedo) and light (shading, plus a residual for highlights and haze) with
Marigold IID Lighting (prs-eth, OpenRAIL++, trained on synthetic interiors, so read outdoor results as a guide). With a
mask folder from segment_still.py it prints, per region, the albedo and the shading of reference and render side by
side, so "this rock is too dark" can be told apart as "the rock material is too dark" or "the rock gets too little light".

Run through the GPU queue with the torch line of read_geometry.py plus `--with diffusers --with "transformers>=4.57" --with accelerate`:
  python -I split_light.py <out folder> <reference> [<render>] [--masks <mask folder>]
Writes <stem>_albedo.png, <stem>_shading.png, <stem>_residual.png and <stem>_intrinsics.npz for each picture.
"""
import glob
import os
import sys

import numpy as np
import torch
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "prs-eth/marigold-iid-lighting-v1-1"


PIPELINE = {}


def load_pipeline():
    if not PIPELINE:
        from diffusers import MarigoldIntrinsicsPipeline
        PIPELINE["model"] = MarigoldIntrinsicsPipeline.from_pretrained(MODEL, variant="fp16", torch_dtype=torch.float16).to("cuda")
    return PIPELINE["model"]


def split(path, output_folder):
    # Renders are often all called gta5.png in their own folders, so the folder name joins the stem.
    stem = os.path.basename(os.path.dirname(os.path.abspath(path))) + "_" + os.path.splitext(os.path.basename(path))[0]
    saved = os.path.join(output_folder, f"{stem}_intrinsics.npz")
    if os.path.exists(saved) and os.path.getmtime(saved) > os.path.getmtime(path):
        return dict(np.load(saved))
    image = Image.open(path).convert("RGB")
    pipeline = load_pipeline()
    output = pipeline(image, num_inference_steps=4, ensemble_size=1)
    pictures = pipeline.image_processor.visualize_intrinsics(output.prediction, pipeline.target_properties)[0]
    arrays = {}
    for name, picture in pictures.items():
        picture = picture.resize(image.size)
        picture.save(os.path.join(output_folder, f"{stem}_{name}.png"))
        arrays[name] = np.asarray(picture).astype(np.float32) / 255
    np.savez_compressed(os.path.join(output_folder, f"{stem}_intrinsics.npz"), **arrays)
    return arrays


def main():
    arguments = [argument for argument in sys.argv[1:]]
    mask_folder = None
    if "--masks" in arguments:
        mask_folder = arguments[arguments.index("--masks") + 1]
        arguments.remove("--masks")
        arguments.remove(mask_folder)
    output_folder, paths = arguments[0], arguments[1:]
    os.makedirs(output_folder, exist_ok=True)
    results = [split(path, output_folder) for path in paths]
    print("parts", {name: value.shape for name, value in results[0].items()})
    if not mask_folder:
        return
    print(f"{'region':16s} {'part':9s} " + " ".join(f"{os.path.basename(path)[:22]:>24s}" for path in paths))
    for mask_path in sorted(glob.glob(os.path.join(mask_folder, "class_*.png"))):
        mask_picture = Image.open(mask_path).convert("L")
        if (np.asarray(mask_picture) > 127).mean() < 0.003:
            continue
        name = os.path.basename(mask_path)[9:-4]
        for part in ("albedo", "shading"):
            if part not in results[0]:
                continue
            cells = []
            for result in results:
                height, width = result[part].shape[:2]
                mask = np.asarray(mask_picture.resize((width, height), Image.NEAREST)) > 127
                values = result[part][mask].mean(axis=0) * 255
                cells.append(str(tuple(int(value) for value in np.round(values))))
            print(f"{name:16s} {part:9s} " + " ".join(f"{cell:>24s}" for cell in cells))


if __name__ == "__main__":
    main()
