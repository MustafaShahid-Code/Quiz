"""Coordinate maths: polar scan points -> sensor plane (mm) -> normalised screen coordinates (u,v in 0..1)."""
import math

import numpy as np


class CalibrationError(ValueError):
    pass


def polar_to_xy(angle_deg: float, dist_mm: float) -> tuple[float, float]:
    """Sensor frame: angle grows clockwise from +y (Slamtec convention). Calibration absorbs any
    mirroring/rotation differences, so only consistency matters."""
    a = math.radians(angle_deg)
    return dist_mm * math.sin(a), dist_mm * math.cos(a)


def _normalise(pts: np.ndarray):
    c = pts.mean(axis=0)
    d = np.sqrt(((pts - c) ** 2).sum(axis=1)).mean()
    s = math.sqrt(2) / d if d > 1e-9 else 1.0
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])
    return T


def compute_homography(src, dst) -> np.ndarray:
    """Direct Linear Transform. src = sensor-plane mm points, dst = (u,v) screen points. Needs >= 4."""
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2:
        raise CalibrationError("src and dst must be matching lists of (x,y) pairs")
    if len(src) < 4:
        raise CalibrationError("at least 4 point pairs are required")
    # reject duplicates / near-duplicates
    for i in range(len(src)):
        for j in range(i + 1, len(src)):
            if np.linalg.norm(src[i] - src[j]) < 20:
                raise CalibrationError("two calibration touches are almost at the same place; touch each target separately")
    Ts, Td = _normalise(src), _normalise(dst)
    sh = np.c_[src, np.ones(len(src))] @ Ts.T
    dh = np.c_[dst, np.ones(len(dst))] @ Td.T
    rows = []
    for (x, y, _), (u, v, _) in zip(sh, dh):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    A = np.array(rows)
    _, S, Vt = np.linalg.svd(A)
    if S[-2] < 1e-9 * S[0]:
        raise CalibrationError("calibration points are collinear or degenerate")
    H = Vt[-1].reshape(3, 3)
    H = np.linalg.inv(Td) @ H @ Ts
    if abs(H[2, 2]) < 1e-12:
        raise CalibrationError("degenerate homography")
    return H / H[2, 2]


def apply_homography(H, x: float, y: float) -> tuple[float, float]:
    H = np.asarray(H, dtype=float)
    p = H @ np.array([x, y, 1.0])
    if abs(p[2]) < 1e-12:
        return float("nan"), float("nan")
    return float(p[0] / p[2]), float(p[1] / p[2])


def reprojection_error(H, src, dst) -> dict:
    """Error in normalised screen units (1.0 = full screen width/height)."""
    errs = []
    for (x, y), (u, v) in zip(src, dst):
        pu, pv = apply_homography(H, x, y)
        errs.append(math.hypot(pu - u, pv - v))
    errs = np.array(errs)
    return {"rmse": float(math.sqrt((errs ** 2).mean())), "max": float(errs.max()), "per_point": [float(e) for e in errs]}
