"""UI sound kit: one set of interface sounds (key, select, switch, tick, arrow, notify, success, error) in one style,
rendered from learned models, checked, and exported for a web page or a motion graphics timeline.

  build  --models ui2 --style soft --out kit/   renders N takes per role, writes kit.json and ui-sounds.js
  check  kit/                                    one onset per short take, length limits per role
  styles                                         prints the style table

A model per role must exist as <models>/<role> (learn it with make.py learn --around-peak). Styles are make.py knobs
plus a top cut. Every take is high-passed at 300 Hz with a low-mid dip, so a click never turns into a thump.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import scipy.signal
import soundfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make  # noqa: E402
import resynth  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RATE = resynth.RATE
HIGHPASS_HZ = 300

# role: takes to render, longest allowed seconds, one onset required, level in dB under full scale for the mix
ROLES = {
    "key": (8, 0.16, False, -20),
    "select": (4, 0.10, True, -18),
    "switch": (4, 0.18, False, -18),
    "tick": (1, 0.08, True, -22),
    "arrow": (4, 0.12, True, -18),
    "notify": (2, 1.2, False, -14),
    "success": (2, 1.2, False, -14),
    "error": (2, 1.2, False, -14),
}

STYLES = {
    "faithful": ({}, None),
    "soft": ({"size": 1.05, "bright": -0.25, "hard": -0.4, "ring": 0.7}, 5000),
    "crisp": ({"size": 0.75, "bright": 0.3, "hard": 0.3, "ring": 0.7}, None),
    "warm": ({"pitch": -2, "bright": -0.5, "hard": -0.2}, 4000),
    "toy": ({"size": 0.7, "pitch": 3, "ring": 1.2}, None),
}

TICK_STEPS = 8
TICK_SEMITONES = 2
# Low-mid dip against a muddy, heavy sound.
MUD_CENTRE_HZ = 350
MUD_CUT_DB = -4.0
# Semitone steps for repeats of one role, so a run never plays the same pitch twice in a row
#.
PITCH_CYCLE = [0, 2, -1, 3, 1, -2]
# Keys never follow the musical cycle: real typing moves under half a semitone, and a key high-passed at 300 Hz loses
# the keyboard's body. Both made coded typing sound childish.
KEY_DETUNE_CENTS = [0, 30, -25, 15, -35, 40, -10]
KEY_HIGHPASS_HZ = 120


def mud_dip(mono):
    """RBJ peaking filter: a broad cut around the low mids where UI clicks turn thick."""
    gain = 10 ** (MUD_CUT_DB / 40)
    omega = 2 * np.pi * MUD_CENTRE_HZ / RATE
    alpha = np.sin(omega) / (2 * 0.8)
    numerator = [1 + alpha * gain, -2 * np.cos(omega), 1 - alpha * gain]
    denominator = [1 + alpha / gain, -2 * np.cos(omega), 1 - alpha / gain]
    return scipy.signal.lfilter(numerator, denominator, mono)


def filtered(mono, lowpass_hz, role=None):
    corner_hz = KEY_HIGHPASS_HZ if role == "key" else HIGHPASS_HZ
    sections = scipy.signal.butter(2, corner_hz, "high", fs=RATE, output="sos")
    mono = scipy.signal.sosfilt(sections, mono)
    if role != "key":
        mono = mud_dip(mono)
    if lowpass_hz:
        sections = scipy.signal.butter(4, lowpass_hz, "low", fs=RATE, output="sos")
        mono = scipy.signal.sosfilt(sections, mono)
    return mono.astype(np.float32)


def trimmed(mono, floor_db=-50):
    peak = np.max(np.abs(mono)) + 1e-9
    loud = np.where(np.abs(mono) > peak * 10 ** (floor_db / 20))[0]
    if loud.size == 0:
        return mono
    return mono[max(0, loud[0] - RATE // 500): loud[-1] + RATE // 100]


def onsets(mono):
    """Separate strikes: rises past a quarter of the peak after at least 25 ms below a tenth of it."""
    window = RATE // 1000
    level = np.convolve(np.abs(mono), np.ones(window) / window, mode="same")
    peak = level.max() + 1e-9
    quiet_needed = int(0.025 * RATE)
    quiet_run = quiet_needed
    found = []
    armed = True
    for index, value in enumerate(level):
        if value < peak * 0.1:
            quiet_run += 1
            if quiet_run >= quiet_needed:
                armed = True
            continue
        quiet_run = 0
        if armed and value > peak * 0.25:
            found.append(index / RATE)
            armed = False
    return found


def audible_seconds(mono, floor_db=-40):
    peak = np.max(np.abs(mono)) + 1e-9
    loud = np.where(np.abs(mono) > peak * 10 ** (floor_db / 20))[0]
    return 0.0 if loud.size == 0 else (loud[-1] - loud[0]) / RATE


def capped(mono, longest):
    """Fade the tail so the take ends within its role's length; the strike itself is never cut."""
    limit = int(longest * RATE)
    if len(mono) <= limit:
        return mono
    shaped = mono[:limit].copy()
    fade = limit // 3
    shaped[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32) ** 2
    return shaped


def render_take(model, seed, controls, lowpass_hz, longest, role=None):
    take, _, _ = make.checked_take(model, seed, controls)
    mono = np.asarray(take, dtype=np.float32)
    if mono.ndim > 1:
        mono = mono.mean(axis=0)
    return make.peak_normalised(capped(trimmed(filtered(mono, lowpass_hz, role)), longest))


