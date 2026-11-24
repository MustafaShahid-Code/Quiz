# Event tools

Everything here is per game. Turn features on in **Admin → Games → Edit → “Event features: prize code, leaderboard, keyboard”**
(existing games are not switched automatically). Then hard-refresh the player screen (Ctrl+Shift+R).

## Bulk question import
Questions page → choose a game in the filter → **⬆ Import**.
1. Download the Excel or CSV template. One row = one question. Columns: `text_en, text_ar, option1_en … option4_ar, correct (1-4 or a-d), image, reveal_image, difficulty, explanation_en, explanation_ar`.
2. Choose the filled sheet (max 300 rows, 2 MB). The screen shows every row, what is wrong, and which pictures it needs.
3. Choose the picture files (or a whole folder). Names are matched ignoring upper/lower case.
4. **Import questions.** Pictures upload one at a time (so it works through the 12 MB Caddy limit), then all questions are created together
   or not at all. Tick “Publish” to make complete questions live; the rest stay drafts.
The “default question text” boxes fill rows whose question text is empty (e.g. “Who is this player?”).

## Pictures are optimised automatically
Uploads are rotated upright, stripped of GPS/EXIF, and shrunk to `FQ_IMAGE_MAX_PX` (default 1600 px on the long side). An 8 MB phone photo
typically becomes a few hundred KB. PNGs with transparency stay PNG. GIFs are left alone.

## Results: filters and export
Results page: filter by game, language, winners/losers, dates and player name. **Export rounds (CSV)** = one row per round;
**Export answers (CSV)** = one row per answer. Files open correctly in Excel (UTF-8, Arabic names OK). Dates follow your browser’s time zone.

## Prize claim codes
Enable “Give winners a prize code + QR”. A winner sees a code like `H37-4S2` and a QR on the WIN screen.
Staff open **Prize claims**, type the code (or scan the QR with a phone, which shows the code), check name and score, press **Mark as collected**.
A code can only be collected once; admins can undo. Staff accounts need the *editor* role to mark collected (*viewer* can only look up).

## Live leaderboard (big screen)
Enable “Allow the live leaderboard page”. Open `https://YOUR-DOMAIN/game/leaderboard.html?game=<slug>` on a TV browser.
Options: `&lang=ar`, `&period=all` (default today), `&refresh=10` (seconds). It shows first names and scores only. Password-protected games ask for the game password.
Games page → **🏆 Leaderboard** / More → *Copy leaderboard link*.

## On-screen keyboard
For kiosks with no physical keyboard: enable “Show an on-screen keyboard”. English and Arabic layouts, shift, backspace and a language key.

## Fresh questions per player
On by default (“Give each player fresh questions”): when a game has more questions than a round uses, the questions served least recently are picked first,
so consecutive players do not get the same ones.

## Event safety net
* **Before opening:** Games → More → **Clear test results…** (type the game’s link name; it offers a CSV download first). Only that game’s rounds are removed.
* **Backup:** Dashboard → System health → **Download a backup now** (zip with the database and all pictures). Keep one copy off the server before every event.
* **Server nightly backup:** `deploy/setup_server.sh` installs a nightly job writing to `/var/backups/fq` (`FQ_BACKUP_DIR` to change). The dashboard warns if the newest one is older than 36 h.
* **Alerts:** add `https://YOUR-DOMAIN/healthz` to a free uptime monitor (e.g. UptimeRobot, 5-minute interval, email/SMS alert). It returns `{"ok": true}`.
* **Disk and uptime** are shown on the same System health card (admins only).

## Analytics (Dashboard)
Win rate, players, completed rounds, average round time, busiest hours, easiest and hardest questions, language split. Pick a game in the selector for per-client numbers.

## Environment
| Variable | Meaning | Default |
|---|---|---|
| `FQ_IMAGE_MAX_PX` | longest side of stored pictures | 1600 |
| `FQ_BACKUP_DIR` | where the nightly server backups are written | /var/backups/fq |
