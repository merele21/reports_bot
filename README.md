# Report Bot - Local 🏠

Полное окружение на вашем компьютере для комфортного использования!

## 🎯 Что включено

### 📦 Основные сервисы
- **Bot** - бот с hot-reload и debugger
- **SQLite** - база данных (не требует отдельного контейнера)
- **Redis** - кэширование и очереди
- **Prometheus** - метрики
- **Grafana** - визуализация
- **Loki** - логи
- **Alertmanager** - уведомления

### 🛠 Dev инструменты
- **MailHog** - тестирование email
- **Redis Commander** - UI для Redis
- **Jaeger** - distributed tracing
- **Portainer** - Docker UI
- **Debugpy** - Python debugger для IDE
- **ngrok** - публичный URL для тестов

### ✨ Фичи разработки
- 🔥 Hot-reload кода
- 🐛 Remote debugging (VS Code, PyCharm)
- 📊 Полный мониторинг
- 📝 Централизованные логи
- 🧪 Готовые тесты
- 🎨 Pre-commit hooks
- 📐 Линтеры и форматтеры

---

## 🚀 Быстрый старт

### Требования

```bash
# Минимальные требования
- Python 3.11+
- Docker 20.10+
- Docker Compose 2.0+
- Git
- Make (опционально)

# Рекомендуемые
- VS Code с расширениями
- 4GB RAM свободно
- 10GB свободного места
```

### Установка за 3 минуты

```bash
# 1. Клонировать и перейти в ветку
git clone https://github.com/your-repo/report-bot.git
cd report-bot
git checkout local

# 2. Инициализация
make init

# 3. Настройка .env.local
cp .env.local.example .env
nano .env  # Добавьте BOT_TOKEN

# 4. Запуск
make start

# 5. Открыть Grafana
make grafana-open
```

**Готово! 🎉** Все сервисы запущены.

---

## 📚 Основные команды

### Управление сервисами

```bash
make local              # Запуск (foreground, видны логи)
make local-bg           # Запуск (background)
make stop             # Остановка
make restart          # Перезапуск
make restart-bot      # Перезапуск только бота
```

### Логи

```bash
make logs             # Все логи
make logs-bot         # Только бот
make debug-logs       # Логи с фильтром debug/error
```

### Разработка

```bash
make shell            # Bash в контейнере бота
make ipython          # IPython в контейнере
make db-shell         # SQLite shell
```

### Тестирование

```bash
make test             # Запуск тестов
make test-watch       # Watch mode
make test-coverage    # С покрытием
make lint             # Линтеры
make format           # Форматирование
make all-checks       # Всё сразу
```

### Мониторинг

```bash
make metrics          # Метрики бота
make health           # Health check всех сервисов
make grafana-open     # Открыть Grafana
make prometheus-open  # Открыть Prometheus
make portainer-open   # Открыть Portainer
```

### Очистка

```bash
make clean            # Temporary files
make clean-logs       # Логи
make clean-docker     # Docker ресурсы
make clean-all        # Всё
```

---

## 🐛 Отладка

### VS Code Remote Debugging

1. Запустите бот:
   ```bash
   make debug
   ```

2. В VS Code: `Run → Start Debugging → Python: Remote Attach`

3. Поставьте breakpoint и отправьте команду боту

### Ручная отладка

```python
# В коде бота добавьте
import debugpy
debugpy.breakpoint()  # Остановит выполнение
```

### Логи в реальном времени

```bash
# Все логи с подсветкой
make logs | grep --color=always -E 'ERROR|WARNING|$'

# Только ошибки
make logs-bot | grep ERROR

# Следить за метриками
watch -n 1 'curl -s localhost:8000/metrics | grep bot_'
```

---

## 📊 Мониторинг

### Grafana Dashboards

После запуска `make grafana-open`:

1. **Login**: admin/admin
2. Дашборды:
   - Bot Overview - общие метрики
   - System Metrics - CPU/Memory/Disk
   - Logs - все логи из Loki

### Custom Metrics

```python
# В вашем коде
from bot.metrics import bot_reports_submitted_total

bot_reports_submitted_total.labels(
    channel_id=channel.id,
    valid=True
).inc()
```

### Alerts

Настроены в `monitoring/alerts.yml`:
- Bot Down
- High Error Rate
- High Memory Usage
- Database Errors

---

## 🧪 Тестирование

### Структура тестов

```
tests/
├── unit/              # Юнит-тесты
│   ├── test_handlers.py
│   ├── test_validators.py
│   └── test_utils.py
├── integration/       # Интеграционные тесты
│   ├── test_database.py
│   └── test_api.py
└── conftest.py        # Fixtures
```

### Запуск тестов

```bash
# Все тесты
pytest

# Конкретный файл
pytest tests/unit/test_handlers.py

# Конкретный тест
pytest tests/unit/test_handlers.py::test_add_user

# С покрытием
pytest --cov=bot --cov-report=html
# Откроется htmlcov/index.html

# Watch mode (автоматически при изменениях)
make test-watch
```

### Mock Telegram API

```python
# tests/conftest.py
@pytest.fixture
def mock_bot():
    with patch('aiogram.Bot') as mock:
        yield mock

# tests/test_handlers.py
def test_command(mock_bot):
    # Ваш тест
    pass
```

---

## 🔧 Дополнительные инструменты

### MailHog (Email Testing)

```bash
make mailhog-open
# http://localhost:8025

# Бот будет отправлять email на mailhog:1025
# Все письма видны в веб-интерфейсе
```

### Redis Commander

```bash
# http://localhost:8081
# Просмотр и редактирование Redis данных
```

