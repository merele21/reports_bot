report_bot/
├── bot/
│   ├── __init__.py
│   ├── main.py                 # Точка входа
│   ├── config.py              # Конфигурация
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── admin.py           # Админ-команды
│   │   ├── reports.py         # Обработка отчетов
│   │   └── stats.py           # Статистика
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py          # SQLAlchemy модели
│   │   ├── engine.py          # Подключение к БД
│   │   └── crud.py            # CRUD операции
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── tasks.py           # Задачи планировщика
│   ├── middlewares/
│   │   ├── __init__.py
│   │   └── database.py        # Middleware для БД
│   └── utils/
│       ├── __init__.py
│       └── validators.py      # Валидаторы
├── alembic/                   # Миграции БД
│   └── versions/
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md