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

## Быстрый вариант с Mac (одна команда)

Если у вас уже открывается `ssh root@IP`, на **своём** компьютере:

```bash
cd /path/to/photocrop
export BOT_TOKEN='вставьте_токен_от_BotFather'
bash deploy/vps-apply-env-and-restart.sh root@YOUR_SERVER_IP
```

Скрипт создаёт пользователя `photocrop`, клонирует/обновляет репо, пишет `.env`, ставит `systemd` и перезапускает бота.

---

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

---

## Ошибка: `Unit mouse-photo-crop-bot.service could not be found`

Значит на этом сервере **ещё не ставили** бота (нет файла в `/etc/systemd/system/`).

### Вариант A1 — один скрипт на сервере (рекомендуется)

На VPS под `root`:

```bash
export BOT_TOKEN='вставьте_токен_от_BotFather'
# ?v=… обходит кэш CDN, если тянулась старая версия скрипта
curl -fsSL "https://raw.githubusercontent.com/srgsprn/photocrop/main/deploy/install-vps-root.sh?v=$(date +%s)" | env BOT_TOKEN="$BOT_TOKEN" bash
```

`env` нужен, чтобы токен дошёл до `bash` из pipe. В начале вывода должно быть: `install-vps-root.sh v3`.

### Вариант A2 — вручную (как раньше)

Выполните подряд (токен подставьте свой в `nano`):

```bash
apt-get update && apt-get install -y python3-venv python3-pip git

id photocrop &>/dev/null || useradd -r -m -s /bin/bash -d /opt/mouse-photo-crop-bot photocrop
mkdir -p /opt/mouse-photo-crop-bot
chown -R photocrop:photocrop /opt/mouse-photo-crop-bot

sudo -u photocrop -H bash -c 'test -f /opt/mouse-photo-crop-bot/bot.py || git clone https://github.com/srgsprn/photocrop.git /opt/mouse-photo-crop-bot'
sudo -u photocrop -H bash -c 'cd /opt/mouse-photo-crop-bot && git pull'

sudo -u photocrop -H bash -c 'cd /opt/mouse-photo-crop-bot && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt'

install -m 600 -o photocrop -g photocrop /dev/null /opt/mouse-photo-crop-bot/.env
nano /opt/mouse-photo-crop-bot/.env
# одна строка: BOT_TOKEN=цифры:секрет

cp /opt/mouse-photo-crop-bot/deploy/mouse-photo-crop-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mouse-photo-crop-bot
systemctl status mouse-photo-crop-bot --no-pager
journalctl -u mouse-photo-crop-bot -n 40 --no-pager
```

### Вариант B — скрипт с вашего Mac

Раньше скрипт требовал SSH-ключ (`BatchMode`); теперь можно **ввести пароль**. На Mac:

```bash
cd /path/to/photocrop && git pull
export BOT_TOKEN='ваш_токен'
bash deploy/vps-apply-env-and-restart.sh root@85.239.51.175
```

### Ошибка: `destination path ... already exists and is not an empty directory`

Папка `/opt/mouse-photo-crop-bot` — это же **домашний каталог** пользователя `photocrop`, там изначально лежат `.bashrc` и др., поэтому обычный `git clone` в неё не работает. В актуальном **`install-vps-root.sh`** это обходится (клон во временный каталог + копирование файлов). Запустите установку ещё раз с GitHub (после `git pull` в репо или заново через `curl`).

---

### Важно: с какого хоста вы подключаетесь

Команда `ssh root@85.239.51.175` должна открывать **Timeweb VPS с ботом**. Если вы сначала зашли на другой сервер (`root@6890201-ng864376`), это нормально — второй `ssh` всё равно должен попасть на `85.239.51.175`. Проверка: на целевом сервере `hostname -I` должен содержать этот IPv4.

## 3. Обновление кода

```bash
sudo -u photocrop -H bash -c 'cd /opt/mouse-photo-crop-bot && git pull && .venv/bin/pip install -r requirements.txt'
systemctl restart mouse-photo-crop-bot
```

## Файрвол

Если включён `ufw`, для **long polling** исходящих достаточно (бот сам ходит к Telegram API). Входящие порты для бота не нужны.
