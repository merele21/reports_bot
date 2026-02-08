"""
Админ-хендлеры

Модуль разбит на логические части:
- registration.py - Регистрация пользователей и магазинов
- channels.py - Управление каналами
- events.py - Управление обычными и временными событиями
- events_special.py - Специальные события (checkout, notext, keyword)
- users.py - Управление пользователями канала
- stats_setup.py - Настройка статистики и служебные команды
- utils.py - Вспомогательные функции и FSM states
"""
from aiogram import Router

from . import (
    registration,
    channels,
    events,
    events_special,
    users,
    stats_setup,
    commands_fsm
)

# Главный роутер для всех админ-хендлеров
router = Router(name="admin")

# Регистрируем все под-роутеры
# ВАЖНО: commands_fsm ПЕРВЫМ
router.include_router(commands_fsm.router)  # ← Перехватывает команды
router.include_router(registration.router)
router.include_router(channels.router)
router.include_router(events.router)
router.include_router(events_special.router)
router.include_router(users.router)
router.include_router(stats_setup.router)

__all__ = ["router"]