"""Draw what was read and understood onto the video, so a viewer can check each claim against the picture.

Usage:
  uv run --no-project --with numpy --with pillow python annotate.py <video> --out annotated.mp4
      [--screen screen/screen.jsonl] [--notes notes.md|notes.json] [--words words.json]
      [--from <s>] [--to <s>] [--note-seconds 3.5] [--no-ocr] [--crf 20] [--text-scale 1.4]

Layers, each optional:
  OCR boxes    every text line read_screen.py found, boxed, with the text it read and its score, held until the
               next read frame. Misreads stay visible, which is the point.
  notes        the claims. A text or Markdown file: every line holding "[mm:ss.s]" becomes a card from that time
               for --note-seconds ("seen", "heard" or "measured" in the line colours it). A JSON list allows more:
               {"t": 12.5, "text": "...", "kind": "seen", "box": [x0, y0, x1, y1]} for a point claim, with an
               optional box in 0-1 frame fractions drawn around the thing it is about, or
               {"start": 31.5, "end": 165, "text": "camera: rover down-look"} for a claim about a span (a banner).
  speech       words.json (from captions.py or transcribe.py) as subtitles: what was heard, to check "heard" claims.
  timeline     a strip along the bottom with a tick per point note and a playhead.

The source audio is kept. A 1080p frame takes about 30 ms, so a 3-minute video annotates in a few minutes.
Notes are copied as written: the overlay never rewords a claim.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KIND_COLOURS = {"seen": (127, 180, 232), "heard": (232, 194, 106), "measured": (140, 203, 140)}
NOTE_COLOUR = (217, 222, 229)
OCR_COLOUR = (64, 224, 208)
PANEL = (20, 25, 32, 205)
STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.+)")
KIND_WORD = re.compile(r"\b(seen|heard|measured)\b", re.IGNORECASE)
TEXT_FONTS = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
MONO_FONTS = ["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
CAPTION_MAX_WORDS = 8
CAPTION_GAP_SECONDS = 0.7
# Subtitles sit this far above the bottom so they clear the progress bars and tickers many videos keep there.
CAPTION_LIFT = 0.13


def load_font(candidates, size):
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def probe(video):
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=width,height,r_frame_rate", "-show_entries", "format=duration", "-of", "json",
                             str(video)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    numerator, denominator = stream["r_frame_rate"].split("/")
    return int(stream["width"]), int(stream["height"]), float(numerator) / float(denominator), float(data["format"]["duration"])


def note_kind(text):
    match = KIND_WORD.search(text)
    return match.group(1).lower() if match else ""


def parse_notes(path):
    """Point notes [{t, text, kind, box}] and span notes [{start, end, text, kind}] from a .json or text file."""
    raw = Path(path).read_text(encoding="utf-8")
    points, spans = [], []
    if Path(path).suffix.lower() == ".json":
        for item in json.loads(raw):
            kind = item.get("kind") or note_kind(item["text"])
            if "start" in item:
                spans.append({"start": float(item["start"]), "end": float(item["end"]), "text": item["text"], "kind": kind})
            else:
                points.append({"t": float(item["t"]), "text": item["text"], "kind": kind, "box": item.get("box")})
    else:
        for line in raw.splitlines():
            match = STAMP.search(line)
            if match:
                seconds = int(match.group(1)) * 60 + float(match.group(2))
                points.append({"t": seconds, "text": match.group(3).strip(), "kind": note_kind(match.group(3)), "box": None})
    points.sort(key=lambda note: note["t"])
    return points, spans


def read_screen_log(path):
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    records.sort(key=lambda record: record["seconds"])
    return records


def box_to_fraction(line, record, fallback_frame):
    """A read_screen box as 0-1 fractions of the source frame, undoing its crop and upscale."""
    frame_width, frame_height = record.get("frame") or fallback_frame
    crop = record.get("crop")
    source = record.get("source")
    if crop and source:
        scale_x, scale_y = crop[2] / frame_width, crop[3] / frame_height
        return ((crop[0] + line["x0"] * scale_x) / source[0], (crop[1] + line["y0"] * scale_y) / source[1],
                (crop[0] + line["x1"] * scale_x) / source[0], (crop[1] + line["y1"] * scale_y) / source[1])
    return (line["x0"] / frame_width, line["y0"] / frame_height, line["x1"] / frame_width, line["y1"] / frame_height)


def caption_lines(words):
    """Group timed words into subtitle lines: a new line after a pause or CAPTION_MAX_WORDS words."""
    lines, current = [], []
    for word in words:
        text = word.get("text", "").replace("&nbsp;", " ").strip()
        if not text:
            continue
        if current and (len(current) >= CAPTION_MAX_WORDS or word["start"] - current[-1]["end"] > CAPTION_GAP_SECONDS):
            lines.append(current)
            current = []
        current.append({"start": float(word["start"]), "end": float(word["end"]), "text": text})
    if current:
        lines.append(current)
    return [{"start": line[0]["start"], "end": line[-1]["end"] + 0.4, "text": " ".join(word["text"] for word in line)}
            for line in lines]


def active_at(items, seconds, start_key, end_key):
    return [index for index, item in enumerate(items) if item[start_key] <= seconds < item[end_key]]


def latest_record_index(records, seconds):
    chosen = None
    for index, record in enumerate(records):
        if record["seconds"] <= seconds:
            chosen = index
        else:
            break
    return chosen


def wrap(draw, text, font, width):
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class Painter:
    def __init__(self, width, height, text_scale=1.0):
        self.width, self.height = width, height
        unit = height / 1080 * text_scale
        self.unit = unit
        self.text_font = load_font(TEXT_FONTS, round(30 * unit))
        self.small_font = load_font(TEXT_FONTS, round(22 * unit))
        self.mono_font = load_font(MONO_FONTS, round(19 * unit))

    def overlay(self, ocr_record, fallback_frame, notes, spans, caption):
        image = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if ocr_record:
            self.draw_ocr(draw, ocr_record, fallback_frame)
        for note in notes:
            if note.get("box"):
                self.draw_note_box(draw, note)
        notes_on_right = self.text_heavier_on_left(ocr_record, fallback_frame)
        self.draw_spans(draw, spans, on_right=not notes_on_right)
        self.draw_notes(draw, notes, on_right=notes_on_right)
        if caption:
            self.draw_caption(draw, caption)
        return image

    def draw_ocr(self, draw, record, fallback_frame):
        line_width = max(2, round(2 * self.unit))
        for line in record["lines"]:
            x0, y0, x1, y1 = box_to_fraction(line, record, fallback_frame)
            box = (x0 * self.width, y0 * self.height, x1 * self.width, y1 * self.height)
            draw.rectangle(box, outline=OCR_COLOUR + (255,), width=line_width)
            label = f"{line['text']}  {line['score']:.2f}"
            label_width = draw.textlength(label, font=self.mono_font)
            label_height = self.mono_font.size + 6
            top = box[1] - label_height if box[1] - label_height > 0 else box[3]
            draw.rectangle((box[0], top, box[0] + label_width + 10, top + label_height), fill=(10, 40, 40, 215))
            draw.text((box[0] + 5, top + 2), label, font=self.mono_font, fill=OCR_COLOUR + (255,))

    def draw_note_box(self, draw, note):
        colour = KIND_COLOURS.get(note["kind"], NOTE_COLOUR)
        x0, y0, x1, y1 = note["box"]
        draw.rectangle((x0 * self.width, y0 * self.height, x1 * self.width, y1 * self.height), outline=colour + (255,),
                       width=max(3, round(4 * self.unit)))

    @staticmethod
    def text_heavier_on_left(record, fallback_frame):
        """True when the read text in the top half sits more on the left, so the note cards go top right."""
        if not record:
            return False
        left_area, right_area = 0.0, 0.0
        for line in record["lines"]:
            x0, y0, x1, y1 = box_to_fraction(line, record, fallback_frame)
            if y0 > 0.5:
                continue
            area = (x1 - x0) * (min(y1, 0.5) - y0)
            left_area += area * max(0.0, min(x1, 0.5) - x0) / max(x1 - x0, 1e-6)
            right_area += area * max(0.0, x1 - max(x0, 0.5)) / max(x1 - x0, 1e-6)
        return left_area > right_area

    def draw_spans(self, draw, spans, on_right):
        margin = round(24 * self.unit)
        y = margin
        for span in spans:
            text = span["text"]
            text_width = draw.textlength(text, font=self.small_font)
            box_width = text_width + 24 * self.unit
            x = self.width - margin - box_width if on_right else margin
            draw.rounded_rectangle((x, y, x + box_width, y + self.small_font.size + 18 * self.unit),
                                   radius=8 * self.unit, fill=PANEL)
            draw.text((x + 12 * self.unit, y + 8 * self.unit), text, font=self.small_font, fill=NOTE_COLOUR + (255,))
            y += self.small_font.size + 28 * self.unit

    def draw_notes(self, draw, notes, on_right):
        margin = round(24 * self.unit)
        card_width = self.width * 0.46
        left = self.width - margin - card_width if on_right else margin
        y = margin
        for note in notes[-2:]:
            colour = KIND_COLOURS.get(note["kind"], NOTE_COLOUR)
            stamp = f"[{int(note['t'] // 60):02d}:{note['t'] % 60:04.1f}]"
            lines = wrap(draw, note["text"], self.text_font, card_width - 40 * self.unit)[:5]
            line_height = self.text_font.size * 1.25
            card_height = 20 * self.unit + self.small_font.size + 8 * self.unit + line_height * len(lines) + 14 * self.unit
            draw.rounded_rectangle((left, y, left + card_width, y + card_height), radius=12 * self.unit, fill=PANEL)
            header_y = y + 14 * self.unit
            dot = 7 * self.unit
            draw.ellipse((left + 20 * self.unit, header_y + self.small_font.size / 2 - dot,
                          left + 20 * self.unit + 2 * dot, header_y + self.small_font.size / 2 + dot), fill=colour + (255,))
            draw.text((left + 20 * self.unit + 2 * dot + 10 * self.unit, header_y),
                      f"Claude {stamp} {note['kind']}".strip(), font=self.small_font, fill=colour + (255,))
            text_y = header_y + self.small_font.size + 8 * self.unit
            for line in lines:
                draw.text((left + 20 * self.unit, text_y), line, font=self.text_font, fill=NOTE_COLOUR + (255,))
                text_y += line_height
            y += card_height + 12 * self.unit

    def draw_caption(self, draw, caption):
        lines = wrap(draw, caption, self.text_font, self.width * 0.7)[:2]
        line_height = self.text_font.size * 1.3
        bottom = self.height * (1 - CAPTION_LIFT)
        top = bottom - line_height * len(lines) - 16 * self.unit
        widest = max(draw.textlength(line, font=self.text_font) for line in lines)
        left = (self.width - widest) / 2
        label = "speech"
        draw.rounded_rectangle((left - 18 * self.unit, top, left + widest + 18 * self.unit, bottom), radius=10 * self.unit,
                               fill=(10, 10, 12, 190))
        draw.text((left - 18 * self.unit, top - self.small_font.size - 6 * self.unit), label, font=self.small_font,
                  fill=KIND_COLOURS["heard"] + (255,))
        for index, line in enumerate(lines):
            line_width = draw.textlength(line, font=self.text_font)
            draw.text(((self.width - line_width) / 2, top + 8 * self.unit + index * line_height), line,
                      font=self.text_font, fill=(245, 245, 245, 255))


def blend(frame, overlay_rgb, overlay_alpha):
    if overlay_alpha is None:
        return frame.copy()
    mixed = frame.astype(numpy.uint16) * (255 - overlay_alpha) + overlay_rgb.astype(numpy.uint16) * overlay_alpha
    return (mixed // 255).astype(numpy.uint8)


def draw_timeline(frame, points, seconds, start, end):
    height, width = frame.shape[:2]
    strip_top = height - max(6, height // 135)
    frame[strip_top:, :] = (frame[strip_top:, :] // 3)
    span = max(end - start, 0.001)
    for note in points:
        x = int((note["t"] - start) / span * (width - 1))
        if 0 <= x < width:
            frame[strip_top:, max(0, x - 2):x + 2] = KIND_COLOURS.get(note["kind"], NOTE_COLOUR)
    playhead = int((seconds - start) / span * (width - 1))
    frame[strip_top - 4:, max(0, playhead - 1):playhead + 2] = (255, 255, 255)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--out", required=True)
    parser.add_argument("--screen", help="screen.jsonl from read_screen.py")
    parser.add_argument("--notes", help="claims: a text file with [mm:ss.s] lines, or a JSON list")
    parser.add_argument("--words", help="words.json from captions.py or transcribe.py")
    parser.add_argument("--from", dest="start", type=float, default=0.0)
    parser.add_argument("--to", dest="end", type=float, default=None)
    parser.add_argument("--note-seconds", type=float, default=3.5, help="how long a point note stays up")
    parser.add_argument("--ocr-frame", default="1280x720", help="OCR frame size for old screen.jsonl files without one")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--text-scale", type=float, default=1.0, help="1.4 when the video will be shown small")
    arguments = parser.parse_args()

    width, height, frame_rate, duration = probe(arguments.video)
    end = arguments.end if arguments.end is not None else duration
    fallback_frame = [int(part) for part in arguments.ocr_frame.split("x")]
    records = read_screen_log(arguments.screen) if arguments.screen and not arguments.no_ocr else []
    points, spans = parse_notes(arguments.notes) if arguments.notes else ([], [])
    for note in points:
        note["end"] = note["t"] + arguments.note_seconds
    captions = caption_lines(json.loads(Path(arguments.words).read_text(encoding="utf-8"))) if arguments.words else []
    painter = Painter(width, height, arguments.text_scale)

    decoder = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", str(arguments.start), "-to", str(end), "-i",
                                arguments.video, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    encoder = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                                f"{width}x{height}", "-r", f"{frame_rate}", "-i", "-", "-ss", str(arguments.start),
                                "-to", str(end), "-i", arguments.video, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264",
                                "-preset", "veryfast", "-crf", str(arguments.crf), "-pix_fmt", "yuv420p", "-c:a", "aac",
                                "-b:a", "192k", "-shortest", arguments.out], stdin=subprocess.PIPE)
    frame_bytes = width * height * 3
    cached_state, overlay_rgb, overlay_alpha = None, None, None
    frame_index = 0
    while True:
        chunk = decoder.stdout.read(frame_bytes)
        if len(chunk) < frame_bytes:
            break
        seconds = arguments.start + frame_index / frame_rate
        record_index = latest_record_index(records, seconds) if records else None
        note_indexes = tuple(active_at(points, seconds, "t", "end"))
        span_indexes = tuple(active_at(spans, seconds, "start", "end"))
        caption_indexes = active_at(captions, seconds, "start", "end")
        caption_index = caption_indexes[-1] if caption_indexes else None
        state = (record_index, note_indexes, span_indexes, caption_index)
        if state != cached_state:
            has_content = record_index is not None or note_indexes or span_indexes or caption_index is not None
            if has_content:
                image = painter.overlay(records[record_index] if record_index is not None else None, fallback_frame,
                                        [points[index] for index in note_indexes], [spans[index] for index in span_indexes],
                                        captions[caption_index]["text"] if caption_index is not None else None)
                pixels = numpy.asarray(image)
                overlay_rgb, overlay_alpha = pixels[:, :, :3], pixels[:, :, 3:4]
            else:
                overlay_rgb, overlay_alpha = None, None
            cached_state = state
        frame = numpy.frombuffer(chunk, dtype=numpy.uint8).reshape(height, width, 3)
        frame = blend(frame, overlay_rgb, overlay_alpha)
        if points:
            frame = numpy.ascontiguousarray(frame)
            draw_timeline(frame, points, seconds, arguments.start, end)
        encoder.stdin.write(frame.tobytes())
        frame_index += 1
    encoder.stdin.close()
    encoder.wait()
    decoder.wait()
    print(f"wrote {arguments.out}: {frame_index} frames, {len(records)} OCR reads, {len(points)} notes, "
          f"{len(spans)} spans, {len(captions)} caption lines")


if __name__ == "__main__":
    main()