def command_build(arguments):
    controls, lowpass_hz = STYLES[arguments.style]
    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)
    kit = {"style": arguments.style, "controls": controls, "lowpass_hz": lowpass_hz, "rate": RATE, "roles": {}}
    for role, (count, longest, _, level_db) in ROLES.items():
        path = make.model_path(f"{arguments.models}/{role}")
        if not Path(path).exists():
            print(f"skip {role}: no model {arguments.models}/{role}")
            continue
        model = resynth.load(path)
        files = []
        steps = TICK_STEPS if role == "tick" else count
        for index in range(steps):
            knobs = dict(controls)
            if role == "tick":
                knobs["pitch"] = knobs.get("pitch", 0) + index * TICK_SEMITONES
            else:
                knobs["vary"] = arguments.vary
            take = render_take(model, arguments.seed + index, knobs, lowpass_hz, longest, role)
            name = f"{role}_{index + 1}.wav"
            soundfile.write(out / name, take, RATE, subtype="PCM_16")
            files.append(name)
        kit["roles"][role] = {"files": files, "level_db": level_db, "rotate": role != "tick"}
        print(f"{role}: {len(files)} takes")
    (out / "kit.json").write_text(json.dumps(kit, indent=1), encoding="utf-8")
    (out / "ui-sounds.js").write_text(web_player(kit), encoding="utf-8")
    problems = check_folder(out)
    print(f"kit {arguments.style} -> {out}  ({len(problems)} problems)")
    return 1 if problems else 0


def web_player(kit):
    roles = {role: {"files": entry["files"], "gain": round(10 ** (entry["level_db"] / 20), 4),
                    "rotate": entry["rotate"]} for role, entry in kit["roles"].items()}
    return f"""// UI sounds, style "{kit['style']}". Usage: import {{ uiSound }} from "./ui-sounds.js"; uiSound("select");
// Ticks step up in pitch: uiSound("tick", stepIndex). Sound starts after the first user gesture (browser rule).
const KIT = {json.dumps(roles)};
const PITCH_CYCLE = {json.dumps(PITCH_CYCLE)};
const KEY_DETUNE_CENTS = {json.dumps(KEY_DETUNE_CENTS)};
const base = new URL(".", import.meta.url);
let context = null;
const buffers = {{}};
const turns = {{}};
const plays = {{}};
let muted = false;

async function load(role) {{
  context ??= new AudioContext();
  buffers[role] ??= Promise.all(KIT[role].files.map(async (file) => {{
    const response = await fetch(new URL(file, base));
    return context.decodeAudioData(await response.arrayBuffer());
  }}));
  return buffers[role];
}}

export function setMuted(value) {{ muted = value; }}

export async function uiSound(role, step = 0) {{
  if (muted || !KIT[role]) return;
  const takes = await load(role);
  turns[role] = ((turns[role] ?? -1) + 1) % takes.length;
  const index = KIT[role].rotate ? turns[role] : Math.min(step, takes.length - 1);
  const source = context.createBufferSource();
  const gain = context.createGain();
  source.buffer = takes[index];
  if (KIT[role].rotate) {{
    // A repeat of the same role moves to the next pitch step, so a run never sounds like one sample looping.
    plays[role] = (plays[role] ?? -1) + 1;
    // Keys only detune a little, like real typing; the musical cycle on keys sounds childish.
    source.detune.value = role === "key"
      ? KEY_DETUNE_CENTS[plays[role] % KEY_DETUNE_CENTS.length]
      : 100 * PITCH_CYCLE[plays[role] % PITCH_CYCLE.length];
  }}
  gain.gain.value = KIT[role].gain;
  source.connect(gain).connect(context.destination);
  source.start();
}}
"""


def check_folder(folder):
    folder = Path(folder)
    kit = json.loads((folder / "kit.json").read_text(encoding="utf-8"))
    problems = []
    for role, entry in kit["roles"].items():
        _, longest, single, _ = ROLES[role]
        for name in entry["files"]:
            mono, _ = soundfile.read(folder / name, dtype="float32")
            seconds = audible_seconds(mono)
            strikes = onsets(mono)
            if seconds > longest:
                problems.append(f"{name}: {seconds * 1000:.0f} ms, longer than {longest * 1000:.0f} ms for {role}")
            if single and len(strikes) > 1:
                problems.append(f"{name}: {len(strikes)} strikes at {[round(t * 1000) for t in strikes]} ms; a "
                                f"{role} must strike once (cut the source tighter with --around-peak)")
    for line in problems:
        print(line)
    return problems


def command_check(arguments):
    problems = check_folder(arguments.folder)
    print("clean" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


def command_styles(arguments):
    for name, (controls, lowpass_hz) in STYLES.items():
        print(f"{name:9s} {json.dumps(controls)}  top cut {lowpass_hz or 'none'}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--models", default="ui2", help="model folder under models/, one model per role")
    build.add_argument("--style", default="faithful", choices=sorted(STYLES))
    build.add_argument("--out", required=True)
    build.add_argument("--seed", type=int, default=40)
    build.add_argument("--vary", type=float, default=0.3)
    check = commands.add_parser("check")
    check.add_argument("folder")
    commands.add_parser("styles")
    arguments = parser.parse_args()
    handler = {"build": command_build, "check": command_check, "styles": command_styles}[arguments.command]
    sys.exit(handler(arguments))


if __name__ == "__main__":
    main()
