"""
Image crop orchestration: OpenCV heuristics first, optional rembg, safe fallbacks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageFile

from config import CropConfig, DEFAULT_CROP_CONFIG
from image_crop import apply_padding, auto_crop_cv_bgr, validate_crop_bbox

logger = logging.getLogger(__name__)

# Allow slightly truncated downloads
ImageFile.LOAD_TRUNCATED_IMAGES = True

_session = None


def _get_session():
    global _session
    if _session is None:
        from rembg import new_session

        _session = new_session("u2net")
    return _session


def get_subject_bbox_rembg(
    image: Image.Image,
    alpha_threshold: int = 22,
) -> Optional[tuple[int, int, int, int]]:
    from rembg import remove

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


@dataclass
class ProcessOutcome:
    """Result of process_image_bytes — used for captions and logging."""

    data: bytes
    method: str
    used_fallback_original: bool


def _pil_to_bgr(img: Image.Image) -> np.ndarray:
    rgb = np.array(img.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _save_png(image: Image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


def process_image_bytes(
    data: bytes,
    cfg: CropConfig = DEFAULT_CROP_CONFIG,
) -> ProcessOutcome:
    """
    Full pipeline: CV crop → optional rembg → optional original fallback.
    Never raises for corrupt images; may raise from caller only if we want — actually we catch in bot.
    """
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as e:
        logger.warning("Invalid image data: %s", e)
        raise ValueError("Unsupported or corrupted image file") from e

    fmt = (img.format or "").upper()
    if fmt not in ("PNG", "JPEG", "JPG", "WEBP", "MPO", ""):
        logger.info("Unusual image format %s, attempting convert", fmt)

    rgb = img.convert("RGB")
    w, h = rgb.size
    bgr = _pil_to_bgr(rgb)

    # --- Stage 1: OpenCV ---
    cv_bbox, cv_conf, cv_method = auto_crop_cv_bgr(bgr, cfg)
    chosen: Optional[tuple[int, int, int, int]] = None
    method_parts: list[str] = []

    if cv_bbox is not None and cv_conf >= cfg.rembg_confidence_threshold:
        chosen = apply_padding(cv_bbox, w, h, cfg.padding_px)
        method_parts.append(f"cv:{cv_method}")
        logger.info(
            "Crop CV: method=%s conf=%.2f bbox=%s", cv_method, cv_conf, chosen
        )

    # --- Stage 2: rembg (if CV weak / missing) ---
    if chosen is None and cfg.use_rembg:
        try:
            rb = get_subject_bbox_rembg(rgb, alpha_threshold=cfg.rembg_alpha_threshold)
        except Exception:
            logger.exception("rembg stage failed")
            rb = None
        if rb is not None and validate_crop_bbox(rb, w, h, cfg):
            chosen = apply_padding(rb, w, h, cfg.padding_px)
            method_parts.append("rembg")
            logger.info("Crop rembg: bbox=%s", chosen)

    # --- Stage 3: CV with moderate confidence if rembg did not help ---
    if (
        chosen is None
        and cv_bbox is not None
        and cv_conf >= cfg.min_cv_alone_confidence
    ):
        chosen = apply_padding(cv_bbox, w, h, cfg.padding_px)
        method_parts.append(f"cv_alone:{cv_method}")
        logger.info("Crop CV alone: conf=%.2f bbox=%s", cv_conf, chosen)

    # --- Stage 4: safe fallback ---
    if chosen is None:
        if cfg.fallback_return_original:
            logger.info("Crop: returning original image (no confident bbox)")
            return ProcessOutcome(
                data=_save_png(rgb),
                method="original_fallback",
                used_fallback_original=True,
            )
        raise ValueError("Could not detect subject")

    cropped = rgb.crop(chosen)
    out_bytes = _save_png(cropped)
    label = "+".join(method_parts) if method_parts else "unknown"
    return ProcessOutcome(
        data=out_bytes,
        method=label,
        used_fallback_original=False,
    )
