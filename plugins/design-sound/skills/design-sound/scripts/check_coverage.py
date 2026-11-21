"""Check that every element a frame reading found has a sound: no detail left silent.

  check_coverage.py elements.json cues.json [--slack 0.1]

elements.json: {"elements": [{"id", "start", "end", "kind", "what", "sound", "prominence"}]} in the same time base
as the cue sheet (shift both the same way). An image-reading pass writes it (references/make.md, "Every element has a
sound"). Elements whose "sound" is "none" (light, glow, colour) are skipped.

A cue covers an element when its "covers" list names the element's id, or, without a "covers" list, when its time
falls inside the element's span (start - slack .. end + slack) and its label shares a word with the element. Every
element left uncovered is printed as MISSING and the exit code is 1. A lead element covered only by cues marked
"detail" (texture under another event) is printed as THIN: a lead needs a cue of its own.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IGNORED_WORDS = {"the", "a", "an", "of", "and", "on", "in", "at", "to", "pass", "lands", "small", "big"}


def words(text):
    return {word for word in re.findall(r"[a-z]+", (text or "").lower()) if word not in IGNORED_WORDS and len(word) > 2}


def covering_cues(element, cues, slack):
    named = [cue for cue in cues if element["id"] in cue.get("covers", [])]
    if named:
        return named
    element_words = words(element.get("what")) | words(element.get("sound"))
    return [cue for cue in cues if "covers" not in cue
            and element["start"] - slack <= cue["t"] <= element["end"] + slack
            and words(cue.get("label")) & element_words]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("elements")
    parser.add_argument("cues")
    parser.add_argument("--slack", type=float, default=0.1)
    arguments = parser.parse_args()
    elements = json.loads(Path(arguments.elements).read_text(encoding="utf-8"))["elements"]
    cues = json.loads(Path(arguments.cues).read_text(encoding="utf-8"))["cues"]
    missing = 0
    for element in elements:
        if str(element.get("sound", "")).lower() in ("none", ""):
            continue
        found = covering_cues(element, cues, arguments.slack)
        span = f"{element['start']:6.2f}-{element['end']:5.2f}"
        if not found:
            missing += 1
            print(f"MISSING {span} {element['id']:18s} {element.get('what', '')[:60]}  ({element.get('sound', '')})")
        elif element.get("prominence") == "lead" and all(cue.get("detail") for cue in found):
            print(f"THIN    {span} {element['id']:18s} a lead with only detail cues: "
                  f"{', '.join(cue.get('label', '?') for cue in found)}")
    total = sum(1 for element in elements if str(element.get("sound", "")).lower() not in ("none", ""))
    print(f"{total - missing} of {total} elements have a sound")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
