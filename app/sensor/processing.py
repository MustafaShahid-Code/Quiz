"""Turns raw LiDAR scans into validated touch events.

The sensor is assumed to scan a plane that runs a few millimetres/centimetres in front of, and parallel
to, the projection surface (mounted at a screen edge/corner). A fingertip/hand/pointer crossing that
plane inside the screen area produces a small cluster of returns. Raw returns are NEVER treated as
touches: they are filtered, clustered, size-checked, confirmed over several scans, mapped through the
calibration homography and debounced.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

from .geometry import apply_homography, polar_to_xy


@dataclass
class ScanPoint:
    angle_deg: float
    dist_mm: float
    quality: int = 0


@dataclass
class Scan:
    points: list[ScanPoint]
    ts: float


@dataclass
class ProcessorConfig:
    min_dist_mm: float = 80.0
    max_dist_mm: float = 6000.0
    angle_min: float = 0.0          # degrees, inclusive window (may wrap: min > max)
    angle_max: float = 360.0
    min_quality: int = 0
    # raw-plane zone (used until a calibration exists, and as an extra limit afterwards)
    zone: dict | None = None        # {"x_min","x_max","y_min","y_max"} in mm
    uv_margin: float = 0.03         # tolerance outside the calibrated screen rectangle
    # clustering
    cluster_gap_mm: float = 80.0
    min_cluster_points: int = 2
    max_cluster_width_mm: float = 220.0   # rejects forearms/bodies
    # tracking
    confirm_scans: int = 2
    release_scans: int = 3
    track_radius_mm: float = 150.0
    debounce_ms: int = 500
    # background subtraction (learnt with the screen clear)
    use_background: bool = False
    background_tolerance_mm: float = 40.0

    @classmethod
    def from_dict(cls, d: dict | None) -> "ProcessorConfig":
        d = d or {}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Cluster:
    x_mm: float
    y_mm: float
    n: int
    width_mm: float
    u: float | None = None
    v: float | None = None


@dataclass
class TouchEvent:
    x_mm: float
    y_mm: float
    u: float | None
    v: float | None
    n_points: int
    width_mm: float
    ts: float
    source: str = "lidar"

    def to_dict(self):
        return asdict(self)


@dataclass
class ProcessResult:
    candidates: list[Cluster] = field(default_factory=list)
    events: list[TouchEvent] = field(default_factory=list)
    n_points: int = 0
    n_foreground: int = 0


def _in_angle_window(a: float, lo: float, hi: float) -> bool:
    a %= 360.0
    if lo <= hi:
        return lo <= a <= hi
    return a >= lo or a <= hi


class TouchProcessor:
    def __init__(self, cfg: ProcessorConfig | None = None, homography=None, background=None):
        self.cfg = cfg or ProcessorConfig()
        self.H = homography
        self.background: dict[int, float] | None = background  # 1-degree bins
        self._reset_tracking()
        self._last_emit_ts = -1e9

    # --- configuration -----------------------------------------------------------------
    def set_homography(self, H):
        self.H = H

    def set_background(self, bins):
        self.background = {int(k): float(v) for k, v in bins.items()} if bins else None

    def _reset_tracking(self):
        self._pending: list[Cluster] = []
        self._held = False
        self._missing = 0

    @staticmethod
    def learn_background(scans: list[Scan]) -> dict[int, float]:
        """Per 1-degree bin median distance over several scans taken with the interaction area clear."""
        per: dict[int, list[float]] = {}
        for sc in scans:
            for p in sc.points:
                if p.dist_mm > 0:
                    per.setdefault(int(p.angle_deg % 360), []).append(p.dist_mm)
        out = {}
        for b, vals in per.items():
            vals.sort()
            out[b] = vals[len(vals) // 2]
        return out

    # --- per-scan pipeline -------------------------------------------------------------
    def _foreground_points(self, scan: Scan):
        cfg = self.cfg
        pts = []
        for p in scan.points:
            if p.dist_mm < cfg.min_dist_mm or p.dist_mm > cfg.max_dist_mm or p.quality < cfg.min_quality:
                continue
            if not _in_angle_window(p.angle_deg, cfg.angle_min, cfg.angle_max):
                continue
            if cfg.use_background and self.background:
                bg = self.background.get(int(p.angle_deg % 360))
                if bg is not None and p.dist_mm >= bg - cfg.background_tolerance_mm:
                    continue
            x, y = polar_to_xy(p.angle_deg, p.dist_mm)
            z = cfg.zone
            if z and not (z["x_min"] <= x <= z["x_max"] and z["y_min"] <= y <= z["y_max"]):
                continue
            u = v = None
            if self.H is not None:
                u, v = apply_homography(self.H, x, y)
                m = cfg.uv_margin
                if not (-m <= u <= 1 + m and -m <= v <= 1 + m):
                    continue
            pts.append((p.angle_deg % 360, x, y, u, v))
        pts.sort(key=lambda t: t[0])
        return pts

    def _cluster(self, pts) -> list[Cluster]:
        cfg = self.cfg
        groups: list[list] = []
        for pt in pts:
            if groups:
                last = groups[-1][-1]
                if math.hypot(pt[1] - last[1], pt[2] - last[2]) <= cfg.cluster_gap_mm:
                    groups[-1].append(pt)
                    continue
            groups.append([pt])
        out = []
        for g in groups:
            if len(g) < cfg.min_cluster_points:
                continue
            xs = [p[1] for p in g]
            ys = [p[2] for p in g]
            width = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            if width > cfg.max_cluster_width_mm:
                continue
            c = Cluster(x_mm=sum(xs) / len(xs), y_mm=sum(ys) / len(ys), n=len(g), width_mm=width)
            if self.H is not None:
                c.u, c.v = apply_homography(self.H, c.x_mm, c.y_mm)
            out.append(c)
        return out

    def process(self, scan: Scan) -> ProcessResult:
        cfg = self.cfg
        pts = self._foreground_points(scan)
        clusters = self._cluster(pts)
        res = ProcessResult(candidates=clusters, n_points=len(scan.points), n_foreground=len(pts))
        best = max(clusters, key=lambda c: c.n) if clusters else None

        if best is None:
            self._pending.clear()
            if self._held:
                self._missing += 1
                if self._missing >= cfg.release_scans:
                    self._held = False
                    self._missing = 0
            return res

        self._missing = 0
        if self._held:
            return res  # finger still down: no duplicate events

        if self._pending:
            last = self._pending[-1]
            if math.hypot(best.x_mm - last.x_mm, best.y_mm - last.y_mm) > cfg.track_radius_mm:
                self._pending.clear()
        self._pending.append(best)
        if len(self._pending) >= cfg.confirm_scans:
            xs = [c.x_mm for c in self._pending]
            ys = [c.y_mm for c in self._pending]
            x, y = sum(xs) / len(xs), sum(ys) / len(ys)
            n = max(c.n for c in self._pending)
            w = max(c.width_mm for c in self._pending)
            self._pending.clear()
            self._held = True
            if (scan.ts - self._last_emit_ts) * 1000 < cfg.debounce_ms:
                return res
            u = v = None
            if self.H is not None:
                u, v = apply_homography(self.H, x, y)
            self._last_emit_ts = scan.ts
            res.events.append(TouchEvent(x_mm=x, y_mm=y, u=u, v=v, n_points=n, width_mm=w, ts=scan.ts))
        return res
