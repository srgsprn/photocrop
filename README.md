# PhotoCrop

**Telegram-бот для автоматической обрезки скриншотов** — убирает пустые поля и выделяет основной объект на фото.

[![Telegram](https://img.shields.io/badge/Telegram-@mouse__photo__crop__bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/mouse_photo_crop_bot)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org)
[![OpenCV](https://img.shields.io/badge/OpenCV-computer_vision-5C3EE8?style=for-the-badge)](https://opencv.org)

> Бот: [@mouse_photo_crop_bot](https://t.me/mouse_photo_crop_bot) · [github.com/srgsprn/photocrop](https://github.com/srgsprn/photocrop)

---

## О проекте

Бот принимает фото или файл (PNG, JPEG, WebP) и возвращает аккуратно обрезанное изображение. Сделан **для своей девушки**, чтобы упростить её рабочие процессы с визуальным контентом.

Автор: **Sergei Suprun**

| | |
|---|---|
| **Задача** | Быстрая обрезка скриншотов без ручной работы в редакторе |
| **Стек** | Python, aiogram 3, OpenCV, rembg (u2net) |
| **Деплой** | VPS (systemd), Fly.io / Railway |

---

## Как работает

1. **OpenCV** — эвристики по градиентам, контурам и контрасту
2. **rembg** — сегментация, если CV не уверен в результате
3. **Fallback** — исходник, если кроп ненадёжен

---

## Быстрый старт

```bash
git clone https://github.com/srgsprn/photocrop.git
cd photocrop
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export BOT_TOKEN="your_token"
python bot.py
```

Пакетная обработка: `python batch_crop.py ./input ./output`

Деплой на VPS: [deploy/timeweb-vps.md](./deploy/timeweb-vps.md)

---

## Навыки

Computer vision · Telegram Bot API · async Python · production deploy

---

**Sergei Suprun** · [@srgsprn](https://github.com/srgsprn) · [sergeysuprun@list.ru](mailto:sergeysuprun@list.ru)
