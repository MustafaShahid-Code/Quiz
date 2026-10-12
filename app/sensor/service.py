"""Background sensor service: owns the scan source, runs the processing pipeline, publishes events and health.

A sensor failure never propagates: errors are recorded in the status, the source is closed and re-opened
with exponential back-off while the game keeps working with mouse/touch input.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Callable

import numpy as np

from .geometry import polar_to_xy
from .processing import ProcessorConfig, Scan, TouchProcessor
from .sources import ScanSource, SensorError, SimulatedScanSource, build_source

STALE_AFTER_S = 2.5


class SensorService:
    def __init__(self, load_config: Callable[[], dict], publish: Callable[[dict], None],
                 publish_diag: Callable[[dict], None] | None = None,
                 diag_subscribers: Callable[[], int] | None = None,
                 source_factory: Callable[[str, dict], ScanSource | None] = build_source,
                 backoff_max_s: float = 10.0):
        self._load_config = load_config
        self._publish = publish
        self._publish_diag = publish_diag
        self._diag_subscribers = diag_subscribers or (lambda: 0)
        self._source_factory = source_factory
        self._backoff_max = backoff_max_s

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self.source: ScanSource | None = None
        self.proc = TouchProcessor()
        self.cfg: dict = {}

        self.state = "disabled"          # disabled | connecting | ok | stale | error
        self.last_error: str | None = None
        self.last_scan_mono = 0.0
        self.scan_hz = 0.0
        self.scans_total = 0
        self.touches_total = 0
        self.reconnects = 0
        self._last_diag = 0.0
        self._last_state_published = None

        self._capture: dict | None = None      # {"event": Event, "result": (x,y)|None}
        self._learn: dict | None = None        # {"scans": [], "n": int, "event": Event}

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._apply_config()
            self._thread = threading.Thread(target=self._run, name="sensor-service", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        src = self.source
        if src is not None:
            try:
                src.close()
            except Exception:
                pass
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=4)
        self._thread = None
        self._set_state("disabled")

    def reload(self):
        """Apply new config (source type, thresholds, calibration)."""
        self.stop()
        self.start()

    def _apply_config(self):
        try:
            self.cfg = self._load_config() or {}
        except Exception as e:  # corrupt config must not stop the app
            self.cfg = {}
            self.last_error = f"bad sensor config: {e}"
        thr = ProcessorConfig.from_dict(self.cfg.get("thresholds"))
        cal = self.cfg.get("calibration") or {}
        H = np.array(cal["homography"]) if cal.get("homography") else None
        bg = cal.get("background")
        thr.use_background = bool(bg) and bool(self.cfg.get("thresholds", {}).get("use_background", True))
        self.proc = TouchProcessor(thr, homography=H, background=bg)

    # ------------------------------------------------------------------ status
    @property
    def source_type(self) -> str:
        return self.cfg.get("source_type", "none")

    @property
    def is_simulated(self) -> bool:
        s = self.source
        return s is None or not s.is_real_hardware

    @property
    def calibrated(self) -> bool:
        return self.proc.H is not None

    @property
    def validated(self) -> bool:
        v = self.cfg.get("validation") or {}
        return bool(v.get("passed")) and self.calibrated and not self.is_simulated

    def current_state(self) -> str:
        if self.state == "ok" and time.monotonic() - self.last_scan_mono > STALE_AFTER_S:
            return "stale"
        return self.state

    def status(self) -> dict:
        age = (time.monotonic() - self.last_scan_mono) if self.last_scan_mono else None
        return {
            "state": self.current_state(),
            "source_type": self.source_type,
            "source": "simulated" if self.is_simulated else "lidar",
            "sensor_model": self.cfg.get("sensor_model"),
            "calibrated": self.calibrated,
            "validated": self.validated,
            "last_scan_age_s": None if age is None else round(age, 2),
            "scan_hz": round(self.scan_hz, 1),
            "scans_total": self.scans_total,
            "touches_total": self.touches_total,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
        }

    def _set_state(self, state: str, error: str | None = None):
        self.state = state
        if error is not None:
            self.last_error = error
        elif state == "ok":
            self.last_error = None
        if state != self._last_state_published:
            self._last_state_published = state
            self._safe_publish({"type": "status", **self.status()})

    def _safe_publish(self, msg: dict):
        try:
            self._publish(msg)
        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------------ development / calibration helpers
    def inject_simulated_touch(self, u: float, v: float) -> bool:
        src = self.source
        if isinstance(src, SimulatedScanSource):
            src.inject_touch(u, v)
            return True
        return False

    def capture_raw_touch(self, timeout: float = 20.0):
        """Wait for the next confirmed touch and return its raw sensor-plane position (x_mm, y_mm)."""
        with self._lock:
            if self._capture is not None:
                raise SensorError("another capture is already running")
            if self.current_state() != "ok":
                raise SensorError("sensor is not delivering scans (state: %s)" % self.current_state())
            cap = {"event": threading.Event(), "result": None, "saved_H": self.proc.H}
            self._capture = cap
            self.proc.H = None
            self.proc._reset_tracking()
        try:
            if not cap["event"].wait(timeout):
                raise SensorError("no touch detected within %.0f s" % timeout)
            return cap["result"]
        finally:
            with self._lock:
                self.proc.H = cap["saved_H"]
                self.proc._reset_tracking()
                self._capture = None

    def learn_background(self, n_scans: int = 20, timeout: float = 20.0) -> dict:
        with self._lock:
            if self._learn is not None:
                raise SensorError("background learning already running")
            if self.current_state() != "ok":
                raise SensorError("sensor is not delivering scans (state: %s)" % self.current_state())
            ln = {"scans": [], "n": n_scans, "event": threading.Event()}
            self._learn = ln
        try:
            if not ln["event"].wait(timeout):
                raise SensorError("timed out while collecting background scans")
            return TouchProcessor.learn_background(ln["scans"])
        finally:
            self._learn = None

    # ------------------------------------------------------------------ main loop
    def _run(self):
        backoff = 1.0
        while not self._stop.is_set():
            src = None
            try:
                src = self._source_factory(self.cfg.get("source_type", "none"), self.cfg.get("params") or {})
                if src is None:
                    self._set_state("disabled")
                    self._stop.wait(0.5)
                    continue
                self.source = src
                self._set_state("connecting")
                src.open()
                self._set_state("ok")
                backoff = 1.0
                last = None
                for scan in src.scans():
                    if self._stop.is_set():
                        break
                    self._handle_scan(scan, last)
                    last = scan.ts
                    if self.state != "ok":
                        self._set_state("ok")
                if not self._stop.is_set():
                    raise SensorError("scan stream ended")
            except Exception as e:  # noqa: BLE001 - the service must survive anything a driver throws
                if self._stop.is_set():
                    break
                self.reconnects += 1
                self._set_state("error", f"{type(e).__name__}: {e}")
            finally:
                if src is not None:
                    try:
                        src.close()
                    except Exception:
                        pass
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, self._backoff_max)

    def _handle_scan(self, scan: Scan, last_ts):
        now = time.monotonic()
        if self.last_scan_mono:
            dt = now - self.last_scan_mono
            if dt > 0:
                inst = 1.0 / dt
                self.scan_hz = inst if self.scan_hz == 0 else 0.8 * self.scan_hz + 0.2 * inst
        self.last_scan_mono = now
        self.scans_total += 1

        ln = self._learn
        if ln is not None:
            ln["scans"].append(scan)
            if len(ln["scans"]) >= ln["n"]:
                ln["event"].set()
            return

        res = self.proc.process(scan)
        cap = self._capture
        for ev in res.events:
            if cap is not None:
                if cap["result"] is None:
                    cap["result"] = (ev.x_mm, ev.y_mm)
                    cap["event"].set()
                continue  # never leak calibration touches to the game
            if ev.u is None:
                continue  # uncalibrated: a raw cluster is not a screen touch
            self.touches_total += 1
            msg = ev.to_dict()
            msg.update({"type": "touch", "source": "simulated" if self.is_simulated else "lidar",
                        "validated": self.validated})
            self._safe_publish(msg)

        if self._publish_diag and (now - self._last_diag) >= 0.1 and self._diag_subscribers() > 0:
            self._last_diag = now
            maxd = self.proc.cfg.max_dist_mm
            step = max(1, len(scan.points) // 600)
            pts = []
            for p in scan.points[::step]:
                if self.proc.cfg.min_dist_mm <= p.dist_mm <= maxd:
                    x, y = polar_to_xy(p.angle_deg, p.dist_mm)
                    pts.append([round(x), round(y)])
            try:
                self._publish_diag({
                    "type": "scan", "points": pts, "hz": round(self.scan_hz, 1),
                    "candidates": [{"x": c.x_mm, "y": c.y_mm, "n": c.n, "w": c.width_mm, "u": c.u, "v": c.v}
                                   for c in res.candidates],
                    "events": [e.to_dict() for e in res.events],
                })
            except Exception:
                traceback.print_exc()
