"""Scan sources. Every source yields `Scan` objects; the rest of the system never knows which one is used.

 * SimulatedScanSource  - synthetic room + virtual finger, drives the REAL processing pipeline (development)
 * ReplayScanSource     - replays a JSON-lines recording (regression tests, offline tuning)
 * SubprocessScanSource - runs any command that prints JSON-lines scans (recommended bridge to the official
                          Slamtec SDK, see docs/SENSOR.md)
 * SerialRplidarSource  - optional pure-Python driver (`rplidar-roboticia`); written for the A-series
                          protocol, NOT verified against S2/S3 hardware.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import threading
import time
from typing import Iterator

from .processing import Scan, ScanPoint


class SensorError(RuntimeError):
    pass


class ScanSource:
    name = "base"
    is_real_hardware = False

    def open(self):  # pragma: no cover - interface
        pass

    def close(self):  # pragma: no cover - interface
        pass

    def scans(self) -> Iterator[Scan]:  # pragma: no cover - interface
        raise NotImplementedError


# ----------------------------------------------------------------------------------------------
class VirtualGeometry:
    """Where the virtual projection screen sits in the simulated sensor plane. Deliberately rotated and
    offset so that calibration is a real (non-trivial) step."""

    def __init__(self, width_mm=1600.0, height_mm=900.0, origin=(-700.0, 900.0), rotation_deg=7.0):
        self.w, self.h, self.origin, self.rot = width_mm, height_mm, origin, math.radians(rotation_deg)

    def screen_to_plane(self, u: float, v: float) -> tuple[float, float]:
        x = u * self.w
        y = (1 - v) * self.h  # screen v grows downwards, sensor y grows upwards
        c, s = math.cos(self.rot), math.sin(self.rot)
        return self.origin[0] + x * c - y * s, self.origin[1] + x * s + y * c


class SimulatedScanSource(ScanSource):
    name = "simulator"
    is_real_hardware = False

    def __init__(self, rate_hz=10.0, step_deg=0.36, realtime=True, noise_mm=4.0, geometry: VirtualGeometry | None = None,
                 finger_radius_mm=18.0, seed=None):
        self.rate_hz, self.step, self.realtime, self.noise = rate_hz, step_deg, realtime, noise_mm
        self.geo = geometry or VirtualGeometry()
        self.finger_r = finger_radius_mm
        self._fingers: list[tuple[float, float, float]] = []  # (x, y, until_ts)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._rng = random.Random(seed)
        self._t = 0.0

    def open(self):
        self._stop.clear()

    def close(self):
        self._stop.set()

    def inject_touch(self, u: float, v: float, duration_s: float = 0.45):
        x, y = self.geo.screen_to_plane(u, v)
        with self._lock:
            self._fingers.append((x, y, time.monotonic() + duration_s))
        return x, y

    def inject_plane_object(self, x: float, y: float, radius_mm: float, duration_s: float = 0.45):
        """Large objects (arm, body) for rejection tests."""
        with self._lock:
            self._fingers.append((x, y, time.monotonic() + duration_s, radius_mm))

    @staticmethod
    def _room_distance(angle_deg: float) -> float:
        # a rectangular room, sensor roughly in the middle: walls 3.5 m left/right, 4.5 m front/back
        a = math.radians(angle_deg)
        dx, dy = math.sin(a), math.cos(a)
        tx = (3500 / abs(dx)) if abs(dx) > 1e-6 else 1e9
        ty = (4500 / abs(dy)) if abs(dy) > 1e-6 else 1e9
        return min(tx, ty)

    def _scan_once(self, now: float) -> Scan:
        with self._lock:
            self._fingers = [f for f in self._fingers if f[2] > now]
            fingers = list(self._fingers)
        pts = []
        n = int(360 / self.step)
        for i in range(n):
            ang = i * self.step
            d = self._room_distance(ang) + self._rng.gauss(0, self.noise)
            a = math.radians(ang)
            for f in fingers:
                fx, fy = f[0], f[1]
                r = f[3] if len(f) > 3 else self.finger_r
                # ray/circle intersection
                dx, dy = math.sin(a), math.cos(a)
                b = fx * dx + fy * dy
                c = fx * fx + fy * fy - r * r
                disc = b * b - c
                if disc >= 0 and b > 0:
                    t = b - math.sqrt(disc)
                    if 0 < t < d:
                        d = t + self._rng.gauss(0, self.noise / 2)
            pts.append(ScanPoint(ang, d, 47))
        return Scan(pts, now)

    def scans(self):
        period = 1.0 / self.rate_hz
        while not self._stop.is_set():
            t0 = time.monotonic()
            yield self._scan_once(t0)
            if self.realtime:
                dt = period - (time.monotonic() - t0)
                if dt > 0:
                    self._stop.wait(dt)


# ----------------------------------------------------------------------------------------------
def _scan_from_json(obj: dict) -> Scan:
    pts = [ScanPoint(float(p[0]), float(p[1]), int(p[2]) if len(p) > 2 else 0) for p in obj["points"]]
    return Scan(pts, float(obj.get("ts", time.monotonic())))


class ReplayScanSource(ScanSource):
    name = "replay"

    def __init__(self, path: str, loop=False, realtime=False, rate_hz=10.0):
        self.path, self.loop, self.realtime, self.rate_hz = path, loop, realtime, rate_hz
        self._stop = threading.Event()

    def close(self):
        self._stop.set()

    def scans(self):
        while not self._stop.is_set():
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        if self._stop.is_set():
                            return
                        line = line.strip()
                        if line:
                            yield _scan_from_json(json.loads(line))
                            if self.realtime:
                                time.sleep(1 / self.rate_hz)
            except OSError as e:
                raise SensorError(f"cannot read replay file: {e}")
            if not self.loop:
                return


class SubprocessScanSource(ScanSource):
    """Runs a command that prints one JSON object per line: {"ts": 12.3, "points": [[angle_deg, dist_mm, quality], ...]}
    This is the documented integration interface for the official Slamtec SDK (C++) or any other driver."""
    name = "subprocess"
    is_real_hardware = True

    def __init__(self, command: list[str] | str, startup_timeout_s=8.0):
        if isinstance(command, str):
            import shlex
            command = shlex.split(command)
        if not command:
            raise SensorError("no command configured for the subprocess source")
        self.command, self.startup_timeout_s = command, startup_timeout_s
        self._proc: subprocess.Popen | None = None

    def open(self):
        try:
            self._proc = subprocess.Popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          text=True, bufsize=1)
        except OSError as e:
            raise SensorError(f"cannot start sensor command: {e}")

    def close(self):
        p, self._proc = self._proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()

    def scans(self):
        p = self._proc
        if p is None or p.stdout is None:
            raise SensorError("source not open")
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                yield _scan_from_json(json.loads(line))
            except (ValueError, KeyError, IndexError, TypeError):
                continue  # ignore a corrupt line, keep going
        raise SensorError("sensor command ended (exit code %s)" % p.poll())


class SerialRplidarSource(ScanSource):
    name = "serial"
    is_real_hardware = True

    def __init__(self, port: str, baudrate: int = 1_000_000, timeout=3):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self._lidar = None

    def open(self):
        try:
            from rplidar import RPLidar  # type: ignore
        except ImportError as e:
            raise SensorError("python package 'rplidar-roboticia' is not installed (pip install rplidar-roboticia)") from e
        try:
            self._lidar = RPLidar(self.port, baudrate=self.baudrate, timeout=self.timeout)
            self._lidar.get_info()
        except Exception as e:
            self._lidar = None
            raise SensorError(f"cannot open RPLIDAR on {self.port}: {e}") from e

    def close(self):
        lid, self._lidar = self._lidar, None
        if lid is not None:
            for fn in (lid.stop, lid.stop_motor, lid.disconnect):
                try:
                    fn()
                except Exception:
                    pass

    def scans(self):
        if self._lidar is None:
            raise SensorError("source not open")
        try:
            for scan in self._lidar.iter_scans(max_buf_meas=6000):
                yield Scan([ScanPoint(a, d, q) for (q, a, d) in scan], time.monotonic())
        except Exception as e:
            raise SensorError(f"RPLIDAR read failed: {e}") from e


def build_source(source_type: str, params: dict) -> ScanSource | None:
    params = params or {}
    if source_type in (None, "", "none"):
        return None
    if source_type == "simulator":
        return SimulatedScanSource(rate_hz=float(params.get("rate_hz", 10)))
    if source_type == "serial":
        return SerialRplidarSource(params.get("port", "/dev/ttyUSB0"), int(params.get("baudrate", 1_000_000)))
    if source_type == "subprocess":
        return SubprocessScanSource(params.get("command", ""))
    if source_type == "replay":
        return ReplayScanSource(params.get("path", ""), loop=bool(params.get("loop", True)),
                                realtime=True, rate_hz=float(params.get("rate_hz", 10)))
    raise SensorError(f"unknown source type {source_type!r}")
