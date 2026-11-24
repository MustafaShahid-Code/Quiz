"""Pure-Python driver for Slamtec RPLIDAR S2 / S3 (and the same protocol family: S1, A-series standard scan).

Ported from the official, BSD-licensed Slamtec rplidar_sdk (sl_lidar_driver.cpp, sl_lidarprotocol_codec.cpp and the
dataunpacker handlers). Only what is needed to read scans is implemented:

  * request framing         A5 <cmd> [<len> <payload> <xor-checksum>]
  * response descriptor     A5 5A <len30|flags2> <type>
  * GET_DEVICE_INFO / GET_DEVICE_HEALTH / GET_LIDAR_CONF (scan modes) / motor speed (S-series use 0xA8 RPM command)
  * scan answer types       0x81 standard, 0x82 capsule, 0x85 dense capsule (S2), 0x86 ultra-dense capsule (S3)

It has been checked against emulated devices that follow the SDK's packet layouts (tests/test_relay.py) but, like any
code that has not seen the real hardware, it needs the `--probe` self-test on the real sensor first.
"""
from __future__ import annotations

import struct
import time

CMD_SYNC = 0xA5
ANS_SYNC1, ANS_SYNC2 = 0xA5, 0x5A
HAS_PAYLOAD = 0x80

CMD_STOP, CMD_SCAN, CMD_FORCE_SCAN, CMD_RESET = 0x25, 0x20, 0x21, 0x40
CMD_GET_INFO, CMD_GET_HEALTH, CMD_GET_SAMPLERATE = 0x50, 0x52, 0x59
CMD_EXPRESS_SCAN, CMD_GET_LIDAR_CONF = 0x82, 0x84
CMD_HQ_MOTOR_SPEED = 0xA8
CMD_SET_MOTOR_PWM, CMD_GET_ACC_BOARD_FLAG = 0xF0, 0xFF

ANS_DEVINFO, ANS_DEVHEALTH = 0x04, 0x06
ANS_MEASUREMENT, ANS_CAPSULED, ANS_HQ, ANS_CAPSULED_ULTRA, ANS_DENSE, ANS_ULTRA_DENSE = 0x81, 0x82, 0x83, 0x84, 0x85, 0x86
ANS_GET_LIDAR_CONF = 0x20
ANS_ACC_BOARD_FLAG = 0xFF

CONF_DESIRED_ROT_FREQ = 0x00000001
CONF_SCAN_MODE_COUNT = 0x00000070
CONF_SCAN_MODE_US_PER_SAMPLE = 0x00000071
CONF_SCAN_MODE_MAX_DISTANCE = 0x00000074
CONF_SCAN_MODE_ANS_TYPE = 0x00000075
CONF_SCAN_MODE_TYPICAL = 0x0000007C
CONF_SCAN_MODE_NAME = 0x0000007F

ANS_NAMES = {ANS_MEASUREMENT: "standard", ANS_CAPSULED: "capsule", ANS_HQ: "hq", ANS_CAPSULED_ULTRA: "ultra-capsule",
             ANS_DENSE: "dense", ANS_ULTRA_DENSE: "ultra-dense"}


class LidarError(RuntimeError):
    pass


def model_name(model: int) -> str:
    major, minor = model >> 4, model & 0xF
    if major >= 12:
        return f"M{major - 12 + 1}M{minor}"
    if major >= 9:
        return f"T{major - 9 + 1}M{minor}"
    if major >= 6:
        return f"S{major - 6 + 1}M{minor}"
    if major >= 4:
        return f"C{major - 4 + 1}M{minor}"
    return f"A{major}M{minor}"


def build_request(cmd: int, payload: bytes = b"") -> bytes:
    if payload and not cmd & HAS_PAYLOAD:
        raise ValueError("command %#x carries no payload" % cmd)
    if not payload:
        return bytes([CMD_SYNC, cmd])
    out = bytes([CMD_SYNC, cmd, len(payload)]) + payload
    cs = 0
    for b in out:
        cs ^= b
    return out + bytes([cs])


# ---------------------------------------------------------------------------------------------- unpackers
class Unpacker:
    """Feed raw bytes with feed(); yields (angle_deg, dist_mm, quality, start_of_revolution) samples."""
    ans_type = 0

    def feed(self, data: bytes):  # pragma: no cover
        raise NotImplementedError

    def reset(self):
        pass


