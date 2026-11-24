#!/usr/bin/env python3
"""Football-quiz LiDAR relay.  Runs next to the LiDAR (Windows laptop / mini PC) and forwards the scans to the game server.

    py fq_relay.py --probe                 # check the sensor and print a report (do this first)
    py fq_relay.py                         # run, using relay_config.txt
    py fq_relay.py --server wss://quiz.example.com --key XXXX --model S2

It contains no game logic. Needs: Python 3.9+, `pip install pyserial websocket-client`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import struct
import sys
import threading
import time

VERSION = "1.0"
MAGIC = 0x53
HEADER = struct.Struct("<BIIH")
POINT = struct.Struct("<HHB")
BAUDS = (1_000_000, 460_800, 256_000, 115_200)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from slamtec import LidarError, SlamtecLidar  # noqa: E402


def log(msg: str):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(os.path.join(HERE, "relay.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except OSError:
        pass


def encode_frame(seq: int, points) -> bytes:
    body = b"".join(POINT.pack(int(round((a % 360.0) * 100)) % 36000, min(int(round(d)), 65535), max(0, min(int(q), 255)))
                    for a, d, q in points if d > 0)
    return HEADER.pack(MAGIC, seq & 0xFFFFFFFF, int(time.monotonic() * 1000) & 0xFFFFFFFF, len(body) // POINT.size) + body


# ------------------------------------------------------------------------------------------------ config
def read_config(path: str) -> dict:
    out = {}
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip().lower()] = v.strip()
    return out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Football-quiz LiDAR relay")
    ap.add_argument("--config", default=os.path.join(HERE, "relay_config.txt"))
    ap.add_argument("--server", help="e.g. wss://quiz.emllc.net")
    ap.add_argument("--key", help="relay key from Admin -> Sensor")
    ap.add_argument("--model", choices=["S2", "S3", "other"], help="informational")
    ap.add_argument("--port", help="COM3 or auto (default)")
    ap.add_argument("--baud", help="baud rate or auto (default)")
    ap.add_argument("--probe", action="store_true", help="check the sensor, print/send a report and exit")
    ap.add_argument("--simulate", action="store_true", help="no sensor: send a synthetic scan (tests the connection to the server)")
    ap.add_argument("--max-dist", type=int, default=0, help="drop points farther than this (mm); the server normally sets it")
    a = ap.parse_args(argv)
    cfg = read_config(a.config)
    a.server = a.server or cfg.get("server")
    a.key = a.key or cfg.get("key")
    a.model = a.model or cfg.get("model", "S2")
    a.port = a.port or cfg.get("port", "auto")
    a.baud = a.baud or cfg.get("baud", "auto")
    return a


# ------------------------------------------------------------------------------------------------ sensor discovery
def list_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return list(list_ports.comports())


def pick_port(want: str) -> str:
    if want and want.lower() != "auto":
        return want
    ports = list_ports()
    if not ports:
        raise LidarError("no serial (COM) ports found. Is the LiDAR's USB adapter plugged in? Is the CP210x driver installed?")
    pref = [p for p in ports if any(k in (p.description or "").upper() + (p.manufacturer or "").upper() for k in ("CP210", "SILICON", "SLAMTEC", "USB-SERIAL", "UART"))]
    return (pref or ports)[0].device


def open_lidar(a, tell=log) -> SlamtecLidar:
    port = pick_port(a.port)
    bauds = [int(a.baud)] if str(a.baud).lower() != "auto" else list(BAUDS)
    last = None
    for baud in bauds:
        lid = SlamtecLidar(port, baud)
        try:
            lid.open()
            lid.stop()
            info = lid.get_info()
            tell(f"sensor found on {port} @ {baud} baud: {info['name']} firmware {info['firmware']} (serial {info['serial'][:8]}…)")
            return lid
        except LidarError as e:
            last = e
            lid.close()
    raise LidarError(f"no answer from the sensor on {port} (tried {', '.join(map(str, bauds))} baud): {last}")


# ------------------------------------------------------------------------------------------------ server link
class Uplink:
    def __init__(self, server: str, key: str, hello: dict):
        self.url = server.rstrip("/") + "/ws/sensor-relay"
        self.key = key
        self.hello = hello
        self.q: queue.Queue = queue.Queue(maxsize=3)
        self.ctl: queue.Queue = queue.Queue()
        self.max_dist = 0
        self.connected = False
        self.fatal = None
        self.sent_bytes = 0
        self.sent_frames = 0
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.t.start()

    def stop(self):
        self._stop.set()

    def send_frame(self, data: bytes):
        while True:
            try:
                self.q.put_nowait(data)
                return
            except queue.Full:
                try:
                    self.q.get_nowait()
                except queue.Empty:
                    pass

    def send_json(self, obj: dict):
        self.ctl.put(json.dumps(obj))

    def _run(self):
        try:
            import websocket  # websocket-client
        except ImportError:
            self.fatal = "websocket-client is not installed (py -m pip install websocket-client)"
            log(self.fatal)
            return
        delay = 1.0
        while not self._stop.is_set():
            try:
                log(f"connecting to {self.url} …")
                ws = websocket.create_connection(self.url, header=[f"x-relay-key: {self.key}"], timeout=10)
                ws.settimeout(0.05)
            except websocket.WebSocketBadStatusException as e:
                msg = "key rejected by the server (HTTP 403): check the relay key" if "403" in str(e) else f"server refused: {e}"
                log(msg)
                self._stop.wait(min(delay, 15))
                delay = min(delay * 2, 15)
                continue
            except Exception as e:  # noqa: BLE001
                log(f"cannot reach the server: {e}")
                self._stop.wait(min(delay, 15))
                delay = min(delay * 2, 15)
                continue
            self.connected = True
            delay = 1.0
            log("connected to the server")
            try:
                ws.send(json.dumps({"type": "hello", "version": VERSION, **self.hello}))
                last_ping = time.monotonic()
                while not self._stop.is_set():
                    try:
                        m = ws.recv()
                        if m:
                            self._on_msg(m)
                    except websocket.WebSocketTimeoutException:
                        pass
                    while True:
                        try:
                            ws.send(self.ctl.get_nowait())
                        except queue.Empty:
                            break
                    try:
                        data = self.q.get(timeout=0.05)
                        ws.send_binary(data)
                        self.sent_bytes += len(data)
                        self.sent_frames += 1
                    except queue.Empty:
                        pass
                    if time.monotonic() - last_ping > 15:
                        ws.ping()
                        last_ping = time.monotonic()
            except websocket.WebSocketConnectionClosedException:
                log("connection to the server closed")
            except Exception as e:  # noqa: BLE001
                log(f"connection lost: {e}")
            finally:
                self.connected = False
                try:
                    ws.close()
                except Exception:
                    pass
            self._stop.wait(1.5)

    def _on_msg(self, text):
        try:
            m = json.loads(text)
        except (TypeError, ValueError):
            return
        if m.get("type") == "welcome":
            self.max_dist = int(m.get("max_dist_mm") or 0)
            log(f"server accepted the relay (will use points up to {self.max_dist} mm)")
        elif m.get("type") == "rejected":
            log("SERVER SAYS: " + str(m.get("reason")))


# ------------------------------------------------------------------------------------------------ modes
def synth_scans(rate_hz=10.0):
    """Synthetic room (no finger). Lets you test the connection and the status on the server without a sensor."""
    import random
    rng = random.Random(1)
    period = 1.0 / rate_hz
    while True:
        t0 = time.monotonic()
        pts = []
        for i in range(1000):
            ang = i * 0.36
            a = math.radians(ang)
            dx, dy = math.sin(a), math.cos(a)
            tx = 3500 / abs(dx) if abs(dx) > 1e-6 else 1e9
            ty = 4500 / abs(dy) if abs(dy) > 1e-6 else 1e9
            pts.append((ang, min(tx, ty) + rng.gauss(0, 4), 47))
        yield pts
        time.sleep(max(0, period - (time.monotonic() - t0)))


def run_probe(a) -> int:
    lines = []

    def say(msg):
        lines.append(msg)
        print(msg, flush=True)

    say(f"Football-quiz relay v{VERSION} probe, {time.strftime('%Y-%m-%d %H:%M:%S')}, Python {sys.version.split()[0]}, platform {sys.platform}")
    say("COM ports: " + (", ".join(f"{p.device} ({p.description})" for p in list_ports()) or "none found"))
    rc = 1
    raw = bytearray()
    try:
        lid = open_lidar(a, say)
        try:
            say(f"device: {lid.info}")
            say(f"health: {lid.get_health()}")
            try:
                modes = lid.get_modes()
                for m in modes:
                    say(f"scan mode {m['id']}: {m['name']} answer type {m['ans_type']:#x} sample {m['us_per_sample']:.1f} us max {m['max_distance']} m")
                say(f"typical mode id: {lid.typical_mode_id()}")
            except LidarError as e:
                say(f"scan modes: not available ({e}); will use the standard scan")
            lid.raw_tap = lambda b: raw.extend(b[:20000]) if len(raw) < 20000 else None
            lid.start_scan()
            say(f"started scan mode '{lid.mode['name']}' (answer type {lid.mode['ans_type']:#x})")
            n, t0, pts = 0, time.monotonic(), 0
            for rev in lid.revolutions(stop_check=lambda: time.monotonic() - t0 > 6.0):
                n += 1
                pts = len(rev)
                near = [p for p in rev if p[1] < 3000]
                if n <= 3:
                    say(f"revolution {n}: {len(rev)} points, nearest {min(p[1] for p in rev):.0f} mm, {len(near)} points under 3 m")
            dt = time.monotonic() - t0
            say(f"result: {n} revolutions in {dt:.1f} s = {n / dt:.1f} Hz, last revolution {pts} points")
            rc = 0 if n >= 20 and 5 <= n / dt <= 20 else 2
            say("PROBE OK" if rc == 0 else "PROBE WARNING: unexpected scan rate or too few revolutions")
        finally:
            lid.close()
    except LidarError as e:
        say(f"PROBE FAILED: {e}")
    except Exception as e:  # noqa: BLE001
        say(f"PROBE CRASHED: {type(e).__name__}: {e}")
    if raw:
        try:
            open(os.path.join(HERE, "probe_raw.bin"), "wb").write(bytes(raw))
            say("saved the first bytes of the raw sensor stream to probe_raw.bin")
        except OSError:
            pass
    report = "\n".join(lines)
    try:
        open(os.path.join(HERE, "probe_report.txt"), "w", encoding="utf-8").write(report + "\n")
    except OSError:
        pass
    if a.server and a.key:                                    # also send it to the admin so it can be read remotely
        try:
            import websocket
            ws = websocket.create_connection(a.server.rstrip("/") + "/ws/sensor-relay", header=[f"x-relay-key: {a.key}"], timeout=10)
            ws.send(json.dumps({"type": "probe", "report": report[:8000]}))
            time.sleep(0.5)
            ws.close()
            say("probe report sent to the server")
        except Exception as e:  # noqa: BLE001
            say(f"could not send the report to the server ({e}); send probe_report.txt manually")
    return rc


def run_relay(a) -> int:
    if not a.server or not a.key:
        log("missing --server and --key (or relay_config.txt). Copy the command from Admin -> Sensor -> Remote relay.")
        return 2
    hello = {"model": a.model, "mode": "simulator" if a.simulate else None, "device": {"name": "simulator" if a.simulate else a.model}}
    up = Uplink(a.server, a.key, hello)
    up.start()
    seq, last_stat, scans, pts_total = 0, time.monotonic(), 0, 0
    lid = None
    stop = threading.Event()
    try:
        while not stop.is_set():
            if up.fatal:
                return 2
            try:
                if a.simulate:
                    source = synth_scans()
                else:
                    lid = open_lidar(a)
                    lid.start_scan()
                    log(f"scanning in mode '{lid.mode['name']}' ({lid.mode['ans_type']:#x})")
                    up.hello = {"model": a.model, "mode": lid.mode["name"], "device": {"name": f"{lid.info['name']} fw {lid.info['firmware']}"}}
                    up.send_json({"type": "hello", "version": VERSION, **up.hello})
                    source = lid.revolutions()
                for rev in source:
                    md = a.max_dist or up.max_dist
                    if md:
                        rev = [p for p in rev if p[1] <= md]
                    seq += 1
                    scans += 1
                    pts_total += len(rev)
                    if up.connected:
                        up.send_frame(encode_frame(seq, rev))
                    now = time.monotonic()
                    if now - last_stat >= 5:
                        dt = now - last_stat
                        log(f"{scans / dt:.1f} scans/s, {pts_total // max(1, scans)} points/scan, uploaded {up.sent_bytes / dt / 1024:.0f} KB/s, server {'connected' if up.connected else 'NOT connected'}")
                        last_stat, scans, pts_total, up.sent_bytes = now, 0, 0, 0
            except LidarError as e:
                log(f"sensor problem: {e}")
                up.send_json({"type": "error", "msg": str(e)[:200]})
            finally:
                if lid is not None:
                    lid.close()
                    lid = None
            time.sleep(3)                                      # then try again (unplugged / replugged cable recovers by itself)
    except KeyboardInterrupt:
        log("stopping")
    finally:
        up.stop()
        if lid is not None:
            lid.close()
    return 0


def main(argv=None) -> int:
    a = parse_args(argv)
    if a.probe:
        return run_probe(a)
    return run_relay(a)


if __name__ == "__main__":
    sys.exit(main())
