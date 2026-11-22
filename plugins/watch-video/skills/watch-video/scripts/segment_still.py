"""Read every region and every small thing in one still, in the shared label colours of label_palette.py.

1. Every pixel gets a label (OneFormer or EoMT-DINOv3, ADE20K classes mapped onto the shared set). With a depth .npz
   (Depth Pro 2 or any map in metres) near "mountain" becomes rock and sky seen through a tree crown becomes sky.
2. Small things come from a text-prompted detector run on the whole frame and on zoomed tiles (compare_detectors.py),
   and SAM 2.1 cuts a mask per box.
Writes panoptic.png and overlay.png (both with a legend), class_*.png and mask_*.png, classes.json and segments.json
(label, score, frame box 0-1, area share, mean colour in sRGB).

Run through the GPU queue, with the torch install line of read_geometry.py plus `--with "transformers>=4.57" --with accelerate --with scipy`:
  python -I segment_still.py <image> <out folder> "bird. utility pole. car. pine tree. bush. rock." [--every-pixel eomt|oneformer] [--detector sam3|mm-gdino-large] [--depth depth.npz] [--near-is-rock 25]
"""
import json
import os
import sys

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from transformers import OneFormerForUniversalSegmentation, OneFormerProcessor, Sam2Model, Sam2Processor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_detectors import detect_tiled, make_detector  # noqa: E402
from label_palette import LABEL_COLOURS, canonical, colour_of, with_legend  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEGMENTER = "facebook/sam2.1-hiera-large"


def segment(image, boxes, device):
    processor = Sam2Processor.from_pretrained(SEGMENTER)
    model = Sam2Model.from_pretrained(SEGMENTER).to(device)
    inputs = processor(images=image, input_boxes=[boxes], return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs, multimask_output=False)
    masks = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0]
    return masks[:, 0].numpy() > 0


EVERY_PIXEL_MODELS = {
    "oneformer": "shi-labs/oneformer_ade20k_swin_large",
    "eomt": "tue-mps/eomt-dinov3-ade-semantic-large-512",
}
NEAR_ROCK_METRES = 40
SKY_METRES = 1500


