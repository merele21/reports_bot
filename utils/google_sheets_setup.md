# 📊 Настройка Google Sheets API для /list_rn

## Обзор

Команда `/list_rn` теперь поддерживает 3 формата вывода:
1. **📱 В текущий канал** - обычное сообщение в Telegram
2. **📊 Google Sheets** - экспорт в таблицу с автоочисткой
3. **📄 Excel файл** - скачиваемый .xlsx файл

## Часть 1: Настройка Google Sheets API

### Шаг 1: Создание проекта в Google Cloud Console

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект:
   - Нажмите на выпадающий список проектов вверху
   - Нажмите "New Project"
   - Название: `TelegramBotStats` (или любое другое)
   - Нажмите "Create"

### Шаг 2: Включение Google Sheets API

1. В боковом меню выберите **"APIs & Services" > "Library"**
2. Найдите **"Google Sheets API"**
3. Нажмите на него и нажмите **"Enable"**
4. Повторите для **"Google Drive API"** (тоже нужно включить)

### Шаг 3: Создание Service Account

1. Перейдите в **"APIs & Services" > "Credentials"**
2. Нажмите **"Create Credentials" > "Service Account"**
3. Заполните форму:
   - **Service account name**: `telegram-bot-stats`
   - **Service account ID**: (автоматически заполнится)
   - **Description**: `Service account for Telegram bot statistics export`
4. Нажмите **"Create and Continue"**
5. В разделе "Grant this service account access to project":
   - **Role**: выберите `Editor` (или `Owner` для полного доступа)
   - Нажмите **"Continue"**
6. Нажмите **"Done"**

### Шаг 4: Создание ключа (credentials.json)

1. В списке Service Accounts найдите созданный аккаунт
2. Нажмите на него (на email вида `telegram-bot-stats@...`)
3. Перейдите на вкладку **"Keys"**
4. Нажмите **"Add Key" > "Create new key"**
5. Выберите тип **JSON**
6. Нажмите **"Create"**
7. Файл `credentials.json` автоматически скачается
8. **ВАЖНО**: Сохраните этот файл в безопасном месте!

### Шаг 5: Создание Google Sheets таблицы

