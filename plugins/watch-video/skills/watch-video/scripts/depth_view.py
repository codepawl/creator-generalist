"""Draw a depth .npz (metres, key "depth") on the fixed scale of label_palette.py: 1 m red to 2000 m dark blue, sky
(beyond --sky metres, default 1500) black, with a legend bar, so every depth picture reads the same way.
  uv run --no-project --with numpy --with pillow python -I depth_view.py <depth.npz> <out.png> [--sky 1500]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from label_palette import depth_picture  # noqa: E402


def main():
    depth = np.load(sys.argv[1])["depth"].astype(np.float32)
    sky_metres = float(sys.argv[sys.argv.index("--sky") + 1]) if "--sky" in sys.argv else 1500.0
    depth_picture(depth, sky_mask=depth > sky_metres).save(sys.argv[2])


if __name__ == "__main__":
    main()
