"""Tests the on-site relay's Slamtec driver against an emulated S2 (dense) and S3 (ultra-dense) sensor."""
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "relay"))
import slamtec as sl  # noqa: E402


def room(angle_deg):
    a = math.radians(angle_deg)
    dx, dy = abs(math.sin(a)), abs(math.cos(a))
    return min(3500 / dx if dx > 1e-6 else 1e9, 4500 / dy if dy > 1e-6 else 1e9)


def _header(frame, start):
    cs = 0
    for b in frame[start:]:
        cs ^= b
    frame[0] = 0xA0 | (cs & 0xF)
    frame[1] = 0x50 | (cs >> 4)
    return bytes(frame)


def dense_stream(revs=3, caps=80, first_start=1.0):
    out = bytearray()
    for k in range(revs * caps + 1):
        start = (first_start + k * 360.0 / caps) % 360
        f = bytearray(84)
        sync = 0x8000 if (k % caps == 0) else 0
        struct.pack_into("<H", f, 2, sync | int(round(start * 64)))
        for i in range(40):
            ang = (start + i * (360.0 / caps) / 40) % 360
            struct.pack_into("<H", f, 4 + i * 2, int(min(room(ang), 60000)))
        out += _header(f, 4)
    return bytes(out)


def ultra_stream(revs=3, caps=100, first_start=2.0):
    out = bytearray()
    for k in range(revs * caps + 1):
        start = (first_start + k * 360.0 / caps) % 360
        f = bytearray(170)
        struct.pack_into("<H", f, 8, (0x8000 if k % caps == 0 else 0) | int(round(start * 64)))
        for c in range(32):
            qds = []
            for j in range(2):
                ang = (start + (c * 2 + j) * (360.0 / caps) / 64) % 360
                d = room(ang)
                if d <= 2046:
                    v = (3 << 12) | (int(d * 2) & 0xFFC)
                else:
                    v = (((int(d * 4) - 8184) // 3) & 0x1FFC) | 1 | (1 << 13)
                qds.append(v)
            struct.pack_into("<HHB", f, 10 + c * 5, qds[0] & 0xFFFF, qds[1] & 0xFFFF, ((qds[0] >> 16) & 0xF) | (((qds[1] >> 16) & 0xF) << 4))
        out += _header(f, 2)
    return bytes(out)


def _check(rev, tol):
    assert len(rev) > 2000
    errs = [abs(d - room(a)) for a, d, _ in rev if 5 < a < 355 and room(a) < 20000]
    assert errs and sorted(errs)[len(errs) // 2] < tol, sorted(errs)[len(errs) // 2]


def test_dense_s2_unpack_and_revolutions():
    u, asm = sl.DenseUnpacker(), sl.RevolutionAssembler()
    revs = []
    data = dense_stream()
    for i in range(0, len(data), 100):                       # arbitrary chunking
        revs += asm.add(u.feed(data[i:i + 100]))
    assert len(revs) >= 2
    _check(revs[0], 25)


def test_ultra_s3_unpack_and_revolutions():
    u, asm = sl.UltraDenseUnpacker(), sl.RevolutionAssembler()
    revs = []
    data = ultra_stream()
    for i in range(0, len(data), 77):
        revs += asm.add(u.feed(data[i:i + 77]))
    assert len(revs) >= 2
    _check(revs[0], 60)


def test_resync_after_garbage_and_bad_checksum():
    u = sl.DenseUnpacker()
    data = dense_stream(revs=1)
    bad = bytearray(data[:84]); bad[10] ^= 0xFF
    out = u.feed(b"\x01\x02\x03" + bytes(bad) + data)
    assert len(out) >= 40 * 70                                # the corrupt capsule is dropped, the stream recovers


def test_standard_unpacker():
    u = sl.StandardUnpacker()
    pts = b""
    for i in range(10):
        ang_q6, dist_q2 = int(i * 36 * 64), 2000 * 4
        pts += bytes([(1 if i == 0 else 2) | (30 << 2), ((ang_q6 << 1) | 1) & 0xFF, ((ang_q6 << 1) | 1) >> 8, dist_q2 & 0xFF, dist_q2 >> 8])
    out = u.feed(pts)
    assert len(out) == 10 and abs(out[3][0] - 108) < 0.1 and out[3][1] == 2000 and out[0][3] is True


class FakeSerial:
    """Emulates the command/response protocol of an S-series sensor."""
    def __init__(self, port, baud, model=0x61, ans=sl.ANS_ULTRA_DENSE):
        self.model, self.ans = model, ans
        self.rx = bytearray()
        self.stream = b""
        self.motor = None
        self.closed = False
        self.dtr = True

    @property
    def in_waiting(self):
        return len(self.rx)

    def reset_input_buffer(self):
        self.rx.clear()

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def read(self, n=1):
        if not self.rx and self.stream:
            self.rx += self.stream[:600]; self.stream = self.stream[600:]
        if not self.rx:
            time.sleep(0.01)
            return b""
        out = bytes(self.rx[:n]); del self.rx[:n]
        return out

    def _ans(self, typ, payload, flags=0):
        self.rx += bytes([0xA5, 0x5A]) + struct.pack("<I", len(payload) | (flags << 30)) + bytes([typ]) + payload

    def write(self, data):
        c = data[1]
        pl = data[3:-1] if len(data) > 3 else b""
        if c == sl.CMD_GET_INFO:
            self._ans(sl.ANS_DEVINFO, bytes([self.model]) + struct.pack("<H", 0x0103) + bytes([18]) + bytes(range(16)))
        elif c == sl.CMD_GET_HEALTH:
            self._ans(sl.ANS_DEVHEALTH, b"\x00\x00\x00")
        elif c == sl.CMD_GET_LIDAR_CONF:
            t = struct.unpack_from("<I", pl, 0)[0]
            arg = pl[4:]
            body = struct.pack("<I", t)
            if t == sl.CONF_SCAN_MODE_COUNT: body += struct.pack("<H", 2)
            elif t == sl.CONF_SCAN_MODE_TYPICAL: body += struct.pack("<H", 1)
            elif t == sl.CONF_DESIRED_ROT_FREQ: body += struct.pack("<H", 600)
            elif t == sl.CONF_SCAN_MODE_US_PER_SAMPLE: body += struct.pack("<I", int(31.25 * 256))
            elif t == sl.CONF_SCAN_MODE_MAX_DISTANCE: body += struct.pack("<I", 30 << 8)
            elif t == sl.CONF_SCAN_MODE_ANS_TYPE: body += bytes([sl.ANS_DENSE if arg[0] == 0 else self.ans])
            elif t == sl.CONF_SCAN_MODE_NAME: body += (b"Standard" if arg[0] == 0 else b"Boost") + b"\0"
            self._ans(sl.ANS_GET_LIDAR_CONF, body)
        elif c == sl.CMD_HQ_MOTOR_SPEED:
            self.motor = struct.unpack("<H", pl)[0]
        elif c == sl.CMD_EXPRESS_SCAN:
            mode = pl[0]
            at = sl.ANS_DENSE if mode == 0 else self.ans
            self._ans(at, b"", flags=1)
            self.stream = dense_stream(40) if at == sl.ANS_DENSE else ultra_stream(40)
        elif c == sl.CMD_STOP:
            self.stream = b""


def _run(ans, hz_ok=True):
    lid = sl.SlamtecLidar("COMX", serial_factory=lambda p, b: FakeSerial(p, b, ans=ans))
    lid.open()
    info = lid.get_info()
    assert info["name"] == "S1M1" or info["name"].startswith("S")
    assert lid.get_health()["status"] == "good"
    modes = lid.get_modes()
    assert len(modes) == 2
    lid.start_scan()
    assert lid.motor_started if hasattr(lid, "motor_started") else lid.ser.motor == 600
    revs = []
    for rev in lid.revolutions(stall_s=2):
        revs.append(rev)
        if len(revs) >= 3:
            break
    lid.close()
    assert lid.ser is None
    return lid, revs


def test_full_driver_s3_boost_mode():
    lid, revs = _run(sl.ANS_ULTRA_DENSE)
    assert lid.mode["name"] == "Boost" and len(revs) == 3
    _check(revs[1], 60)


def test_full_driver_s2_dense_mode():
    lid, revs = _run(sl.ANS_DENSE)
    assert len(revs) == 3
    _check(revs[1], 25)


def test_unsupported_answer_type_message():
    class F(FakeSerial):
        pass
    lid = sl.SlamtecLidar("COMX", serial_factory=lambda p, b: F(p, b, ans=0x84))
    lid.open(); lid.get_info()
    try:
        lid.start_scan()
        raise AssertionError("should fail")
    except sl.LidarError as e:
        assert "does not decode" in str(e)


def test_relay_frame_matches_server_decoder():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "relay"))
    import fq_relay
    from app.sensor.relayproto import decode_frame
    seq, ms, pts = decode_frame(fq_relay.encode_frame(5, [(12.34, 1500.4, 33), (0, 0, 0), (359.9, 70000, 300)]))
    assert seq == 5 and len(pts) == 2 and abs(pts[0][0] - 12.34) < 0.01 and pts[1][1] == 65535 and pts[1][2] == 255