1. Перейдите в [Google Sheets](https://sheets.google.com/)
2. Создайте новую таблицу:
   - Нажмите "+ Blank" или "Создать"
   - Название: `Статистика бота` (или любое другое)
3. **ВАЖНО**: Скопируйте ID таблицы из URL:
   ```
   https://docs.google.com/spreadsheets/d/1ABC...XYZ/edit
                                          ^^^^^^^^
                                          Это ID таблицы
   ```
4. Откройте доступ для Service Account:
   - Нажмите кнопку **"Share"** (Поделиться)
   - Вставьте email вашего Service Account (из credentials.json, поле `client_email`)
   - Выберите роль **"Editor"**
   - **СНИМИТЕ галочку** "Notify people" (чтобы не отправлять email)
   - Нажмите **"Share"**

## Часть 2: Установка зависимостей

### Установка Python пакетов

```bash
# Основные библиотеки для Google Sheets
pip install gspread google-auth google-auth-oauthlib google-auth-httplib2 --break-system-packages

# Библиотека для Excel
pip install openpyxl --break-system-packages
```

## Часть 3: Настройка проекта

### Шаг 1: Размещение credentials.json

```bash
# Создайте директорию для credentials (если еще нет)
mkdir -p /path/to/your/bot/credentials

# Скопируйте скачанный файл
cp ~/Downloads/credentials.json /path/to/your/bot/credentials/google_sheets_credentials.json
```

### Шаг 2: Обновление .env файла

Добавьте в `.env`:

```env
# === Google Sheets Configuration ===
GOOGLE_SHEETS_CREDENTIALS_PATH=/path/to/your/bot/credentials/google_sheets_credentials.json
GOOGLE_SHEETS_STATS_SPREADSHEET_ID=1ABC...XYZ

# ПРИМЕР:
# GOOGLE_SHEETS_CREDENTIALS_PATH=/home/user/bot/credentials/google_sheets_credentials.json
# GOOGLE_SHEETS_STATS_SPREADSHEET_ID=1ABCdefGHIjklMNOpqrSTUvwxYZ123456789
```

### Шаг 3: Копирование файлов

```bash
# Скопируйте файлы в проект
cp list_rn_v2.py bot/handlers/admin/list_rn.py
cp google_sheets_exporter.py bot/utils/google_sheets_exporter.py
cp excel_exporter.py bot/utils/excel_exporter.py
```

### Шаг 4: Обновление __init__.py

В `bot/handlers/admin/__init__.py`:

```python
from . import (
    # ... existing imports ...
    list_rn  # <- ДОБАВЬТЕ
)

router.include_router(list_rn.router)  # <- ДОБАВЬТЕ
```

В `bot/utils/__init__.py` (создайте если нет):

```python
from .user_grouping import *
from .google_sheets_exporter import GoogleSheetsExporter
from .excel_exporter import ExcelExporter

__all__ = [
    'GoogleSheetsExporter',
    'ExcelExporter',
]
```

### Шаг 5: Обновление commands_ui.py

```python
admin_commands = user_commands + [
    # ... existing commands ...
    BotCommand(command="list_rn", description="📊 Текущая статистика"),
]
```

## Часть 4: Тестирование

### Проверка подключения к Google Sheets

Создайте тестовый скрипт `test_google_sheets.py`:

```python
import os
from utils.google_sheets_exporter import GoogleSheetsExporter

# Проверяем переменные окружения
print("Credentials path:", os.getenv('GOOGLE_SHEETS_CREDENTIALS_PATH'))
print("Spreadsheet ID:", os.getenv('GOOGLE_SHEETS_STATS_SPREADSHEET_ID'))

# Пробуем подключиться
try:
    exporter = GoogleSheetsExporter()
    print("✅ Google Sheets API подключен успешно!")
except Exception as e:
    print(f"❌ Ошибка подключения: {e}")
```

Запустите:
```bash
python test_google_sheets.py
```

### Тестирование команды

1. Запустите бота
2. В канале с событиями выполните `/list_rn`
3. Выберите формат вывода
4. Проверьте результат

## Использование

### Вариант 1: Вывод в канал

```
/list_rn
→ Выбрать "📱 В текущий канал"
```

Результат: обычное сообщение в Telegram

### Вариант 2: Экспорт в Google Sheets

```
/list_rn
→ Выбрать "📊 Google Sheets"
```

Результат:
- Таблица полностью очищается
- Заполняется новыми данными
- Применяется красивое форматирование
- Бот отправляет ссылку на таблицу

### Вариант 3: Скачать Excel

```
/list_rn
→ Выбрать "📄 Excel файл"
```

Результат:
- Создается .xlsx файл
- Применяется форматирование
- Файл отправляется в чат для скачивания

## Форматирование таблиц

### Google Sheets

**Цвета:**
- 🔵 Заголовок: синий фон, белый текст
- ⬜ Подзаголовки: светло-серый фон
- 🟡 Предупреждения (⚠️): светло-желтый фон
- 🔴 Ошибки (❌): светло-красный фон
- 🟢 Успех (✅, 🎉): светло-зеленый фон

**Структура:**
- Автоматическая ширина колонок
- Границы ячеек
- Выравнивание текста
- Шрифт Arial

### Excel

**То же самое + дополнительно:**
- Перенос текста в длинных ячейках
- Фиксированная ширина колонок
- Готов к печати

## Troubleshooting

### Ошибка: "Missing environment variables"

**Причина:** Не установлены переменные окружения

**Решение:**
```bash
# Проверьте .env
cat .env | grep GOOGLE_SHEETS

# Должно быть:
GOOGLE_SHEETS_CREDENTIALS_PATH=/path/to/credentials.json
GOOGLE_SHEETS_STATS_SPREADSHEET_ID=your_spreadsheet_id
```

### Ошибка: "Permission denied" при доступе к таблице

**Причина:** Service Account не имеет доступа к таблице

**Решение:**
1. Откройте таблицу в браузере
2. Нажмите "Share"
3. Добавьте email Service Account с ролью Editor
4. Email можно найти в credentials.json → `client_email`

### Ошибка: "File not found: credentials.json"

**Причина:** Неправильный путь к файлу

**Решение:**
```bash
# Проверьте путь
ls -la /path/to/credentials.json

# Обновите .env с правильным путем
GOOGLE_SHEETS_CREDENTIALS_PATH=/correct/path/to/credentials.json
```

### Ошибка: "gspread module not found"

**Причина:** Не установлены зависимости

**Решение:**
```bash
pip install gspread google-auth --break-system-packages
```

### Таблица не очищается

**Причина:** Возможно, ошибка в коде очистки

**Проверка:**
```python
# В google_sheets_exporter.py проверьте метод export_stats
# Должны быть строки:
worksheet.clear()
worksheet.clear_basic_filter()
```

### Excel файл не создается

**Причина:** Не установлена библиотека openpyxl

**Решение:**
```bash
pip install openpyxl --break-system-packages
```

## Безопасность

### ⚠️ ВАЖНО: credentials.json

1. **НЕ КОММИТЬТЕ** credentials.json в Git!
2. Добавьте в `.gitignore`:
   ```
   credentials/
   *.json
   !package.json
   ```

3. Храните credentials.json в безопасном месте
4. Если файл утерян или скомпрометирован:
   - Удалите старый ключ в Google Cloud Console
   - Создайте новый ключ
   - Обновите файл

### Права доступа

Service Account должен иметь доступ ТОЛЬКО к конкретной таблице статистики, а не ко всем вашим Google Sheets.

## Автоматизация

### Планирование автоматического экспорта

Можно настроить автоматический экспорт каждый час:

```python
# В bot/scheduler/tasks.py

async def auto_export_stats():
    """Автоматический экспорт статистики каждый час"""
    async with async_session_maker() as session:
        channels = await ChannelCRUD.get_all_active(session)
        
        for channel in channels:
            stats_data = await _collect_stats_data(session, channel.id)
            exporter = GoogleSheetsExporter()
            await exporter.export_stats(stats_data)

# Добавить в scheduler:
scheduler.add_job(
    auto_export_stats,
    trigger=CronTrigger(minute=0, timezone=settings.TZ),  # Каждый час
    id="auto_export_stats"
)
```

## Расширенные возможности

### Множественные таблицы

Можно создать отдельную таблицу для каждого канала:

```python
# В .env
GOOGLE_SHEETS_CHANNEL_1_ID=...
GOOGLE_SHEETS_CHANNEL_2_ID=...

# В коде
spreadsheet_id = os.getenv(f'GOOGLE_SHEETS_{channel.title.upper()}_ID')
```

### История экспортов

Добавить новый лист вместо очистки:

```python
# Вместо worksheet.clear()
timestamp = datetime.now().strftime('%Y%m%d_%H%M')
new_sheet = spreadsheet.add_worksheet(
    title=f"Stats_{timestamp}",
    rows=1000,
    cols=20
)
```

### Графики и визуализация

Добавить графики в Google Sheets:

```python
# После заполнения данных
chart = {
    "addChart": {
        "chart": {
            "spec": {
                "title": "Статистика по событиям",
                # ... настройки графика
            }
        }
    }
}
worksheet.spreadsheet.batch_update({"requests": [chart]})
```

---

**Версия:** 2.0  
**Дата:** 2026-02-09  
**Автор:** Telegram Bot Stats System