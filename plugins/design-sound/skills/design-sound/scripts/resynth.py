"""Learn a recording as numbers and render new takes of it: analysis and resynthesis on a hearing-sized grid.

A recording becomes a model, never a copy of its samples:
  bands     56 bands from 40 Hz to 20 kHz, equally spaced on the ERB scale, with half-cosine windows whose squares
            sum to one, so splitting and summing the bands gives the signal back.
  envelope  every band's level on a 0.25 ms grid (what makes an onset sharp and a tail grainy).
  carrier   every 2 ms, how much of each band is one steady tone (its coherent share) and that tone's offset from
            the band centre. The coherent share is rendered as a phase-continuous oscillator, the rest as fresh
            band noise with its own envelope divided out, so the take carries the model's envelope and not the
            noise's ripple.
  stereo    per band, each channel's envelope and the coherence between the channels.

Every render draws fresh noise from its seed: the same seed gives the same samples, another seed a new take of the
same thing. Controls transform the model physically: length (time between onsets, onsets keep their speed), size
(bigger is lower and slower), pitch, bright (tilt around 1 kHz), hard (onset level and brightness), ring (decay
time), weight (level under 150 Hz), energy, vary (small random amounts of all of them).

After a render, the take's band envelopes are measured and corrected toward the model, and the 30 ms before each
onset are clamped so the take never stands above the recording there (band filters ring before a strike; a soft
attack is the failure this module exists to avoid).

fidelity() says how close a take is: env_db (band envelope distance in dB over heard cells, 2 ms), shape_db (the
same smoothed over a band and 5 ms), rise_ms (10-90 % rise of the main onset). A model is good when its take differs
from the recording about as much as two of its takes differ from each other (floor()).
"""
import json
import zipfile
from functools import lru_cache
from math import gcd
from pathlib import Path

import numpy as np
from scipy import ndimage, signal

RATE = 48000
BAND_COUNT = 56
HOP = 12                      # samples per envelope frame: 0.25 ms
FRAME_RATE = RATE / HOP       # 4000 frames per second
CARRIER_STEP = 8              # envelope frames per carrier frame: 2 ms
PAD_SECONDS = 0.08            # silence around a recording while it is analysed (the low bands ring that long)
FLOOR_DB = -100.0
PRE_ONSET_CLAMP_SECONDS = 0.03


def erb_number(frequency):
    return 21.4 * np.log10(1.0 + 0.00437 * np.asarray(frequency, dtype=float))


def frequency_of_erb(erb):
    return (10 ** (np.asarray(erb, dtype=float) / 21.4) - 1.0) / 0.00437


ERB_LOW = float(erb_number(40.0))
ERB_STEP = (float(erb_number(20000.0)) - ERB_LOW) / (BAND_COUNT - 1)
CENTRES = frequency_of_erb(ERB_LOW + ERB_STEP * np.arange(BAND_COUNT))
WIDTHS = frequency_of_erb(ERB_LOW + ERB_STEP * (np.arange(BAND_COUNT) + 0.5)) - frequency_of_erb(
    ERB_LOW + ERB_STEP * (np.arange(BAND_COUNT) - 0.5))
# Envelope frames after which a band of noise has forgotten its phase: one over its bandwidth.
NOISE_MEMORY = np.clip(np.round(FRAME_RATE / WIDTHS), 1, 64).astype(int)


@lru_cache(maxsize=8)
def band_windows(length):
    """Half-cosine windows on the ERB scale for an rfft of `length` samples; their squares sum to one."""
    frequencies = np.fft.rfftfreq(length, 1.0 / RATE)
    position = (erb_number(frequencies) - ERB_LOW) / ERB_STEP
    windows = np.zeros((BAND_COUNT, len(frequencies)))
    for band in range(BAND_COUNT):
        distance = position - band
        inside = np.abs(distance) < 1.0
        windows[band, inside] = np.cos(0.5 * np.pi * distance[inside])
    windows[0, position < 0] = 1.0
    windows[-1, position > BAND_COUNT - 1] = 1.0
    return windows


