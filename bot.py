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
from typing import Deque, Dict, List, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message, ReplyParameters

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
_worker_sem = asyncio.Semaphore(max(1, _bot_cfg.max_parallel_jobs))

ALLOWED_DOC_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

# Альбом: ждём все части media_group, затем один ответ
ALBUM_DEBOUNCE_SEC = 1.25
_album_buffers: Dict[Tuple[int, str], List[Message]] = {}
_album_flush_tasks: Dict[Tuple[int, str], asyncio.Task] = {}
STARTUP_RETRY_DELAY_SEC = 8
STARTUP_MAX_DELAY_SEC = 60


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


async def _download_largest_photo(message: Message) -> bytes:
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buf = BytesIO()
    await message.bot.download_file(file.file_path, buf)
    return buf.getvalue()


async def _process_bytes_with_limits(data: bytes) -> ProcessOutcome:
    """
    CPU-heavy crop executed in a bounded worker slot with timeout.
    Prevents bot-wide stalls under burst load.
    """
    timeout = max(5, int(_bot_cfg.process_timeout_sec))
    async with _worker_sem:
        return await asyncio.wait_for(
            asyncio.to_thread(process_image_bytes, data),
            timeout=timeout,
        )


async def _process_album_and_reply(messages: List[Message]) -> None:
    """Обрезка всех фото альбома и ответ одной медиа-группой (до 10 за раз)."""
    messages = sorted({m.message_id: m for m in messages}.values(), key=lambda m: m.message_id)
    if not messages:
        return
    first = messages[0]
    uid = first.from_user.id if first.from_user else 0

    for _ in messages:
        if not _rate_allow(uid):
            await first.answer(
                "⏳ Слишком много изображений за короткое время. Подождите минуту и попробуйте снова."
            )
            return

    for m in messages:
        if m.photo is None:
            continue
        ph = m.photo[-1]
        if ph.file_size and ph.file_size > _bot_cfg.max_image_bytes:
            await first.answer(
                "❌ Одно из фото слишком большое. До "
                f"{_bot_cfg.max_image_bytes // (1024 * 1024)} МБ на файл."
            )
            return

    status = await first.answer(f"⏳ Обрезаю {len(messages)} фото…")
    outcomes: List[ProcessOutcome] = []
    try:
        for m in messages:
            try:
                data = await _download_largest_photo(m)
            except Exception:
                logger.exception("Album: download failed")
                await status.delete()
                await first.answer("❌ Не удалось скачать одно из фото из Telegram.")
                return
            if len(data) > _bot_cfg.max_image_bytes:
                await status.delete()
                await first.answer("❌ Одно из фото слишком большое.")
                return
            try:
                out = await _process_bytes_with_limits(data)
            except ValueError as e:
                await status.delete()
                await first.answer(f"❌ {e}")
                return
            except asyncio.TimeoutError:
                logger.warning("Album: timeout while processing image")
                await status.delete()
                await first.answer(
                    "⏱️ Одно из фото обрабатывалось слишком долго. "
                    "Попробуй фото меньшего размера."
                )
                return
            except Exception:
                logger.exception("Album: crop failed")
                await status.delete()
                await first.answer("❌ Не получилось обработать одно из фото.")
                return
            outcomes.append(out)
    finally:
        try:
            await status.delete()
        except Exception:
            pass

    if not outcomes:
        return

    logger.info(
        "Album OK user=%s count=%s methods=%s",
        uid,
        len(outcomes),
        [o.method for o in outcomes],
    )

    bot = first.bot
    chat_id = first.chat.id
    reply_to = first.message_id

    for i in range(0, len(outcomes), 10):
        chunk = outcomes[i : i + 10]
        media: List[InputMediaPhoto] = []
        for j, out in enumerate(chunk):
            global_idx = i + j
            bf = BufferedInputFile(
                file=out.data,
                filename=f"mouse_crop_{global_idx + 1}.png",
            )
            media.append(InputMediaPhoto(media=bf))
        await bot.send_media_group(
            chat_id=chat_id,
            media=media,
            reply_parameters=ReplyParameters(message_id=reply_to),
        )


