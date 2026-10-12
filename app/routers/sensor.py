"""Sensor configuration, calibration, validation and diagnostics (admin)."""
import json
import math
import os
import secrets

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from .. import config, security
from ..db import connect, get_db, now_iso
from ..schemas import CalibrationIn, SensorConfigIn, SimTouchIn, ValidationIn
from ..security import require_admin, require_editor, require_viewer
from ..sensor.geometry import CalibrationError, apply_homography, compute_homography, reprojection_error
from ..sensor.processing import ProcessorConfig
from ..sensor.sources import SensorError

router = APIRouter(prefix="/api/admin/sensor", tags=["sensor"])

CALIBRATION_WARN_RMSE = 0.015   # 1.5 % of the screen
CALIBRATION_MAX_RMSE = 0.06
VALIDATION_LIMITS = {"detection_rate": 0.90, "mean_error": 0.03, "p95_error": 0.06, "mean_latency_ms": 700}


def active_config_row(conn):
    row = conn.execute("SELECT * FROM sensor_configs WHERE active=1 ORDER BY id LIMIT 1").fetchone()
    if not row:
        ts = now_iso()
        default = "simulator" if config.is_dev() else "none"
        params = {"port": "/dev/ttyUSB0", "baudrate": 1000000, "command": "", "path": "", "input_key": secrets.token_urlsafe(24)}
        cur = conn.execute("INSERT INTO sensor_configs(name,active,sensor_model,source_type,params,thresholds,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                           ("Default", 1, "S2", default, json.dumps(params), json.dumps(ProcessorConfig().__dict__), ts, ts))
        row = conn.execute("SELECT * FROM sensor_configs WHERE id=?", (cur.lastrowid,)).fetchone()
    return row


def load_service_config() -> dict:
    conn = connect()
    try:
        r = active_config_row(conn)
        return {"id": r["id"], "sensor_model": r["sensor_model"], "source_type": r["source_type"],
                "params": json.loads(r["params"] or "{}"), "thresholds": json.loads(r["thresholds"] or "{}"),
                "calibration": json.loads(r["calibration"] or "{}"), "validation": json.loads(r["validation"] or "{}")}
    finally:
        conn.close()


def _row_dict(r, admin=False):
    params = json.loads(r["params"] or "{}")
    if not admin:
        params.pop("input_key", None)
    cal = json.loads(r["calibration"] or "{}")
    return {"id": r["id"], "name": r["name"], "sensor_model": r["sensor_model"], "source_type": r["source_type"],
            "params": params, "thresholds": {**ProcessorConfig().__dict__, **json.loads(r["thresholds"] or "{}")},
            "calibration": {k: v for k, v in cal.items() if k != "background"},
            "has_background": bool(cal.get("background")), "validation": json.loads(r["validation"] or "{}"),
            "updated_at": r["updated_at"]}


def _svc(request: Request):
    return request.app.state.sensor


def _save(conn, rid, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    conn.execute(f"UPDATE sensor_configs SET {sets}, updated_at=? WHERE id=?", [*cols.values(), now_iso(), rid])


@router.get("/status")
def status(request: Request, _=Depends(require_viewer), conn=Depends(get_db)):
    svc = _svc(request)
    r = active_config_row(conn)
    cal = json.loads(r["calibration"] or "{}")
    quad = None
    if cal.get("homography"):
        Hinv = np.linalg.inv(np.array(cal["homography"]))
        quad = [list(apply_homography(Hinv, u, v)) for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
    return {**svc.status(), "screen_quad_mm": quad, "calibration_rmse": cal.get("rmse"),
            "hardware_note": None if svc.source_type in ("serial", "subprocess") else
            "Not using real hardware: touches are simulated or the sensor is disabled."}


@router.get("/config")
def get_config(user=Depends(require_viewer), conn=Depends(get_db)):
    d = _row_dict(active_config_row(conn), admin=user["role"] == "admin")
    d["subprocess_allowed"] = subprocess_allowed()
    d["validation_limits"] = VALIDATION_LIMITS
    return d


def subprocess_allowed() -> bool:
    return config.is_dev() or os.environ.get("FQ_ALLOW_SUBPROCESS_SOURCE") == "1"


@router.put("/config")
def put_config(body: SensorConfigIn, request: Request, _=Depends(require_admin), conn=Depends(get_db)):
    r = active_config_row(conn)
    cols = {}
    if body.name is not None:
        cols["name"] = body.name
    if body.sensor_model is not None:
        cols["sensor_model"] = body.sensor_model
    if body.source_type is not None:
        if body.source_type == "subprocess" and not subprocess_allowed():
            raise HTTPException(403, "The subprocess source runs a program on this machine. Enable it by starting the server with FQ_ALLOW_SUBPROCESS_SOURCE=1.")
        cols["source_type"] = body.source_type
    if body.params is not None:
        old = json.loads(r["params"] or "{}")
        p = {**old, **{k: v for k, v in body.params.items() if k != "input_key"}}
        if not isinstance(p.get("baudrate", 0), int) or p.get("baudrate", 0) < 0:
            raise HTTPException(422, "baudrate must be a whole number")
        for k in ("port", "command", "path"):
            if k in p and (not isinstance(p[k], str) or len(p[k]) > 500):
                raise HTTPException(422, f"{k} must be text")
        cols["params"] = json.dumps(p)
    if body.thresholds is not None:
        base = ProcessorConfig().__dict__
        th = {**json.loads(r["thresholds"] or "{}")}
        for k, v in body.thresholds.items():
            if k not in base:
                raise HTTPException(422, f"Unknown threshold {k!r}")
            if k == "zone":
                if v is not None and (not isinstance(v, dict) or set(v) != {"x_min", "x_max", "y_min", "y_max"}
                                      or any(not isinstance(x, (int, float)) for x in v.values())):
                    raise HTTPException(422, "zone needs x_min, x_max, y_min, y_max (mm)")
            elif isinstance(base[k], bool):
                if not isinstance(v, bool):
                    raise HTTPException(422, f"{k} must be true or false")
            elif not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                raise HTTPException(422, f"{k} must be a non-negative number")
            th[k] = v
        if th.get("confirm_scans", 2) < 1 or th.get("min_cluster_points", 2) < 1:
            raise HTTPException(422, "confirm_scans and min_cluster_points must be at least 1")
        cols["thresholds"] = json.dumps(th)
    if cols:
        # a changed source/thresholds invalidates earlier hardware validation
        if {"source_type", "thresholds"} & set(cols) or "sensor_model" in cols:
            cols["validation"] = "{}"
        _save(conn, r["id"], **cols)
        _svc(request).reload()
    return _row_dict(active_config_row(conn), admin=True)


@router.post("/restart")
def restart(request: Request, _=Depends(require_admin)):
    _svc(request).reload()
    return {"ok": True}


@router.post("/input-key/rotate")
def rotate_input_key(_=Depends(require_admin), conn=Depends(get_db)):
    r = active_config_row(conn)
    p = json.loads(r["params"] or "{}")
    p["input_key"] = secrets.token_urlsafe(24)
    _save(conn, r["id"], params=json.dumps(p))
    return {"input_key": p["input_key"]}


# ------------------------------------------------------------------ calibration
@router.post("/calibration/capture")
def capture(request: Request, _=Depends(require_admin)):
    """Blocks until the next confirmed touch; returns its raw sensor-plane position."""
    try:
        x, y = _svc(request).capture_raw_touch(timeout=25)
    except SensorError as e:
        raise HTTPException(409, str(e))
    return {"x_mm": x, "y_mm": y}


@router.post("/calibration")
def save_calibration(body: CalibrationIn, request: Request, _=Depends(require_admin), conn=Depends(get_db)):
    src = [p.raw for p in body.points]
    dst = [p.target for p in body.points]
    try:
        H = compute_homography(src, dst)
    except CalibrationError as e:
        raise HTTPException(422, str(e))
    err = reprojection_error(H, src, dst)
    if err["rmse"] > CALIBRATION_MAX_RMSE:
        raise HTTPException(422, f"Calibration error is too large ({err['rmse'] * 100:.1f}% of the screen). Check that each target was touched accurately and repeat.")
    r = active_config_row(conn)
    cal = json.loads(r["calibration"] or "{}")
    cal.update({"homography": H.tolist(), "points": [{"target": list(t), "raw": list(s)} for s, t in zip(src, dst)],
                "rmse": err["rmse"], "max_error": err["max"], "created_at": now_iso()})
    _save(conn, r["id"], calibration=json.dumps(cal), validation="{}")
    _svc(request).reload()
    return {"ok": True, "rmse": err["rmse"], "max_error": err["max"], "per_point": err["per_point"],
            "warning": "Error is above 1.5% of the screen; consider repeating the calibration." if err["rmse"] > CALIBRATION_WARN_RMSE else None}


@router.delete("/calibration")
def clear_calibration(request: Request, _=Depends(require_admin), conn=Depends(get_db)):
    r = active_config_row(conn)
    cal = json.loads(r["calibration"] or "{}")
    bg = cal.get("background")
    _save(conn, r["id"], calibration=json.dumps({"background": bg} if bg else {}), validation="{}")
    _svc(request).reload()
    return {"ok": True}


@router.post("/background/learn")
def learn_background(request: Request, _=Depends(require_admin), conn=Depends(get_db)):
    try:
        bins = _svc(request).learn_background(n_scans=25, timeout=30)
    except SensorError as e:
        raise HTTPException(409, str(e))
    r = active_config_row(conn)
    cal = json.loads(r["calibration"] or "{}")
    cal["background"] = {str(k): v for k, v in bins.items()}
    _save(conn, r["id"], calibration=json.dumps(cal), validation="{}")
    _svc(request).reload()
    return {"ok": True, "bins": len(bins)}


@router.delete("/background")
def clear_background(request: Request, _=Depends(require_admin), conn=Depends(get_db)):
    r = active_config_row(conn)
    cal = json.loads(r["calibration"] or "{}")
    cal.pop("background", None)
    _save(conn, r["id"], calibration=json.dumps(cal), validation="{}")
    _svc(request).reload()
    return {"ok": True}


@router.post("/validation")
def save_validation(body: ValidationIn, request: Request, _=Depends(require_admin), conn=Depends(get_db)):
    """Accuracy test: the operator touches N known targets; results decide whether the hardware setup counts as validated."""
    svc = _svc(request)
    errs, lats, hits = [], [], 0
    for t in body.trials:
        if t.hit is not None:
            hits += 1
            errs.append(math.hypot(t.hit[0] - t.target[0], t.hit[1] - t.target[1]))
            if t.latency_ms is not None:
                lats.append(t.latency_ms)
    n = len(body.trials)
    m = {"trials": n, "detected": hits, "detection_rate": hits / n,
         "mean_error": float(np.mean(errs)) if errs else None, "p95_error": float(np.percentile(errs, 95)) if errs else None,
         "mean_latency_ms": float(np.mean(lats)) if lats else None, "limits": VALIDATION_LIMITS, "at": now_iso(),
         "source_type": svc.source_type}
    m["passed"] = bool(errs) and m["detection_rate"] >= VALIDATION_LIMITS["detection_rate"] \
        and m["mean_error"] <= VALIDATION_LIMITS["mean_error"] and m["p95_error"] <= VALIDATION_LIMITS["p95_error"] \
        and (m["mean_latency_ms"] is None or m["mean_latency_ms"] <= VALIDATION_LIMITS["mean_latency_ms"])
    r = active_config_row(conn)
    _save(conn, r["id"], validation=json.dumps(m))
    svc.cfg["validation"] = m
    return {**m, "validated_hardware": m["passed"] and svc.source_type in ("serial", "subprocess")}


# ------------------------------------------------------------------ development helpers & diagnostics
@router.post("/simulate-touch")
def simulate_touch(body: SimTouchIn, request: Request, _=Depends(require_editor)):
    if not _svc(request).inject_simulated_touch(body.u, body.v):
        raise HTTPException(409, "Simulation is only available when the sensor source is set to 'simulator'")
    return {"ok": True}


@router.websocket("/ws")
async def diagnostics_ws(ws: WebSocket, token: str = ""):
    conn = connect()
    try:
        user = security.user_from_token(token, conn)
    except Exception:
        await ws.close(code=4401)
        return
    finally:
        conn.close()
    hub = ws.app.state.diag_hub
    await hub.connect(ws, {"type": "hello", "role": user["role"]})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
