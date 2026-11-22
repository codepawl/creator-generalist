"""Meme sounds: a catalogue of originals with the moments each one fits, and a detector that finds those moments.

Memes are used as they are. A take is never made from a meme; only pitch and speed may change at placement.

  memes.py build <folder>... [--audit audit.json] [--out <library>/memes.json]
      Scan folders for meme files, tag each with the moments it fits (from its name, see TAG_RULES), measure its
      length and the time of its peak, and drop files an audit marks as duplicates. Tags in
      <library>/memes-overrides.json ({"file name": ["moment", ...]}) replace the rule tags for that file.
  memes.py detect <words.json> [--events events.json] [--out cues.json] [--gap 6] [--per-minute 4] [--seed N]
      Find meme moments in a word-timed transcript (watch-video words.json: start, end, text) and an optional event
      list (t, kind: hit, fall, impact, fail, win, reveal), choose one meme per moment without reuse, and write cues.
      Each cue says why it was chosen. Cues sit in pauses, never on top of speech, except a censor beep.
  memes.py stem cues.json --out memes.wav [--seconds S]
      Put the cues' original files on one stem (gain, pitch, speed, fade at the next word) for mix.py.
  memes.py list

The detector proposes; the cut decides. A project rule that forbids memes wins.
"""
import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))
from sound_library import LIBRARY_DIRECTORY  # noqa: E402

CATALOGUE_FILE = LIBRARY_DIRECTORY / "memes.json"
OVERRIDES_FILE = LIBRARY_DIRECTORY / "memes-overrides.json"
SAMPLE_RATE = 24000
AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".mp4"}

# Name fragment -> moments it fits. Placement per moment is in MOMENTS.
TAG_RULES = [
    ("vine boom", ["shock", "punchline"]), ("dun dun", ["shock", "dramatic"]), ("taco bell", ["shock"]),
    ("record scratch", ["flashback", "shock"]), ("flashback", ["flashback"]), ("rewind", ["flashback"]),
    ("few moments later", ["later"]), ("to be continued", ["ending"]), ("directed by", ["ending"]),
    ("sad violin", ["fail"]), ("sad music", ["fail"]), ("fail", ["fail"]), ("wasted", ["fail"]), ("mario death", ["fail"]),
    ("oof", ["fail", "hit"]), ("hurt", ["hit"]), ("emotional damage", ["fail"]), ("error", ["fail"]),
    ("wrong answer", ["fail"]), ("curb your", ["fail", "awkward"]), ("bruh", ["fail", "confused"]),
    ("crickets", ["awkward"]), ("awkward", ["awkward"]), ("huh", ["confused"]), ("hmm", ["confused"]),
    ("nani", ["shock", "confused"]), ("sus", ["confused"]), ("villager", ["confused"]),
    ("correct", ["win"]), ("mission passed", ["win"]), ("angelic", ["win"]), ("angels", ["win"]),
    ("powerup", ["win"]), ("level up", ["win"]), ("gigachad", ["win"]), ("cheering", ["win", "applause"]),
    ("yeyy", ["win", "applause"]), ("applause", ["applause"]), ("clapping", ["applause"]), ("party horn", ["win"]),
    ("airhorn", ["win", "punchline"]), ("wow", ["shock", "win"]), ("rizz", ["win"]),
    ("idea", ["idea"]), ("cash", ["money"]), ("coin", ["money"]), ("racks", ["money"]), ("kaching", ["money"]),
    ("bonk", ["hit"]), ("metal pipe", ["hit"]), ("punch", ["hit"]), ("slap", ["hit"]), ("splash", ["hit"]),
    ("splat", ["hit"]), ("slip", ["hit", "fail"]), ("fart", ["hit", "punchline"]), ("quack", ["punchline"]),
    ("rubber duck", ["punchline"]), ("badum", ["punchline"]), ("dolphin", ["punchline"]), ("goofy", ["punchline"]),
    ("censor", ["censor"]), ("fbi open up", ["reveal"]), ("among us", ["reveal"]), ("drum roll", ["reveal"]),
    ("suspense", ["dramatic"]), ("scream", ["shock"]), ("shocked", ["shock"]), ("awww", ["fail"]), ("boo", ["fail"]),
    ("yeet", ["throw"]), ("throw", ["throw"]), ("glass break", ["hit"]), ("falling", ["fall"]),
    ("windows xp startup", ["start"]), ("windows xp shutdown", ["ending"]), ("boxing bell", ["start"]),
    ("snore", ["awkward"]), ("laugh", ["punchline"]), ("hes bacaaaack", ["reveal"]), ("i cant stop", ["punchline"]),
    ("you look lonely", ["punchline"]), ("heartbeat", ["dramatic"]), ("alert", ["reveal"]),
]

