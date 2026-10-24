import random
import threading
import time

import numpy as np
import pytest

from app.sensor.geometry import CalibrationError, apply_homography, compute_homography, reprojection_error
from app.sensor.processing import ProcessorConfig, TouchProcessor
from app.sensor.service import SensorService
from app.sensor.sources import ScanSource, SensorError, SimulatedScanSource


def feed_touch(src, proc, u, v):
    """Inject a finger, run enough scans to confirm it, then lift and flush; return emitted events."""
    src.inject_touch(u, v, duration_s=60)
    t = 0.0
    events = []
    for _ in range(4):
        t += 0.1
        events += proc.process(src._scan_once(time.monotonic())).events
    src._fingers.clear()
    for _ in range(6):
        proc.process(src._scan_once(time.monotonic()))
    return events


def calibrated_pipeline():
    src = SimulatedScanSource(realtime=False, seed=1)
    cfg = ProcessorConfig(debounce_ms=0)
    proc = TouchProcessor(cfg)
    pts = []
    for u, v in [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9), (0.5, 0.5)]:
        ev = feed_touch(src, proc, u, v)
        assert ev, "raw touch should be reported even when uncalibrated"
        pts.append(((ev[0].x_mm, ev[0].y_mm), (u, v)))
    H = compute_homography([p[0] for p in pts], [p[1] for p in pts])
    proc.set_homography(H)
    return src, proc, H, pts


def test_homography_roundtrip_and_error_metrics():
    src = [(0, 0), (1000, 0), (1000, 500), (0, 500), (500, 250)]
    dst = [(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5)]
    H = compute_homography(src, dst)
    assert reprojection_error(H, src, dst)["rmse"] < 1e-6
    u, v = apply_homography(H, 250, 125)
    assert abs(u - 0.25) < 1e-6 and abs(v - 0.25) < 1e-6


def test_degenerate_calibration_rejected():
    with pytest.raises(CalibrationError):
        compute_homography([(0, 0), (1, 1), (2, 2), (3, 3)], [(0, 0), (1, 0), (1, 1), (0, 1)])


def test_touch_accuracy_after_calibration():
    src, proc, H, _ = calibrated_pipeline()
    rng = random.Random(3)
    errs = []
    for _ in range(12):
        u, v = rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9)
        ev = [e for e in feed_touch(src, proc, u, v) if e.u is not None]
        assert ev, "touch not detected"
        errs.append(np.hypot(ev[0].u - u, ev[0].v - v))
    assert np.mean(errs) < 0.02 and max(errs) < 0.05


def test_large_object_is_rejected():
    src = SimulatedScanSource(realtime=False, seed=2)
    proc = TouchProcessor(ProcessorConfig(debounce_ms=0))
    src.inject_plane_object(0, 1200, 250, duration_s=60)  # a forearm / body, not a finger
    events = []
    for _ in range(5):
        events += proc.process(src._scan_once(time.monotonic())).events
    assert events == []


def test_nothing_reported_without_touch():
    src = SimulatedScanSource(realtime=False, seed=4)
    proc = TouchProcessor(ProcessorConfig())
    events = []
    for _ in range(10):
        events += proc.process(src._scan_once(time.monotonic())).events
    assert events == []


class FlakySource(ScanSource):
    """Fails on the first two opens, then streams empty scans."""
    attempts = 0
    is_real_hardware = True

    def open(self):
        FlakySource.attempts += 1
        if FlakySource.attempts <= 2:
            raise SensorError("device unplugged")

    def scans(self):
        from app.sensor.processing import Scan
        while True:
            time.sleep(0.02)
            yield Scan([], time.monotonic())


