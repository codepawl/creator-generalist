"""Run several open text-prompted detectors on one still, on the whole frame and on overlapping zoomed tiles, merge the
boxes, and write one overlay per model in the shared label colours plus a count table, so a new detector is judged on
the same picture before it replaces the current one.

Run through the GPU queue with the torch line of read_geometry.py plus `--with "transformers>=4.57" --with accelerate`:
  python -I compare_detectors.py <image> <out folder> "bird. utility pole. car. pine tree. bush. rock. fence. pier." [model ...]
Models: gdino-base, mm-gdino-large, llmdet-large, owlv2, sam3 (default: all; SAM 3 needs an approved Hugging Face
access request and is called once per phrase). Expected counts for the table can be
given as label=count after the models, for example bird=38 "utility pole=3" car=1.
"""
import json
import os
import sys
import time

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from torchvision.ops import nms
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor, Owlv2ForObjectDetection, Owlv2Processor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from label_palette import canonical, colour_of, with_legend  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODELS = {
    "gdino-base": ("IDEA-Research/grounding-dino-base", 0.3),
    "mm-gdino-large": ("openmmlab-community/mm_grounding_dino_large_all", 0.3),
    "llmdet-large": ("iSEE-Laboratory/llmdet_large", 0.3),
    "owlv2": ("google/owlv2-large-patch14-ensemble", 0.2),
    "sam3": ("facebook/sam3", 0.4),
}
TILE_COLUMNS = 3
TILE_ROWS = 2
TILE_OVERLAP = 0.15


def tiles(width, height):
    """The whole frame, then a grid of overlapping tiles, as (left, top, right, bottom)."""
    boxes = [(0, 0, width, height)]
    tile_width = width / TILE_COLUMNS * (1 + TILE_OVERLAP)
    tile_height = height / TILE_ROWS * (1 + TILE_OVERLAP)
    for row in range(TILE_ROWS):
        for column in range(TILE_COLUMNS):
            left = min(width - tile_width, column * width / TILE_COLUMNS)
            top = min(height - tile_height, row * height / TILE_ROWS)
            boxes.append((int(left), int(top), int(left + tile_width), int(top + tile_height)))
    return boxes


class GroundingDetector:
    def __init__(self, repository, threshold, device):
        self.processor = AutoProcessor.from_pretrained(repository)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(repository).to(device)
        self.threshold = threshold
        self.device = device

    def __call__(self, image, phrases):
        inputs = self.processor(images=image, text=". ".join(phrases) + ".", return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=self.threshold, text_threshold=0.25, target_sizes=[image.size[::-1]])[0]
        labels = result.get("text_labels", result.get("labels"))
        return [(str(label), float(score), box) for label, score, box in zip(labels, result["scores"].tolist(), result["boxes"].tolist())]


