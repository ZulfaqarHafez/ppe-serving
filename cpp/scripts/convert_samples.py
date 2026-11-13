"""Convert the five WebP sample images to lossless PNG.

stb_image cannot decode WebP, so the C++ side reads PNG copies. The PNG holds
exactly the pixels Pillow decodes from the WebP file (the pixels the reference
run in samples.json saw); this script checks that before it writes anything.

Usage: python3 scripts/convert_samples.py <dir with the .webp files> data/samples
"""
import pathlib
import sys

import numpy as np
from PIL import Image

IDS = ["site-backs", "rooftop-cctv", "plant-cctv", "hi-vis-walk", "packing-cctv"]


def main() -> int:
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    for sid in IDS:
        rgb = Image.open(src / f"{sid}.webp").convert("RGB")
        out = dst / f"{sid}.png"
        rgb.save(out, "PNG", optimize=True)
        back = np.asarray(Image.open(out).convert("RGB"))
        if not np.array_equal(back, np.asarray(rgb)):
            print(f"{sid}: PNG differs from the decoded WebP", file=sys.stderr)
            return 1
        print(f"{sid}: {rgb.size[0]}x{rgb.size[1]} -> {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
