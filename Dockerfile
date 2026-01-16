FROM python:3.11-slim

# Установка зависимостей системы
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Установка рабочей директории
WORKDIR /app

# Копирование файлов зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY bot ./bot

# Создание директории для БД (если используется SQLite)
RUN mkdir -p /app/data

# Установка часового пояса по умолчанию
ENV TZ=Europe/Moscow
ENV PYTHONUNBUFFERED=1

# Запуск бота
CMD ["python", "-m", "bot.main"]