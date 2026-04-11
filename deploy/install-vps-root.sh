#!/usr/bin/env bash
# Запускать НА VPS под root (один раз).
#   export BOT_TOKEN='цифры:секрет'
#   bash install-vps-root.sh
# Или: curl -fsSL https://raw.githubusercontent.com/srgsprn/photocrop/main/deploy/install-vps-root.sh | bash -s
#   (тогда перед этим: export BOT_TOKEN='...')
set -euo pipefail

if [[ -z "${BOT_TOKEN:-}" ]]; then
  echo "Укажите токен:  export BOT_TOKEN='123456:AA...'" >&2
  exit 1
fi

INSTALL="/opt/mouse-photo-crop-bot"
REPO="https://github.com/srgsprn/photocrop.git"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git

if ! id photocrop &>/dev/null; then
  useradd -r -m -s /bin/bash -d "$INSTALL" photocrop
fi
mkdir -p "$INSTALL"
chown -R photocrop:photocrop "$INSTALL"

if [[ ! -f "$INSTALL/bot.py" ]]; then
  sudo -u photocrop -H git clone "$REPO" "$INSTALL"
fi
sudo -u photocrop -H bash -c "cd \"$INSTALL\" && git pull --ff-only"

if [[ ! -x "$INSTALL/.venv/bin/python" ]]; then
  sudo -u photocrop -H bash -c "cd \"$INSTALL\" && python3 -m venv .venv && .venv/bin/pip install -q -U pip"
fi
sudo -u photocrop -H bash -c "cd \"$INSTALL\" && .venv/bin/pip install -q -r requirements.txt"

umask 077
printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN" > /tmp/mpcb.env.$$
chmod 600 /tmp/mpcb.env.$$
chown photocrop:photocrop /tmp/mpcb.env.$$
mv -f /tmp/mpcb.env.$$ "$INSTALL/.env"

cp "$INSTALL/deploy/mouse-photo-crop-bot.service" /etc/systemd/system/mouse-photo-crop-bot.service
systemctl daemon-reload
systemctl enable mouse-photo-crop-bot
systemctl restart mouse-photo-crop-bot
sleep 2
systemctl --no-pager status mouse-photo-crop-bot || true
echo "=== journalctl (last 35) ==="
journalctl -u mouse-photo-crop-bot -n 35 --no-pager
