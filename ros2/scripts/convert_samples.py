"""
Convert the five PPE sample images from WebP to PNG for the replay publisher.

The samples come from the public site (zulfaqarhafez.com/demos/ppe-compliance/
samples/<id>.webp). They are test images from the team's Roboflow dataset
"Personal Protective Equipment" v5, licence CC BY 4.0 (see NOTICE).
PNG is lossless, so the pixels are exactly what Pillow decodes from the WebP,
which is what the reference results in samples.json were computed on.

Usage: python3 scripts/convert_samples.py <dir with samples.json and samples/> <out dir>
       (or --url to fetch the WebP files from the public site)
Needs Pillow.
"""
from io import BytesIO
import json
import os
import sys
import urllib.request

from PIL import Image

BASE = 'https://zulfaqarhafez.com/demos/ppe-compliance/'


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    if src == '--url':
        meta = json.load(urllib.request.urlopen(BASE + 'samples.json'))

        def read(sid):
            return BytesIO(urllib.request.urlopen(f'{BASE}samples/{sid}.webp').read())
    else:
        meta = json.load(open(os.path.join(src, 'samples.json')))

        def read(sid):
            return os.path.join(src, 'samples', f'{sid}.webp')
    json.dump(meta, open(os.path.join(out, 'samples.json'), 'w'), indent=1)
    for s in meta['samples']:
        img = Image.open(read(s['id'])).convert('RGB')
        assert img.size == (s['width'], s['height']), (s['id'], img.size)
        img.save(os.path.join(out, f"{s['id']}.png"), optimize=True)
        print(s['id'], img.size)


if __name__ == '__main__':
    main()
