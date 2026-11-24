"""Wire format between the on-site relay program (tools/relay/fq_relay.py) and this server.

Binary WebSocket frame, little endian:
    u8  magic 0x53 ('S')
    u32 sequence number
    u32 relay clock in ms (wraps; informational)
    u16 number of points
    n x { u16 angle in 1/100 degree (0..35999), u16 distance in mm (0 = no echo, never sent), u8 quality }
Text frames are JSON control messages (hello, stats, welcome, rejected).
"""
from __future__ import annotations

import struct

import numpy as np

MAGIC = 0x53
HEADER = struct.Struct("<BIIH")
POINT = np.dtype([("a", "<u2"), ("d", "<u2"), ("q", "u1")])
MAX_POINTS = 12000


class FrameError(ValueError):
    pass


def decode_frame(data: bytes):
    """Returns (seq, relay_ms, [(angle_deg, dist_mm, quality), ...])."""
    if len(data) < HEADER.size:
        raise FrameError("short frame")
    magic, seq, ms, n = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise FrameError("bad magic")
    if n > MAX_POINTS or len(data) != HEADER.size + n * POINT.itemsize:
        raise FrameError("bad length")
    arr = np.frombuffer(data, dtype=POINT, count=n, offset=HEADER.size)
    pts = [(float(a) / 100.0, float(d), int(q)) for a, d, q in zip(arr["a"], arr["d"], arr["q"]) if d > 0]
    return seq, ms, pts


def encode_frame(seq: int, ms: int, points) -> bytes:
    """points: iterable of (angle_deg, dist_mm, quality). Used by tests; the relay has its own copy."""
    pts = [(int(round((a % 360.0) * 100)) % 36000, min(int(round(d)), 65535), max(0, min(int(q), 255))) for a, d, q in points if d > 0]
    arr = np.zeros(len(pts), dtype=POINT)
    if pts:
        arr["a"], arr["d"], arr["q"] = zip(*pts)
    return HEADER.pack(MAGIC, seq & 0xFFFFFFFF, ms & 0xFFFFFFFF, len(pts)) + arr.tobytes()
