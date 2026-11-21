"""Physics for placed sounds: something passing the listener, or a sound heard from a distance.

  physics.py pass  in.wav --out out.wav [--speed 20] [--closest 2] [--at 0.5] [--direction 1] [--air 1]
  physics.py far   in.wav --out out.wav --distance 40

pass moves the source on a straight line past the listener: x(t) = speed * (t - at) * direction, nearest point
`closest` metres away at time `at` (as a share of the file, 0..1). Four effects follow from that path alone:
  Doppler    the listener hears the source as it was r(t)/343 s ago, so pitch is higher coming in, lower going away
  distance   level falls as 1/r, set to 0 dB at the closest point
  air        highs fall with distance (a one-pole low-pass whose corner drops as r grows)
  pan        equal-power pan from the angle, plus a small time difference between the ears (up to 0.6 ms)
A close fast pass ("whipping past the ear") is closest under 1 m with a speed of 15-40 m/s; a train is 3-6 m at
10-25 m/s; a jet flyover is 50-200 m at 100-250 m/s.
far puts a sound at a distance: 1/r level, air low-pass and the travel delay.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SPEED_OF_SOUND = 343.0
EAR_SPACING = 0.2
BLOCK = 256


def air_corner(distance, air=1.0):
    """Corner frequency of the air low-pass at a distance: about 18 kHz at 1 m, 6 kHz at 30 m, 2.5 kHz at 150 m."""
    return float(np.clip(18000.0 / (1.0 + air * distance / 15.0) ** 0.8, 400.0, 20000.0))


def varying_lowpass(audio, corners, rate):
    """One-pole low-pass with its corner changed every BLOCK samples (corners holds one value per block)."""
    result = np.zeros_like(audio)
    state = np.zeros(audio.shape[0])
    for block, corner in enumerate(corners):
        start = block * BLOCK
        piece = audio[:, start:start + BLOCK]
        if piece.shape[1] == 0:
            break
        coefficient = np.exp(-2 * np.pi * corner / rate)
        filtered, final = signal.lfilter([1 - coefficient], [1, -coefficient], piece, axis=1,
                                         zi=(state * coefficient)[:, None])
        result[:, start:start + BLOCK] = filtered
        state = final[:, 0] / max(coefficient, 1e-9)
    return result


def pass_by(audio, rate, speed=20.0, closest=2.0, at=0.5, direction=1.0, air=1.0):
    mono = audio.mean(axis=0) if audio.ndim == 2 else audio
    count = len(mono)
    time = np.arange(count) / rate
    position = speed * (time - at * count / rate) * direction
    distance = np.sqrt(position ** 2 + closest ** 2)
    # Doppler from the travel delay: the ear hears the sample emitted distance / c seconds earlier.
    heard_time = time - (distance - closest) / SPEED_OF_SOUND
    source = np.interp(heard_time * rate, np.arange(count), mono, left=0.0, right=0.0)
    angle = np.arctan2(position, closest)  # -pi/2 far left .. +pi/2 far right
    pan = (0.85 * np.sin(angle) + 1) * np.pi / 4  # never fully one-sided: a real far source still reaches both ears
    gain = closest / distance
    left_delay = np.maximum(0, np.sin(angle)) * EAR_SPACING / SPEED_OF_SOUND
    right_delay = np.maximum(0, -np.sin(angle)) * EAR_SPACING / SPEED_OF_SOUND
    left = np.interp((time - left_delay) * rate, np.arange(count), source, left=0.0, right=0.0)
    right = np.interp((time - right_delay) * rate, np.arange(count), source, left=0.0, right=0.0)
    stereo = np.vstack([left * np.cos(pan), right * np.sin(pan)]) * np.sqrt(2) * gain
    corners = [air_corner(distance[min(count - 1, block * BLOCK)], air) for block in range(count // BLOCK + 1)]
    return varying_lowpass(stereo, corners, rate)


def far(audio, rate, distance=40.0, air=1.0):
    audio = audio if audio.ndim == 2 else np.vstack([audio, audio])
    delay = int(distance / SPEED_OF_SOUND * rate)
    delayed = np.pad(audio, ((0, 0), (delay, 0)))
    corner = air_corner(distance, air)
    low = signal.butter(2, corner, "lowpass", fs=rate, output="sos")
    return signal.sosfilt(low, delayed, axis=1) / max(1.0, distance)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["pass", "far"])
    parser.add_argument("input")
    parser.add_argument("--out", required=True)
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--closest", type=float, default=2.0)
    parser.add_argument("--at", type=float, default=0.5)
    parser.add_argument("--direction", type=float, default=1.0)
    parser.add_argument("--air", type=float, default=1.0)
    parser.add_argument("--distance", type=float, default=40.0)
    arguments = parser.parse_args()
    audio, rate = sf.read(arguments.input, always_2d=True)
    audio = audio.T
    if arguments.mode == "pass":
        result = pass_by(audio, rate, arguments.speed, arguments.closest, arguments.at, arguments.direction, arguments.air)
    else:
        result = far(audio, rate, arguments.distance, arguments.air)
    result *= 10 ** (-1 / 20) / (np.abs(result).max() + 1e-12)
    sf.write(arguments.out, result.T, rate, subtype="PCM_24")
    print(f"{Path(arguments.out).name}: {arguments.mode} {result.shape[1] / rate:.2f} s")


if __name__ == "__main__":
    main()