# Moment -> where the meme goes: "after" sits in the pause after the phrase, "on" puts its peak on the event,
# "lead" ends its peak on the event (a drum roll), "over" covers the word.
MOMENTS = {
    "punchline": {"place": "after", "words": []},
    "awkward": {"place": "after", "words": []},
    "fail": {"place": "after", "words": ["fail", "failed", "broke", "broken", "crash", "crashed", "oops", "wrong",
                                          "died", "dead", "lost", "ruined", "disaster", "mistake", "bug", "exploded",
                                          "collapsed", "fell", "destroyed", "failure"]},
    "shock": {"place": "after", "words": ["wait", "actually", "secret", "impossible", "insane", "crazy", "seriously",
                                           "unbelievable", "no way", "turns out", "what the"]},
    "win": {"place": "after", "words": ["worked", "finally", "perfect", "success", "passed", "won", "nailed",
                                         "done it", "it works"]},
    "confused": {"place": "after", "words": ["huh", "why", "confused", "weird", "strange", "hmm", "what?"]},
    "flashback": {"place": "after", "words": ["years ago", "back then", "remember when", "flashback", "used to"]},
    "later": {"place": "after", "words": ["hours later", "later that", "next day", "meanwhile", "weeks later"]},
    "idea": {"place": "after", "words": ["idea", "figured", "realised", "realized", "genius"]},
    "money": {"place": "after", "words": ["money", "dollars", "paid", "price", "cost", "cash", "rich", "expensive"]},
    "reveal": {"place": "lead", "words": ["introducing", "here it is", "reveal", "ladies and gentlemen"]},
    "hit": {"place": "on", "words": []},
    "fall": {"place": "on", "words": []},
    "throw": {"place": "on", "words": ["yeet", "throw", "threw"]},
    "applause": {"place": "after", "words": ["thank you", "congrats", "congratulations", "celebrate"]},
    "censor": {"place": "over", "words": ["fuck", "fucking", "shit", "bitch", "damn"]},
    "ending": {"place": "after", "words": []},
    "start": {"place": "on", "words": []},
    "dramatic": {"place": "after", "words": ["suddenly", "but then", "until"]},
}
EVENT_MOMENTS = {"hit": "hit", "impact": "hit", "fall": "fall", "fail": "fail", "win": "win", "reveal": "reveal",
                 "throw": "throw", "end": "ending", "start": "start"}


def decode(path):
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True).stdout, dtype=np.float32)


def tags_for(name):
    lowered = re.sub(r"[_\-]+", " ", name.lower())
    tags = []
    for fragment, moments in TAG_RULES:
        # Whole words only: "boo" must not tag "boom", nor "sus" tag "suspense".
        if re.search(rf"\b{re.escape(fragment)}\b", lowered):
            tags += [moment for moment in moments if moment not in tags]
    return tags


def command_build(arguments):
    duplicates = set()
    if arguments.audit:
        for record in json.loads(Path(arguments.audit).read_text(encoding="utf-8")):
            if record.get("is_dup"):
                duplicates.add(Path(record["path"]).name.lower())
    overrides = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8")) if OVERRIDES_FILE.exists() else {}
    entries = []
    seen_names = set()
    for folder in arguments.folders:
        for path in sorted(Path(folder).rglob("*")):
            if path.suffix.lower() not in AUDIO_EXTENSIONS or path.name.lower() in duplicates:
                continue
            tags = overrides.get(path.name) or tags_for(path.stem)
            # Same meme under another file name ("Mario Coin Sound - Sound Effect (HD)" and "mario-coin").
            plain = re.sub(r"\(.*?\)|\[.*?\]|\b(sound|effects?|sfx|hd|no copyright|free|meme|microsoft)\b", " ",
                           path.stem.lower())
            key = re.sub(r"[^a-z]", "", plain)
            if not tags or key in seen_names:
                continue
            seen_names.add(key)
            mono = decode(path)
            if mono.size == 0:
                continue
            envelope = np.convolve(np.abs(mono), np.ones(240) / 240, mode="same")
            # Audible length: the last moment above -45 dB of the peak, so padded files fit the pauses they fill.
            audible = np.where(envelope > envelope.max() * 10 ** (-45 / 20))[0]
            entries.append({"id": key, "file": str(path.resolve()), "name": path.stem, "moments": tags,
                            "seconds": round((audible[-1] if audible.size else mono.size) / SAMPLE_RATE, 3),
                            "file_seconds": round(mono.size / SAMPLE_RATE, 3),
                            "peak_s": round(int(np.argmax(envelope)) / SAMPLE_RATE, 3),
                            "licence": "unknown"})
    out = Path(arguments.out) if arguments.out else CATALOGUE_FILE
    out.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    counts = {}
    for entry in entries:
        for moment in entry["moments"]:
            counts[moment] = counts.get(moment, 0) + 1
    print(f"{len(entries)} memes -> {out}")
    print("  " + ", ".join(f"{moment} {count}" for moment, count in sorted(counts.items(), key=lambda item: -item[1])))
    untagged = [moment for moment in MOMENTS if moment not in counts]
    if untagged:
        print(f"  no meme yet for: {', '.join(untagged)}")


