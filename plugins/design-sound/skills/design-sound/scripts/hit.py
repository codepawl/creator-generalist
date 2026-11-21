"""Build one hit from layers, each in its own band, aligned on their peaks, then finished for punch.

A hit that reads as one strong event is a short bright transient, the object's own body, a gated tail and, for the
2-3 biggest hits of a piece only, a sub. Each layer comes from its own learned model (make.py) or a design, so the
layers never share one recording's smear. finish() then lifts a short sound until its loudest 5 ms sit 3.5 dB under
the peak, folding the spike over smoothly instead of limiting it: a one-millisecond spike at full peak otherwise
holds the body 15 dB down, and the hit sounds small however loud the file is.

Spec (JSON, also accepted as a cue's "hit" field in a cue sheet):
  {"layers": [
     {"role": "transient", "make": "impact/rock", "seed": 3, "controls": {"hard": 0.6}, "gain_db": 0},
     {"role": "body", "make": "impact/punch", "gain_db": -2},
     {"role": "tail", "make": "debris/stones", "gain_db": -8, "length": 0.6},
     {"role": "sub", "design": "subdrop", "options": {"seconds": 0.8}, "gain_db": -6}],
   "lift_db": 10}

  hit.py spec.json --out hit.wav
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))
import designs  # noqa: E402
import resynth  # noqa: E402
from sound_library import LIBRARY_DIRECTORY  # noqa: E402

RATE = resynth.RATE
MODELS = LIBRARY_DIRECTORY / "models"
# Band and gate of each role: (high-pass Hz, low-pass Hz, seconds kept after the peak, fade seconds).
ROLES = {
    "transient": (1800.0, None, 0.04, 0.02),
    "body": (140.0, 6000.0, 0.35, 0.12),
    "tail": (300.0, None, 0.9, 0.4),
    "sub": (None, 120.0, 0.9, 0.3),
    "punch": (30.0, 250.0, 0.45, 0.2),
    "rumble": (25.0, 500.0, 2.5, 1.2),
    "whole": (None, None, 2.0, 0.3),
}
BODY_UNDER_PEAK_DB = 3.5
MONO_BELOW_HZ = 150.0


def saturate(audio, drive):
    """tanh drive: adds harmonics so a low layer is heard on small speakers, and rounds its peaks."""
    if drive <= 0:
        return audio
    gain = 1 + 6 * drive
    peak = np.abs(audio).max() + 1e-12
    return np.tanh(gain * audio / peak) / np.tanh(gain) * peak


def mono_lows(audio):
    """Everything under MONO_BELOW_HZ in the middle: wide lows lose level on phones and mono speakers."""
    low = signal.sosfiltfilt(signal.butter(4, MONO_BELOW_HZ, "lowpass", fs=RATE, output="sos"), audio, axis=-1)
    return audio - low + low.mean(axis=0, keepdims=True)


def stacked_attacks(take, window=0.025, hop=0.005, peak_db=-6.0, dip_db=10.0, span=0.5):
    """Separate attacks in the first span seconds: peaks within 6 dB of the loudest with a 10 dB dip between.
    A hit that reads as one event has one; two means layers that did not land together."""
    mono = take.mean(axis=0)[:int(span * RATE)]
    size = int(window * RATE)
    step = int(hop * RATE)
    levels = np.array([10 * np.log10(np.mean(mono[start:start + size] ** 2) + 1e-20)
                       for start in range(0, max(1, len(mono) - size), step)])
    loud = levels.max()
    count = 0
    armed = True
    lowest = loud
    for level in levels:
        lowest = min(lowest, level)
        if armed and level >= loud + peak_db and (count == 0 or lowest <= loud + peak_db - dip_db):
            count += 1
            armed = False
            lowest = level
        elif level < loud + peak_db - dip_db:
            armed = True
    return count


def band(audio, highpass, lowpass):
    if highpass:
        audio = signal.sosfilt(signal.butter(4, highpass, "highpass", fs=RATE, output="sos"), audio, axis=-1)
    if lowpass:
        audio = signal.sosfilt(signal.butter(4, lowpass, "lowpass", fs=RATE, output="sos"), audio, axis=-1)
    return audio


def layer_take(layer):
    if "make" in layer:
        model = resynth.load(MODELS / f"{layer['make']}.npz")
        return resynth.render(model, seed=layer.get("seed", 0), **layer.get("controls", {}))
    return designs.make(layer["design"], seed=layer.get("seed", 0), **layer.get("options", {}))


def loudest_window_db(audio, seconds=0.005):
    mono = np.abs(audio).max(axis=0)
    window = max(1, int(seconds * RATE))
    power = np.convolve(mono ** 2, np.ones(window) / window, mode="valid")
    return 10 * np.log10(power.max() + 1e-20)


def fold(audio, ceiling_db=-1.0, knee=0.5):
    """Samples above the knee are bent toward the ceiling on a smooth curve; nothing reaches past it."""
    ceiling = 10 ** (ceiling_db / 20)
    start = ceiling * knee
    magnitude = np.abs(audio)
    over = magnitude > start
    room = ceiling - start
    bent = start + room * np.tanh((magnitude[over] - start) / room)
    result = audio.copy()
    result[over] = np.sign(audio[over]) * bent
    return result


def finish(take, peak_db=-1.0, lift_db=10.0):
    """Peak to peak_db, then raise a short sound until its loudest 5 ms sit 3.5 dB under the peak, folding the spike."""
    take = band(take, 25.0, None)
    take = take * (10 ** (peak_db / 20) / (np.abs(take).max() + 1e-12))
    # The hit's front decides punch, so measure only its first 0.6 s; a long tail must not exempt a big hit.
    front = take[:, :int(0.6 * RATE)]
    raise_db = min(lift_db, peak_db - BODY_UNDER_PEAK_DB - loudest_window_db(front))
    if raise_db > 0.5:
        take = fold(take * 10 ** (raise_db / 20), peak_db)
    return take


LAST_REPORT = []


def build(spec):
    LAST_REPORT.clear()
    pieces = []
    for layer in spec["layers"]:
        highpass, lowpass, keep, fade_seconds = ROLES[layer.get("role", "whole")]
        take = band(layer_take(layer), layer.get("highpass", highpass), layer.get("lowpass", lowpass))
        take = saturate(take, layer.get("drive", 0.0))
        _, peak = resynth.timing(take)
        peak_index = int(peak * RATE)
        end = min(take.shape[1], peak_index + int(layer.get("length", keep) * RATE))
        take = take[:, :end].copy()
        fade = min(end - peak_index, int(fade_seconds * RATE))
        if fade > 1:
            take[:, -fade:] *= np.cos(np.linspace(0, np.pi / 2, fade)) ** 2
        take *= 10 ** (layer.get("gain_db", 0.0) / 20) / (np.abs(take).max() + 1e-12)
        # "offset" (seconds) lands a layer after the others on purpose: a fireball that roars up after the flash.
        offset = int(layer.get("offset", 0.0) * RATE)
        take = np.pad(take, ((0, 0), (offset, 0)))
        pieces.append((take, peak_index))  # aligned on the unshifted peak, so the padding delays this layer
        # gain_db sets the peak, but a long low layer carries far more energy than its peak suggests.
        LAST_REPORT.append((layer.get("make") or layer.get("design"), layer.get("role", "whole"), float((take ** 2).sum())))
    lead = max(peak_index for _, peak_index in pieces)
    length = max(lead - peak_index + take.shape[1] for take, peak_index in pieces)
    mixed = np.zeros((2, length))
    for take, peak_index in pieces:
        start = lead - peak_index
        mixed[:, start:start + take.shape[1]] += take
    return finish(mono_lows(mixed), lift_db=spec.get("lift_db", 10.0))


def main():
    spec_path = Path(sys.argv[1])
    out = Path(sys.argv[sys.argv.index("--out") + 1])
    take = build(json.loads(spec_path.read_text(encoding="utf-8")))
    sf.write(out, take.T, RATE, subtype="PCM_24")
    onset, peak = resynth.timing(take)
    print(f"{out.name}: {take.shape[1] / RATE:.2f} s, onset {onset:.3f} s, peak {peak:.3f} s, "
          f"loudest 5 ms {loudest_window_db(take):.1f} dBFS, audit {resynth.audit(take) or 'clean'}")
    spectrum = np.abs(np.fft.rfft(take.mean(axis=0))) ** 2
    frequencies = np.fft.rfftfreq(take.shape[1], 1 / RATE)
    total = spectrum.sum() + 1e-20
    shares = {name: 100 * spectrum[(frequencies >= low) & (frequencies < high)].sum() / total
              for name, (low, high) in {"sub <80": (0, 80), "boom 80-250": (80, 250), "body 250-2k": (250, 2000),
                                        "crack 2k+": (2000, RATE)}.items()}
    layer_total = sum(energy for _, _, energy in LAST_REPORT) + 1e-20
    print("layers " + ", ".join(f"{name} ({role}) {100 * energy / layer_total:.0f}%" for name, role, energy in LAST_REPORT))
    print("energy " + ", ".join(f"{name} {share:.0f}%" for name, share in shares.items()))
    attacks = stacked_attacks(take)
    if attacks > 1:
        print(f"STACKED: {attacks} separate attacks in the first 0.5 s; align the layers or drop one")


if __name__ == "__main__":
    main()
