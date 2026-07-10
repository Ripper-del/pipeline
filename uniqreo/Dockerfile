# питон 3.11 слим
FROM python:3.11-slim

# системные зависимости (build-essential нужен, чтобы pip собрал tgcrypto -
# это C-расширение, готовых wheel под все платформы для него нет)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# рабочая директория
WORKDIR /app

# общий пакет для TikTok/AdsPower-автоматизации (используется uploader.py),
# кладём его сюда же, чтобы он резолвился как соседний top-level модуль "common"
COPY tiktok_scraper/common/ ./common

# полный tiktok_scraper - bot.py запускает automator.py подпроцессом (панель
# управления в ветках), common/ дублируется внутри, это ок и дёшево по месту
COPY tiktok_scraper/ ./tiktok_scraper
ENV TIKTOK_SCRAPER_DIR=/app/tiktok_scraper

# установка зависимостей
COPY uniqreo/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# временные папки для обработки файлов
RUN mkdir -p /app/tmp_input /app/tmp_output

# копируем весь код проекта в контейнер
COPY uniqreo/ .

# bot.py пишет в HEARTBEAT_FILE каждые 30с - если файл не обновлялся дольше 90с,
# процесс жив, но завис (например, застрял в ожидании капчи/сети)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import time,sys; sys.exit(0 if time.time()-float(open('/tmp/heartbeat').read())<90 else 1)"

# команда для запуска бота
CMD ["python", "bot.py"]
