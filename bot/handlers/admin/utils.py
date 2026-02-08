"""
Утилиты для админ-хендлеров
"""
import re
import shlex
from typing import Optional, Dict

from aiogram.fsm.state import State, StatesGroup

from bot.config import settings


# ==================== FSM States ====================

class EventDeletionStates(StatesGroup):
    """Состояния для удаления событий"""
    waiting_for_event_index = State()


class EventCreationStates(StatesGroup):
    """Состояния для создания событий"""
    waiting_for_users = State()


class RegistrationStates(StatesGroup):
    """Состояния для регистрации"""
    waiting_for_display_name = State()


# ==================== Проверка прав ====================

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in settings.admin_list


def is_super_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь суперадмином"""
    return user_id in settings.super_admin_list


# ==================== Парсинг команд ====================

def parse_quoted_keyword(text: str) -> Optional[str]:
    """
    Извлекает keyword в кавычках из команды

    Args:
        text: Текст команды

    Returns:
        Ключевое слово или None

    Examples:
        >>> parse_quoted_keyword('"Касса 1 утро" 10:00 1')
        'Касса 1 утро'
        >>> parse_quoted_keyword('simple_keyword 10:00')
        'simple_keyword'
    """
    try:
        parts = shlex.split(text)
        if len(parts) > 0:
            return parts[0]
    except ValueError:
        pass
    return None


def parse_time_string(time_str: str) -> Optional[tuple[int, int]]:
    """
    Парсит строку времени в формате HH:MM

    Args:
        time_str: Строка времени

    Returns:
        Кортеж (hour, minute) или None при ошибке

    Examples:
        >>> parse_time_string("10:00")
        (10, 0)
        >>> parse_time_string("invalid")
        None
    """
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
            hour = int(parts[0])
            minute = int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return (hour, minute)
    except (ValueError, AttributeError):
        pass
    return None


# ==================== Валидация ====================

def validate_store_id_format(store_id: str) -> Dict[str, any]:
    """
    Валидация формата store_id

    Формат: XXX-NNN где XXX - буквы, NNN - цифры
    Примеры: MSK-001, SPB-042, KRD-15

    Args:
        store_id: ID магазина для проверки

    Returns:
        Dict с ключами:
            - valid: bool
            - error_message: str (если valid=False)

    Examples:
        >>> validate_store_id_format("MSK-001")
        {'valid': True}
        >>> validate_store_id_format("invalid")
        {'valid': False, 'error_message': '...'}
    """
    # Паттерн: буквы-цифры (например, MSK-001)
    pattern = r'^[A-Z]{3}-\d{1,3}$'

    if not re.match(pattern, store_id):
        return {
            "valid": False,
            "error_message": (
                "❌ <b>Неверный формат ID магазина!</b>\n\n"
                "<b>Правильный формат:</b> <code>XXX-NNN</code>\n"
                "где XXX — буквы (3 символа), NNN — цифры (1-3 цифры)\n\n"
                "<b>Примеры:</b>\n"
                "• <code>MSK-001</code> — Москва, магазин 1\n"
                "• <code>SPB-042</code> — Санкт-Петербург, магазин 42\n"
                "• <code>KRD-15</code> — Краснодар, магазин 15\n\n"
                f"<b>Вы ввели:</b> <code>{store_id}</code>"
            )
        }

    return {"valid": True}


def validate_keyword_length(keyword: str, max_length: int = 24) -> Dict[str, any]:
    """
    Валидация длины ключевого слова

    Args:
        keyword: Ключевое слово
        max_length: Максимальная длина (по умолчанию 24)

    Returns:
        Dict с ключами:
            - valid: bool
            - error_message: str (если valid=False)
    """
    if len(keyword) > max_length:
        return {
            "valid": False,
            "error_message": f"⚠️ Ключевое слово не должно превышать {max_length} символов."
        }

    return {"valid": True}


# ==================== Форматирование ====================

def format_event_list_item(
        index: int,
        event_type: str,
        keyword: str,
        deadline_time: str,
        additional_info: str = ""
) -> str:
    """
    Форматирует элемент списка событий

    Args:
        index: Номер в списке
        event_type: Тип события
        keyword: Ключевое слово
        deadline_time: Время дедлайна
        additional_info: Дополнительная информация

    Returns:
        Отформатированная строка
    """
    base = f"{index}. <b>{keyword}</b> — {deadline_time}"
    if additional_info:
        base += f" {additional_info}"
    return base


def format_user_mention(username: Optional[str], full_name: str, telegram_id: int) -> str:
    """
    Форматирует упоминание пользователя

    Args:
        username: Username пользователя (без @)
        full_name: Полное имя
        telegram_id: Telegram ID

    Returns:
        Отформатированное упоминание

    Examples:
        >>> format_user_mention("ivan", "Иван Иванов", 123)
        '@ivan'
        >>> format_user_mention(None, "Иван Иванов", 123)
        'Иван Иванов'
    """
    if username:
        return f"@{username}"
    return full_name or f"ID:{telegram_id}"


# ==================== Работа со списками ====================

def parse_user_list(args: str) -> list[str]:
    """
    Парсит список пользователей из строки

    Поддерживает разделители: запятая, точка с запятой, пробел

    Args:
        args: Строка с пользователями

    Returns:
        Список пользователей (без @)

    Examples:
        >>> parse_user_list("@user1, @user2; @user3")
        ['user1', 'user2', 'user3']
    """
    # Заменяем разделители на пробелы
    processed = args.replace(",", " ").replace(";", " ")

    # Удаляем @ и фильтруем пустые строки
    entries = [
        entry.replace("@", "").strip()
        for entry in processed.split()
        if entry.strip()
    ]

    return entries