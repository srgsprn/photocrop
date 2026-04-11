# Бот для Fly.io: зависимости ставятся при сборке образа
FROM python:3.11-slim

WORKDIR /app

# Зависимости (rembg, onnxruntime и т.д.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код бота
COPY bot.py crop_engine.py image_crop.py config.py ./

# Запуск (BOT_TOKEN задаётся через fly secrets)
CMD ["python", "bot.py"]
