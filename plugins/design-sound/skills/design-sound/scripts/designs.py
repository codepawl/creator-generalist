"""Designed sounds written in code, for gestures no recording holds: riser, subdrop, whoosh, blip, tick.

Real things (steps, hits, doors, explosions) are learned from recordings with make.py learn; sounds invented from
formulas for real things fail by ear. These designs are gestures that exist only in edits and interfaces. Every one
is seeded (same seed and options, same samples) and ends faded, never cut, except a riser, which ends on its cut.

  designs.py riser   --out r.wav [--seconds 2] [--low 300] [--high 6000] [--tone 0.3] [--curve 2.5] [--seed 0]
  designs.py subdrop --out s.wav [--seconds 1.2] [--start-hz 90] [--end-hz 32] [--drive 0.4]
  designs.py kick    --out k.wav [--start-hz 160] [--end-hz 48] [--decay 0.22] [--drop 0.035] [--click 0.25] [--drive 0.6]
  designs.py rumble  --out u.wav [--seconds 2.4] [--cutoff 420] [--grain 0.03] [--decay 0.7] [--width 0.8]
  designs.py air     --out a.wav [--seconds 1.6] [--centre 1500] [--width 1.2] [--flutter 0.15]  (pass it: physics.py)
  designs.py whoosh  --out w.wav [--seconds 0.8] [--centre 1200] [--sweep 1.5] [--peak 0.6] [--pan 0.8]
  designs.py blip    --out b.wav [--pitch 880] [--glide 1.5] [--decay 0.06] [--click 0.4]
  designs.py tick    --out t.wav [--centre 4000] [--decay 0.004] [--ring-hz 0]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))
import resynth  # noqa: E402

RATE = resynth.RATE
WINDOW = 1024
STEP = 256


def swept_noise(generator, seconds, centre_of_time, width_octaves, channels=2, coherence=0.6):
    """Noise whose band centre follows centre_of_time(t) (Hz), Gaussian on log frequency, one width in octaves."""
    count = int(seconds * RATE)
    common = generator.standard_normal(count)
    result = np.zeros((channels, count))
    for channel in range(channels):
        own = generator.standard_normal(count)
        noise = np.sqrt(coherence) * common + np.sqrt(1.0 - coherence) * own
        frequencies, times, spectrum = signal.stft(noise, RATE, nperseg=WINDOW, noverlap=WINDOW - STEP)
        centres = centre_of_time(np.clip(times, 0, seconds))
        distance = np.log2(np.maximum(frequencies[:, None], 1.0) / centres[None, :])
        spectrum *= np.exp(-0.5 * (distance / width_octaves) ** 2)
        _, filtered = signal.istft(spectrum, RATE, nperseg=WINDOW, noverlap=WINDOW - STEP)
        result[channel] = filtered[:count]
    return result


def fade(take, fade_in=0.002, fade_out=0.01):
    take = take.copy()
    count = take.shape[1]
    head = min(count, int(fade_in * RATE))
    tail = min(count, int(fade_out * RATE))
    if head:
        take[:, :head] *= np.linspace(0, 1, head)
    if tail:
        take[:, -tail:] *= np.linspace(1, 0, tail) ** 2
    return take


def riser(generator, seconds=2.0, low=300.0, high=6000.0, tone=0.3, curve=2.5):
    time = np.arange(int(seconds * RATE)) / RATE
    progress = time / seconds
    centre = lambda moment: low * (high / low) ** ((moment / seconds) ** 1.5)  # noqa: E731
    noise = swept_noise(generator, seconds, centre, 0.6)
    noise /= np.abs(noise).max() + 1e-12
    pitch = 0.5 * low * (high / low) ** (0.5 * progress ** 1.5)
    phase = 2 * np.pi * np.cumsum(pitch) / RATE
    partials = sum(np.sin(phase * harmonic) / harmonic for harmonic in range(1, 6))
    tones = np.vstack([partials, np.roll(partials, 37)]) / 2.0
    envelope = progress ** curve
    take = envelope * ((1 - tone) * noise + tone * tones)
    return fade(take, fade_in=0.05, fade_out=0.004)


def subdrop(generator, seconds=1.2, start_hz=90.0, end_hz=32.0, drive=0.4):
    time = np.arange(int(seconds * RATE)) / RATE
    frequency = end_hz + (start_hz - end_hz) * np.exp(-time / (0.18 * seconds))
    phase = 2 * np.pi * np.cumsum(frequency) / RATE
    body = np.sin(phase) * np.exp(-time / (0.45 * seconds))
    attack = np.minimum(1.0, time / 0.004)
    shaped = np.tanh((1 + 4 * drive) * body * attack) / np.tanh(1 + 4 * drive)
    return fade(np.vstack([shaped, shaped]), fade_in=0.001, fade_out=0.05)


def kick(generator, start_hz=160.0, end_hz=48.0, decay=0.22, drop=0.035, click=0.25, drive=0.6):
    """The chest punch of a big hit: a sine that falls fast from start_hz to end_hz, a short click on top, and
    saturation so its harmonics reach phone speakers. It is the "boom" a recorded explosion rarely holds up close."""
    seconds = decay * 5
    time = np.arange(int(seconds * RATE)) / RATE
    frequency = end_hz + (start_hz - end_hz) * np.exp(-time / drop)
    phase = 2 * np.pi * np.cumsum(frequency) / RATE
    body = np.sin(phase) * np.exp(-time / decay) * np.minimum(1.0, time / 0.0015)
    burst = generator.standard_normal(len(time)) * np.exp(-time / 0.003)
    burst = signal.sosfilt(signal.butter(2, [800, 5000], "bandpass", fs=RATE, output="sos"), burst)
    mono = body + click * burst / (np.abs(burst).max() + 1e-12)
    mono = np.tanh((1 + 4 * drive) * mono) / np.tanh(1 + 4 * drive)
    return fade(np.vstack([mono, mono]), fade_in=0.0005, fade_out=0.05)


def rumble(generator, seconds=2.4, cutoff=420.0, grain=0.03, decay=0.7, width=0.8):
    """A low granular tail: low-passed noise broken into overlapping grains, decaying, wide. The long roll after
    a blast that keeps the low end moving after the hit."""
    count = int(seconds * RATE)
    time = np.arange(count) / RATE
    low = signal.butter(4, cutoff, "lowpass", fs=RATE, output="sos")
    channels = []
    common = generator.standard_normal(count)
    for _ in range(2):
        noise = np.sqrt(1 - width) * common + np.sqrt(width) * generator.standard_normal(count)
        noise = signal.sosfilt(low, noise)
        grains = np.convolve(generator.random(count) ** 6, np.hanning(max(3, int(grain * RATE))), mode="same")
        channels.append(noise * (0.4 + grains / (grains.max() + 1e-12)))
    envelope = np.exp(-time / decay) * np.minimum(1.0, time / 0.04)
    return fade(np.vstack(channels) * envelope, fade_in=0.002, fade_out=0.6)


def air(generator, seconds=1.6, centre=1500.0, width=1.2, flutter=0.15):
    """Steady rushing air with a little flutter. Alone it is a hiss; run through physics.pass_by at under 1 m it
    becomes the whip of something passing the ear, with its rise, pan and Doppler made by the path."""
    count = int(seconds * RATE)
    noise = swept_noise(generator, seconds, lambda moment: np.full_like(moment, centre), width, coherence=0.7)
    wobble = np.convolve(generator.standard_normal(count), np.hanning(int(0.04 * RATE)), mode="same")
    wobble = 1 + flutter * wobble / (np.abs(wobble).max() + 1e-12)
    return fade(noise * wobble, fade_in=0.05, fade_out=0.05)


def whistle(generator, seconds=0.7, start_hz=1800.0, end_hz=700.0, air_mix=0.35, grow=2.0):
    """A falling bomb: a tone gliding down as it nears (the cartoon and war-film idiom), with air noise around it,
    growing louder until it cuts at the impact. Ends on its cut, like a riser."""
    time = np.arange(int(seconds * RATE)) / RATE
    progress = time / seconds
    frequency = start_hz * (end_hz / start_hz) ** (progress ** 1.3)
    phase = 2 * np.pi * np.cumsum(frequency * (1 + 0.004 * np.sin(2 * np.pi * 6 * time))) / RATE
    tone = np.sin(phase) + 0.25 * np.sin(2 * phase)
    noise = swept_noise(generator, seconds, lambda moment: start_hz * (end_hz / start_hz) ** ((moment / seconds) ** 1.3), 0.5)
    noise = noise / (np.abs(noise).max() + 1e-12)
    envelope = (0.15 + progress) ** grow
    take = envelope * ((1 - air_mix) * np.vstack([tone, tone]) + air_mix * noise)
    return fade(take, fade_in=0.03, fade_out=0.004)


def billow(generator, seconds=2.0, low=180.0, high=700.0, swell=0.35):
    """Smoke or a dust cloud rolling up: soft low air whose band rises slowly, swelling in and thinning out."""
    time = np.arange(int(seconds * RATE)) / RATE
    progress = time / seconds
    noise = swept_noise(generator, seconds, lambda moment: low * (high / low) ** (moment / seconds), 0.9,
                        coherence=0.3)
    noise /= np.abs(noise).max() + 1e-12
    envelope = np.where(progress < swell, (progress / swell) ** 1.5, np.exp(-(progress - swell) / 0.35))
    churn = 1 + 0.3 * np.convolve(generator.standard_normal(len(time)), np.hanning(int(0.12 * RATE)), mode="same") / 30
    return fade(noise * envelope * churn, fade_in=0.05, fade_out=0.2)


def crackle(generator, seconds=1.5, rate_per_second=25.0, centre=3500.0, decay=0.0015, fall=0.6, spread=0.7):
    """Sparks or embers: sparse tiny pops at random times, each a short band-passed burst, thinning out over time
    (fall seconds) and spread across the stereo field."""
    count = int(seconds * RATE)
    time = np.arange(count) / RATE
    take = np.zeros((2, count))
    expected = rate_per_second * fall * (1 - np.exp(-seconds / fall))
    pops = generator.poisson(expected)
    moments = -fall * np.log(1 - generator.random(pops) * (1 - np.exp(-seconds / fall)))
    length = int(decay * 12 * RATE)
    shape = np.exp(-np.arange(length) / (decay * RATE))
    band = signal.butter(2, [centre / 2, min(RATE / 2 - 100, centre * 2)], "bandpass", fs=RATE, output="sos")
    for moment in moments:
        start = int(moment * RATE)
        if start + length >= count:
            continue
        burst = signal.sosfilt(band, generator.standard_normal(length) * shape)
        level = generator.uniform(0.2, 1.0) * np.exp(-moment / fall)
        position = generator.uniform(-spread, spread)
        take[0, start:start + length] += burst * level * np.cos((position + 1) * np.pi / 4)
        take[1, start:start + length] += burst * level * np.sin((position + 1) * np.pi / 4)
    return fade(take, fade_in=0.0005, fade_out=0.05)


def whoosh(generator, seconds=0.8, centre=1200.0, sweep=1.5, peak=0.6, pan=0.8):
    time = np.arange(int(seconds * RATE)) / RATE
    position = time / seconds
    centre_of_time = lambda moment: centre * 2 ** (sweep * (  # noqa: E731
        np.where(moment / seconds < peak, moment / seconds / peak - 1, -(moment / seconds - peak) / (1 - peak))))
    noise = swept_noise(generator, seconds, centre_of_time, 0.45, coherence=0.8)
    rise = np.exp(-0.5 * ((position - peak) / (0.28 * peak)) ** 2)
    fall = np.exp(-0.5 * ((position - peak) / (0.22 * (1 - peak) + 1e-3)) ** 2)
    envelope = np.where(position < peak, rise, fall)
    angle = (np.clip(pan * (2 * position - 1), -1, 1) + 1) * np.pi / 4
    take = envelope * noise * np.vstack([np.cos(angle), np.sin(angle)]) * np.sqrt(2)
    return fade(take)


def blip(generator, pitch=880.0, glide=1.5, decay=0.06, click=0.4):
    seconds = decay * 7
    time = np.arange(int(seconds * RATE)) / RATE
    frequency = pitch * (1 + (glide - 1) * np.exp(-time / 0.012))
    phase = 2 * np.pi * np.cumsum(frequency) / RATE
    tone = np.sin(phase) * np.exp(-time / decay) * np.minimum(1.0, time / 0.0015)
    burst = generator.standard_normal(len(time)) * np.exp(-time / 0.0015)
    burst = signal.sosfilt(signal.butter(2, [2000, 8000], "bandpass", fs=RATE, output="sos"), burst)
    mono = tone + click * burst / (np.abs(burst).max() + 1e-12)
    return fade(np.vstack([mono, mono]), fade_in=0.0005, fade_out=0.01)


def tick(generator, centre=4000.0, decay=0.004, ring_hz=0.0):
    seconds = max(0.03, decay * 10)
    time = np.arange(int(seconds * RATE)) / RATE
    burst = generator.standard_normal(len(time)) * np.exp(-time / decay)
    low_edge = centre / 1.8
    high_edge = min(RATE / 2 - 100, centre * 1.8)
    burst = signal.sosfilt(signal.butter(2, [low_edge, high_edge], "bandpass", fs=RATE, output="sos"), burst)
    if ring_hz:
        burst = burst + 0.5 * np.sin(2 * np.pi * ring_hz * time) * np.exp(-time / (decay * 4)) * np.abs(burst).max()
    return fade(np.vstack([burst, burst]), fade_in=0.0002, fade_out=0.005)


DESIGNS = {"riser": riser, "subdrop": subdrop, "kick": kick, "rumble": rumble, "air": air, "whistle": whistle, "billow": billow, "crackle": crackle, "whoosh": whoosh, "blip": blip,
           "tick": tick}


def make(name, seed=0, **options):
    take = DESIGNS[name](np.random.default_rng(seed), **options)
    return take * (10 ** (-1 / 20) / (np.abs(take).max() + 1e-12))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("design", choices=sorted(DESIGNS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=0)
    arguments, extra = parser.parse_known_args(argv)
    options = {}
    for index in range(0, len(extra), 2):
        options[extra[index].lstrip("-").replace("-", "_")] = float(extra[index + 1])
    take = make(arguments.design, arguments.seed, **options)
    sf.write(arguments.out, take.T, RATE, subtype="PCM_24")
    onset, peak = resynth.timing(take)
    faults = resynth.audit(take)
    if arguments.design in ("riser", "whistle"):
        faults = [fault for fault in faults if fault != "cut tail"]  # these end on their cut by design
    print(f"{Path(arguments.out).name}: {arguments.design} {take.shape[1] / RATE:.2f} s, onset {onset:.3f} s, "
          f"peak {peak:.3f} s, audit {faults or 'clean'}")


if __name__ == "__main__":
    main()
