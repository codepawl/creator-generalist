"""Compare a mix against a reference mix: band shares over the piece, and for each hit its peak and how far it jumps.

Usage:
  reference_gap.py ours.wav reference.wav [--hits 11.86,27.54,...] [--from 0] [--to end] [--dip 0.4]

Band shares are the % of energy in <60, 60-250, 250-2k, 2k-8k and 8k+ Hz. For each hit:
- peak: the highest 50 ms RMS in the 0.4 s after the hit, in dBFS;
- jump: that peak over the mean level of the 0.5 s before the hit;
- dip: the level in the `--dip` seconds before the hit over the level of the half second before that. A negative dip
  in the reference means it goes quiet before the hit; a positive one means it builds into it.

A hit that peaks as loud as the reference but jumps less is buried by what comes before it, not too quiet.
Numbers are measurements, not listening.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import soundfile
from scipy import signal

BANDS = [(20.0, 60.0), (60.0, 250.0), (250.0, 2000.0), (2000.0, 8000.0), (8000.0, 16000.0)]
BAND_NAMES = ["<60", "60-250", "250-2k", "2k-8k", "8k+"]
PEAK_WINDOW_SECONDS = 0.05
PEAK_SEARCH_SECONDS = 0.4
BEFORE_SECONDS = 0.5


def load_mono(path: str) -> tuple[np.ndarray, int]:
    samples, rate = soundfile.read(path, always_2d=True, dtype="float64")
    return samples.mean(axis=1), rate


def band_shares(sound: np.ndarray, rate: int) -> list[float]:
    energies = []
    for low, high in BANDS:
        sections = signal.butter(4, [low, min(high, rate / 2 - 1)], "bandpass", fs=rate, output="sos")
        energies.append(float(np.mean(signal.sosfilt(sections, sound) ** 2)))
    total = sum(energies) + 1e-20
    return [100.0 * energy / total for energy in energies]


def level_decibels(sound: np.ndarray, rate: int, start: float, end: float) -> float:
    first = max(0, int(start * rate))
    last = max(first + 1, int(end * rate))
    chunk = sound[first:last]
    return float(10.0 * np.log10(np.mean(chunk ** 2) + 1e-12))


def peak_decibels(sound: np.ndarray, rate: int, at: float) -> float:
    window = int(PEAK_WINDOW_SECONDS * rate)
    first = int(at * rate)
    chunk = sound[first : first + int(PEAK_SEARCH_SECONDS * rate)]
    if chunk.shape[0] < window:
        return -120.0
    power = np.convolve(chunk ** 2, np.ones(window) / window, mode="valid")
    return float(10.0 * np.log10(power.max() + 1e-12))


def hit_row(sound: np.ndarray, rate: int, at: float, dip_seconds: float) -> tuple[float, float, float]:
    peak = peak_decibels(sound, rate, at)
    before = level_decibels(sound, rate, at - BEFORE_SECONDS, at)
    inside_dip = level_decibels(sound, rate, at - dip_seconds, at - 0.02)
    ahead_of_dip = level_decibels(sound, rate, at - dip_seconds - 0.5, at - dip_seconds)
    return peak, peak - before, inside_dip - ahead_of_dip


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ours")
    parser.add_argument("reference")
    parser.add_argument("--hits", default="", help="comma-separated hit times in seconds")
    parser.add_argument("--from", dest="start", type=float, default=0.0)
    parser.add_argument("--to", dest="end", type=float, default=None)
    parser.add_argument("--dip", type=float, default=0.4, help="seconds before each hit checked for a dip")
    arguments = parser.parse_args()
    ours, ours_rate = load_mono(arguments.ours)
    reference, reference_rate = load_mono(arguments.reference)
    print("band shares %      " + "  ".join(name.rjust(7) for name in BAND_NAMES))
    for label, sound, rate in (("reference", reference, reference_rate), ("ours", ours, ours_rate)):
        end = arguments.end if arguments.end is not None else sound.shape[0] / rate
        shares = band_shares(sound[int(arguments.start * rate) : int(end * rate)], rate)
        print(f"{label:18} " + "  ".join(f"{share:7.1f}" for share in shares))
    hits = [float(value) for value in arguments.hits.split(",") if value.strip()]
    if not hits:
        return
    print("\nhit s     peak ref/ours    jump ref/ours    dip ref/ours")
    jumps = []
    for at in hits:
        reference_peak, reference_jump, reference_dip = hit_row(reference, reference_rate, at, arguments.dip)
        ours_peak, ours_jump, ours_dip = hit_row(ours, ours_rate, at, arguments.dip)
        jumps.append((reference_jump, ours_jump))
        flag = "  JUMPS LESS" if ours_jump < reference_jump - 3.0 else ""
        print(f"{at:7.2f}  {reference_peak:6.1f}/{ours_peak:6.1f}   {reference_jump:6.1f}/{ours_jump:6.1f}   "
              f"{reference_dip:6.1f}/{ours_dip:6.1f}{flag}")
    median_reference = float(np.median([pair[0] for pair in jumps]))
    median_ours = float(np.median([pair[1] for pair in jumps]))
    print(f"\nmedian jump: reference {median_reference:.1f} dB, ours {median_ours:.1f} dB")


if __name__ == "__main__":
    main()