class StandardUnpacker(Unpacker):
    """5 bytes per sample: [sync|!sync|quality<<2][check(1)|angle_q6<<1 lo][angle hi][dist_q2 lo][dist_q2 hi]"""
    ans_type = ANS_MEASUREMENT

    def __init__(self):
        self.buf = bytearray()

    def reset(self):
        self.buf.clear()

    def feed(self, data):
        self.buf += data
        out = []
        i = 0
        n = len(self.buf)
        while n - i >= 5:
            b0, b1, b2, b3, b4 = self.buf[i:i + 5]
            sync, inv = b0 & 1, (b0 >> 1) & 1
            if sync == inv or not (b1 & 1):          # not a valid node header: slide by one byte (resync)
                i += 1
                continue
            angle = (((b2 << 8) | b1) >> 1) / 64.0
            dist = ((b4 << 8) | b3) / 4.0
            out.append((angle, dist, b0 >> 2, bool(sync)))
            i += 5
        del self.buf[:i]
        return out


class CapsuleBase(Unpacker):
    SIZE = 0
    CHECK_FROM = 4          # checksum covers bytes[CHECK_FROM:]

    def __init__(self):
        self.buf = bytearray()
        self.prev = None

    def reset(self):
        self.buf.clear()
        self.prev = None

    def _frames(self, data):
        """Yield checksum-valid capsule frames; resynchronise on the 0xA?/0x5? nibble header on any error."""
        self.buf += data
        while len(self.buf) >= self.SIZE:
            if (self.buf[0] >> 4) != 0xA or (self.buf[1] >> 4) != 0x5:
                del self.buf[0]
                self.prev = None
                continue
            frame = bytes(self.buf[:self.SIZE])
            cs = 0
            for b in frame[self.CHECK_FROM:]:
                cs ^= b
            recv = ((frame[0] & 0xF) | ((frame[1] & 0xF) << 4))
            if cs != recv:
                del self.buf[0]
                self.prev = None
                continue
            del self.buf[:self.SIZE]
            yield frame


MAX_CAPSULE_DEG = 60      # one capsule never spans more than this (10-15 Hz sensors: ~5 degrees)


def _angle_step(prev_q8_start: int, cur_q8_start: int) -> int:
    diff = cur_q8_start - prev_q8_start
    if prev_q8_start > cur_q8_start:
        diff += 360 << 8
    return diff


class CapsuleUnpacker(CapsuleBase):
    """0x82: 84 bytes: 2 checksum, u16 start_angle_sync_q6, 16 cabins x {u16,u16,u8} = 2 samples each."""
    ans_type = ANS_CAPSULED
    SIZE = 84
    CHECK_FROM = 4

    def feed(self, data):
        out = []
        for fr in self._frames(data):
            start_sync = struct.unpack_from("<H", fr, 2)[0]
            cur = (fr, start_sync)
            if self.prev is not None:
                pfr, psync = self.prev
                cur_start = (start_sync & 0x7FFF) << 2
                prev_start = (psync & 0x7FFF) << 2
                diff_q8 = _angle_step(prev_start, cur_start)
                inc_q16 = diff_q8 << 3
                raw_q16 = prev_start << 8
                for pos in range(16):
                    d1, d2, off = struct.unpack_from("<HHB", pfr, 4 + pos * 5)
                    dist = (d1 & 0xFFFC, d2 & 0xFFFC)
                    off1 = (off & 0xF) | ((d1 & 3) << 4)
                    off2 = (off >> 4) | ((d2 & 3) << 4)
                    for k, off_q3 in enumerate((off1, off2)):
                        a_q6 = (raw_q16 - (off_q3 << 13)) >> 10
                        sync = 1 if ((raw_q16 + inc_q16) % (360 << 16)) < inc_q16 else 0
                        raw_q16 += inc_q16
                        a_q6 %= (360 << 6)
                        out.append((a_q6 / 64.0, dist[k] / 4.0, 0x2F if dist[k] else 0, bool(sync)))
            self.prev = cur
        return out