def clean_words(words):
    kept = []
    for word in words:
        text = re.sub(r"&gt;|&lt;|\[.*?\]", "", word.get("text", "")).strip()
        if text:
            kept.append({"start": float(word["start"]), "end": float(word["end"]), "text": text})
    return kept


def pause_after(words, index):
    return (words[index + 1]["start"] - words[index]["end"]) if index + 1 < len(words) else 3.0


def phrase_end(words, index, minimum_pause=0.35, look_ahead_seconds=4.0):
    """The first word at or after index followed by a real pause: a meme goes there, not inside the sentence."""
    for later in range(index, len(words)):
        if words[later]["start"] - words[index]["start"] > look_ahead_seconds:
            break
        if pause_after(words, later) >= minimum_pause:
            return later
    return index


def find_moments(words, events, awkward_pause):
    """Candidate moments: trigger words and phrases, long pauses, short exclamations before a pause, and events."""
    moments = []
    lowered = [word["text"].lower().strip(".,!?\"'") for word in words]
    for index, word in enumerate(words):
        window = " ".join(lowered[max(0, index - 3): index + 1])
        for moment, rule in MOMENTS.items():
            for trigger in rule["words"]:
                trigger_lower = trigger.lower()
                matched = (lowered[index] == trigger_lower.strip("?")) if " " not in trigger_lower \
                    else window.endswith(trigger_lower)
                if trigger_lower.endswith("?"):
                    matched = matched and word["text"].endswith("?")
                if matched:
                    end_index = index if rule["place"] == "over" else phrase_end(words, index)
                    moments.append({"moment": moment, "word_index": end_index, "t": words[end_index]["end"],
                                    "pause": pause_after(words, end_index), "strength": 2, "trigger_index": index,
                                    "why": f'said "{trigger}" at {word["start"]:.2f} s'})
        word_pause = pause_after(words, index)
        sentence_end = word["text"][-1:] in "!?."
        if sentence_end and word_pause >= awkward_pause:
            moments.append({"moment": "awkward", "word_index": index, "t": word["end"], "pause": word_pause,
                            "strength": 1, "why": f"{word_pause:.1f} s of silence after a line"})
        elif word["text"].endswith("!") and word_pause >= 0.6:
            moments.append({"moment": "punchline", "word_index": index, "t": word["end"], "pause": word_pause,
                            "strength": 1, "why": f"exclamation, then {word_pause:.1f} s pause"})
    for event in events:
        moment = EVENT_MOMENTS.get(event.get("kind", ""))
        if moment:
            moments.append({"moment": moment, "word_index": None, "t": float(event["t"]), "pause": None,
                            "strength": 3, "why": f'event "{event.get("what", event["kind"])}" at {event["t"]} s'})
    return moments


def speech_at(words, start, end):
    return any(word["start"] < end and word["end"] > start for word in words)


