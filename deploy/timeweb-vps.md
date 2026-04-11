# Деплой на VPS (Timeweb Cloud и любой Ubuntu/Debian)

Бот живёт **отдельно** от других проектов: свой каталог `/opt/mouse-photo-crop-bot`, свой системный пользователь `photocrop`, свой `systemd`-юнит. С другими приложениями не пересекается.

## 1. Репозиторий на GitHub

На своём Mac (или локально):

```bash
cd /path/to/photocrop
git init   # если ещё нет
git add -A
git commit -m "Initial commit: mouse photo crop bot"
```

Создайте **пустой** репозиторий на GitHub (без README, чтобы не конфликтовало), затем:

```bash
git remote add origin https://github.com/YOUR_USER/mouse-photo-crop-bot.git
git branch -M main
git push -u origin main
```

Не коммитьте `.env` и токен — в `.gitignore` уже есть `.env`.

## 2. На сервере (под root по SSH)

```bash
ssh root@YOUR_SERVER_IP
```

### Пользователь и каталог

```bash
useradd -r -m -s /bin/bash -d /opt/mouse-photo-crop-bot photocrop
chown -R photocrop:photocrop /opt/mouse-photo-crop-bot
sudo -u photocrop -H bash -c 'cd /opt/mouse-photo-crop-bot && git clone https://github.com/YOUR_USER/mouse-photo-crop-bot.git .'
```

Если репозиторий приватный — настройте [deploy key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) или клонируйте под `photocrop` с HTTPS + token.

### Python и venv

```bash
apt-get update
apt-get install -y python3-venv python3-pip git
sudo -u photocrop -H bash -c '
cd /opt/mouse-photo-crop-bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
'
```

Первый запуск скачает модель **rembg** (~176 МБ). Чтобы не тянуть модель на слабом VPS:

```bash
echo "CROP_USE_REMBG=0" >> /opt/mouse-photo-crop-bot/.env
```

(только OpenCV; для скринов маркетплейсов часто достаточно.)

### Токен бота

```bash
nano /opt/mouse-photo-crop-bot/.env
```

Содержимое (подставьте **новый** токен после `/revoke` у BotFather, если старый светился где-то):

```
BOT_TOKEN=123456789:AA...ваш_новый_токен
```

Права:

```bash
chown photocrop:photocrop /opt/mouse-photo-crop-bot/.env
chmod 600 /opt/mouse-photo-crop-bot/.env
```

### systemd

Скопируйте юнит из репозитория:

```bash
cp /opt/mouse-photo-crop-bot/deploy/mouse-photo-crop-bot.service /etc/systemd/system/mouse-photo-crop-bot.service
systemctl daemon-reload
systemctl enable mouse-photo-crop-bot
systemctl start mouse-photo-crop-bot
systemctl status mouse-photo-crop-bot
```

Логи:

```bash
journalctl -u mouse-photo-crop-bot -f
```

## 3. Обновление кода

```bash
sudo -u photocrop -H bash -c 'cd /opt/mouse-photo-crop-bot && git pull && .venv/bin/pip install -r requirements.txt'
systemctl restart mouse-photo-crop-bot
```

## Файрвол

Если включён `ufw`, для **long polling** исходящих достаточно (бот сам ходит к Telegram API). Входящие порты для бота не нужны.
