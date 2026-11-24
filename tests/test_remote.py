import time
import pytest
from starlette.websockets import WebSocketDisconnect

from app.sensor.relayproto import decode_frame, encode_frame


def _key(client, admin):
    return client.get("/api/admin/sensor/config", headers=admin).json()["params"]["relay_key"]


def _use_remote(client, admin):
    r = client.put("/api/admin/sensor/config", headers=admin, json={"source_type": "remote"})
    assert r.status_code == 200, r.text


def _room():
    return [(i * 0.4, 3000.0, 40) for i in range(900)]


def test_proto_roundtrip():
    seq, ms, pts = decode_frame(encode_frame(7, 123, [(10.0, 1500, 30), (359.99, 65000, 255)]))
    assert seq == 7 and ms == 123 and len(pts) == 2
    assert abs(pts[0][0] - 10.0) < 0.01 and pts[1][1] == 65000


def test_wrong_key_rejected(client, admin):
    _use_remote(client, admin)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/sensor-relay", headers={"x-relay-key": "nope"}):
            pass


def test_rejected_when_source_not_remote(client, admin):
    key = _key(client, admin)
    with client.websocket_connect("/ws/sensor-relay", headers={"x-relay-key": key}) as ws:
        assert ws.receive_json()["type"] == "rejected"


def test_relay_feeds_status(client, admin):
    _use_remote(client, admin)
    key = _key(client, admin)
    with client.websocket_connect("/ws/sensor-relay", headers={"x-relay-key": key}) as ws:
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json({"type": "hello", "version": "1.0", "mode": "DenseBoost", "device": {"name": "S2"}})
        for i in range(8):
            ws.send_bytes(encode_frame(i, 0, _room()))
            time.sleep(0.05)
        ws.send_bytes(b"garbage")
        time.sleep(0.4)
        st = client.get("/api/admin/sensor/status", headers=admin).json()
        assert st["relay"]["connected"] and st["relay"]["scans_rx"] >= 8
        assert st["relay"]["bad_frames"] == 1 and st["relay"]["device"] == "S2"
        assert st["source"] in ("lidar", "remote") or st["scans_total"] > 0
        ws.send_json({"type": "probe", "report": "hello report"})
        time.sleep(0.2)
    assert client.get("/api/admin/sensor/relay-probe", headers=admin).json()["report"] == "hello report"


def test_rotate_key_and_hidden_for_non_admin(client, admin):
    from tests.conftest import make_user
    old = _key(client, admin)
    new = client.post("/api/admin/sensor/relay-key/rotate", headers=admin).json()
    assert new.get("relay_key") and new["relay_key"] != old
    ed = make_user(client, admin, "eddie", "editor")
    r = client.get("/api/admin/sensor/config", headers=ed)
    if r.status_code == 200:
        assert "relay_key" not in (r.json().get("params") or {})


def test_calibration_show_broadcasts(client, admin):
    r = client.post("/api/admin/sensor/calibration/show", headers=admin, json={"action": "show", "u": 0.5, "v": 0.5, "title": "t"})
    assert r.status_code == 200
    assert client.post("/api/admin/sensor/calibration/show", headers=admin, json={"action": "bogus"}).status_code == 422
    assert client.post("/api/admin/sensor/calibration/show", headers=admin, json={"action": "show", "u": 3, "v": 0}).status_code == 422
