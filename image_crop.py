"""
OpenCV-based auto-crop: gradients, edges, contours, connected components.
Designed for web screenshots — trim empty margins and isolate main visual mass.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from config import CropConfig, DEFAULT_CROP_CONFIG

logger = logging.getLogger(__name__)

BBox = Tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass
class CropProposal:
    bbox: BBox
    confidence: float
    method: str


def _clamp_bbox(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> BBox:
    x1 = max(0, min(w, x1))
    y1 = max(0, min(h, y1))
    x2 = max(0, min(w, x2))
    y2 = max(0, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return 0, 0, w, h
    return x1, y1, x2, y2


def _area(b: BBox) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _scale_bbox(
    bbox: BBox, scale_x: float, scale_y: float, w_full: int, h_full: int
) -> BBox:
    x1 = int(round(bbox[0] * scale_x))
    y1 = int(round(bbox[1] * scale_y))
    x2 = int(round(bbox[2] * scale_x))
    y2 = int(round(bbox[3] * scale_y))
    return _clamp_bbox(x1, y1, x2, y2, w_full, h_full)


def _resize_work(
    bgr: np.ndarray, max_edge: int
) -> tuple[np.ndarray, float, float]:
    h, w = bgr.shape[:2]
    m = max(h, w)
    if m <= max_edge:
        return bgr.copy(), 1.0, 1.0
    s = max_edge / m
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    small = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
    return small, w / nw, h / nh


def _center_score(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> float:
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    dx = abs(cx - w / 2) / (w / 2 + 1e-6)
    dy = abs(cy - h / 2) / (h / 2 + 1e-6)
    dist = float(np.sqrt(dx * dx + dy * dy))
    return max(0.0, 1.0 - min(1.0, dist))


def bbox_from_gradient_energy(gray: np.ndarray, q: float) -> Optional[CropProposal]:
    """Trim low-activity margins using mean Sobel magnitude per row/column."""
    h, w = gray.shape[:2]
    if h < 8 or w < 8:
        return None

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    row_e = mag.mean(axis=1)
    col_e = mag.mean(axis=0)
    rt = float(np.quantile(row_e, q))
    ct = float(np.quantile(col_e, q))
    # Slightly above noise floor
    row_thr = max(rt, float(row_e.mean() * 0.35))
    col_thr = max(ct, float(col_e.mean() * 0.35))

    ys = np.where(row_e >= row_thr)[0]
    xs = np.where(col_e >= col_thr)[0]
    if ys.size == 0 or xs.size == 0:
        return None

    y1, y2 = int(ys.min()), int(ys.max()) + 1
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    full = w * h
    inner = (x2 - x1) * (y2 - y1)
    if inner < 0.05 * full:
        return None

    removed = 1.0 - inner / full
    conf = float(np.clip(0.35 + removed * 1.2, 0.35, 0.88))
    return CropProposal((x1, y1, x2, y2), conf, "gradient_trim")


def bbox_from_canny_contours(
    gray: np.ndarray, cfg: CropConfig
) -> Optional[CropProposal]:
    h, w = gray.shape[:2]
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, cfg.canny_low, cfg.canny_high)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.dilate(edges, k, iterations=2)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k, iterations=1)

    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None

    total = float(h * w)
    min_a = cfg.min_area_ratio * total
    max_a = cfg.max_area_ratio * total

    best: Optional[tuple[float, BBox]] = None
    for c in cnts:
        a = cv2.contourArea(c)
        if a < min_a or a > max_a:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < 3 or bh < 3:
            continue
        cs = _center_score(x, y, x + bw, y + bh, w, h)
        score = a * (0.65 + 0.35 * cs)
        if best is None or score > best[0]:
            best = (score, (x, y, x + bw, y + bh))

    if best is None:
        return None
    _, box = best
    x1, y1, x2, y2 = box
    inner_area = (x2 - x1) * (y2 - y1)
    conf = float(np.clip(0.4 + (inner_area / total) * 0.45, 0.4, 0.82))
    return CropProposal(box, conf, "canny_contour")


def bbox_from_listing_white_ui(
    gray: np.ndarray, cfg: CropConfig
) -> Optional[CropProposal]:
    """
    Mobile resale apps (Vestiaire, etc.): hero photo on top, then carousel / white
    listing block. We skip the top status chrome, then cut at the first row that
    clearly belongs to the UI (near-white bar, carousel, text area).
    """
    h, w = gray.shape[:2]
    if h < 200 or w < 200:
        return None

    wl = int(np.clip(cfg.listing_gray_white_min, 0, 255))
    white_frac = (gray >= wl).mean(axis=1).astype(np.float64)
    row_mean = gray.mean(axis=1).astype(np.float64)
    row_std = gray.std(axis=1).astype(np.float64)

    def is_ui_row(y: int) -> bool:
        if white_frac[y] >= cfg.listing_footer_white_frac and row_mean[y] >= cfg.listing_footer_mean_min:
            return True
        if row_mean[y] >= 251 and row_std[y] <= cfg.listing_footer_std_max:
            return True
        if row_mean[y] >= 252 and white_frac[y] >= 0.55:
            return True
        return False

    top_lim = max(1, int(h * cfg.listing_top_scan_max))
    y1 = 0
    for y in range(top_lim):
        if (
            white_frac[y] <= cfg.listing_photo_white_frac_max
            and row_mean[y] <= cfg.listing_photo_mean_max
        ):
            y1 = y
            break

    min_photo_h = max(int(0.16 * h), cfg.listing_min_footer_px)
    y2 = y1
    found_ui = False
    for y in range(y1, h):
        if is_ui_row(y):
            if y - y1 >= min_photo_h:
                y2 = y
                found_ui = True
                break
        else:
            y2 = y + 1

    if not found_ui:
        return None

    rest_h = h - y2
    min_rest = max(cfg.listing_min_footer_px, int(cfg.listing_min_footer_frac * h))
    if rest_h < min_rest:
        return None

    min_h = int(0.22 * h)
    if y2 - y1 < min_h:
        return None

    inner_ratio = (y2 - y1) / float(h)
    rest_ratio = rest_h / float(h)
    conf = float(
        np.clip(
            0.55 + 0.28 * min(1.0, rest_ratio / 0.38) + 0.12 * inner_ratio,
            0.55,
            0.92,
        )
    )
    return CropProposal((0, y1, w, y2), conf, "listing_white_ui")


def bbox_from_connected_components(
    gray: np.ndarray, cfg: CropConfig
) -> Optional[CropProposal]:
    h, w = gray.shape[:2]
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    th = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 5
    )
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, k, iterations=1)

    num, labels, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    if num <= 1:
        return None

    total = float(h * w)
    min_a = cfg.min_area_ratio * total
    max_a = cfg.max_area_ratio * total

    best: Optional[tuple[float, BBox]] = None
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]
        if area < min_a or area > max_a:
            continue
        if bw < 5 or bh < 5:
            continue
        cs = _center_score(x, y, x + bw, y + bh, w, h)
        score = float(area) * (0.6 + 0.4 * cs)
        if best is None or score > best[0]:
            best = (score, (x, y, x + bw, y + bh))

    if best is None:
        return None
    _, box = best
    x1, y1, x2, y2 = box
    inner_area = (x2 - x1) * (y2 - y1)
    conf = float(np.clip(0.38 + (inner_area / total) * 0.4, 0.38, 0.78))
    return CropProposal(box, conf, "connected_components")


def _iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = _area(a) + _area(b) - inter
    return inter / ua if ua > 0 else 0.0


def _merge_proposals(
    proposals: list[CropProposal], w: int, h: int
) -> Optional[CropProposal]:
    """Fuse boxes that agree; otherwise pick strongest by confidence * sqrt(area)."""
    valid = [p for p in proposals if p is not None]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]

    valid.sort(key=lambda p: p.confidence * np.sqrt(_area(p.bbox)), reverse=True)
    anchor = valid[0]
    cluster = [anchor]
    for p in valid[1:]:
        if _iou(anchor.bbox, p.bbox) >= 0.25:
            cluster.append(p)

    xs = [p.bbox[0] for p in cluster]
    ys = [p.bbox[1] for p in cluster]
    xe = [p.bbox[2] for p in cluster]
    ye = [p.bbox[3] for p in cluster]
    merged = _clamp_bbox(min(xs), min(ys), max(xe), max(ye), w, h)
    avg_conf = float(np.mean([p.confidence for p in cluster]))
    boost = min(0.12, 0.04 * (len(cluster) - 1))
    methods = "+".join(sorted({p.method for p in cluster}))
    return CropProposal(
        merged, float(np.clip(avg_conf + boost, 0.0, 0.95)), methods
    )


def validate_crop_bbox(
    bbox: BBox, full_w: int, full_h: int, cfg: CropConfig
) -> bool:
    x1, y1, x2, y2 = bbox
    cw, ch = x2 - x1, y2 - y1
    if cw <= 0 or ch <= 0:
        return False
    if cw < cfg.min_side_ratio * full_w or ch < cfg.min_side_ratio * full_h:
        return False
    if _area(bbox) < cfg.min_output_area_ratio * full_w * full_h:
        return False
    return True


def auto_crop_cv_bgr(
    bgr: np.ndarray, cfg: CropConfig = DEFAULT_CROP_CONFIG
) -> tuple[Optional[BBox], float, str]:
    """
    Returns (bbox on full-resolution image, confidence 0..1, method label).
    bbox is None if no safe crop.
    """
    h0, w0 = bgr.shape[:2]
    if h0 < 16 or w0 < 16:
        return None, 0.0, "skip_tiny"

    work, sx, sy = _resize_work(bgr, cfg.max_process_edge)
    h, w = work.shape[:2]
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    props: list[CropProposal] = []
    listing = bbox_from_listing_white_ui(gray, cfg)
    if listing:
        props.append(listing)
    g = bbox_from_gradient_energy(gray, cfg.gradient_energy_quantile)
    if g:
        props.append(g)
    c = bbox_from_canny_contours(gray, cfg)
    if c:
        props.append(c)
    cc = bbox_from_connected_components(gray, cfg)
    if cc:
        props.append(cc)

    merged = _merge_proposals(props, w, h)
    if merged is None:
        logger.debug("CV crop: no proposals")
        return None, 0.0, "none"

    listing_prop = next(
        (p for p in props if p is not None and p.method == "listing_white_ui"),
        None,
    )
    if (
        listing_prop is not None
        and listing_prop.confidence >= cfg.listing_prefer_confidence
        and validate_crop_bbox(listing_prop.bbox, w, h, cfg)
    ):
        bx = _scale_bbox(listing_prop.bbox, sx, sy, w0, h0)
        if validate_crop_bbox(bx, w0, h0, cfg):
            conf = float(np.clip(listing_prop.confidence + 0.04, 0.0, 0.94))
            logger.debug("CV crop: prefer listing_white_ui bbox")
            return bx, conf, "listing_white_ui_preferred"

    bx = _scale_bbox(merged.bbox, sx, sy, w0, h0)
    if not validate_crop_bbox(bx, w0, h0, cfg):
        logger.debug("CV crop: rejected aggressive bbox %s", bx)
        return None, 0.0, "rejected_aggressive"

    # If merged is almost full frame, low usefulness
    ar = _area(bx) / float(w0 * h0)
    if ar > 0.97:
        conf = merged.confidence * 0.35
    else:
        conf = merged.confidence

    return bx, float(np.clip(conf, 0.0, 0.95)), merged.method


def apply_padding(bbox: BBox, w: int, h: int, pad: int) -> BBox:
    x1, y1, x2, y2 = bbox
    return _clamp_bbox(x1 - pad, y1 - pad, x2 + pad, y2 + pad, w, h)