class DenseUnpacker(CapsuleBase):
    """0x85 (S2): 84 bytes: 2 checksum, u16 start_angle_sync_q6, 40 x u16 distance (mm)."""
    ans_type = ANS_DENSE
    SIZE = 84
    CHECK_FROM = 4
    N = 40

    def feed(self, data):
        out = []
        for fr in self._frames(data):
            start_sync = struct.unpack_from("<H", fr, 2)[0]
            cur = (fr, start_sync)
            if self.prev is not None:
                pfr, psync = self.prev
                cur_start = (start_sync & 0x7FFF) << 2
                prev_start = (psync & 0x7FFF) << 2
                diff_q8 = _angle_step(prev_start, cur_start)
                if diff_q8 > (MAX_CAPSULE_DEG << 8):    # implausible jump (lost capsules): drop the pair
                    self.prev = cur
                    continue
                inc_q16 = (diff_q8 << 8) // self.N
                raw_q16 = prev_start << 8
                dists = struct.unpack_from("<%dH" % self.N, pfr, 4)
                for pos in range(self.N):
                    a_q6 = (raw_q16 >> 10) % (360 << 6)
                    sync = 1 if ((raw_q16 + inc_q16) % (360 << 16)) < (inc_q16 << 1) else 0
                    raw_q16 += inc_q16
                    d = dists[pos]
                    out.append((a_q6 / 64.0, float(d), 0x2F if d else 0, bool(sync)))
            self.prev = cur
        return out


class UltraDenseUnpacker(CapsuleBase):
    """0x86 (S3): 170 bytes: 2 checksum, u32 timestamp, u16 dev_status, u16 start_angle_sync_q6, 32 cabins x 5 bytes = 64 samples.
    Checksum covers everything from the timestamp on (offset 2)."""
    ans_type = ANS_ULTRA_DENSE
    SIZE = 2 + 4 + 2 + 2 + 32 * 5
    CHECK_FROM = 2
    N = 64

    def __init__(self):
        super().__init__()
        self.last_dist_q2 = 0

    def reset(self):
        super().reset()
        self.last_dist_q2 = 0

    def feed(self, data):
        out = []
        for fr in self._frames(data):
            start_sync = struct.unpack_from("<H", fr, 8)[0]
            cur = (fr, start_sync)
            if self.prev is not None:
                pfr, psync = self.prev
                cur_start = (start_sync & 0x7FFF) << 2
                prev_start = (psync & 0x7FFF) << 2
                diff_q8 = _angle_step(prev_start, cur_start)
                if diff_q8 > (MAX_CAPSULE_DEG << 8):
                    self.prev = cur
                    continue
                inc_q16 = (diff_q8 << 8) // self.N
                raw_q16 = prev_start << 8
                for pos in range(self.N):
                    base = 10 + (pos >> 1) * 5
                    ql0, ql1, qh = struct.unpack_from("<HHB", pfr, base)
                    qds = (ql0 | ((qh & 0x0F) << 16)) if not (pos & 1) else (ql1 | ((qh >> 4) << 16))
                    scale = qds & 3
                    if scale == 0:
                        quality = qds >> 12
                        dist_q2 = (qds & 0xFFC) * 2
                        if self.last_dist_q2 and abs(dist_q2 - self.last_dist_q2) <= 8:
                            dist_q2 = (dist_q2 + self.last_dist_q2) >> 1
                    elif scale == 1:
                        quality = (qds >> 13) << 1
                        dist_q2 = (qds & 0x1FFC) * 3 + (2046 << 2)
                    elif scale == 2:
                        quality = (qds >> 14) << 2
                        dist_q2 = (qds & 0x3FFC) * 4 + (8187 << 2)
                    else:
                        quality = (qds >> 15) << 3
                        dist_q2 = (qds & 0x7FFC) * 5 + (24567 << 2)
                    self.last_dist_q2 = dist_q2
                    a_q6 = (raw_q16 >> 10) % (360 << 6)
                    sync = 1 if ((raw_q16 + inc_q16) % (360 << 16)) < (inc_q16 << 1) else 0
                    raw_q16 += inc_q16
                    out.append((a_q6 / 64.0, dist_q2 / 4.0, quality, bool(sync)))
            self.prev = cur
        return out


UNPACKERS = {ANS_MEASUREMENT: StandardUnpacker, ANS_CAPSULED: CapsuleUnpacker, ANS_DENSE: DenseUnpacker, ANS_ULTRA_DENSE: UltraDenseUnpacker}


# ---------------------------------------------------------------------------------------------- revolutions
class RevolutionAssembler:
    """Collects samples into full revolutions. A revolution ends when the angle wraps (new angle much smaller than the last)
    or when a sample carries the start-of-revolution flag after enough points were collected. Independent of exact sync-bit quirks."""

    def __init__(self, min_points=60):
        self.pts = []
        self.last_angle = None
        self.min_points = min_points

    def add(self, samples):
        done = []
        for angle, dist, q, sync in samples:
            wrapped = self.last_angle is not None and angle < self.last_angle - 180.0
            if wrapped and len(self.pts) >= self.min_points:
                done.append(self.pts)
                self.pts = []
            elif wrapped:
                self.pts = []
            self.last_angle = angle
            if dist > 0:
                self.pts.append((angle, dist, q))
        return done


