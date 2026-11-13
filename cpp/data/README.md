# Test data

`samples/` holds five images from the test split of the "Personal Protective
Equipment" dataset, version 5, Roboflow Universe workspace `maxis`
(https://universe.roboflow.com/maxis/personal-protective-equipment-dtt2i-9qixs),
licensed CC BY 4.0. They are the five sample images of the in-browser demo on
zulfaqarhafez.com: resized to a long side of 640 px and compressed to WebP
there, then converted here to lossless PNG by `scripts/convert_samples.py`
(stb_image cannot decode WebP). The PNG pixels are exactly the pixels Pillow
decodes from those WebP files; the script checks this.

| File | Size | Dataset file |
|---|---|---|
| `samples/site-backs.png` | 640 x 486 | `ppe_0305_jpg.rf.dcb8ae3362275cc2272871bad7575a10.jpg` |
| `samples/rooftop-cctv.png` | 640 x 360 | `ppe_0576_jpg.rf.f0a7da3930541bfb1d5d9e5cfc7c4744.jpg` |
| `samples/plant-cctv.png` | 640 x 640 | `file_1_519_jpg.rf.26f08b7d2a236da2b3a6d74cbc481842.jpg` |
| `samples/hi-vis-walk.png` | 640 x 450 | `ppe_0222_jpg.rf.3a2e47250cfc193f251f6bdec757edb0.jpg` |
| `samples/packing-cctv.png` | 640 x 360 | `PP02img440_jpg.rf.06e419b5f7858200320e5b7cf83b46d7.jpg` |

`reference/samples.json` is a copy of the site's
`public/demos/ppe-compliance/samples.json`: what the int8 model found in each
image at thresholds 0.25 and 0.5, produced in Python with Pillow's bilinear
resize and onnxruntime. The parity test checks that the C++ pipeline
reproduces every label and score in it.
