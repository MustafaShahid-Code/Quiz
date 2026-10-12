#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 22.04/24.04 Hostinger VPS. Run as root:
#   DOMAIN=quiz.yourdomain.com bash setup_server.sh
set -euo pipefail
: "${DOMAIN:?set DOMAIN=quiz.yourdomain.com}"

apt-get update
apt-get install -y python3 python3-venv rsync curl ufw debian-keyring debian-archive-keyring apt-transport-https gpg
# Caddy (automatic HTTPS)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy.list
sed -i 's#^deb #deb [signed-by=/usr/share/keyrings/caddy.gpg] #' /etc/apt/sources.list.d/caddy.list
apt-get update && apt-get install -y caddy

id fq >/dev/null 2>&1 || useradd --system --home /var/lib/fq --shell /usr/sbin/nologin fq
id deploy >/dev/null 2>&1 || useradd -m -s /bin/bash deploy
mkdir -p /opt/footballquiz/releases /var/lib/fq
chown -R deploy:deploy /opt/footballquiz
chown fq:fq /var/lib/fq && chmod 750 /var/lib/fq
chmod 755 /opt/footballquiz /opt/footballquiz/releases

if [ ! -f /etc/footballquiz.env ]; then
  cat > /etc/footballquiz.env <<EOT
FQ_ADMIN_USER=admin
FQ_ADMIN_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_urlsafe(14)+"Aa1")')
EOT
  chmod 600 /etc/footballquiz.env
  echo "Initial admin credentials are in /etc/footballquiz.env (change the password after first login)."
fi

cp "$(dirname "$0")/footballquiz.service" /etc/systemd/system/
systemctl daemon-reload && systemctl enable footballquiz

cat > /etc/sudoers.d/deploy <<EOT
deploy ALL=(root) NOPASSWD: /bin/systemctl restart footballquiz
EOT
chmod 440 /etc/sudoers.d/deploy

sed "s/quiz.example.com/$DOMAIN/" "$(dirname "$0")/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

# Nightly backup of database + uploads (keeps 14)
cat > /etc/cron.daily/fq-backup <<'EOT'
#!/bin/sh
mkdir -p /var/backups/fq
tar czf /var/backups/fq/fq-$(date +%F).tgz -C /var/lib fq
ls -1t /var/backups/fq/*.tgz | tail -n +15 | xargs -r rm -f
EOT
chmod +x /etc/cron.daily/fq-backup
echo "Done. Add the GitHub deploy public key to /home/deploy/.ssh/authorized_keys, then push to main."
