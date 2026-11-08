"""Generate a foley track for a silent video with HunyuanVideo-Foley XL (local, offloaded, fits a 12 GB card).

Runs inside the model's own venv (install steps: references/video-foley.md):
  <model root>/repo/.venv/Scripts/python.exe video_foley.py film.mp4 \
      --prompt "furniture dropped on a wooden floor, soft thuds" --out foley.wav [--mux out.mp4]

The model root defaults to ~/models/hunyuanvideo-foley (set HUNYUAN_FOLEY_ROOT to move it). Films longer than --chunk
seconds are generated in overlapping pieces (the model takes at most 15 s) joined with an equal-power crossfade.
Prints and writes <out>.report.json: time, real-time factor, peak VRAM, peak RAM, CPU use, and whether the model
heard nothing (near-silent output), which means the film needs hand-placed foley instead.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_ROOT = os.environ.get("HUNYUAN_FOLEY_ROOT", str(Path.home() / "models" / "hunyuanvideo-foley"))
os.environ.setdefault("HF_HUB_CACHE", str(Path(MODEL_ROOT).parent / "hf-hub"))
sys.path.insert(0, os.path.join(MODEL_ROOT, "repo"))

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
MODEL_MAX_SECONDS = 15.0
SILENT_WINDOW_DB = -80.0  # the DAC decoder's floor sits near -89 dB when the model hears nothing
HEARD_NOTHING_SHARE = 0.8


def lower_own_priority():
    if os.name == "nt":
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
    else:
        os.nice(10)


class ResourceSampler:
    """Samples whole-card VRAM (nvidia-smi), this process's RAM and its CPU use while the model runs."""

    def __init__(self, interval_seconds=0.5):
        import psutil

        self.process = psutil.Process()
        self.process.cpu_percent(None)
        self.interval_seconds = interval_seconds
        self.baseline_mb = self.read_used_mb()
        self.peak_mb = self.baseline_mb
        self.peak_ram_mb = 0
        self.cpu_samples = []
        self.running = True
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def sample_process(self):
        try:
            self.peak_ram_mb = max(self.peak_ram_mb, self.process.memory_info().rss // 2**20)
            self.cpu_samples.append(self.process.cpu_percent(None))
        except Exception:
            pass

    def cpu_summary(self):
        import psutil

        samples = self.cpu_samples or [0.0]
        return {
            "cpu_average_cores": round(sum(samples) / len(samples) / 100, 1),
            "cpu_peak_cores": round(max(samples) / 100, 1),
            "cpu_logical_cores": psutil.cpu_count(),
        }

    @staticmethod
    def read_used_mb():
        try:
            output = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            return int(output.strip().splitlines()[0])
        except Exception:
            return 0

    def loop(self):
        while self.running:
            self.peak_mb = max(self.peak_mb, self.read_used_mb())
            self.sample_process()
            time.sleep(self.interval_seconds)

    def stop(self):
        self.running = False
        self.thread.join(timeout=2)


def heard_nothing_share(track, sample_rate):
    """Share of half-second windows below SILENT_WINDOW_DB."""
    import numpy

    mono = track.mean(0).numpy() if track.ndim > 1 else track.numpy()
    window = sample_rate // 2
    count = max(1, len(mono) // window)
    silent = 0
    for index in range(count):
        piece = mono[index * window:(index + 1) * window]
        level = 20 * numpy.log10(numpy.sqrt(numpy.mean(piece ** 2)) + 1e-9)
        if level < SILENT_WINDOW_DB:
            silent += 1
    return silent / count


def probe_duration(video_path):
    output = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(output.strip())


def plan_chunks(duration, chunk_seconds, overlap_seconds):
    if duration <= chunk_seconds:
        return [(0.0, duration)]
    chunks = []
    start = 0.0
    while start < duration:
        end = min(start + chunk_seconds, duration)
        chunks.append((start, end))
        if end >= duration:
            break
        start = end - overlap_seconds
    return chunks


def cut_clip(video_path, start, end, folder, index):
    clip_path = os.path.join(folder, f"chunk_{index:03d}.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", video_path, "-t", f"{end - start:.3f}",
         "-an", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", clip_path],
        check=True,
    )
    return clip_path


def join_with_crossfade(pieces, sample_rate, chunks, overlap_seconds, total_seconds):
    import torch

    total_samples = int(round(total_seconds * sample_rate))
    channels = pieces[0].shape[0]
    output = torch.zeros(channels, total_samples)
    fade_samples = int(round(overlap_seconds * sample_rate))
    for index, (piece, (start, _end)) in enumerate(zip(pieces, chunks)):
        piece = piece.clone()
        if index > 0 and fade_samples > 0:
            ramp = torch.linspace(0, 1, fade_samples)
            piece[:, :fade_samples] *= torch.sin(ramp * torch.pi / 2)
        if index < len(pieces) - 1 and fade_samples > 0:
            ramp = torch.linspace(1, 0, fade_samples)
            piece[:, -fade_samples:] *= torch.sin(ramp * torch.pi / 2)
        offset = int(round(start * sample_rate))
        length = min(piece.shape[1], total_samples - offset)
        output[:, offset:offset + length] += piece[:, :length]
    return output


def mux(video_path, audio_path, out_path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", video_path, "-i", audio_path, "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--prompt", required=True, help="what makes the sound, in plain words")
    parser.add_argument("--neg", default=None, help="negative prompt (model default: 'noisy, harsh')")
    parser.add_argument("--out", required=True, help="output WAV (48 kHz)")
    parser.add_argument("--mux", default=None, help="also write the video with this audio as AAC")
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--guidance", type=float, default=4.5)
    parser.add_argument("--chunk", type=float, default=12.0, help="piece length for long films, at most 15")
    parser.add_argument("--overlap", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--model-size", choices=["xl", "xxl"], default="xl")
    parser.add_argument("--no-offload", action="store_true", help="only with 16+ GB free")
    arguments = parser.parse_args()

    lower_own_priority()
    started = time.time()
    sampler = ResourceSampler()

    import random
    import numpy as np
    import soundfile
    import torch
    from hunyuanvideo_foley.utils.model_utils import load_model, denoise_process
    from hunyuanvideo_foley.utils.feature_utils import feature_process

    random.seed(arguments.seed)
    np.random.seed(arguments.seed)
    torch.manual_seed(arguments.seed)

    weights_folder = os.path.join(MODEL_ROOT, "weights")
    config_name = f"hunyuanvideo-foley-{arguments.model_size}.yaml"
    config_path = os.path.join(MODEL_ROOT, "repo", "configs", config_name)
    model_dict, config = load_model(
        weights_folder, config_path, torch.device("cuda:0"),
        enable_offload=not arguments.no_offload, model_size=arguments.model_size,
    )
    loaded = time.time()

    duration = probe_duration(arguments.video)
    chunk_seconds = min(arguments.chunk, MODEL_MAX_SECONDS)
    chunks = plan_chunks(duration, chunk_seconds, arguments.overlap)
    # The offload manager unloads its models after every call. Hold them for the whole film instead: all feature
    # passes first (encoders resident), release, then all denoise passes (generator and VAE resident), release.
    manager = getattr(model_dict, "manager", None)
    offloading = manager is not None and manager.enable_offload

    def hold_models(hold):
        if offloading:
            manager.enable_offload = not hold

    pieces = []
    sample_rate = 48000
    features = []
    with tempfile.TemporaryDirectory() as folder:
        hold_models(True)
        for index, (start, end) in enumerate(chunks):
            clip_path = arguments.video if len(chunks) == 1 else cut_clip(arguments.video, start, end, folder, index)
            features.append(feature_process(clip_path, arguments.prompt, model_dict, config, neg_prompt=arguments.neg))
            print(f"features {index + 1}/{len(chunks)} done at {time.time() - started:.0f} s")
        hold_models(False)
        if offloading:
            manager.release_feature_models()
        hold_models(True)
        for index, (visual_feats, text_feats, audio_seconds) in enumerate(features):
            audio, sample_rate = denoise_process(
                visual_feats, text_feats, audio_seconds, model_dict, config,
                guidance_scale=arguments.guidance, num_inference_steps=arguments.steps,
            )
            pieces.append(audio[0].float().cpu())
            start, end = chunks[index]
            print(f"chunk {index + 1}/{len(chunks)} {start:.1f}-{end:.1f} s done at {time.time() - started:.0f} s")
        hold_models(False)
        if offloading:
            manager.release_inference_models()

    if len(pieces) == 1:
        track = pieces[0]
    else:
        track = join_with_crossfade(pieces, sample_rate, chunks, arguments.overlap, duration)
    os.makedirs(os.path.dirname(os.path.abspath(arguments.out)), exist_ok=True)
    soundfile.write(arguments.out, track.numpy().T, sample_rate, subtype="PCM_24")
    finished = time.time()
    sampler.stop()

    if arguments.mux:
        mux(arguments.video, arguments.out, arguments.mux)

    generation_seconds = finished - loaded
    silent_share = heard_nothing_share(track, sample_rate)
    report = {
        "video": arguments.video,
        "prompt": arguments.prompt,
        "video_seconds": round(duration, 2),
        "chunks": len(chunks),
        "steps": arguments.steps,
        "load_seconds": round(loaded - started, 1),
        "generation_seconds": round(generation_seconds, 1),
        "seconds_per_video_second": round(generation_seconds / duration, 2),
        "torch_peak_reserved_mb": round(torch.cuda.max_memory_reserved() / 2**20),
        "card_peak_used_mb": sampler.peak_mb,
        "card_baseline_used_mb": sampler.baseline_mb,
        "process_peak_ram_mb": sampler.peak_ram_mb,
        **sampler.cpu_summary(),
        "silent_share": round(silent_share, 2),
        "heard_nothing": silent_share >= HEARD_NOTHING_SHARE,
        "sample_rate": sample_rate,
    }
    with open(arguments.out + ".report.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report, indent=2))
    if report["heard_nothing"]:
        print(f"WARNING heard nothing: {silent_share:.0%} of the track is under {SILENT_WINDOW_DB:.0f} dB. "
              "Place this film's foley from its event list instead (foley.py).")
    sys.stdout.flush()
    os._exit(0)  # leave no worker thread or child holding VRAM


if __name__ == "__main__":
    main()