### Jaeger (Tracing)

```bash
make jaeger-open
# http://localhost:16686

# Включите в .env.local:
JAEGER_ENABLED=true
```

### Portainer (Docker UI)

```bash
make portainer-open
# http://localhost:9000

# Управление контейнерами через UI
```

### ngrok (публичный URL)

```bash
# Запуск туннеля
make ngrok-start

# Получить URL
make ngrok-url
# Вернет: https://xxxx.ngrok.io

# Использовать для тестирования вебхуков
# Остановка
make ngrok-stop
```

---

## 🎨 Code Quality

### Pre-commit Hooks

```bash
# Установка
pip install pre-commit
pre-commit install

# Теперь при каждом коммите будут автоматически:
# - Форматироваться код (black, isort)
# - Проверяться линтерами (ruff, mypy)
# - Сканироваться на секреты
# - Проверяться YAML/JSON

# Ручной запуск на всех файлах
pre-commit run --all-files
```

### Линтеры

```bash
# Ruff (быстрый linter)
ruff check bot/
ruff check --fix bot/  # С автофиксом

# MyPy (type checking)
mypy bot/

# Bandit (security)
bandit -r bot/

# Всё сразу
make lint
```

### Форматтеры

```bash
# Black (форматтер кода)
black bot/

# isort (сортировка импортов)
isort bot/

# Всё сразу
make format
```

---

## 💾 База данных

### SQLite Shell

```bash
make db-shell

# Внутри SQLite:
.tables                    # Показать таблицы
.schema channels          # Показать структуру
SELECT * FROM users;      # Запросы
.exit                     # Выход
```

### Бэкапы

```bash
# Создать бэкап
make db-backup

# Восстановить
make db-restore file=data/backup_20240118.db

# Полный бэкап (включая конфиги)
make backup-full
```

### Миграции

```bash
# Запуск миграций
make migrate

# Откат (если используете Alembic)
alembic downgrade -1
```

---

## 🔥 Hot Reload

Код автоматически перезагружается при изменениях:

```bash
# 1. Запустите бота
make dev-bg

# 2. Измените файл bot/handlers/admin.py
nano bot/handlers/admin.py

# 3. Сохраните - бот автоматически перезапустится!
```

### Отключение hot-reload

В `.env`:
```bash
AUTO_RELOAD=false
```

---

## 📈 Performance Profiling

### Memory Profiling

```bash
# Установка
pip install memory_profiler

# В коде
from memory_profiler import profile

@profile
def my_function():
    # Код
    pass

# Запуск
python -m memory_profiler bot/main.py
```

### CPU Profiling

```bash
# Установка
pip install py-spy

# Запуск
py-spy top -- python -m bot.main

# Flame graph
py-spy record -o profile.svg -- python -m bot.main
```

---

## 🆘 Troubleshooting

### Проблема: Порт уже занят

```bash
# Найти процесс
lsof -i :3000

# Убить процесс
kill -9 <PID>

# Или изменить порт в .env.local
GRAFANA_PORT=3001
```

### Проблема: Контейнер не запускается

```bash
# Проверить логи
docker-compose -f docker-compose.local.yml logs bot

# Пересобрать образ
make rebuild

# Очистить всё и начать заново
make clean-all && make start
```

### Проблема: Нет места на диске

```bash
# Очистить Docker
docker system prune -af --volumes

# Очистить логи
make clean-logs

# Проверить использование
du -sh data/ logs/ backups/
```

### Проблема: Медленная работа

```bash
# Проверить ресурсы
make stats

# Увеличить лимиты Docker Desktop:
# Settings → Resources → Memory: 4GB+

# Отключить необязательные сервисы
# В docker-compose.local.yml закомментируйте:
# - jaeger
# - cadvisor
```

---

## 🎓 Лучшие практики

### Workflow разработки

```bash
# 1. Создать ветку
git checkout -b your_name

# 2. Запустить окружение
make start

# 3. Разработка с hot-reload
# Код → Сохранить → Автоперезагрузка

# 4. Тесты
make test-watch

# 5. Проверка качества
make all-checks

# 6. Коммит (pre-commit hooks запустятся автоматически)
git add .
git commit -m "feat: add new command"

# 7. Push
git push origin feature/new-command
```

### Советы

- ✅ Используйте `make debug` для отладки сложных багов
- ✅ Смотрите метрики в Grafana постоянно
- ✅ Пишите тесты сразу (TDD)
- ✅ Используйте type hints (mypy проверит)
- ✅ Документируйте функции (docstrings)
- ✅ Делайте атомарные коммиты
- ✅ Используйте conventional commits

---

## 📚 Дополнительные ресурсы

### Документация

- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
- [aiogram 3.x](https://docs.aiogram.dev/en/dev-3.x/)
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/)
- [Prometheus](https://prometheus.io/docs/)
- [Grafana](https://grafana.com/docs/)

### Полезные ссылки

```bash
# Service URLs (после make start)
make urls

# Документация API
http://localhost:8000/docs  # Если добавите FastAPI

# Метрики
http://localhost:8000/metrics

# Health
http://localhost:8000/health
```

---

## 🎯 Что дальше?

После освоения локальной разработки:

1. **Переход на Free VPS** (`vps`)
   ```bash
   git checkout vps
   # Следуйте README.md
   ```

2. **Переход на AWS** (`aws`)
   ```bash
   git checkout aws
   # Следуйте AWS.md
   ```

---

## 🤝 Помощь

Вопросы? Проблемы?

1. Проверьте [Troubleshooting](#-troubleshooting)
2. Посмотрите логи: `make logs-bot`
3. Создайте issue на GitHub