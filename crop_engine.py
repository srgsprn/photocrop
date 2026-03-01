"""
Crop engine: uses rembg to detect the main subject, then crops the image to its bounding box.
"""
from io import BytesIO
from typing import Optional, Tuple

import numpy as np
from PIL import Image
from rembg import remove, new_session

# One session per model = faster for multiple images
_session = None

def _get_session():
    global _session
    if _session is None:
        # u2net is more accurate; u2netp is faster/smaller
        _session = new_session("u2net")
    return _session


def get_subject_bbox(image: Image.Image, alpha_threshold: int = 20) -> Optional[Tuple[int, int, int, int]]:
    """
    Get bounding box (x1, y1, x2, y2) of the main subject using rembg.
    Returns None if no subject found.
    """
    session = _get_session()
    out = remove(image, session=session)
    out = out.convert("RGBA")
    a = np.array(out.getchannel("A"))
    ys, xs = np.where(a > alpha_threshold)
    if ys.size == 0 or xs.size == 0:
        return None
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    return (x1, y1, x2, y2)


def crop_to_subject(
    image: Image.Image,
    padding: int = 12,
    alpha_threshold: int = 20,
) -> Optional[Image.Image]:
    """
    Crop image to the bounding box of the main subject (product/person).
    Adds padding around the box. Returns None if no subject detected.
    """
    bbox = get_subject_bbox(image, alpha_threshold=alpha_threshold)
    if bbox is None:
        return None
    x1, y1, x2, y2 = bbox
    w, h = image.size
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(w, x2 + padding)
    y2 = min(h, y2 + padding)
    return image.crop((x1, y1, x2, y2))


def process_image_bytes(data: bytes, padding: int = 12) -> Optional[bytes]:
    """
    Load image from bytes, crop to subject, return PNG bytes.
    Returns None if subject not found.
    """
    img = Image.open(BytesIO(data)).convert("RGB")
    cropped = crop_to_subject(img, padding=padding)
    if cropped is None:
        return None
    buf = BytesIO()
    cropped.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
