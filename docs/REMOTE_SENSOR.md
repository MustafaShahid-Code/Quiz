# Remote LiDAR (S2 / S3) – test a sensor in another place

The game and all its code stay on your server. A tiny program (`tools/relay`, no game code) runs on a Windows laptop
next to the LiDAR and streams the scans to the server over `wss://`. Calibration targets are drawn on the projector
by the game page itself, so nobody on site needs an admin login.

## Remote admin (you)
1. Deploy this version (git push). Admin → Sensor → **Source = Remote relay** → Save & apply.
2. Same page, "Remote LiDAR relay" box → **Show start command** → copy the key into the site's `relay_config.txt`
   (or send them the command). *Generate new key* invalidates the old one at once.
3. When the on-site person has run `probe.bat`, press **View last sensor check** to read the report.
4. Status row shows "relay connected / scans per second". Then follow docs/HARDWARE_TEST_GUIDE.md:
   Learn background → Calibrate (Show the targets: **On the game screen**) → Accuracy test → thresholds.

## On site
Give them the `relay-kit` zip (README.txt inside). Chrome on the projector computer opens the game URL, full screen.

## Notes
- Needs ~50–200 KB/s upload. The relay reconnects automatically; the server marks the sensor stale after ~6 s of silence.
- Caddy proxies WebSockets automatically; no change needed.
- Wrong key shows as HTTP 403 in the relay window. A server not set to "Remote relay" answers "SERVER SAYS …".
- Decoders: S2 (dense capsule, 0x85) and S3 (ultra-dense, 0x86) ported from Slamtec's SDK and tested against
  emulated sensors only. If `probe.bat` reports a decode problem, send `probe_report.txt` + `probe_raw.bin`.
