"""
Telegram bot: upload screenshots → get back images cropped to the product only.
Send one or several photos; the bot crops each to the main subject (bag, clothes, etc.).
"""
import asyncio
import logging
from io import BytesIO

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from crop_engine import process_image_bytes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set your token in env: BOT_TOKEN=...
import os
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

dp = Dispatcher()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>Product crop bot</b>\n\n"
        "Send me one or several <b>screenshots</b> (photos).\n"
        "I’ll automatically crop each image to the main object — bag, clothes, accessory — "
        "and send back the cropped versions.\n\n"
        "You can send multiple photos in one message (as an album) or one by one.\n\n"
        "No commands needed: just send the pictures."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📷 <b>How to use</b>\n\n"
        "• Send a photo (screenshot of a product page).\n"
        "• Or send several photos at once (album).\n"
        "• I’ll detect the product, cut off the rest (browser, UI) and send the cropped image(s) back.\n\n"
        "Best results: product is clearly visible and not too small in the screenshot."
    )


async def process_one_photo(message: Message, photo_bytes: bytes) -> bool:
    """Process one photo: crop and send. Returns True if crop succeeded."""
    try:
        result = await asyncio.to_thread(process_image_bytes, photo_bytes, 12)
    except Exception as e:
        logger.exception("Crop failed for one image")
        await message.answer(f"❌ Error processing image: {e}")
        return False
    if result is None:
        await message.answer("⚠️ Could not detect a clear subject in this image. Try a screenshot where the product is more visible.")
        return False
    await message.answer_photo(
        photo=BufferedInputFile(file=result, filename="cropped.png"),
        caption="✅ Cropped to product",
    )
    return True


@dp.message(F.photo)
async def on_photo(message: Message) -> None:
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buf = BytesIO()
    await message.bot.download_file(file.file_path, buf)
    buf.seek(0)
    data = buf.read()

    status = await message.answer("⏳ Cropping…")
    await process_one_photo(message, data)
    await status.delete()


async def main() -> None:
    if not BOT_TOKEN:
        logger.error("Set BOT_TOKEN environment variable")
        return
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())