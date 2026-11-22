"""One number per render for "how close does it look to the reference", so versions can be ranked without reading
pictures: DreamSim (MIT; distance trained on human same/different judgements of layout, colour and content, 0 is
identical) and LPIPS (BSD; texture-level distance). Lower is closer on both.

Run through the GPU queue with the torch line of read_geometry.py plus `--with dreamsim --with lpips`:
  python -I score_similarity.py <reference> <render> [<render> ...]
"""
import sys

import torch
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    reference_path = sys.argv[1]
    render_paths = sys.argv[2:]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    from dreamsim import dreamsim
    import lpips
    import torchvision.transforms.functional as transforms

    dreamsim_model, preprocess = dreamsim(pretrained=True, device=device)
    lpips_model = lpips.LPIPS(net="alex").to(device)
    reference = Image.open(reference_path).convert("RGB")

    def as_lpips_tensor(picture):
        resized = picture.resize((512, 288))
        return transforms.to_tensor(resized).unsqueeze(0).to(device) * 2 - 1

    reference_dreamsim = preprocess(reference).to(device)
    reference_lpips = as_lpips_tensor(reference)
    print(f"{'render':60s} {'DreamSim':>9s} {'LPIPS':>7s}")
    for render_path in render_paths:
        render = Image.open(render_path).convert("RGB").resize(reference.size)
        with torch.no_grad():
            dreamsim_distance = float(dreamsim_model(reference_dreamsim, preprocess(render).to(device)))
            lpips_distance = float(lpips_model(reference_lpips, as_lpips_tensor(render)))
        print(f"{render_path[-60:]:60s} {dreamsim_distance:9.3f} {lpips_distance:7.3f}")


if __name__ == "__main__":
    main()
