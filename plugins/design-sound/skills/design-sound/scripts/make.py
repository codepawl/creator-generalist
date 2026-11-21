"""Make sounds by code: learn recordings into models, render new takes with controls, check every take.

  make.py learn <recording> --name family/id [--from S] [--to S] [--force]
      Analyse a recording (or a cut of it) into a model under <library>/models/family/id.npz. Prints how close a
      take comes to the recording against the model's own floor (two takes against each other) and the audit.
  make.py render <family/id or model.npz> --out take.wav [--seed N] [--n N] [controls]
      A new take. Controls: --size (0.6-1.6, bigger is lower and slower), --pitch (semitones), --length (time
      between onsets), --bright, --hard, --energy, --weight (-1..1), --ring (decay time factor), --vary (0..1).
      A take that fails its audit is rendered again on seed + 101, + 202, + 303. Prints onset_s and peak_s:
      start the file at the event time minus peak_s.
  make.py design <riser|subdrop|whoosh|blip|tick> --out x.wav [design options]  (see designs.py)
  make.py list

Models are numbers learned from recordings, never their samples; every render draws fresh noise, and the same
seed and controls always give the same samples. Licence and source of each recording travel in the model.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))
import resynth  # noqa: E402
from sound_library import INDEX_FILE, LIBRARY_DIRECTORY, load_mono  # noqa: E402,F401

MODELS_DIRECTORY = LIBRARY_DIRECTORY / "models"
CONTROL_NAMES = ("size", "pitch", "length", "bright", "hard", "ring", "weight", "energy", "vary")
RESEED_STEPS = (0, 101, 202, 303)


def library_entry(path):
    if not INDEX_FILE.exists():
        return {}
    wanted = str(Path(path).resolve()).replace("\\", "/").lower()
    for entry in json.loads(INDEX_FILE.read_text(encoding="utf-8")).get("files", []):
        if str(entry.get("path", "")).replace("\\", "/").lower() == wanted:
            return {key: entry.get(key) for key in ("licence", "licence_text", "author", "origin")}
    return {}


def read_recording(path, start, end):
    import librosa
    duration = None if end is None else max(0.01, end - start)
    audio, _ = librosa.load(str(path), sr=resynth.RATE, mono=False, offset=start, duration=duration)
    if audio.ndim == 1:
        audio = np.stack([audio, audio])
    return audio


def model_path(name):
    candidate = Path(name)
    if candidate.suffix == ".npz" and candidate.exists():
        return candidate
    return MODELS_DIRECTORY / f"{name}.npz"


def peak_normalised(take, peak_db=-1.0):
    return take * (10 ** (peak_db / 20) / (np.abs(take).max() + 1e-12))


def checked_take(model, seed, controls):
    """Render on seed, then on seed + 101 ... until the audit is clean; returns the take, its seed and faults."""
    reference_rise = model["meta"].get("rise_ms")
    first = None
    for step in RESEED_STEPS:
        take = resynth.render(model, seed=seed + step, **controls)
        faults = resynth.audit(take, reference_rise if not controls.get("length") else None)
        if not faults:
            return take, seed + step, []
        first = first or (take, seed + step, faults)
    return first


def take_summary(take, seed, faults):
    onset, peak = resynth.timing(take)
    return {"seconds": round(take.shape[1] / resynth.RATE, 3), "onset_s": round(onset, 3),
            "peak_s": round(peak, 3), "seed": seed, "audit": faults or "clean"}


def source_quality(path, audio):
    """Problems that make a model sound cheap: a lossy file, a cut-off top end, clipping. Empty means fine."""
    import subprocess
    problems = []
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                            "stream=codec_name,bit_rate", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True).stdout.strip().split(",")
    codec = probe[0] if probe and probe[0] else "?"
    bitrate = int(probe[1]) if len(probe) > 1 and probe[1].isdigit() else None
    if codec in ("mp3", "vorbis", "aac", "opus") and bitrate and bitrate < 128000:
        problems.append(f"lossy {codec} at {bitrate // 1000} kbps")
    mono = audio.mean(axis=0)
    spectrum = np.convolve(np.abs(np.fft.rfft(mono)) ** 2, np.ones(200) / 200, mode="same")
    frequencies = np.fft.rfftfreq(len(mono), 1.0 / resynth.RATE)
    heard = np.where(10 * np.log10(spectrum + 1e-20) > 10 * np.log10(spectrum.max() + 1e-20) - 70)[0]
    top = frequencies[heard[-1]] if len(heard) else 0.0
    # A cut-off top end is an encoder's low-pass only in a lossy file; an explosion or a thunder WAV is dark by nature.
    if codec in ("mp3", "vorbis", "aac", "opus") and top < 15000:
        problems.append(f"top end stops at {top / 1000:.1f} kHz")
    clipped = int((np.abs(audio) > 0.99).sum())
    if clipped > max(3, 0.0005 * audio.size):
        problems.append(f"{clipped} clipped samples")
    return problems, codec


def command_learn(arguments):
    source = Path(arguments.recording).resolve()
    target = model_path(arguments.name)
    if target.exists() and not arguments.force:
        sys.exit(f"{target} exists; pass --force to learn it again")
    audio = read_recording(source, arguments.start, arguments.end)
    if arguments.around_peak:
        # Learn one event: from 0.15 s before the loudest 20 ms to around_peak seconds after it.
        power = np.convolve((audio ** 2).mean(axis=0), np.ones(960) / 960, mode="same")
        peak = int(np.argmax(power))
        audio = audio[:, max(0, peak - int(0.15 * resynth.RATE)):peak + int(arguments.around_peak * resynth.RATE)]
    problems, codec = source_quality(source, audio)
    if problems and not arguments.allow_poor_source:
        sys.exit(f"refused {source.name}: {'; '.join(problems)}. Fetch a full-quality WAV (fetch_bigsoundbank.py) "
                 f"or pass --allow-poor-source to learn it anyway")
    if codec in ("mp3", "vorbis", "aac", "opus"):
        print(f"note: {source.name} is {codec}; a WAV of the same sound learns cleaner")
    model = resynth.analyze(audio, resynth.RATE, source={
        "file": str(source), "from": arguments.start, "to": arguments.end, **library_entry(source)})
    takes = [resynth.render(model, seed=seed) for seed in (1, 2)]
    closeness = resynth.fidelity(audio, takes[0])
    floor = resynth.fidelity(takes[1], takes[0])
    model["meta"]["rise_ms"] = closeness["reference_rise_ms"]
    model["meta"]["fidelity"] = {"take": closeness, "floor": floor}
    resynth.save(target, model)
    verdict = "good" if closeness["env_db"] <= floor["env_db"] + 1.5 else "off: listen before using it"
    print(f"learned {arguments.name}  {resynth.model_size(target) / 1024:.0f} kB  "
          f"take env {closeness['env_db']} dB (floor {floor['env_db']})  rise {closeness['rise_ms']} ms "
          f"(recording {closeness['reference_rise_ms']})  {verdict}")
    licence = model["meta"]["source"].get("licence")
    if licence and licence not in ("cc0", "public-domain"):
        print(f"licence: {licence} ({model['meta']['source'].get('author') or 'author unknown'}); a model is a "
              f"derivative of its recording")


def command_render(arguments):
    model = resynth.load(model_path(arguments.model))
    controls = {name: getattr(arguments, name) for name in CONTROL_NAMES if getattr(arguments, name) is not None}
    out = Path(arguments.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for index in range(arguments.n):
        take, seed, faults = checked_take(model, arguments.seed + index, controls)
        name = out if arguments.n == 1 else out.with_name(f"{out.stem}_{index + 1}{out.suffix}")
        sf.write(name, peak_normalised(take).T, resynth.RATE, subtype="PCM_24")
        results.append({"file": str(name), **take_summary(take, seed, faults)})
        print(f"{name.name}: {arguments.model} {json.dumps(results[-1]['audit'])}  {results[-1]['seconds']} s, "
              f"onset {results[-1]['onset_s']} s, peak {results[-1]['peak_s']} s, seed {seed}")
    if arguments.json:
        print(json.dumps(results, indent=1))


def command_design(arguments, extra):
    import designs
    designs.main([arguments.design, "--out", arguments.out, *extra])


def command_list(_arguments):
    for path in sorted(MODELS_DIRECTORY.rglob("*.npz")):
        meta = resynth.load(path)["meta"]
        name = path.relative_to(MODELS_DIRECTORY).with_suffix("").as_posix()
        fidelity = meta.get("fidelity", {})
        print(f"{name:32s} {meta['source'].get('licence') or '?':10s} "
              f"take {fidelity.get('take', {}).get('env_db', '?')} / floor {fidelity.get('floor', {}).get('env_db', '?')} dB  "
              f"{Path(meta['source'].get('file', '')).name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    learn = commands.add_parser("learn")
    learn.add_argument("recording")
    learn.add_argument("--name", required=True)
    learn.add_argument("--from", dest="start", type=float, default=0.0)
    learn.add_argument("--to", dest="end", type=float)
    learn.add_argument("--force", action="store_true")
    learn.add_argument("--allow-poor-source", action="store_true")
    learn.add_argument("--around-peak", type=float, help="learn only the loudest event: this many seconds after it")
    render = commands.add_parser("render")
    render.add_argument("model")
    render.add_argument("--out", required=True)
    render.add_argument("--seed", type=int, default=0)
    render.add_argument("--n", type=int, default=1)
    render.add_argument("--json", action="store_true")
    for name in CONTROL_NAMES:
        render.add_argument(f"--{name}", type=float)
    design = commands.add_parser("design")
    design.add_argument("design")
    design.add_argument("--out", required=True)
    commands.add_parser("list")
    arguments, extra = parser.parse_known_args()
    if arguments.command == "design":
        command_design(arguments, extra)
    elif extra:
        parser.error(f"unknown arguments: {extra}")
    else:
        {"learn": command_learn, "render": command_render, "list": command_list}[arguments.command](arguments)


if __name__ == "__main__":
    main()
