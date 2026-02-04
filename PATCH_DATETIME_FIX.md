# Патч для исправления ошибки "NameError: name 'datetime' is not defined"

## Проблема
Отсутствовал импорт `datetime` в файле `bot/handlers/reports.py`, что вызывало ошибку:
```
NameError: name 'datetime' is not defined
```

## Решение
Файл `bot/handlers/reports.py` был обновлен с правильными импортами.

## Что изменено

**Файл:** `bot/handlers/reports.py`

**Строки 1-15 (было):**
```python
import logging
import json
from asyncio import sleep
from datetime import date

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import (
    UserCRUD, ChannelCRUD, ReportCRUD, UserChannelCRUD, EventCRUD,
    TempEventCRUD, CheckoutEventCRUD, CheckoutSubmissionCRUD, CheckoutReportCRUD,
    extract_keywords_from_text, normalize_keyword, parse_checkout_keywords
)
```

**Строки 1-16 (стало):**
```python
import logging
import json
from asyncio import sleep
from datetime import date, datetime
import pytz

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.crud import (
    UserCRUD, ChannelCRUD, ReportCRUD, UserChannelCRUD, EventCRUD,
    TempEventCRUD, CheckoutEventCRUD, CheckoutSubmissionCRUD, CheckoutReportCRUD,
    extract_keywords_from_text, normalize_keyword, parse_checkout_keywords
)
```

## Что добавлено
1. `, datetime` в импорт из datetime
2. `import pytz`
3. `from bot.config import settings`

## Что удалено
Удалены дублирующиеся импорты внутри функций (они теперь импортируются в начале файла).

## Как применить патч

### Вариант 1: Автоматически (если используете обновленный архив)
Новый архив уже содержит исправленный файл. Просто распакуйте и используйте.

### Вариант 2: Вручную
Если вы уже распаковали старый архив, откройте файл `bot/handlers/reports.py` и замените первые 15 строк на исправленный код выше.

### Вариант 3: Только для этого файла
```bash
# Скачайте исправленный файл из нового архива
cd report-bot-local/bot/handlers/
# Замените reports.py
```

## Проверка
После применения патча проверьте синтаксис:
```bash
python -m py_compile bot/handlers/reports.py
```

Если нет ошибок - патч применен успешно!

## Перезапуск бота
```bash
sudo systemctl restart report-bot
# или
# Ctrl+C и затем python -m bot.main
```

## Проверка работы
После перезапуска проверьте логи:
```bash
journalctl -u report-bot -f
# или
tail -f logs/bot.log
```

Ошибка `NameError: name 'datetime' is not defined` больше не должна появляться.
