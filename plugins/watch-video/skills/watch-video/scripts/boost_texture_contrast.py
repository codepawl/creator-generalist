"""Write a higher-contrast copy of a base colour map, keeping its mean.

The cracked boulder scan has a relative spread of 0.12 (std / mean); the reference's rock reads about 0.3 at the
same scale, so its cracks and lichen vanish once the dark rock colour multiplies the map. Contrast is raised in
log space so dark cracks deepen without clipping the light patches.

uv run --no-project --with numpy --with pillow python -I tools/boost_texture_contrast.py <in.jpg> <out.jpg> <gain>
"""
import sys

import numpy
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
source_path, output_path, gain = sys.argv[1], sys.argv[2], float(sys.argv[3])
picture = numpy.asarray(Image.open(source_path).convert("RGB"), dtype=numpy.float32) / 255
linear = numpy.power(picture, 2.2) + 1e-4
log_light = numpy.log(linear.mean(axis=2, keepdims=True))
mean_log = log_light.mean()
boosted = linear * numpy.exp((log_light - mean_log) * (gain - 1))
boosted *= linear.mean() / boosted.mean()
result = numpy.power(numpy.clip(boosted, 0, 1), 1 / 2.2)
Image.fromarray((result * 255).astype(numpy.uint8)).save(output_path, quality=92)
print(f"{output_path}: relative spread {picture.std() / picture.mean():.2f} -> {result.std() / result.mean():.2f}")