def test_service_survives_driver_failure_and_reconnects():
    FlakySource.attempts = 0
    svc = SensorService(lambda: {"source_type": "serial", "params": {}, "thresholds": {}, "calibration": {}},
                        publish=lambda m: None, source_factory=lambda t, p: FlakySource(), backoff_max_s=0.1)
    svc._source_factory = lambda t, p: FlakySource()
    svc.start()
    try:
        deadline = time.time() + 8
        while time.time() < deadline and svc.current_state() != "ok":
            time.sleep(0.05)
        assert svc.current_state() == "ok"
        assert svc.reconnects >= 2
        assert not svc.calibrated and not svc.validated  # real hardware but never calibrated/validated
    finally:
        svc.stop()


def test_service_error_state_visible_and_no_crash():
    class Dead(ScanSource):
        def open(self):
            raise OSError("no such device")

    svc = SensorService(lambda: {"source_type": "serial", "params": {}, "thresholds": {}, "calibration": {}},
                        publish=lambda m: None, source_factory=lambda t, p: Dead(), backoff_max_s=0.1)
    svc.start()
    try:
        time.sleep(0.5)
        st = svc.status()
        assert st["state"] == "error" and "no such device" in st["last_error"]
    finally:
        svc.stop()


def test_simulated_source_never_marked_validated():
    cfg = {"source_type": "simulator", "params": {}, "thresholds": {}, "calibration": {},
           "validation": {"passed": True}}
    svc = SensorService(lambda: cfg, publish=lambda m: None)
    svc.start()
    try:
        time.sleep(0.3)
        assert svc.is_simulated and svc.validated is False
    finally:
        svc.stop()


# ----------------------------------------------------------------- API level
def test_sensor_api_status_and_validation_rules(client, admin):
    st = client.get("/api/admin/sensor/status", headers=admin).json()
    assert st["state"] == "disabled" or st["state"] in ("ok", "connecting", "error")
    trials = [{"target": [0.5, 0.5], "hit": [0.5, 0.5], "latency_ms": 100} for _ in range(5)]
    r = client.post("/api/admin/sensor/validation", headers=admin, json={"trials": trials}).json()
    assert r["passed"] is True and r["validated_hardware"] is False  # not real hardware
    bad = [{"target": [0.5, 0.5], "hit": [0.8, 0.8], "latency_ms": 100} for _ in range(5)]
    assert client.post("/api/admin/sensor/validation", headers=admin, json={"trials": bad}).json()["passed"] is False
    missed = [{"target": [0.5, 0.5], "hit": None} for _ in range(5)]
    assert client.post("/api/admin/sensor/validation", headers=admin, json={"trials": missed}).json()["passed"] is False


def test_calibration_api_rejects_garbage(client, admin):
    pts = [{"target": [0, 0], "raw": [0, 0]}, {"target": [1, 0], "raw": [1, 1]}, {"target": [1, 1], "raw": [2, 2]}, {"target": [0, 1], "raw": [3, 3]}]
    assert client.post("/api/admin/sensor/calibration", headers=admin, json={"points": pts}).status_code == 422


def test_subprocess_source_blocked_in_production(client, admin, monkeypatch):
    from app import config
    config.configure(data_dir=config.data_dir(), env="production")
    monkeypatch.delenv("FQ_ALLOW_SUBPROCESS_SOURCE", raising=False)
    r = client.put("/api/admin/sensor/config", headers=admin, json={"source_type": "subprocess"})
    assert r.status_code == 403


def test_simulate_touch_requires_simulator(client, admin):
    assert client.post("/api/admin/sensor/simulate-touch", headers=admin, json={"u": 0.5, "v": 0.5}).status_code == 409


def test_pose_endpoint_requires_key(client):
    assert client.post("/api/input/pose", json={"label": "x"}).status_code in (401, 403)
    assert client.post("/api/input/pose", json={"label": "x"}, headers={"x-input-key": "wrong"}).status_code in (401, 403)


def test_game_works_with_sensor_failed(client):
    assert client.get("/health").status_code == 200
    assert client.post("/api/game/sessions", json={"lang": "en"}).status_code == 201
