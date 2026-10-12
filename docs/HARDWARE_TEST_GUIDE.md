# Connecting a real RPLIDAR and projector — step-by-step test guide

Windows laptop/PC runs the server; the projector is a second display; the LiDAR is plugged in by USB.

## 1. Physical setup
1. **Projector**: set it as an *extended* display (Windows + P → Extend). Note which display is "2".
2. **Mount the LiDAR** so its scan plane runs **parallel to the projection surface, 5–15 mm in front of it**, along the bottom (or a side) edge. It must see the whole screen area and nothing blocking it. Fix it rigidly — if it moves, you must recalibrate.
3. Use only the **front 180°** (the half facing away from the wall). In Admin → Sensor → Detection thresholds set the angle window if needed (angle_min / angle_max) so the wall behind the sensor is ignored.
4. Plug the sensor in with its **USB-UART adapter** (supplied with the dev kit). Windows installs a COM port (CP210x driver if prompted). Find it in *Device Manager → Ports (COM & LPT)*, e.g. `COM3`.

## 2. Start the server with the sensor allowed
```powershell
$env:FQ_ADMIN_PASSWORD = "Choose-A-Strong-Pass1"
$env:FQ_ALLOW_SUBPROCESS_SOURCE = "1"      # only needed for the SDK-bridge option
python -m uvicorn --factory app.main:app_factory --host 0.0.0.0 --port 8000
```

## 3. Connect the sensor (Admin → Sensor & calibration → Configuration)
* **Recommended: SDK bridge.** Build the small bridge program from Slamtec's official SDK (template: `tools/sdk_bridge/main.cpp`, untested) so it prints one JSON line per revolution (format in `docs/SENSOR.md`). Source = *Official-SDK bridge*, command e.g. `C:\fq\sdk_bridge.exe --port COM3 --baud 1000000`.
* **Quick try: serial driver.** Source = *Serial driver*, port `COM3`, baud as in your sensor's datasheet (S2/S3 are normally 1,000,000). This driver speaks the A-series protocol and is **unverified on S2/S3**; if the status stays in `error`, use the bridge.
* Press **Save & apply**. Success = State **ok** and a steady scan rate (≈10 Hz) with points drawn in the live view. Unplug/replug to confirm it shows `error` then recovers.

## 4. Show the game on the projector
Drag a Chrome window onto the projector display and run (adjust the path/position):
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --kiosk --user-data-dir="C:\fq\kiosk" --window-position=1920,0 "http://localhost:8000/game/?fullscreen=1&hidecursor=1"
```
Keep the **admin** on the laptop screen in a normal browser window.

## 5. Calibrate and validate
1. Make sure the projected area is **clear of people**, then in Admin → Sensor press **Learn background**, and tick *Ignore static background* → Save.
2. **Drag the admin browser window onto the projector**, press **Calibrate…**: a full-screen overlay shows 7 targets one by one; touch the centre of each with a finger. Result must be well under **1.5 % error**. Move the window back to the laptop.
3. **Accuracy test…** (same way, 15 random targets). It passes at ≥ 90 % detected, mean error ≤ 3 %, p95 ≤ 6 %, latency ≤ 700 ms. Only a pass on real hardware marks it **validated**.
4. If detection is poor: lower *Min points per object*, raise *Cluster gap*, adjust *Max object width* (fingers vs hands), re-learn the background, check the plane height.

## 6. Workflow test checklist (do in this order)
| # | Test | Expected |
|---|---|---|
| 1 | Sensor status | `ok`, steady Hz, chip on welcome screen shows LiDAR (not "Simulator") |
| 2 | Touch the language buttons / Start | Responds under your finger, no double-fires |
| 3 | Play 5 questions with finger only | Highlight → "Are you sure?" countdown → lock → feedback |
| 4 | Touch the same answer again | Locks immediately |
| 5 | Touch a different answer during the countdown | Selection moves, countdown restarts |
| 6 | Whole hand / arm near the screen | Ignored (size filter) |
| 7 | Two people, one touching at a time | No ghost touches |
| 8 | Unplug the sensor mid-game | Game continues with mouse; status `error`/`stale` |
| 9 | Re-plug | Recovers on its own |
| 10 | Admin → Results | Answers show input source **lidar** |
| 11 | Leave idle > 60 s | Returns to the sponsor screen |
| 12 | Ambient light / sun on the surface | Retest; learn background again if needed |

## 7. Troubleshooting
* **Port busy / access denied**: close any other Slamtec tool using the COM port.
* **State stays `error`**: wrong COM port/baud; try the bridge.
* **Touches offset after moving the sensor or projector**: recalibrate (any move invalidates it).
* **Ghost touches**: re-learn background; raise *Scans to confirm*; tighten the angle window.
