"""
Telegram bot: screenshots / photos / image documents → auto-cropped picture.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from io import BytesIO
from typing import Deque, Dict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import os

from config import DEFAULT_BOT_CONFIG
from crop_engine import ProcessOutcome, process_image_bytes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()

dp = Dispatcher()
bot: Bot | None = None


def _token_looks_valid(token: str) -> bool:
    # BotFather: <digits>:<alphanumeric + _ -> ~35 chars; allow a bit of range
    return bool(re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token))

# user_id -> deque of unix timestamps (last 60s)
_rate: Dict[int, Deque[float]] = {}
_bot_cfg = DEFAULT_BOT_CONFIG

ALLOWED_DOC_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _rate_allow(user_id: int) -> bool:
    now = time.monotonic()
    window = 60.0
    q = _rate.setdefault(user_id, deque())
    while q and now - q[0] > window:
        q.popleft()
    limit = _bot_cfg.max_crops_per_minute
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def _caption_for(out: ProcessOutcome) -> str:
    if out.used_fallback_original:
        return (
            "ℹ️ Не удалось уверенно выделить объект — отправляю исходник без обрезки. "
            "Попробуйте скрин крупнее или с более контрастным фоном."
        )
    return "Фотка обрезана, маусок 🐭"


async def _process_and_reply(message: Message, data: bytes, source: str) -> None:
    user = message.from_user
    uid = user.id if user else 0
    if not _rate_allow(uid):
        await message.answer(
            "⏳ Слишком много изображений за короткое время. Подождите минуту и попробуйте снова."
        )
        logger.warning("Rate limited user_id=%s", uid)
        return

    if len(data) > _bot_cfg.max_image_bytes:
        await message.answer(
            "❌ Файл слишком большой. Отправьте изображение до "
            f"{_bot_cfg.max_image_bytes // (1024 * 1024)} МБ."
        )
        return

    status = await message.answer("⏳ Обрезаю…")
    try:
        outcome = await asyncio.to_thread(process_image_bytes, data)
    except ValueError as e:
        logger.info("Reject image user=%s: %s", uid, e)
        await status.delete()
        await message.answer(f"❌ {e}")
        return
    except Exception:
        logger.exception("Unexpected error user=%s source=%s", uid, source)
        await status.delete()
        await message.answer(
            "❌ Не получилось обработать файл. Проверьте, что это PNG/JPEG/WebP."
        )
        return

    await status.delete()
    logger.info(
        "OK user=%s source=%s method=%s fallback_orig=%s bytes_out=%s",
        uid,
        source,
        outcome.method,
        outcome.used_fallback_original,
        len(outcome.data),
    )
    await message.answer_photo(
        photo=BufferedInputFile(file=outcome.data, filename="cropped.png"),
        caption=_caption_for(outcome),
    )


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>Product crop bot</b> (@mouse_photo_crop_bot)\n\n"
        "Пришлите <b>скриншот</b> или фото страницы — я обрежу лишнее "
        "(поля, интерфейс браузера) и оставлю основную картинку/карточку.\n\n"
        "Можно отправить как <b>фото</b> или как <b>файл</b> (PNG, JPG, WebP).\n"
        "Несколько фото в одном сообщении обрабатываются по одному."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📷 <b>Как пользоваться</b>\n\n"
        "• Фото или картинка-документ с сайта.\n"
        "• Бот ищет основной визуальный блок и обрезает поля.\n"
        "• Если уверенности мало — пришлю исходник без кропа.\n\n"
        "<b>Совет:</b> чтобы товар был крупнее в кадре — результат обычно лучше."
    )


@dp.message(F.photo)
async def on_photo(message: Message) -> None:
    photo = message.photo[-1]
    try:
        file = await message.bot.get_file(photo.file_id)
        buf = BytesIO()
        await message.bot.download_file(file.file_path, buf)
        data = buf.getvalue()
    except Exception:
        logger.exception("Telegram download failed (photo)")
        await message.answer("❌ Не удалось скачать фото из Telegram. Попробуйте ещё раз.")
        return
    await _process_and_reply(message, data, "photo")


@dp.message(F.document)
async def on_document(message: Message) -> None:
    doc = message.document
    if not doc:
        return
    mime = (doc.mime_type or "").lower()
    if mime not in ALLOWED_DOC_MIME:
        await message.answer(
            "📎 Пришлите изображение как документ: <b>PNG, JPEG или WebP</b>."
        )
        return
    if doc.file_size and doc.file_size > _bot_cfg.max_image_bytes:
        await message.answer(
            "❌ Файл слишком большой. Уменьшите размер или отправьте как сжатое фото."
        )
        return
    try:
        file = await message.bot.get_file(doc.file_id)
        buf = BytesIO()
        await message.bot.download_file(file.file_path, buf)
        data = buf.getvalue()
    except Exception:
        logger.exception("Telegram download failed (document)")
        await message.answer("❌ Не удалось скачать файл. Попробуйте ещё раз.")
        return
    await _process_and_reply(message, data, f"document:{mime}")


@dp.message(~F.photo, ~F.document)
async def fallback_need_image(message: Message) -> None:
    """Ответ, если прислали не картинку — иначе кажется, что бот «спит»."""
    if message.text and message.text.startswith("/"):
        await message.answer("Неизвестная команда. Используйте /start или пришлите <b>фото</b> скрина.")
        return
    await message.answer(
        "📷 Пришлите скрин <b>как фотографию</b> (галерея → Фото), "
        "или <b>файлом</b> PNG / JPEG / WebP. Ссылка или текст без картинки не обрабатываются."
    )


async def main() -> None:
    global bot
    if not BOT_TOKEN:
        logger.error("Set BOT_TOKEN environment variable (never commit it to git).")
        return
    if not _token_looks_valid(BOT_TOKEN):
        logger.error(
            "BOT_TOKEN format looks wrong. Copy the full token from @BotFather "
            "(digits:secret, no spaces). If you leaked the token, use /revoke and create a new one."
        )
        return
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    me = await bot.get_me()
    logger.info("Starting bot @%s (id=%s) — long polling", me.username, me.id)
    # Иначе при включённом webhook getUpdates пустой — бот «молчит»
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
