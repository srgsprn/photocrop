#!/usr/bin/env bash
# Запускать НА VPS под root.
#   export BOT_TOKEN='цифры:секрет'
#   curl -fsSL .../install-vps-root.sh | env BOT_TOKEN="$BOT_TOKEN" bash
set -euo pipefail

echo "install-vps-root.sh v3 — clone via /tmp only (never git clone into home dir)"

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

# Клон только во временный каталог (у photocrop дом = $INSTALL, там .bashrc — не пустой).
sync_repo() {
  local tmp
  tmp="$(mktemp -d /tmp/photocrop-install.XXXXXX)"
  chown photocrop:photocrop "$tmp"
  if sudo -u photocrop -H test -d "$INSTALL/.git"; then
    sudo -u photocrop -H bash -c "cd \"$INSTALL\" && git remote get-url origin &>/dev/null || git remote add origin \"$REPO\""
    sudo -u photocrop -H bash -c "cd \"$INSTALL\" && git fetch origin && (git checkout -B main origin/main 2>/dev/null || true) && (git pull --ff-only origin main || git pull --ff-only || true)"
    rmdir "$tmp" 2>/dev/null || rm -rf "$tmp"
    return 0
  fi
  sudo -u photocrop -H git clone --depth 1 "$REPO" "$tmp/repo"
  sudo -u photocrop -H cp -a "$tmp/repo"/. "$INSTALL/"
  rm -rf "$tmp"
}

sync_repo

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