def ade_label_map(image, device, model_name):
    """Every pixel's ADE20K class name, from OneFormer or EoMT (DINOv3 backbone)."""
    repository = EVERY_PIXEL_MODELS[model_name]
    if model_name == "eomt":
        from transformers import AutoImageProcessor, AutoModelForUniversalSegmentation
        processor = AutoImageProcessor.from_pretrained(repository)
        model = AutoModelForUniversalSegmentation.from_pretrained(repository).to(device)
        inputs = processor(images=image, return_tensors="pt").to(device)
    else:
        processor = OneFormerProcessor.from_pretrained(repository)
        model = OneFormerForUniversalSegmentation.from_pretrained(repository).to(device)
        inputs = processor(images=image, task_inputs=["semantic"], return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    width, height = image.size
    if model_name == "eomt":
        # EoMT's processor pads the picture to a square at the bottom and right, and its post-processing does not
        # crop the padding back off (transformers 5.24): ask for the square, then cut the picture's part out of it.
        side = max(width, height)
        label_map = processor.post_process_semantic_segmentation(outputs, target_sizes=[(side, side)])[0].cpu().numpy()
        label_map = label_map[:height, :width]
    else:
        label_map = processor.post_process_semantic_segmentation(outputs, target_sizes=[(height, width)])[0].cpu().numpy()
    names = {int(index): name.split(",")[0] for index, name in model.config.id2label.items()}
    del model
    torch.cuda.empty_cache()
    return np.vectorize(lambda index: names[int(index)])(label_map)


def label_every_pixel(image, device, output_folder, model_name="oneformer", depth=None, near_is_rock=None):
    """A label for every pixel in the shared label set (label_palette.py), so no region is left out the way
    text-prompted boxes leave gaps. With a depth map (metres along the view axis) two known mistakes are fixed:
    "mountain" nearer than NEAR_ROCK_METRES becomes rock, and tree pixels farther than SKY_METRES (sky seen through the
    crown) become sky. Classes under 0.05% of the frame are folded into the class around them, since those were false
    on the GTA V still (a "person" that was a pier post). Writes panoptic.png with a legend, class_NN_<label>.png
    masks and classes.json (area, mean colour, frame box)."""
    raw = ade_label_map(image, device, model_name)
    labels = np.vectorize(canonical)(raw)
    if depth is not None:
        depth = np.asarray(Image.fromarray(depth.astype(np.float32)).resize(image.size, Image.NEAREST))
        labels[(labels == "far mountain") & (depth < NEAR_ROCK_METRES)] = "rock"
        if near_is_rock:
            # For a still whose foreground is known to be rock (the GTA V shelf read as "earth" and "road" by EoMT).
            labels[np.isin(labels, ["ground", "road", "far mountain"]) & (depth < near_is_rock)] = "rock"
        labels[(labels == "tree") & (~np.isfinite(depth) | (depth > SKY_METRES))] = "sky"
    for name in list(np.unique(labels)):
        mask = labels == name
        if mask.mean() < 0.0005:
            grown = ndimage.binary_dilation(mask, iterations=3) & ~mask
            neighbours, counts = np.unique(labels[grown], return_counts=True)
            labels[mask] = neighbours[np.argmax(counts)] if len(neighbours) else "other"
    pixels = np.asarray(image).astype(np.float32)
    picture = pixels.copy()
    height, width = labels.shape
    names = sorted(np.unique(labels), key=lambda value: -(labels == value).sum())
    classes = []
    for rank, name in enumerate(names):
        mask = labels == name
        picture[mask] = picture[mask] * 0.35 + np.array(LABEL_COLOURS[name], dtype=np.float32) * 0.65
        rows, columns = np.nonzero(mask)
        classes.append({"class": name, "area": round(float(mask.mean()), 4),
                        "meanColour": [round(float(value)) for value in pixels[mask].mean(axis=0)],
                        "box": [round(columns.min() / width, 3), round(rows.min() / height, 3),
                                round(columns.max() / width, 3), round(rows.max() / height, 3)]})
        Image.fromarray((mask * 255).astype(np.uint8)).save(os.path.join(output_folder, f"class_{rank:02d}_{name.replace(' ', '_')}.png"))
    with_legend(Image.fromarray(picture.astype(np.uint8)), names).save(os.path.join(output_folder, "panoptic.png"))
    with open(os.path.join(output_folder, "classes.json"), "w", encoding="utf-8") as handle:
        json.dump(classes, handle, indent=1)
    for entry in classes:
        print("class", entry["class"], entry["area"], entry["meanColour"], entry["box"])


def option(name, default):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def main():
    image_path, output_folder, prompt = sys.argv[1], sys.argv[2], sys.argv[3]
    every_pixel = option("--every-pixel", "eomt")
    # SAM 3 won the 2026-11-22 comparison on the GTA V still (compare_detectors.py): the only one to find the pier,
    # the car, fence and bushes in place, no false "pine tree" on the bare crown. mm-gdino-large is the open fallback
    # when the SAM 3 access request is not approved.
    detector_name = option("--detector", "sam3")
    near_is_rock = option("--near-is-rock", None)
    depth_path = option("--depth", None)
    os.makedirs(output_folder, exist_ok=True)
    # Masks from an earlier run would be read as regions of this one, so this script's own outputs are cleared first.
    for name in os.listdir(output_folder):
        if (name.startswith("class_") or name.startswith("mask_")) and name.endswith(".png"):
            os.remove(os.path.join(output_folder, name))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    depth =np.load(depth_path)["depth"] if depth_path else None
    label_every_pixel(image, device, output_folder, every_pixel, depth, float(near_is_rock) if near_is_rock else None)
    detector = make_detector(detector_name, device)
    phrases = [phrase.strip() for phrase in prompt.split(".") if phrase.strip()]
    detections = detect_tiled(detector, image, phrases)
    del detector
    torch.cuda.empty_cache()
    print("detections", len(detections))
    if not detections:
        return
    masks = segment(image, [box for _, _, box in detections], device)
    pixels = np.asarray(image).astype(np.float32)
    overlay = pixels.copy()
    segments = []
    order = np.argsort([-mask.sum() for mask in masks])
    for rank, index in enumerate(order):
        label, score, box = detections[index]
        mask = masks[index]
        overlay[mask] = overlay[mask] * 0.45 + np.array(colour_of(label), dtype=np.float32) * 0.55
        Image.fromarray((mask * 255).astype(np.uint8)).save(os.path.join(output_folder, f"mask_{rank:02d}_{label.replace(' ', '_')}.png"))
        mean = pixels[mask].mean(axis=0) if mask.any() else np.zeros(3)
        segments.append({
            "rank": rank, "label": label, "score": round(score, 3),
            "box": [round(box[0] / width, 3), round(box[1] / height, 3), round(box[2] / width, 3), round(box[3] / height, 3)],
            "area": round(float(mask.mean()), 4), "meanColour": [round(float(value)) for value in mean],
        })
    picture = Image.fromarray(overlay.astype(np.uint8))
    draw = ImageDraw.Draw(picture)
    for segment_info in segments:
        box = segment_info["box"]
        draw.rectangle([box[0] * width, box[1] * height, box[2] * width, box[3] * height], outline=colour_of(segment_info["label"]), width=2)
    with_legend(picture, [segment_info["label"] for segment_info in segments]).save(os.path.join(output_folder, "overlay.png"))
    with open(os.path.join(output_folder, "segments.json"), "w", encoding="utf-8") as handle:
        json.dump(segments, handle, indent=1)
    for segment_info in segments:
        print(segment_info["rank"], segment_info["label"], segment_info["score"], segment_info["box"], segment_info["area"], segment_info["meanColour"])


if __name__ == "__main__":
    main()
