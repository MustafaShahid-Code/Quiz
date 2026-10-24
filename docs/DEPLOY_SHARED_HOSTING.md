# Running on Hostinger shared hosting (experimental)

Shared plans are built for PHP. This only works if **hPanel -> Websites -> Manage -> Advanced shows
"Python App" / "Setup Python App"** (it varies by plan). If you do not see it, shared hosting cannot run
this app - use a VPS, or run it on a PC and expose it, or host only the PowerPoint/marketing site on shared.

Limits on shared hosting: no WebSockets (no live LiDAR view / accuracy test over the web; mouse and
touchscreen play are fine), no background sensor thread, restricted RAM/CPU. Fine for demos and admin.

## Steps
1. Setup Python App: pick Python 3.11+, app root `footballquiz`, domain/subfolder of your choice,
   startup file `passenger_wsgi.py`, entry point `application`.
2. Upload the project zip contents into `~/footballquiz` (File Manager, or `git clone` via SSH if your plan has SSH).
3. In the Python App page, "Run pip install" for `requirements.txt` and `requirements-shared.txt`
   (or in the shown virtualenv: `pip install -r requirements.txt -r requirements-shared.txt`).
4. Environment variables (same page): `FQ_ENV=production`, `FQ_ADMIN_PASSWORD=<strong>`,
   `FQ_DATA_DIR=/home/<user>/fq_data` (outside public_html so the database is never web-served).
5. Restart the app, open your domain `/admin/`. Force HTTPS in hPanel -> SSL.

## CI/CD on shared hosting
Only if SSH is enabled: adapt `.github/workflows/deploy.yml` to `rsync` into `~/footballquiz`, install deps,
then `touch ~/footballquiz/tmp/restart.txt` (Passenger restart). Without SSH, deploy manually via File Manager/FTP.