class OwlDetector:
    def __init__(self, repository, threshold, device):
        self.processor = Owlv2Processor.from_pretrained(repository)
        self.model = Owlv2ForObjectDetection.from_pretrained(repository).to(device)
        self.threshold = threshold
        self.device = device

    def __call__(self, image, phrases):
        queries = [f"a photo of a {phrase}" for phrase in phrases]
        inputs = self.processor(text=[queries], images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        # OWLv2 pads the picture to a square, so boxes come back in the padded square's pixels.
        side = max(image.size)
        result = self.processor.post_process_grounded_object_detection(
            outputs, threshold=self.threshold, target_sizes=[(side, side)], text_labels=[phrases])[0]
        return [(phrases[int(index)], float(score), box)
                for index, score, box in zip(result["labels"].tolist(), result["scores"].tolist(), result["boxes"].tolist())]


class Sam3Detector:
    """SAM 3: a text phrase in, every matching instance out (box, score and mask). Boxes are returned here so it is
    compared like the others; segment_still.py can take its masks directly."""

    def __init__(self, repository, threshold, device):
        from transformers import Sam3Model, Sam3Processor
        self.processor = Sam3Processor.from_pretrained(repository)
        self.model = Sam3Model.from_pretrained(repository).to(device)
        self.threshold = threshold
        self.device = device

    def __call__(self, image, phrases):
        found = []
        for phrase in phrases:
            inputs = self.processor(images=image, text=phrase, return_tensors="pt").to(self.device)
            with torch.no_grad():
                outputs = self.model(**inputs)
            result = self.processor.post_process_instance_segmentation(
                outputs, threshold=self.threshold, mask_threshold=0.5, target_sizes=inputs.get("original_sizes").tolist())[0]
            for score, box in zip(result["scores"].tolist(), result["boxes"].tolist()):
                found.append((phrase, float(score), box))
        return found


def make_detector(name, device):
    repository, threshold = MODELS[name]
    kind = {"owlv2": OwlDetector, "sam3": Sam3Detector}.get(name, GroundingDetector)
    return kind(repository, threshold, device)


def detect_tiled(detector, image, phrases):
    width, height = image.size
    found = []
    for left, top, right, bottom in tiles(width, height):
        crop = image.crop((left, top, right, bottom))
        for label, score, box in detector(crop, phrases):
            if not label.strip():
                continue
            found.append((canonical(label), score, [box[0] + left, box[1] + top, box[2] + left, box[3] + top]))
    return merge(found)


def contained_share(inner, outer):
    left, top = max(inner[0], outer[0]), max(inner[1], outer[1])
    right, bottom = min(inner[2], outer[2]), min(inner[3], outer[3])
    overlap = max(0.0, right - left) * max(0.0, bottom - top)
    area = max(1e-6, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return overlap / area


def merge(found):
    """Per label, drop boxes that overlap a higher-scoring one (IoU over 0.5), then boxes that lie 80% or more inside
    a larger box of the same label: a thing cut by a tile edge shows up as a part nested in the whole. On the GTA V
    still SAM 3 gave 5 poles for 2 and 43 rocks for about 8 before the second rule."""
    kept = []
    for label in sorted(set(item[0] for item in found)):
        items = [item for item in found if item[0] == label]
        boxes = torch.tensor([item[2] for item in items], dtype=torch.float32)
        scores = torch.tensor([item[1] for item in items])
        survivors = [items[index] for index in nms(boxes, scores, 0.5).tolist()]
        survivors.sort(key=lambda item: -(item[2][2] - item[2][0]) * (item[2][3] - item[2][1]))
        for position, item in enumerate(survivors):
            if any(contained_share(item[2], larger[2]) >= 0.8 for larger in survivors[:position]):
                continue
            kept.append(item)
    return kept


def draw_overlay(image, detections, path):
    picture = image.copy()
    draw = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=max(12, image.size[0] // 110))
    for label, score, box in detections:
        colour = colour_of(label)
        draw.rectangle(box, outline=colour, width=2)
        draw.text((box[0] + 2, box[1] - 14), f"{score:.2f}", fill=colour, font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    with_legend(picture, [label for label, _, _ in detections] or ["other"]).save(path)


def main():
    image_path, output_folder, prompt = sys.argv[1:4]
    rest = sys.argv[4:]
    chosen = [name for name in rest if name in MODELS] or list(MODELS)
    expected = dict((pair.split("=")[0], int(pair.split("=")[1])) for pair in rest if "=" in pair)
    phrases = [phrase.strip() for phrase in prompt.split(".") if phrase.strip()]
    os.makedirs(output_folder, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    image = Image.open(image_path).convert("RGB")
    table = {}
    for name in chosen:
        started = time.time()
        detector = make_detector(name, device)
        detections = detect_tiled(detector, image, phrases)
        seconds = time.time() - started
        del detector
        torch.cuda.empty_cache()
        counts = {}
        for label, _, _ in detections:
            counts[label] = counts.get(label, 0) + 1
        table[name] = {"seconds": round(seconds, 1), "counts": counts,
                       "detections": [{"label": label, "score": round(score, 3), "box": [round(value) for value in box]} for label, score, box in detections]}
        draw_overlay(image, detections, os.path.join(output_folder, f"detect_{name}.png"))
        print(name, f"{seconds:.0f} s", counts)
    with open(os.path.join(output_folder, "detectors.json"), "w", encoding="utf-8") as handle:
        json.dump(table, handle, indent=1)
    labels = sorted(set(canonical(label) for label in expected) | set(label for entry in table.values() for label in entry["counts"]))
    print("\n" + "label".ljust(14) + "expected".rjust(9) + "".join(name.rjust(16) for name in chosen))
    for label in labels:
        wanted = next((count for key, count in expected.items() if canonical(key) == label), None)
        print(label.ljust(14) + (str(wanted) if wanted is not None else "-").rjust(9)
              + "".join(str(table[name]["counts"].get(label, 0)).rjust(16) for name in chosen))


if __name__ == "__main__":
    main()
