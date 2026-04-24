"""
Central configuration for crop pipeline and bot limits.
Override via environment variables where noted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class CropConfig:
    """Image auto-crop parameters (no magic numbers in call sites)."""

    # Border padding around detected box (before inner matte trim)
    padding_px: int = _int("CROP_PADDING_PX", 6)

    # Minimum contour / component area as fraction of image pixels
    min_area_ratio: float = _float("CROP_MIN_AREA_RATIO", 0.02)

    # Ignore candidates covering almost entire frame (likely background hull)
    max_area_ratio: float = _float("CROP_MAX_AREA_RATIO", 0.98)

    # Reject crop if width or height would be below this fraction of original
    min_side_ratio: float = _float("CROP_MIN_SIDE_RATIO", 0.28)

    # Reject crop if area below this fraction of original (too aggressive zoom)
    min_output_area_ratio: float = _float("CROP_MIN_OUTPUT_AREA_RATIO", 0.08)

    # Alpha threshold for rembg bbox (0–255)
    rembg_alpha_threshold: int = _int("CROP_REMBG_ALPHA_THRESHOLD", 22)

    # Longest edge for CV processing (speed); full-res bbox mapped back
    max_process_edge: int = _int("CROP_MAX_PROCESS_EDGE", 1600)

    # Canny thresholds (on resized gray)
    canny_low: int = _int("CROP_CANNY_LOW", 40)
    canny_high: int = _int("CROP_CANNY_HIGH", 120)

    # Gradient trim: row/column is "content" if mean gradient >= this quantile of all rows/cols
    gradient_energy_quantile: float = _float("CROP_GRADIENT_QUANTILE", 0.12)

    # Prefer rembg when CV confidence is below this
    rembg_confidence_threshold: float = _float("CROP_REMBG_CONFIDENCE_THRESHOLD", 0.45)

    # If rembg off or failed, still apply CV when confidence reaches this floor
    min_cv_alone_confidence: float = _float("CROP_MIN_CV_ALONE_CONFIDENCE", 0.30)

    # If True, return original image when no method is confident
    fallback_return_original: bool = _bool("CROP_FALLBACK_ORIGINAL", True)

    # Enable rembg stage (requires model download)
    use_rembg: bool = _bool("CROP_USE_REMBG", True)
    # Faster model by default; set CROP_REMBG_MODEL=u2net for maximum quality
    rembg_model: str = os.environ.get("CROP_REMBG_MODEL", "u2netp")
    # Skip rembg on very large frames to avoid CPU/RAM spikes and hangs
    rembg_max_pixels: int = _int("CROP_REMBG_MAX_PIXELS", 3_000_000)

    # --- Mobile marketplace screenshots (white footer + carousel) ---
    listing_gray_white_min: int = _int("CROP_LISTING_WHITE_MIN", 248)
    listing_footer_white_frac: float = _float("CROP_LISTING_FOOTER_WHITE_FRAC", 0.72)
    listing_footer_mean_min: float = _float("CROP_LISTING_FOOTER_MEAN_MIN", 248.0)
    listing_footer_std_max: float = _float("CROP_LISTING_FOOTER_STD_MAX", 14.0)
    listing_min_footer_frac: float = _float("CROP_LISTING_MIN_FOOTER_FRAC", 0.045)
    listing_min_footer_px: int = _int("CROP_LISTING_MIN_FOOTER_PX", 48)
    listing_top_scan_max: float = _float("CROP_LISTING_TOP_SCAN_MAX", 0.48)
    listing_photo_white_frac_max: float = _float("CROP_LISTING_PHOTO_WHITE_FRAC_MAX", 0.52)
    listing_photo_mean_max: float = _float("CROP_LISTING_PHOTO_MEAN_MAX", 238.0)

    # If listing layout confidence ≥ this, prefer its bbox over merged CV boxes
    listing_prefer_confidence: float = _float("CROP_LISTING_PREFER_CONFIDENCE", 0.52)

    # --- Matte / paspartout (white bars inside the hero frame, app UI) ---
    trim_matte_enabled: bool = _bool("CROP_TRIM_MATTE", True)
    trim_matte_gray_floor: int = _int("CROP_TRIM_MATTE_GRAY", 245)
    trim_matte_chroma_max: int = _int("CROP_TRIM_MATTE_CHROMA", 28)
    trim_matte_edge_light_frac: float = _float("CROP_TRIM_MATTE_LIGHT_FRAC", 0.86)
    trim_matte_edge_mean_min: float = _float("CROP_TRIM_MATTE_MEAN_MIN", 242.0)
    trim_matte_max_passes: int = _int("CROP_TRIM_MATTE_PASSES", 8)
    trim_matte_min_side_px: int = _int("CROP_TRIM_MATTE_MIN_SIDE", 64)
    trim_matte_min_remain_frac: float = _float("CROP_TRIM_MATTE_MIN_REMAIN", 0.62)


@dataclass(frozen=True)
class BotConfig:
    max_crops_per_minute: int = _int("BOT_RATE_LIMIT_PER_MINUTE", 25)
    max_image_bytes: int = _int("BOT_MAX_IMAGE_BYTES", 20 * 1024 * 1024)
    # Hard timeout per image processing; prevents endless waits
    process_timeout_sec: int = _int("BOT_PROCESS_TIMEOUT_SEC", 35)
    # Global parallel workers for CPU-heavy crop pipeline
    max_parallel_jobs: int = _int("BOT_MAX_PARALLEL_JOBS", 2)


DEFAULT_CROP_CONFIG = CropConfig()
DEFAULT_BOT_CONFIG = BotConfig()
