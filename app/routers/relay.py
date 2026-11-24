"""WebSocket entry point for the remote LiDAR relay (a small program next to the sensor, possibly in another country)."""
import hmac
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..db import connect
from ..sensor.processing import Scan, ScanPoint
from ..sensor.relayproto import FrameError, decode_frame
from .sensor import active_config_row

router = APIRouter(tags=["sensor-relay"])


def relay_key_for(conn) -> str:
    p = json.loads(active_config_row(conn)["params"] or "{}")
    return p.get("relay_key", "")


@router.websocket("/ws/sensor-relay")
async def sensor_relay_ws(ws: WebSocket):
    app = ws.app
    svc = app.state.sensor
    given = ws.headers.get("x-relay-key", "")
    conn = connect()
    try:
        expected = relay_key_for(conn)
    finally:
        conn.close()
    if not given or not expected or not hmac.compare_digest(given, expected):
        await ws.close(code=4401)          # before accept: the relay sees HTTP 403 = wrong key
        return
    await ws.accept()
    if svc.source_type != "remote":
        await ws.send_json({"type": "rejected", "reason": "The server's sensor source is not 'Remote relay'. In Admin → Sensor choose Source = Remote relay and press Save & apply."})
        await ws.close(code=4409)
        return
    old = getattr(app.state, "relay_ws", None)
    if old is not None:
        try:
            await old.close(code=4410)
        except Exception:
            pass
    app.state.relay_ws = ws
    svc.relay = {"connected": True, "since": time.time(), "last_seen_mono": time.monotonic(), "scans_rx": 0, "bad_frames": 0,
                 "device": None, "mode": None, "version": None}
    await ws.send_json({"type": "welcome", "max_dist_mm": int(svc.proc.cfg.max_dist_mm + 300), "min_dist_mm": 0})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            now = time.monotonic()
            if msg.get("bytes") is not None:
                try:
                    _seq, _ms, pts = decode_frame(msg["bytes"])
                except FrameError:
                    svc.relay["bad_frames"] += 1
                    continue
                svc.relay["last_seen_mono"] = now
                svc.relay["scans_rx"] += 1
                svc.push_remote_scan(Scan([ScanPoint(a, d, q) for a, d, q in pts], now))
            elif msg.get("text") is not None:
                try:
                    m = json.loads(msg["text"])
                except ValueError:
                    continue
                svc.relay["last_seen_mono"] = now
                if m.get("type") == "hello":
                    dev = m.get("device") or {}
                    svc.relay.update({"device": str(dev.get("name", ""))[:60] or None, "mode": str(m.get("mode", ""))[:40] or None,
                                      "version": str(m.get("version", ""))[:20] or None, "error": None})
                elif m.get("type") == "error":
                    svc.relay["error"] = str(m.get("msg", ""))[:200]
                elif m.get("type") == "probe":
                    svc.relay_probe = {"at": time.time(), "report": str(m.get("report", ""))[:8000]}
    except WebSocketDisconnect:
        pass
    finally:
        if getattr(app.state, "relay_ws", None) is ws:
            app.state.relay_ws = None
            svc.relay = {**svc.relay, "connected": False}