def analytic_bands(spectrum, length):
    """Yield (band, analytic band signal) for an rfft spectrum: positive frequencies only, doubled."""
    windows = band_windows(length)
    for band in range(BAND_COUNT):
        full = np.zeros(length, dtype=complex)
        half = spectrum * windows[band]
        full[:len(half)] = half
        full[1:len(half)] *= 2.0
        if length % 2 == 0:
            full[len(half) - 1] /= 2.0
        yield band, np.fft.ifft(full)


def frames_of(values, frame_count):
    return values[:frame_count * HOP].reshape(frame_count, HOP)


def prepare(audio, rate):
    audio = np.asarray(audio, dtype=float)
    if audio.ndim == 1:
        audio = audio[None, :]
    if audio.shape[0] > audio.shape[1]:
        audio = audio.T
    if rate != RATE:
        divisor = gcd(int(rate), RATE)
        audio = signal.resample_poly(audio, RATE // divisor, int(rate) // divisor, axis=-1)
    if audio.shape[0] == 1:
        audio = np.vstack([audio, audio])
    pad = int(PAD_SECONDS * RATE)
    padded = np.pad(audio[:2], ((0, 0), (pad, pad)))
    length = fast_length(padded.shape[1])
    return np.pad(padded, ((0, 0), (0, length - padded.shape[1])))


def fast_length(count):
    """The next length of at least `count` that is a whole number of frames and has only small prime factors.
    A length with a large prime factor made every band's FFT many times slower."""
    length = int(np.ceil(count / HOP) * HOP)
    while True:
        remainder = length // HOP
        for prime in (2, 3, 5, 7):
            while remainder % prime == 0:
                remainder //= prime
        if remainder == 1:
            return length
        length += HOP


def band_envelopes(audio):
    """Amplitude of every band of every channel on the 0.25 ms grid, shape (2, bands, frames)."""
    length = audio.shape[1]
    frame_count = length // HOP
    envelopes = np.zeros((2, BAND_COUNT, frame_count))
    for channel in range(2):
        spectrum = np.fft.rfft(audio[channel])
        for band, analytic in analytic_bands(spectrum, length):
            envelopes[channel, band] = np.sqrt(np.mean(np.abs(frames_of(analytic, frame_count)) ** 2, axis=1))
    return envelopes


def find_onsets(level_db, limit=24):
    """Frames where many bands jump within 1 ms: the strikes a time warp must keep sharp."""
    rise = np.clip(level_db[:, 4:] - level_db[:, :-4], 0, None)
    heard = level_db[:, 4:] > level_db.max() - 50
    flux = np.pad((rise * heard).mean(axis=0), (4, 0))
    if flux.max() <= 0:
        return np.array([int(np.argmax(level_db.max(axis=0)))])
    peaks, _ = signal.find_peaks(flux, height=max(1.0, 0.25 * flux.max()), distance=int(0.03 * FRAME_RATE))
    if len(peaks) == 0:
        peaks = np.array([int(np.argmax(flux))])
    strongest = peaks[np.argsort(flux[peaks])[::-1][:limit]]
    return np.sort(strongest)


@lru_cache(maxsize=1)
def noise_coherence_baseline():
    """The coherence statistic measured on white noise, per band: what 'no tone at all' reads as."""
    generator = np.random.default_rng(12345)
    noise = generator.standard_normal(int(1.0 * RATE))
    model = analyze(noise, RATE, calibrate=False)
    return np.median(model["coherence_raw"], axis=1)


def analyze(audio, rate=RATE, calibrate=True, source=None):
    audio = prepare(audio, rate)
    length = audio.shape[1]
    frame_count = length // HOP
    carrier_count = int(np.ceil(frame_count / CARRIER_STEP))
    envelopes = np.zeros((2, BAND_COUNT, frame_count))
    coherence = np.zeros((BAND_COUNT, carrier_count))
    offsets = np.zeros((BAND_COUNT, carrier_count))
    channel_coherence = np.ones(BAND_COUNT)
    spectra = [np.fft.rfft(audio[channel]) for channel in range(2)]
    mid_spectrum = 0.5 * (spectra[0] + spectra[1])
    sample_index = np.arange(length)
    analytic_left = dict(analytic_bands(spectra[0], length))
    analytic_right = dict(analytic_bands(spectra[1], length))
    for band, analytic_mid in analytic_bands(mid_spectrum, length):
        for channel, analytic in enumerate((analytic_left[band], analytic_right[band])):
            envelopes[channel, band] = np.sqrt(np.mean(np.abs(frames_of(analytic, frame_count)) ** 2, axis=1))
        cross = np.sum(analytic_left[band] * np.conj(analytic_right[band]))
        power = np.sqrt(np.sum(np.abs(analytic_left[band]) ** 2) * np.sum(np.abs(analytic_right[band]) ** 2))
        channel_coherence[band] = float(np.clip(np.real(cross) / (power + 1e-20), 0.0, 1.0))
        baseband = analytic_mid * np.exp(-2j * np.pi * CENTRES[band] * sample_index / RATE)
        phasors = frames_of(baseband, frame_count).mean(axis=1)
        weight = np.abs(phasors) ** 2
        step = phasors[1:] * np.conj(phasors[:-1])
        offset = np.angle(step) * FRAME_RATE / (2 * np.pi)
        offset = np.pad(offset, (0, 1), mode="edge")
        smoothing = CARRIER_STEP * 2
        smooth_offset = ndimage.uniform_filter1d(offset * weight, smoothing) / (
            ndimage.uniform_filter1d(weight, smoothing) + 1e-30)
        lag = NOISE_MEMORY[band]
        lagged = np.zeros(frame_count, dtype=complex)
        lagged[:-lag] = phasors[lag:] * np.conj(phasors[:-lag])
        magnitude = np.zeros(frame_count)
        magnitude[:-lag] = np.abs(phasors[lag:]) * np.abs(phasors[:-lag])
        window = max(8, 6 * lag)
        coherent_sum = ndimage.uniform_filter1d(lagged.real, window) + 1j * ndimage.uniform_filter1d(lagged.imag, window)
        statistic = np.abs(coherent_sum) / (ndimage.uniform_filter1d(magnitude, window) + 1e-30)
        carrier_frames = np.arange(carrier_count) * CARRIER_STEP
        coherence[band] = statistic[np.minimum(carrier_frames, frame_count - 1)]
        offsets[band] = np.clip(smooth_offset[np.minimum(carrier_frames, frame_count - 1)], -WIDTHS[band], WIDTHS[band])
    level_db = 20 * np.log10(envelopes.mean(axis=0) + 1e-12)
    true_envelope = np.sqrt(np.mean(frames_of(np.abs(audio).mean(axis=0), frame_count) ** 2, axis=1))
    model = {
        "envelopes": envelopes,
        "coherence_raw": coherence,
        "offsets": offsets,
        "channel_coherence": channel_coherence,
        "onsets": find_onsets(level_db),
        "true_envelope": true_envelope,
        "pad_frames": int(PAD_SECONDS * FRAME_RATE),
        "meta": {"source": source or {}, "version": 1},
    }
    if calibrate:
        baseline = noise_coherence_baseline()[:, None]
        model["coherence"] = np.clip((coherence - baseline) / (1.0 - baseline), 0.0, 1.0)
    return model


# ---------------------------------------------------------------- transforms of the model

def onset_mask(frame_count, onsets, before=0.003, after=0.009):
    mask = np.zeros(frame_count, dtype=bool)
    for onset in onsets:
        start = max(0, onset - int(before * FRAME_RATE))
        mask[start:min(frame_count, onset + int(after * FRAME_RATE))] = True
    return mask


def warp_map(frame_count, onsets, stretch):
    """Source frame for every output frame: onset windows play at speed 1, everything else is stretched."""
    if abs(stretch - 1.0) < 1e-3:
        return np.arange(frame_count, dtype=float), onsets
    keep = onset_mask(frame_count, onsets)
    durations = np.where(keep, 1.0, stretch)
    output_position = np.concatenate([[0.0], np.cumsum(durations)])
    output_count = int(output_position[-1])
    source_frame = np.interp(np.arange(output_count), output_position[:-1], np.arange(frame_count))
    new_onsets = np.round(np.interp(onsets, np.arange(frame_count), output_position[:-1])).astype(int)
    return source_frame, new_onsets


def resample_rows(rows, positions):
    index = np.arange(rows.shape[-1])
    flat = rows.reshape(-1, rows.shape[-1])
    result = np.array([np.interp(positions, index, row) for row in flat])
    return result.reshape(rows.shape[:-1] + (len(positions),))


def transformed(model, length=1.0, bright=0.0, hard=0.0, ring=1.0, weight=0.0, energy=0.0, vary=0.0, generator=None):
    """The model's envelope in dB and carriers after the controls (size and pitch are applied to the take)."""
    generator = generator or np.random.default_rng(0)
    envelope_db = 20 * np.log10(model["envelopes"] + 1e-12)
    coherence = model["coherence"]
    offsets = model["offsets"]
    onsets = model["onsets"]
    if vary:
        length *= float(np.exp(generator.normal(0, 0.08 * vary)))
        ring *= float(np.exp(generator.normal(0, 0.2 * vary)))
        hard += float(generator.normal(0, 0.3 * vary))
        bright += float(generator.normal(0, 0.25 * vary))
        jitter = ndimage.gaussian_filter1d(generator.normal(0, 2.5 * vary, BAND_COUNT), 2.0)
        envelope_db = envelope_db + jitter[None, :, None]
    hard += 0.5 * energy
    bright += 0.2 * energy
    level_gain = 6.0 * energy
    octaves = np.log2(CENTRES / 1000.0)
    envelope_db = envelope_db + (3.0 * bright * octaves)[None, :, None] + level_gain
    envelope_db[:, CENTRES < 150, :] += 6.0 * weight
    if hard:
        mask = onset_mask(envelope_db.shape[-1], onsets)
        brightness = np.clip(0.6 + 0.25 * octaves, 0.2, 1.5)
        envelope_db[:, :, mask] += (6.0 * hard * brightness)[None, :, None]
    if abs(ring - 1.0) > 1e-3:
        peaks = np.argmax(envelope_db.mean(axis=0), axis=-1)
        if ring > 1.0:
            extra = int((ring - 1.0) * 0.25 * envelope_db.shape[-1])
            envelope_db = np.pad(envelope_db, ((0, 0), (0, 0), (0, extra)), mode="edge")
            coherence = np.pad(coherence, ((0, 0), (0, int(np.ceil(extra / CARRIER_STEP)))), mode="edge")
            offsets = np.pad(offsets, ((0, 0), (0, int(np.ceil(extra / CARRIER_STEP)))), mode="edge")
        frames = np.arange(envelope_db.shape[-1])
        for band in range(BAND_COUNT):
            after = frames > peaks[band]
            peak_db = envelope_db[:, band, peaks[band]][:, None]
            envelope_db[:, band, after] = peak_db + (envelope_db[:, band, after] - peak_db) / ring
    if abs(length - 1.0) > 1e-3:
        source_frame, onsets = warp_map(envelope_db.shape[-1], onsets, length)
        envelope_db = resample_rows(envelope_db, source_frame)
        carrier_positions = source_frame[::CARRIER_STEP] / CARRIER_STEP
        coherence = resample_rows(coherence, carrier_positions)
        offsets = resample_rows(offsets, carrier_positions)
    return envelope_db, coherence, offsets, onsets


# ---------------------------------------------------------------- render

def unit_noise(spectrum, band, length):
    """Fresh noise in one band with its own envelope divided out: a phase that wanders like band noise."""
    windows = band_windows(length)
    full = np.zeros(length, dtype=complex)
    half = spectrum * windows[band]
    full[:len(half)] = half
    full[1:len(half)] *= 2.0
    analytic = np.fft.ifft(full)
    return analytic / (np.abs(analytic) + 1e-12)


def upsample_frames(values, length, step):
    positions = (np.arange(len(values)) + 0.5) * step
    return np.interp(np.arange(length), positions, values)


def render_raw(envelope_db, coherence, offsets, channel_coherence, generator):
    frame_count = fast_length(envelope_db.shape[-1] * HOP) // HOP
    if frame_count > envelope_db.shape[-1]:
        extra = frame_count - envelope_db.shape[-1]
        envelope_db = np.pad(envelope_db, ((0, 0), (0, 0), (0, extra)), constant_values=FLOOR_DB)
    length = frame_count * HOP
    white = [np.fft.rfft(generator.standard_normal(length)) for _ in range(3)]
    sample_index = np.arange(length)
    take = np.zeros((2, length))
    start_phases = generator.uniform(0, 2 * np.pi, BAND_COUNT)
    for band in range(BAND_COUNT):
        share = np.clip(upsample_frames(coherence[band], length, HOP * CARRIER_STEP), 0.0, 1.0)
        offset = upsample_frames(offsets[band], length, HOP * CARRIER_STEP)
        phase = start_phases[band] + 2 * np.pi * np.cumsum(CENTRES[band] + offset) / RATE
        tone = np.exp(1j * phase)
        common = unit_noise(white[0], band, length)
        linked = channel_coherence[band]
        for channel in range(2):
            if linked > 0.999:
                noise = common
            else:
                own = unit_noise(white[1 + channel], band, length)
                mixed = np.sqrt(linked) * common + np.sqrt(1.0 - linked) * own
                noise = mixed / (np.abs(mixed) + 1e-12)
            amplitude = upsample_frames(10 ** (envelope_db[channel, band] / 20), length, HOP)
            carrier = np.sqrt(share) * tone + np.sqrt(1.0 - share) * noise
            take[channel] += amplitude * np.real(carrier)
    del sample_index
    return take


def correct_envelopes(take, envelope_db, strength=1.0, limit_db=12.0):
    """Measure the take's band envelopes and pull them toward the model's (one pass)."""
    length = take.shape[1]
    frame_count = length // HOP
    measured_db = 20 * np.log10(band_envelopes(take) + 1e-12)
    target_db = envelope_db[:, :, :frame_count]
    if target_db.shape[-1] < frame_count:
        missing = frame_count - target_db.shape[-1]
        target_db = np.pad(target_db, ((0, 0), (0, 0), (0, missing)), constant_values=FLOOR_DB)
    heard = target_db > target_db.max() - 70
    gain_db = np.where(heard, target_db - measured_db, 0.0)
    gain_db = ndimage.uniform_filter1d(np.clip(gain_db, -limit_db, limit_db), 4, axis=-1) * strength
    windows = band_windows(length) ** 2
    corrected = np.zeros_like(take)
    for channel in range(2):
        spectrum = np.fft.rfft(take[channel])
        for band in range(BAND_COUNT):
            component = np.fft.irfft(spectrum * windows[band], length)
            gain = upsample_frames(10 ** (gain_db[channel, band] / 20), length, HOP)
            corrected[channel] += component * gain
    return corrected


def clamp_before_onsets(take, true_envelope, onsets):
    """In the 30 ms before each onset, never stand above the recording's own envelope."""
    length = take.shape[1]
    frame_count = min(length // HOP, len(true_envelope))
    take_envelope = np.sqrt(np.mean(frames_of(np.abs(take).mean(axis=0), frame_count) ** 2, axis=1))
    gain = np.ones(frame_count)
    span = int(PRE_ONSET_CLAMP_SECONDS * FRAME_RATE)
    for onset in onsets:
        start = max(0, onset - span)
        stop = min(frame_count, onset)
        ratio = (true_envelope[start:stop] * 1.12 + 1e-9) / (take_envelope[start:stop] + 1e-12)
        gain[start:stop] = np.minimum(gain[start:stop], np.clip(ratio, 0.0, 1.0))
    gain = ndimage.minimum_filter1d(gain, 3)
    full_gain = upsample_frames(gain, length, HOP)
    return take * full_gain


def resample_by(take, factor):
    """Play the take `factor` times slower: lower and longer when factor > 1."""
    if abs(factor - 1.0) < 1e-4:
        return take
    numerator = int(round(factor * 1000))
    divisor = gcd(numerator, 1000)
    return signal.resample_poly(take, numerator // divisor, 1000 // divisor, axis=-1)


def render(model, seed=0, length=1.0, size=1.0, pitch=0.0, bright=0.0, hard=0.0, ring=1.0, weight=0.0, energy=0.0,
           vary=0.0, correct=True):
    generator = np.random.default_rng(seed)
    pitch_ratio = 2 ** (pitch / 12.0)
    envelope_db, coherence, offsets, onsets = transformed(
        model, length=length / pitch_ratio, bright=bright, hard=hard, ring=ring, weight=weight, energy=energy,
        vary=vary, generator=generator)
    take = render_raw(envelope_db, coherence, offsets, model["channel_coherence"], generator)
    if correct:
        take = correct_envelopes(take, envelope_db)
    if abs(length / pitch_ratio - 1.0) < 1e-3 and abs(ring - 1.0) < 1e-3 and not vary:
        take = clamp_before_onsets(take, model["true_envelope"], onsets)
    take = resample_by(take, size / pitch_ratio)
    return tidy(take)


def tidy(take, silence_db=-70.0):
    """Drop leading silence, fade the start over 1 ms and the end where it falls under the floor."""
    level = np.abs(take).max(axis=0)
    peak = level.max() + 1e-12
    heard = np.where(level > peak * 10 ** (silence_db / 20))[0]
    if len(heard) == 0:
        return take
    start = max(0, heard[0] - int(0.001 * RATE))
    end = min(take.shape[1], heard[-1] + int(0.005 * RATE))
    take = take[:, start:end].copy()
    fade_in = min(take.shape[1], int(0.001 * RATE))
    take[:, :fade_in] *= np.linspace(0, 1, fade_in)
    fade_out = min(take.shape[1], int(0.005 * RATE))
    take[:, -fade_out:] *= np.linspace(1, 0, fade_out) ** 2
    return take


# ---------------------------------------------------------------- measures

def broadband_envelope(audio, frame_seconds=0.00025):
    audio = np.asarray(audio, dtype=float)
    mono = audio.mean(axis=0) if audio.ndim == 2 else audio
    step = int(frame_seconds * RATE)
    count = len(mono) // step
    return np.sqrt(np.mean(mono[:count * step].reshape(count, step) ** 2, axis=1))


def timing(take):
    """Onset (first point within 20 dB of the loudest 5 ms) and peak, in seconds from the start of the take."""
    envelope = broadband_envelope(take, 0.001)
    smooth = ndimage.uniform_filter1d(envelope, 5)
    peak_frame = int(np.argmax(smooth))
    above = np.where(envelope[:peak_frame + 1] >= smooth[peak_frame] * 0.1)[0]
    onset_frame = int(above[0]) if len(above) else peak_frame
    return onset_frame / 1000.0, peak_frame / 1000.0


def rise_ms(audio):
    """10-90 % rise time of the main onset, in ms, from a 0.25 ms envelope."""
    envelope = broadband_envelope(audio)
    smooth = ndimage.uniform_filter1d(envelope, 8)
    peak = int(np.argmax(smooth))
    top = envelope[max(0, peak - 40):peak + 40].max()
    peak_index = max(0, peak - 40) + int(np.argmax(envelope[max(0, peak - 40):peak + 40]))
    before = envelope[:peak_index + 1]
    low = np.where(before < 0.1 * top)[0]
    start = low[-1] if len(low) else 0
    high = np.where(envelope[start:peak_index + 1] >= 0.9 * top)[0]
    finish = start + (high[0] if len(high) else peak_index - start)
    return (finish - start) * 0.25


def aligned_pair(first, second):
    """Both cut from their own onset and to the same length."""
    first_onset, _ = timing(first)
    second_onset, _ = timing(second)
    first = first[:, int(first_onset * RATE):]
    second = second[:, int(second_onset * RATE):]
    count = min(first.shape[1], second.shape[1])
    count -= count % HOP
    return first[:, :count], second[:, :count]


def fidelity(reference, take):
    reference = prepare(reference, RATE)
    take = prepare(take, RATE)
    reference, take = aligned_pair(reference, take)
    reference_db = 20 * np.log10(band_envelopes(reference).mean(axis=0) + 1e-12)
    take_db = 20 * np.log10(band_envelopes(take).mean(axis=0) + 1e-12)
    reference_db = ndimage.uniform_filter1d(reference_db, CARRIER_STEP, axis=-1)[:, ::CARRIER_STEP]
    take_db = ndimage.uniform_filter1d(take_db, CARRIER_STEP, axis=-1)[:, ::CARRIER_STEP]
    level_db = float(reference_db.max() - take_db.max())
    take_db = take_db + level_db
    heard = (reference_db > reference_db.max() - 40) & (reference_db > reference_db.max(axis=1, keepdims=True) - 25)
    env_db = float(np.sqrt(np.mean((reference_db - take_db)[heard] ** 2)))
    smooth_reference = ndimage.uniform_filter(reference_db, (3, 3))
    smooth_take = ndimage.uniform_filter(take_db, (3, 3))
    shape_db = float(np.sqrt(np.mean((smooth_reference - smooth_take)[heard] ** 2)))
    return {"env_db": round(env_db, 2), "shape_db": round(shape_db, 2),
            "rise_ms": round(rise_ms(take), 2), "reference_rise_ms": round(rise_ms(reference), 2),
            "level_db": round(level_db, 2)}


def audit(take, reference_rise=None):
    """Faults a take must not have; an empty list is clean."""
    faults = []
    peak = np.abs(take).max() + 1e-12
    if abs(take.mean()) > 0.01 * peak:
        faults.append("dc offset")
    tail = take[:, -int(0.005 * RATE):]
    if np.sqrt(np.mean(tail ** 2)) > peak * 10 ** (-45 / 20):
        faults.append("cut tail")
    if not np.all(np.isfinite(take)):
        faults.append("not finite")
    if reference_rise is not None:
        take_rise = rise_ms(take)
        if take_rise > 2.0 * reference_rise + 1.0:
            faults.append(f"soft attack ({take_rise:.1f} ms against {reference_rise:.1f} ms)")
    return faults


# ---------------------------------------------------------------- storage

def save(path, model):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope_db = np.clip(20 * np.log10(model["envelopes"] + 1e-12), FLOOR_DB, 20)
    np.savez_compressed(
        path,
        envelope_db=np.round(envelope_db * 4).astype(np.int16),
        coherence=np.round(model["coherence"] * 255).astype(np.uint8),
        offsets=model["offsets"].astype(np.float32),
        channel_coherence=model["channel_coherence"].astype(np.float32),
        onsets=model["onsets"].astype(np.int32),
        true_envelope=model["true_envelope"].astype(np.float32),
        meta=np.frombuffer(json.dumps(model["meta"]).encode("utf-8"), dtype=np.uint8),
    )


def load(path):
    with np.load(path) as stored:
        return {
            "envelopes": 10 ** (stored["envelope_db"].astype(float) / 4 / 20),
            "coherence": stored["coherence"].astype(float) / 255,
            "offsets": stored["offsets"].astype(float),
            "channel_coherence": stored["channel_coherence"].astype(float),
            "onsets": stored["onsets"].astype(int),
            "true_envelope": stored["true_envelope"].astype(float),
            "meta": json.loads(bytes(stored["meta"]).decode("utf-8")),
        }


def model_size(path):
    with zipfile.ZipFile(path) as archive:
        return sum(item.compress_size for item in archive.infolist())
