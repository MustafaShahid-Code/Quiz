# Sensor integration notes (RPLIDAR S2 / S3)

## What the LiDAR can and cannot do
* A 2-D LiDAR returns distances around one plane. Mounted along the bottom edge of the screen (a few mm above the surface),
  a finger crossing the plane produces a small cluster of points. That cluster can be mapped to screen coordinates after calibration.
* It cannot see pose, gestures, hover height or multi-plane information. **Pose answers require a camera service** that posts to
  `POST /api/input/pose` (header `x-input-key`, key rotated in Admin → Sensor). Pose schemes remain disabled until then.
* Ambient light, glossy projection surfaces, rails and the bezel affect results. Learn the static background with the screen clear.

## Pipeline
`scan source → range/angle filter → background subtraction → clustering → size check (rejects arms/bodies) →
confirm over N scans → homography (sensor mm → screen 0..1) → debounce / hold-release → WebSocket /ws/input → game`.

## Sources (Admin → Sensor → Source)
| Source | Use |
|---|---|
| none | disabled; mouse/touch/keyboard only |
| simulator | development; clearly labelled **simulated**; never counts as hardware validation |
| serial | `rplidar-roboticia` (A-series protocol). **Unverified on S2/S3** — treat as experimental |
| subprocess | **recommended for real S2/S3**: run a small program built on the official Slamtec SDK that prints one JSON object per scan on stdout |
| replay | replay a recorded `.jsonl` file |

### Bridge JSON-lines format
```json
{"ts": 12345.678, "points": [[angle_deg, distance_mm, quality], [0.36, 2481.0, 47], ...]}
```
One line per full revolution; flush after each line. Exit non-zero on fatal errors; the service restarts it with back-off.
Enable with `FQ_ALLOW_SUBPROCESS_SOURCE=1` (it executes a configured command, so it is off by default in production).
Set the command in Admin → Sensor (e.g. `/opt/fq/sdk_bridge --port /dev/ttyUSB0`). Official SDK and datasheets:
https://www.slamtec.com/en/Lidar/S2 and https://www.slamtec.com/en/Lidar/S3 (check the current baud rate and protocol there).

## Commissioning checklist
1. Mount the sensor so its scan plane is parallel to and ~5–15 mm in front of the screen surface; fix it rigidly.
2. Admin → Sensor: choose model and source, set the port, save; status must reach `ok` with a steady scan rate.
3. Clear the area, **Learn background**, then enable “ignore static background”.
4. **Calibrate** (7 targets) on the real display; error should be well under 1.5 % of screen width.
5. **Accuracy test** (15 random targets). Limits: detection ≥ 90 %, mean error ≤ 3 %, p95 ≤ 6 %, latency ≤ 700 ms.
   Only a pass on a non-simulated source marks the setup *validated*.
6. Unplug the sensor: the game must keep working (mouse/touch) and the status must show `error`/`stale`, then recover on re-plug.

Changing the source, sensor model or thresholds clears the stored validation; re-run steps 4–5.

## Failure behaviour
Driver exceptions never reach the game: the service records the error, closes the source and reconnects with exponential
back-off (max 10 s). Touches while uncalibrated are not forwarded. Calibration touches are never delivered to the game.
The server ignores a client’s claim of `lidar`/`simulated` input unless that sensor is really running.

## Database
SQLite (WAL). Versioned migrations in `app/db.py` (`schema_migrations`), applied at start or via `python manage.py migrate`.