# ---------------------------------------------------------------------------------------------- device
class SlamtecLidar:
    def __init__(self, port: str, baudrate: int = 1_000_000, serial_factory=None):
        self.port, self.baud = port, baudrate
        self._factory = serial_factory
        self.ser = None
        self.info = None
        self.mode = None            # dict with id,name,ans_type,us_per_sample,max_distance
        self.unpacker: Unpacker | None = None
        self.raw_tap = None         # optional callable(bytes) used by --probe to save a raw capture

    # --- transport
    def open(self):
        if self._factory:
            self.ser = self._factory(self.port, self.baud)
        else:
            try:
                import serial  # pyserial
            except ImportError as e:
                raise LidarError("pyserial is not installed (py -m pip install pyserial)") from e
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=0.2, write_timeout=2)
            except Exception as e:
                raise LidarError(f"cannot open {self.port}: {e}") from e
        try:
            self.ser.dtr = False        # A-series accessory boards run the motor when DTR is low; harmless on S-series
        except Exception:
            pass

    def close(self):
        try:
            if self.ser is not None:
                try:
                    self._stop_motor()
                except Exception:
                    pass
                self._write(build_request(CMD_STOP))
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def _write(self, data: bytes):
        self.ser.write(data)
        try:
            self.ser.flush()
        except Exception:
            pass

    def _read(self, n: int, deadline: float) -> bytes:
        out = bytearray()
        while len(out) < n:
            if time.monotonic() > deadline:
                raise LidarError("timeout waiting for the sensor")
            chunk = self.ser.read(n - len(out))
            if chunk:
                out += chunk
        return bytes(out)

    def _flush_input(self):
        try:
            self.ser.reset_input_buffer()
        except Exception:
            time.sleep(0.05)
            while self.ser.read(4096):
                pass

    def _read_descriptor(self, timeout: float):
        deadline = time.monotonic() + timeout
        state = 0
        while True:
            b = self._read(1, deadline)[0]
            if state == 0:
                state = 1 if b == ANS_SYNC1 else 0
            else:
                if b == ANS_SYNC2:
                    break
                state = 1 if b == ANS_SYNC1 else 0
        rest = self._read(5, deadline)
        size_flags = struct.unpack("<I", rest[:4])[0]
        return size_flags & 0x3FFFFFFF, size_flags >> 30, rest[4]

    def request(self, cmd: int, expect_type: int, payload: bytes = b"", timeout: float = 1.0) -> bytes:
        self._flush_input()
        self._write(build_request(cmd, payload))
        size, flags, typ = self._read_descriptor(timeout)
        if typ != expect_type:
            raise LidarError(f"unexpected answer type {typ:#x} (wanted {expect_type:#x})")
        return self._read(size, time.monotonic() + timeout) if size else b""

    # --- queries
    def stop(self):
        self._write(build_request(CMD_STOP))
        time.sleep(0.02)
        self._flush_input()

    def get_info(self) -> dict:
        d = self.request(CMD_GET_INFO, ANS_DEVINFO)
        if len(d) < 20:
            raise LidarError("short device info")
        model, fw, hw = d[0], struct.unpack_from("<H", d, 1)[0], d[3]
        self.info = {"model_id": model, "name": model_name(model), "firmware": f"{fw >> 8}.{fw & 0xFF:02d}", "hardware": hw,
                     "serial": d[4:20].hex().upper()}
        return self.info

    def get_health(self) -> dict:
        d = self.request(CMD_GET_HEALTH, ANS_DEVHEALTH)
        status, err = d[0], struct.unpack_from("<H", d, 1)[0]
        return {"status": {0: "good", 1: "warning", 2: "error"}.get(status, str(status)), "error_code": err}

    def _conf(self, typ: int, arg: bytes = b"", timeout: float = 1.0) -> bytes:
        d = self.request(CMD_GET_LIDAR_CONF, ANS_GET_LIDAR_CONF, struct.pack("<I", typ) + arg, timeout)
        if len(d) < 4 or struct.unpack_from("<I", d, 0)[0] != typ:
            raise LidarError("config reply mismatch")
        return d[4:]

    def get_modes(self) -> list[dict]:
        """Scan modes the sensor offers (needs the LIDAR_CONF commands, available on S-series)."""
        count = struct.unpack("<H", self._conf(CONF_SCAN_MODE_COUNT)[:2])[0]
        modes = []
        for i in range(count):
            a = struct.pack("<H", i)
            us = struct.unpack("<I", self._conf(CONF_SCAN_MODE_US_PER_SAMPLE, a)[:4])[0] / 256.0
            mx = struct.unpack("<I", self._conf(CONF_SCAN_MODE_MAX_DISTANCE, a)[:4])[0] >> 8
            at = self._conf(CONF_SCAN_MODE_ANS_TYPE, a)[0]
            name = self._conf(CONF_SCAN_MODE_NAME, a).split(b"\x00")[0].decode("ascii", "replace")
            modes.append({"id": i, "name": name, "ans_type": at, "us_per_sample": us, "max_distance": mx})
        return modes

    def typical_mode_id(self) -> int:
        return struct.unpack("<H", self._conf(CONF_SCAN_MODE_TYPICAL)[:2])[0]

    # --- motor
    def _major(self):
        return (self.info["model_id"] >> 4) if self.info else 0

    def _start_motor(self):
        if self._major() >= 6:                              # S/T/M/C series: motor is driven by an RPM command
            rpm = 600
            try:
                d = self._conf(CONF_DESIRED_ROT_FREQ)
                rpm = struct.unpack_from("<H", d, 0)[0] or 600
            except LidarError:
                pass
            self._write(build_request(CMD_HQ_MOTOR_SPEED, struct.pack("<H", rpm)))
            time.sleep(0.05)
        elif self._major() >= 2:                            # A2/A3 with the PWM accessory board
            self._write(build_request(CMD_SET_MOTOR_PWM, struct.pack("<H", 660)))
            time.sleep(0.05)

    def _stop_motor(self):
        if self._major() >= 6:
            self._write(build_request(CMD_HQ_MOTOR_SPEED, struct.pack("<H", 0)))
        elif self._major() >= 2:
            self._write(build_request(CMD_SET_MOTOR_PWM, struct.pack("<H", 0)))

    # --- scanning
    def start_scan(self, prefer_ans: int | None = None):
        """Start the sensor's typical scan mode (what the official SDK does), or the mode with answer type `prefer_ans`."""
        self.stop()
        mode = None
        try:
            modes = self.get_modes()
            if prefer_ans is not None:
                mode = next((m for m in modes if m["ans_type"] == prefer_ans), None)
            if mode is None:
                tid = self.typical_mode_id()
                mode = next((m for m in modes if m["id"] == tid), modes[0] if modes else None)
        except LidarError:
            mode = None                                      # legacy sensor without LIDAR_CONF: standard scan
        self._start_motor()
        if mode is None or mode["ans_type"] == ANS_MEASUREMENT:
            self.mode = mode or {"id": 0, "name": "Standard", "ans_type": ANS_MEASUREMENT, "us_per_sample": 0, "max_distance": 0}
            self._write(build_request(CMD_SCAN))
            ans_expected = ANS_MEASUREMENT
        else:
            self.mode = mode
            self._write(build_request(CMD_EXPRESS_SCAN, struct.pack("<BHH", mode["id"], 0, 0)))   # working_mode, flags, param
            ans_expected = mode["ans_type"]
        cls = UNPACKERS.get(ans_expected)
        if cls is None:
            raise LidarError(f"this sensor's scan mode '{self.mode['name']}' uses answer type {ans_expected:#x}, which this relay does not decode yet "
                             f"(run --probe and send the report)")
        size, flags, typ = self._read_descriptor(3.0)
        if typ != ans_expected:
            raise LidarError(f"sensor answered with type {typ:#x}, expected {ans_expected:#x}")
        self.unpacker = cls()
        self.unpacker.reset()

    def revolutions(self, stop_check=lambda: False, stall_s: float = 5.0):
        """Generator of full revolutions: lists of (angle_deg, dist_mm, quality). Raises LidarError if the stream stalls."""
        if self.unpacker is None:
            raise LidarError("scan not started")
        asm = RevolutionAssembler()
        last_data = time.monotonic()
        while not stop_check():
            data = self.ser.read(self.ser.in_waiting or 1) if hasattr(self.ser, "in_waiting") else self.ser.read(1024)
            if not data:
                if time.monotonic() - last_data > stall_s:
                    raise LidarError("no data from the sensor for %.0f s (cable? power? wrong COM port?)" % stall_s)
                continue
            last_data = time.monotonic()
            if self.raw_tap:
                self.raw_tap(data)
            for rev in asm.add(self.unpacker.feed(data)):
                yield rev
