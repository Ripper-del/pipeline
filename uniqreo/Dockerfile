# питон 3.11 слим
FROM python:3.11-slim

# системные зависимости
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# рабочая директория
WORKDIR /app

# установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# временные папки для обработки файлов
RUN mkdir -p /app/tmp_input /app/tmp_output

# копируем весь код проекта в контейнер
COPY . .

# команда для запуска бота
CMD ["python", "bot.py"]