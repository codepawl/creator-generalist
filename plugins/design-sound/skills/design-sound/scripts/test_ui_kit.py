"""Tests for ui_kit.py checks: run with
uv run --no-project --python 3.12 --with numpy --with scipy --with librosa --with soundfile --with pyloudnorm
--with psutil python test_ui_kit.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_kit  # noqa: E402

RATE = ui_kit.RATE


def click(seconds=0.04, at=0.0, total=0.1):
    mono = np.zeros(int(total * RATE), dtype=np.float32)
    start = int(at * RATE)
    length = int(seconds * RATE)
    envelope = np.exp(-np.linspace(0, 8, length)).astype(np.float32)
    noise = np.random.default_rng(1).standard_normal(length).astype(np.float32)
    mono[start:start + length] += 0.8 * envelope * noise
    return mono


def write_kit(folder, role, takes):
    names = []
    for index, mono in enumerate(takes):
        name = f"{role}_{index + 1}.wav"
        soundfile.write(Path(folder) / name, mono, RATE)
        names.append(name)
    kit = {"roles": {role: {"files": names, "level_db": -18, "rotate": True}}}
    (Path(folder) / "kit.json").write_text(json.dumps(kit), encoding="utf-8")


class CheckTests(unittest.TestCase):
    def test_single_click_is_clean(self):
        with tempfile.TemporaryDirectory() as folder:
            write_kit(folder, "select", [click()])
            self.assertEqual(ui_kit.check_folder(folder), [])

    def test_double_strike_is_flagged(self):
        with tempfile.TemporaryDirectory() as folder:
            double = click(total=0.1) + click(at=0.06, total=0.1)
            write_kit(folder, "select", [double])
            problems = ui_kit.check_folder(folder)
            self.assertTrue(any("strike once" in line for line in problems))

    def test_long_arrow_is_flagged(self):
        with tempfile.TemporaryDirectory() as folder:
            long_tone = 0.5 * np.sin(np.linspace(0, 2 * np.pi * 800 * 0.4, int(0.4 * RATE))).astype(np.float32)
            write_kit(folder, "arrow", [long_tone])
            problems = ui_kit.check_folder(folder)
            self.assertTrue(any("longer than" in line for line in problems))

    def test_capped_take_fits_its_role(self):
        long_tone = np.ones(int(0.5 * RATE), dtype=np.float32) * 0.5
        shaped = ui_kit.capped(long_tone, 0.12)
        self.assertLessEqual(len(shaped), int(0.12 * RATE))
        self.assertLess(abs(shaped[-1]), 0.01)

    def test_highpass_removes_thump(self):
        thump = np.sin(np.linspace(0, 2 * np.pi * 60, RATE)).astype(np.float32)
        self.assertLess(np.max(np.abs(ui_kit.filtered(thump, None)[RATE // 2:])), 0.15)


if __name__ == "__main__":
    unittest.main()
