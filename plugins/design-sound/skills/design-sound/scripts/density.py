"""Check a cue sheet for a wall of sound: too many events, events too close, tails piling up.

  density.py cues.json [--max-per-second 1.0] [--min-gap 0.25] [--max-overlap 2]

A designed moment needs room around it. Flags:
  BUSY      a 2 s window with more effects cues than max-per-second allows
  CROWDED   two strong cues (not marked "small") closer than min-gap seconds
  PILED     more than max-overlap cues sounding at once (each cue lasts pre + length)
Beds are left out. A cue may carry "small": true for a quiet detail (a tick under a hit) that does not count as a
moment of its own; it still counts toward PILED. A cue with "detail": true is part of another event's texture
(sparks, dust, smoke and embers of a blast) and counts toward neither: keep it well under its lead in the mix.
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cues")
    parser.add_argument("--max-per-second", type=float, default=1.0)
    parser.add_argument("--min-gap", type=float, default=0.25)
    parser.add_argument("--max-overlap", type=int, default=2)
    arguments = parser.parse_args()
    sheet = json.loads(Path(arguments.cues).read_text(encoding="utf-8"))
    effects = sorted((cue for cue in sheet["cues"] if cue.get("stem", "sfx") != "bed" and not cue.get("detail")),
                     key=lambda cue: cue["t"])
    duration = sheet.get("duration", effects[-1]["t"] + 1 if effects else 0)
    flags = []
    window = 2.0
    start = 0.0
    while start < duration:
        inside = [cue for cue in effects if start <= cue["t"] < start + window and not cue.get("small")]
        if len(inside) > arguments.max_per_second * window:
            flags.append(f"BUSY     {start:5.1f}-{start + window:4.1f} s: {len(inside)} moments "
                         f"({', '.join(cue.get('label', '?') for cue in inside)})")
        start += 1.0
    strong = [cue for cue in effects if not cue.get("small")]
    for first, second in zip(strong, strong[1:]):
        if second["t"] - first["t"] < arguments.min_gap:
            flags.append(f"CROWDED  {first['t']:5.2f} s {first.get('label', '?')} and {second['t']:.2f} s "
                         f"{second.get('label', '?')}: {second['t'] - first['t']:.2f} s apart")
    spans = [(cue["t"] - cue.get("pre", 0.03), cue["t"] + cue.get("length", 1.0), cue.get("label", "?")) for cue in effects]
    reported = set()
    for begin, _, label in spans:
        sounding = [name for start_time, end_time, name in spans if start_time <= begin + 0.05 < end_time]
        if len(sounding) > arguments.max_overlap and tuple(sounding) not in reported:
            reported.add(tuple(sounding))
            flags.append(f"PILED    {begin:5.2f} s: {len(sounding)} at once ({', '.join(sounding)})")
    moments = len(strong)
    print(f"{len(effects)} effects cues, {moments} moments, {moments / max(duration, 1e-6):.2f} per second over {duration:.1f} s")
    for flag in flags:
        print(flag)
    if not flags:
        print("clean")
    sys.exit(1 if flags else 0)


if __name__ == "__main__":
    main()
