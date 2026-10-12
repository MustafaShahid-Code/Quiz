# Deploying on Hostinger (VPS) with CI/CD

**Plan needed: a Hostinger VPS (KVM 1 is enough).** Shared/Web/Cloud hosting cannot run
this app (it needs a long-running Python process). Choose Ubuntu 22.04/24.04.

Flow: `git push main` -> GitHub Actions runs tests -> rsync a new release to the VPS ->
`release.sh` installs deps, switches the `current` symlink, restarts, health-checks
`/healthz`, and **rolls back automatically** if it fails. Data lives in `/var/lib/fq`
(never touched by deploys).

## 1. DNS
Point an A record (e.g. `quiz.yourdomain.com`) at the VPS IP.

## 2. One-time server setup
```bash
ssh root@VPS_IP
git clone https://github.com/YOU/REPO.git /tmp/fq && cd /tmp/fq/deploy
DOMAIN=quiz.yourdomain.com bash setup_server.sh
cat /etc/footballquiz.env      # initial admin login
```
Caddy obtains the HTTPS certificate automatically.

## 3. Deploy key
On your PC (PowerShell): `ssh-keygen -t ed25519 -f fq_deploy -N '""'`
Append `fq_deploy.pub` to `/home/deploy/.ssh/authorized_keys` on the VPS
(`chown -R deploy:deploy /home/deploy/.ssh; chmod 700 .ssh; chmod 600 .ssh/authorized_keys`).

## 4. GitHub secrets (Repo -> Settings -> Secrets -> Actions)
| Secret | Value |
|---|---|
| `VPS_HOST` | VPS IP or hostname |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | contents of the private `fq_deploy` file |
| `VPS_PORT` | optional, default 22 |

Optionally add required reviewers to the `production` environment for approval gates.

## 5. Ship
Push to `main`. Watch the Actions tab. Open `https://quiz.yourdomain.com/admin/`.

## Notes
* Logs: `journalctl -u footballquiz -f`. Manual rollback: repoint `/opt/footballquiz/current`
  to an older folder in `releases/` and `sudo systemctl restart footballquiz`.
* Backups: nightly in `/var/backups/fq`; also use Hostinger VPS snapshots before big changes.
* The LiDAR cannot be plugged into the VPS: for a live event, run the game on the venue PC
  (see HARDWARE_TEST_GUIDE.md); the VPS is for admin/content and demos. The venue PC can
  run the same code locally and import content, or use the hosted URL if internet is reliable.
* One instance per client: repeat the setup per VPS/domain (or per `FQ_DATA_DIR` + port
  and a Caddy site block) to keep client data separated.