def _schedule_album_flush(key: Tuple[int, str]) -> None:
    async def _flush() -> None:
        try:
            await asyncio.sleep(ALBUM_DEBOUNCE_SEC)
        except asyncio.CancelledError:
            return
        msgs = _album_buffers.pop(key, [])
        _album_flush_tasks.pop(key, None)
        if msgs:
            try:
                await _process_album_and_reply(msgs)
            except Exception:
                logger.exception("Album flush task crashed key=%s", key)
                first = msgs[0]
                await first.answer("❌ Ошибка обработки альбома. Попробуй отправить ещё раз.")

    if key in _album_flush_tasks:
        _album_flush_tasks[key].cancel()
    task = asyncio.create_task(_flush())
    _album_flush_tasks[key] = task


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
        outcome = await _process_bytes_with_limits(data)
    except ValueError as e:
        logger.info("Reject image user=%s: %s", uid, e)
        await status.delete()
        await message.answer(f"❌ {e}")
        return
    except asyncio.TimeoutError:
        logger.warning("Timeout user=%s source=%s", uid, source)
        await status.delete()
        await message.answer(
            "⏱️ Обработка заняла слишком много времени. "
            "Попробуй отправить фото поменьше."
        )
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
        photo=BufferedInputFile(file=outcome.data, filename="mouse_crop.png"),
    )


async def _wait_for_telegram_api(bot: Bot) -> None:
    """
    Не валим процесс при временной недоступности Telegram API.
    Ждём сеть и только потом начинаем polling.
    """
    delay = STARTUP_RETRY_DELAY_SEC
    while True:
        try:
            me = await bot.get_me(request_timeout=60)
            logger.info(
                "Telegram API OK for @%s (id=%s), workers=%s timeout=%ss",
                me.username,
                me.id,
                _bot_cfg.max_parallel_jobs,
                _bot_cfg.process_timeout_sec,
            )
            return
        except TelegramNetworkError:
            logger.exception(
                "Telegram API timeout on startup; retry in %ss",
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(STARTUP_MAX_DELAY_SEC, delay + 5)
        except Exception:
            logger.exception(
                "Unexpected startup error while contacting Telegram; retry in %ss",
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(STARTUP_MAX_DELAY_SEC, delay + 5)


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>Product crop bot</b> (@mouse_photo_crop_bot)\n\n"
        "Пришлите <b>скриншот</b> или фото страницы — я обрежу лишнее "
        "(поля, интерфейс браузера) и оставлю основную картинку/карточку.\n\n"
        "Можно отправить как <b>фото</b> или как <b>файл</b> (PNG, JPG, WebP).\n"
        "Несколько фото <b>одним альбомом</b> — отвечу тоже <b>альбомом</b> (до 10 за раз)."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📷 <b>Как пользоваться</b>\n\n"
        "• Фото или картинка-документ с сайта.\n"
        "• Бот ищет основной визуальный блок и обрезает поля.\n"
        "• Если уверенности мало — пришлю исходник без кропа.\n"
        "• Несколько фото альбомом — верну обрезанные одним альбомом.\n\n"
        "<b>Канал:</b> бот <b>не может</b> сам класть посты в «отложенные» публикации "
        "(так устроен Telegram Bot API). Можно позже добавить отправку в канал "
        "сразу или планировщик на сервере.\n\n"
        "<b>Совет:</b> чтобы товар был крупнее в кадре — результат обычно лучше."
    )


@dp.message(F.photo, F.media_group_id)
async def on_photo_album_piece(message: Message) -> None:
    mg = message.media_group_id
    if mg is None:
        return
    key = (message.chat.id, str(mg))
    _album_buffers.setdefault(key, []).append(message)
    _schedule_album_flush(key)


@dp.message(F.photo, ~F.media_group_id)
async def on_photo_single(message: Message) -> None:
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
    await _wait_for_telegram_api(bot)

    # Иначе при включённом webhook getUpdates пустой — бот «молчит».
    # Из-за сетевых лагов это тоже делаем с ретраями.
    while True:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
            return
        except TelegramNetworkError:
            logger.exception(
                "Polling/network error; keep process alive and retry in %ss",
                STARTUP_RETRY_DELAY_SEC,
            )
            await asyncio.sleep(STARTUP_RETRY_DELAY_SEC)
        except Exception:
            logger.exception(
                "Unhandled polling crash; retry in %ss",
                STARTUP_RETRY_DELAY_SEC,
            )
            await asyncio.sleep(STARTUP_RETRY_DELAY_SEC)


if __name__ == "__main__":
    asyncio.run(main())
