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

    Формат: XXX-NNN
    - XXX: буквы (A-Z), от 2 до 7 символов
    - NNN: цифры (0-9), от 1 до 10 цифр

    Args:
        store_id: ID магазина для проверки (уже в верхнем регистре)

    Returns:
        Dict с ключами:
            - valid: bool
            - error_message: str (если valid=False)

    Examples:
        >>> validate_store_id_format("MSK-001")
        {'valid': True}
        >>> validate_store_id_format("AB-1")
        {'valid': True}
        >>> validate_store_id_format("ABCDEFG-1234567890")
        {'valid': True}
        >>> validate_store_id_format("A-1")
        {'valid': False, 'error_message': '...'}
    """

    # Проверка общей длины (минимум: AB-1 = 4, максимум: ABCDEFG-1234567890 = 18)
    if len(store_id) < 4:
        return {
            "valid": False,
            "error_message": (
                "❌ <b>ID магазина слишком короткий</b>\n\n"
                "Минимальная длина: 4 символа (например, <code>AB-1</code>)\n"
                f"Ваш ID: <code>{store_id}</code> ({len(store_id)} симв.)\n\n"
                "<b>Правильный формат:</b> <code>XXX-NNN</code>\n"
                "• XXX — буквы и цифры (2-7 символов)\n"
                "• NNN — цифры (1-10 цифр)\n\n"
                "<b>Примеры:</b>\n"
                "• <code>AB-1</code> (минимум)\n"
                "• <code>MSK999-001</code>\n"
                "• <code>SHOP-42</code>"
            )
        }

    if len(store_id) > 18:  # 7 букв + 1 дефис + 10 цифр
        return {
            "valid": False,
            "error_message": (
                "❌ <b>ID магазина слишком длинный</b>\n\n"
                f"Максимальная длина: 18 символов\n"
                f"Ваш ID: <code>{store_id[:20]}...</code> ({len(store_id)} симв.)\n\n"
                "<b>Правильный формат:</b> <code>XXX-NNN</code>\n"
                "• XXX — буквы и цифры (2-7 символов)\n"
                "• NNN — цифры (1-10 цифр)\n\n"
                "<b>Примеры:</b>\n"
                "• <code>MOSCOW-123</code>\n"
                "• <code>SHOP32-98765432</code> (максимум)"
            )
        }

    # ПАТТЕРН: 2-7 букв, дефис, 1-10 цифр
    pattern = r'^[A-Z0-9]{2,7}-\d{1,10}$'

    if not re.match(pattern, store_id):
        # Детальная диагностика ошибки
        error_details = []

        # Проверяем наличие дефиса
        if '-' not in store_id:
            error_details.append("• Отсутствует дефис между буквами/цифрами и цифрами")
        elif store_id.count('-') > 1:
            error_details.append("• Допускается только один дефис")
        else:
            parts = store_id.split('-')

            if len(parts) != 2:
                error_details.append("• Неправильная структура (должно быть: БУКВЫ/ЦИФРЫ-ЦИФРЫ)")
            else:
                letter_part, number_part = parts

                # Проверка первой части
                if not letter_part:
                    error_details.append("• Первая часть отсутствует")
                elif not letter_part.isalnum():
                    # Ищем символы, которые НЕ буквы и НЕ цифры
                    invalid_chars = [c for c in letter_part if not c.isalnum()]
                    error_details.append(
                        f"• Недопустимые символы: {', '.join(invalid_chars)}"
                    )
                elif len(letter_part) < 2:
                    error_details.append(
                        f"• Первая часть слишком короткая ({len(letter_part)} симв., нужно 2-7)"
                    )
                elif len(letter_part) > 7:
                    error_details.append(
                        f"• Первая часть слишком длинная ({len(letter_part)} симв., максимум 7)"
                    )

                # Проверка цифровой части
                if not number_part:
                    error_details.append("• Цифровая часть отсутствует")
                elif not number_part.isdigit():
                    invalid_chars = [c for c in number_part if not c.isdigit()]
                    error_details.append(
                        f"• В цифровой части недопустимые символы: {', '.join(invalid_chars)}"
                    )
                elif len(number_part) > 10:
                    error_details.append(
                        f"• Цифровая часть слишком длинная ({len(number_part)} цифр, максимум 10)"
                    )

        # Формируем сообщение об ошибке
        error_message = (
                "❌ <b>Неправильный формат ID магазина</b>\n\n"
                f"Ваш ID: <code>{store_id}</code>\n\n"
                "<b>Обнаруженные проблемы:</b>\n" +
                "\n".join(error_details) +
                "\n\n<b>Правильный формат:</b> <code>XXX-NNN</code>\n"
                "• XXX — латинские буквы A-Z и цифры 0-9 (от 2 до 7 символов)\n"
                "• NNN — цифры 0-9 (от 1 до 10 цифр)\n\n"
                "<b>Примеры правильных ID:</b>\n"
                "• <code>AB-1</code> (минимум)\n"
                "• <code>MSK999-001</code>\n"
                "• <code>SHOP-42</code>\n"
                "• <code>MOSCOW-123</code>\n"
                "• <code>ABCDEFG-1234567890</code> (максимум)\n\n"
                "<b>Примеры неправильных ID:</b>\n"
                "• <code>A-1</code> ❌ (мало букв, нужно минимум 2)\n"
                "• <code>ABCDEFGH-1</code> ❌ (много букв, максимум 7)\n"
                "• <code>MSK_001</code> ❌ (нужен дефис, а не подчеркивание)\n"
                "• <code>МСК-001</code> ❌ (кириллица, нужна латиница)\n"
                "• <code>MSK-12345678901</code> ❌ (много цифр, максимум 10)"
        )

        return {
            "valid": False,
            "error_message": error_message
        }

    # Все проверки пройдены
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