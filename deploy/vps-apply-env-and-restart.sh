#!/usr/bin/env bash
# Запускать на СВОЁМ Mac, где работает: ssh root@85.239.51.175
# Токен не попадает в git.
#
#   export BOT_TOKEN='ваш_токен_от_BotFather'
#   bash deploy/vps-apply-env-and-restart.sh root@85.239.51.175
#
set -euo pipefail
TARGET="${1:-root@85.239.51.175}"
if [[ -z "${BOT_TOKEN:-}" ]]; then
  echo "Сначала: export BOT_TOKEN='...'" >&2
  exit 1
fi

B64=$(printf '%s' "$BOT_TOKEN" | base64 | tr -d '\n')

# Без BatchMode: можно вводить пароль SSH (если нет ключа).
ssh "$TARGET" "export BASE=\"$B64\"; bash -s" <<'REMOTE'
set -euo pipefail
BOT_TOKEN=$(printf '%s' "$BASE" | base64 -d)
INSTALL="/opt/mouse-photo-crop-bot"

if ! command -v python3 &>/dev/null || ! python3 -m venv -h &>/dev/null; then
  apt-get update -qq
  apt-get install -y -qq python3-venv python3-pip git
fi

if ! id photocrop &>/dev/null; then
  useradd -r -m -s /bin/bash -d "$INSTALL" photocrop
fi
mkdir -p "$INSTALL"
chown -R photocrop:photocrop "$INSTALL"

REPO="https://github.com/srgsprn/photocrop.git"
if sudo -u photocrop -H test -d "$INSTALL/.git"; then
  sudo -u photocrop -H bash -c "cd \"$INSTALL\" && git remote get-url origin &>/dev/null || git remote add origin \"$REPO\""
  sudo -u photocrop -H bash -c "cd \"$INSTALL\" && git fetch origin && (git checkout -B main origin/main 2>/dev/null || true) && (git pull --ff-only origin main || git pull --ff-only || true)"
else
  tmp="$(mktemp -d /tmp/photocrop-install.XXXXXX)"
  chown photocrop:photocrop "$tmp"
  sudo -u photocrop -H git clone --depth 1 "$REPO" "$tmp/repo"
  sudo -u photocrop -H cp -a "$tmp/repo"/. "$INSTALL/"
  rm -rf "$tmp"
fi
if [[ ! -x "$INSTALL/.venv/bin/python" ]]; then
  sudo -u photocrop -H bash -c "cd \"$INSTALL\" && python3 -m venv .venv && .venv/bin/pip install -q -U pip"
fi
sudo -u photocrop -H bash -c "cd \"$INSTALL\" && .venv/bin/pip install -q -r requirements.txt"

printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN" > /tmp/mpcb.env.$$
chmod 600 /tmp/mpcb.env.$$
chown photocrop:photocrop /tmp/mpcb.env.$$
mv /tmp/mpcb.env.$$ "$INSTALL/.env"

cp "$INSTALL/deploy/mouse-photo-crop-bot.service" /etc/systemd/system/mouse-photo-crop-bot.service
systemctl daemon-reload
systemctl enable mouse-photo-crop-bot
systemctl restart mouse-photo-crop-bot
sleep 2
systemctl --no-pager status mouse-photo-crop-bot || true
echo "--- последние логи ---"
journalctl -u mouse-photo-crop-bot -n 30 --no-pager
REMOTE
