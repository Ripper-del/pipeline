# Берем легкий официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем библиотеки
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код
COPY . .

# bot.py пишет в HEARTBEAT_FILE каждые 30с - если файл не обновлялся дольше 90с,
# процесс жив, но завис
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import time,sys; sys.exit(0 if time.time()-float(open('/tmp/heartbeat').read())<90 else 1)"
