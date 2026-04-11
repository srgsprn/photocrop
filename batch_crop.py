#!/usr/bin/env python3
"""
Local batch test: process all images in a folder and write cropped PNGs.

  python batch_crop.py ./screens_in ./screens_out

Environment: same CROP_* and CROP_USE_REMBG as the bot (see config.py).
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from config import DEFAULT_CROP_CONFIG
from crop_engine import process_image_bytes

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("batch_crop")

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".jpe"}


def main() -> int:
    p = argparse.ArgumentParser(description="Batch auto-crop images (same pipeline as bot).")
    p.add_argument("input_dir", type=Path, help="Folder with input images")
    p.add_argument("output_dir", type=Path, help="Folder for cropped PNGs")
    p.add_argument(
        "--no-rembg",
        action="store_true",
        help="Disable rembg stage (OpenCV only, faster, no model)",
    )
    args = p.parse_args()
    in_dir: Path = args.input_dir
    out_dir: Path = args.output_dir
    if not in_dir.is_dir():
        logger.error("Not a directory: %s", in_dir)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = DEFAULT_CROP_CONFIG
    if args.no_rembg:
        cfg = replace(cfg, use_rembg=False)

    files = sorted(
        f
        for f in in_dir.iterdir()
        if f.is_file() and f.suffix.lower() in EXTENSIONS
    )
    if not files:
        logger.warning("No images found in %s", in_dir)
        return 0

    ok = 0
    for f in files:
        try:
            data = f.read_bytes()
            out = process_image_bytes(data, cfg)
            dest = out_dir / (f.stem + "_cropped.png")
            dest.write_bytes(out.data)
            logger.info(
                "%s -> %s [%s fallback=%s]",
                f.name,
                dest.name,
                out.method,
                out.used_fallback_original,
            )
            ok += 1
        except Exception as e:
            logger.error("%s: %s", f.name, e)

    logger.info("Done: %s/%s files", ok, len(files))
    return 0 if ok == len(files) else 2


if __name__ == "__main__":
    sys.exit(main())