def command_detect(arguments):
    catalogue = json.loads(CATALOGUE_FILE.read_text(encoding="utf-8"))
    words = clean_words(json.loads(Path(arguments.words).read_text(encoding="utf-8")))
    events = json.loads(Path(arguments.events).read_text(encoding="utf-8")) if arguments.events else []
    generator = random.Random(arguments.seed)
    candidates = find_moments(words, events, arguments.awkward_pause)
    # Strongest first; in one phrase the trigger said last wins ("actually worked" is a win, not a shock).
    candidates.sort(key=lambda moment: (-moment["strength"], moment["t"], -moment.get("trigger_index", 0)))
    used_files = set()
    cues = []
    for moment in candidates:
        rule = MOMENTS[moment["moment"]]
        options = [entry for entry in catalogue if moment["moment"] in entry["moments"]
                   and entry["file"] not in used_files]
        if not options:
            continue
        if rule["place"] == "after" and moment["pause"] is not None:
            # Prefer a meme that ends inside the pause; a longer one is faded out when the next word starts.
            fitting = [entry for entry in options if entry["seconds"] <= moment["pause"] + 0.3]
            options = fitting or [entry for entry in options if entry["seconds"] <= 6.0] or options
        entry = generator.choice(options)
        gain_db = -8.0
        if rule["place"] == "after":
            start = moment["t"] + 0.08
        elif rule["place"] == "lead":
            start = moment["t"] - entry["peak_s"] - 0.05
            gain_db = -12.0
        elif rule["place"] == "over":
            word = words[moment["word_index"]]
            start = word["start"]
            gain_db = -4.0
        else:
            start = moment["t"] - entry["peak_s"]
        start = max(0.0, start)
        end = start + entry["seconds"]
        if any(abs(start - cue["t"]) < arguments.gap for cue in cues):
            continue
        minute = int(start // 60)
        if sum(1 for cue in cues if int(cue["t"] // 60) == minute) >= arguments.per_minute:
            continue
        if rule["place"] == "after" and speech_at(words, start + 0.05, start + 0.3):
            continue
        if rule["place"] == "on" and speech_at(words, start, end):
            # A hit in the picture still plays under speech, only quieter.
            gain_db = -14.0
        next_words = [word["start"] for word in words if word["start"] > start + 0.3]
        fade_at = None
        if rule["place"] == "after" and next_words and next_words[0] < end:
            fade_at = round(next_words[0], 3)
        used_files.add(entry["file"])
        cues.append({"t": round(start, 3), "file": entry["file"], "meme": entry["name"], "moment": moment["moment"],
                     "why": moment["why"], "gain_db": gain_db, "fade_at": fade_at,
                     "pitch": 0, "speed": 1.0})
    cues.sort(key=lambda cue: cue["t"])
    for cue in cues:
        print(f'{cue["t"]:8.2f} s  {cue["moment"]:10s} {cue["meme"][:34]:34s}  {cue["why"]}')
    print(f"{len(cues)} cues from {len(candidates)} candidate moments")
    if arguments.out:
        Path(arguments.out).write_text(json.dumps(cues, indent=1, ensure_ascii=False), encoding="utf-8")


def load_original(path, pitch, speed):
    """The original file at 48 kHz stereo; pitch in semitones (length follows, like a record) and speed (pitch kept)."""
    filters = []
    if pitch:
        factor = 2 ** (pitch / 12)
        filters.append(f"asetrate={int(48000 * factor)},aresample=48000")
    if speed and abs(speed - 1.0) > 1e-3:
        filters.append(f"atempo={speed}")
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", "48000"]
    if filters:
        command += ["-af", ",".join(filters)]
    raw = subprocess.run(command + ["-f", "f32le", "-"], capture_output=True).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    return samples[: samples.size // 2 * 2].reshape(-1, 2)


def command_stem(arguments):
    """Place the cues' original files on one stereo stem: gain, pitch, speed and a 150 ms fade at fade_at."""
    import soundfile

    cues = json.loads(Path(arguments.cues).read_text(encoding="utf-8"))
    length = arguments.seconds or max(cue["t"] + 30 for cue in cues)
    stem = np.zeros((int(length * 48000), 2), dtype=np.float32)
    for cue in cues:
        clip = load_original(cue["file"], cue.get("pitch", 0), cue.get("speed", 1.0)) * 10 ** (cue["gain_db"] / 20)
        if cue.get("fade_at"):
            cut = int((cue["fade_at"] - cue["t"]) * 48000)
            fade = 7200
            if 0 < cut < len(clip):
                clip = clip[: cut + fade].copy()
                clip[cut:] *= np.linspace(1, 0, len(clip) - cut)[:, None]
        begin = int(cue["t"] * 48000)
        end = min(len(stem), begin + len(clip))
        stem[begin:end] += clip[: end - begin]
    soundfile.write(arguments.out, stem, 48000, subtype="PCM_24")
    print(f"{len(cues)} memes -> {arguments.out} ({length:.1f} s); originals, no new takes")


def command_list(arguments):
    for entry in json.loads(CATALOGUE_FILE.read_text(encoding="utf-8")):
        print(f'{entry["name"][:40]:40s} {entry["seconds"]:5.2f} s  {", ".join(entry["moments"])}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("folders", nargs="+")
    build.add_argument("--audit")
    build.add_argument("--out")
    detect = commands.add_parser("detect")
    detect.add_argument("words")
    detect.add_argument("--events")
    detect.add_argument("--out")
    detect.add_argument("--gap", type=float, default=6.0, help="seconds between two memes at least")
    detect.add_argument("--per-minute", type=int, default=4)
    detect.add_argument("--awkward-pause", type=float, default=1.6)
    detect.add_argument("--seed", type=int, default=0)
    commands.add_parser("list")
    stem = commands.add_parser("stem")
    stem.add_argument("cues")
    stem.add_argument("--out", required=True)
    stem.add_argument("--seconds", type=float)
    arguments = parser.parse_args()
    commands_by_name = {"build": command_build, "detect": command_detect, "stem": command_stem, "list": command_list}
    commands_by_name[arguments.command](arguments)


if __name__ == "__main__":
    main()
