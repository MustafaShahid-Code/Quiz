# Football Quiz Platform (white-label)

Admin-managed, bilingual (English / العربية) football identification quiz for a projector or large display,
with mouse / keyboard / touch-screen input and an optional Slamtec RPLIDAR S2/S3 touch layer.
Colours, logos, fonts and sponsor slides are all controlled from the admin panel, so one install can be
re-skinned per client.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export FQ_ADMIN_PASSWORD='Choose-A-Strong-Pass1'   # optional; otherwise a password is generated and printed once
uvicorn --factory app.main:app_factory --host 0.0.0.0 --port 8000
```

* Player screen: `http://HOST:8000/game/`  ·  Admin: `http://HOST:8000/admin/`
* First start creates the database (`data/quiz.db`), 4 theme presets, 6 sample bilingual questions and a sponsor slide.
  The first admin (`admin`) must change its password at first sign-in.
* `python manage.py status | create-admin | reset-password | migrate | seed`
* Tests: `python -m pytest -q`

## What the admin controls

| Area | What you can do |
|---|---|
| Questions | CRUD, EN + AR text/explanation, image, optional reveal image, options (one correct), category, difficulty, interaction scheme, draft → publish / unpublish, duplicate, preview |
| Characters, Media | reusable characters/objects, uploaded images and fonts (content-sniffed, size-limited) |
| Interaction schemes | answer layout (2×2 grid etc.); the pose scheme stays disabled until a camera service exists |
| Branding slides | the first screen: image/text sponsor slides, duration, schedule window, order |
| Themes & colours | full white-labelling: colours, gradient, fonts (custom font upload), logos, button shape/style, effects; live preview, presets, duplicate, **export/import** (assets embedded) and activate |
| Game settings | titles/instructions in both languages, questions per game, shuffle, retries, scoring, **“Are you sure?” confirmation delay**, idle reset, feedback messages, admin product name/logo/accent colour |
| Sensor & calibration | status, live scan view, calibration, accuracy test, thresholds, background learning, simulator pad |
| Results, Users | sessions and per-answer detail (input source shown); roles admin / editor / viewer |

## Game flow

Sponsor slides (touch to continue) → welcome + language → question → tap answer: it is **highlighted and a
countdown (default 3 s) lets the player change their mind**; tap it again to lock immediately → server validates →
correct/incorrect feedback (burst + confetti) → final result. Correct answers are never sent to the client before the
answer is final; question edits do not change a running session.

Kiosk URL parameters: `?lang=ar`, `?fullscreen=1`, `?hidecursor=1`.
Chromium kiosk: `chromium --kiosk --noerrdialogs --autoplay-policy=no-user-gesture-required "http://localhost:8000/game/?fullscreen=1&hidecursor=1"`

## Configuration (environment)

| Variable | Meaning |
|---|---|
| `FQ_DATA_DIR` | database, uploads and JWT secret location (default `./data`) |
| `FQ_ENV` | `production` disables dev-only features (default `development`) |
| `FQ_ADMIN_USER`, `FQ_ADMIN_PASSWORD` | initial admin |
| `FQ_JWT_SECRET` | override the generated secret |
| `FQ_ALLOW_SUBPROCESS_SOURCE=1` | allow the SDK-bridge sensor source (runs a program) |
| `FQ_SEED=0` | skip sample content on first start |

## Deployment

* Run behind HTTPS (nginx/Caddy) when the admin is reachable over a network; use `FQ_ENV=production`.
* A systemd unit: `ExecStart=/opt/fq/.venv/bin/uvicorn --factory app.main:app_factory --host 127.0.0.1 --port 8000`, with
  `Environment=FQ_DATA_DIR=/var/lib/fq FQ_ENV=production` and `Restart=always`.
* Back up `FQ_DATA_DIR` (SQLite + uploads). Migrations run automatically at start (`schema_migrations`).
* One install per client is the simplest rental model; export/import themes to move branding between installs.

## Troubleshooting

| Symptom | Check |
|---|---|
| “No published questions” | publish at least one question complete in the chosen language (text and every option label) |
| A question missing in Arabic | all Arabic fields must be filled; the Questions list shows the playable languages |
| Admin shows blank / login loops | clear `fq_token` in browser storage; check the server log |
| Sensor state `error` | see Sensor docs; the game keeps working with mouse/touch |
| Locked out | `python manage.py reset-password admin` |
| Wrong colours on the screen | reload the game page after activating a theme |

## Honest status of the touch sensor

Everything except real-hardware behaviour is implemented and tested against a simulator. **The RPLIDAR S2/S3 path has not been
**Multiple games / multiple customers:** see [docs/MULTI_GAME.md](docs/MULTI_GAME.md).

verified on physical hardware in this build.** Read [docs/SENSOR.md](docs/SENSOR.md) before going to production:
the installation counts as validated only after calibration plus a passing accuracy test on a real sensor.
A LiDAR measures distance in a plane; it can detect a finger near the surface after calibration, but it cannot recognise body poses
or act as a full touch screen by itself.
