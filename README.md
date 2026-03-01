# Product crop Telegram bot

Bot for Telegram that **automatically crops screenshots** to the main subject (bag, clothes, accessory). You send one or several photos — it detects the product, cuts off the rest (browser, UI, etc.) and sends back the cropped images.

No commands needed: just send the pictures (single or as an album).

## How it works

1. You send a screenshot (e.g. from a product page).
2. The bot uses [rembg](https://github.com/danielgatis/rembg) to detect the main object (subject/background removal).
3. It crops the image to the bounding box of that object and sends the result.

## Setup

### 1. Create a bot in Telegram

- Open [@BotFather](https://t.me/BotFather) in Telegram.
- Send `/newbot`, follow the steps, copy the **token**.

### 2. Install dependencies

```bash
cd telegram-crop-bot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Note:** First run will download the `u2net` model (~176 MB). Later runs use the cached model.

### 3. Run the bot

```bash
export BOT_TOKEN="your_bot_token_here"
python bot.py
```

Or use a `.env` file (install `python-dotenv` and load it in `bot.py` if you prefer).

### 4. Use it

- Open your bot in Telegram.
- Send `/start` for a short intro.
- Send one or several **photos** (screenshots). Each will be cropped to the product and sent back.

## Tips for best results

- Product should be clearly visible and not too small in the screenshot.
- One main object per image works best (e.g. one bag, one item of clothing).

## Optional: lighter model

To use a smaller/faster model, in `crop_engine.py` change:

```python
_session = new_session("u2netp")  # instead of "u2net"
```

`u2net` is more accurate; `u2netp` is faster and uses less memory.

## Deploy (бот 24/7 без ноутбука)

Если нужен бот, который работает всегда (даже когда компьютер выключен), разверни его на облаке. Подробно: **[DEPLOY.md](DEPLOY.md)** — там пошагово Railway и Render. Кратко: заливаешь репо на GitHub → подключаешь к Railway или Render → добавляешь переменную `BOT_TOKEN` → деплой.
