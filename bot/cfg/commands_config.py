"""
Конфигурация команд бота с параметрами и описаниями
"""
from typing import Dict, List, Optional, Literal
from dataclasses import dataclass


@dataclass
class CommandParameter:
    """Параметр команды"""
    name: str  # Название параметра
    description: str  # Описание
    example: str  # Пример значения
    required: bool = True  # Обязательный или нет
    input_type: Literal["text", "choice"] = "text"  # Тип ввода
    choices: Optional[List[str]] = None  # Варианты выбора (для choice)


@dataclass
class CommandConfig:
    """Конфигурация команды"""
    command: str  # Название команды без /
    description: str  # Краткое описание
    parameters: List[CommandParameter]  # Список параметров
    examples: List[str]  # Примеры использования
    note: Optional[str] = None  # Дополнительная заметка
    use_fsm: bool = True  # Использовать FSM для ввода


# ==================== КОНФИГУРАЦИЯ КОМАНД ====================

COMMANDS_CONFIG: Dict[str, CommandConfig] = {

    # === РЕГИСТРАЦИЯ ===
    "register": CommandConfig(
        command="register",
        description="Регистрация/обновление профиля",
        parameters=[
            CommandParameter(
                name="store_id",
                description="ID магазина для группировки",
                example="MSK-001",
                required=False
            )
        ],
        examples=[
            "/register  — без магазина",
            "/register MSK-001  — с магазином"
        ],
        note="Несколько пользователей могут использовать один ID магазина"
    ),

    # === УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ===
    "add_user": CommandConfig(
        command="add_user",
        description="Добавить пользователя в канал",
        parameters=[
            CommandParameter(
                name="user_identifier",
                description="@username или telegram_id",
                example="@ivan или 123456789",
                required=True
            )
        ],
        examples=[
            "/add_user @ivan",
            "/add_user 123456789",
            "Reply на сообщение + /add_user"
        ],
        note="Можно использовать reply на сообщение пользователя"
    ),

    "add_users": CommandConfig(
        command="add_users",
        description="Добавить несколько пользователей",
        parameters=[
            CommandParameter(
                name="users_list",
                description="Список пользователей через пробел",
                example="@user1 @user2 123456789",
                required=True
            )
        ],
        examples=[
            "/add_users @ivan @petr @maria",
            "/add_users 111 222 333",
            "/add_users @ivan 123456789 @petr"
        ],
        note="Разделители: пробел, запятая, точка с запятой"
    ),

    "add_users_by_store": CommandConfig(
        command="add_users_by_store",
        description="Добавить всех пользователей магазина",
        parameters=[
            CommandParameter(
                name="store_id",
                description="ID магазина",
                example="MSK-001",
                required=True
            )
        ],
        examples=[
            "/add_users_by_store MSK-001",
            "/add_users_by_store SPB-042"
        ],
        note="Добавит ВСЕХ пользователей с этим store_id"
    ),

    "rm_user": CommandConfig(
        command="rm_user",
        description="Удалить пользователя из канала",
        parameters=[
            CommandParameter(
                name="user_identifier",
                description="@username или telegram_id",
                example="@ivan или 123456789",
                required=True
            )
        ],
        examples=[
            "/rm_user @ivan",
            "/rm_user 123456789",
            "Reply на сообщение + /rm_user"
        ],
        note="Можно использовать reply на сообщение пользователя"
    ),

    "rm_users": CommandConfig(
        command="rm_users",
        description="Удалить несколько пользователей",
        parameters=[
            CommandParameter(
                name="users_list",
                description="Список пользователей через пробел",
                example="@user1 @user2 123456789",
                required=True
            )
        ],
        examples=[
            "/rm_users @ivan @petr @maria",
            "/rm_users 111 222 333"
        ]
    ),

    # === УПРАВЛЕНИЕ СОБЫТИЯМИ ===
    "add_event": CommandConfig(
        command="add_event",
        description="Добавить обычное событие",
        parameters=[
            CommandParameter(
                name="keyword",
                description="Ключевое слово (в кавычках если с пробелами)",
                example='"Касса 1 утро"',
                required=True
            ),
            CommandParameter(
                name="deadline_time",
                description="Время дедлайна",
                example="10:00",
                required=True
            ),
            CommandParameter(
                name="min_photos",
                description="Минимум фотографий",
                example="1",
                required=False
            )
        ],
        examples=[
            '"Касса 1 утро" 10:00 1',
            '"Склад/вечер" 18:00 2',
            'Утро 09:00'
        ],
        note="Ключевые слова с пробелами берите в кавычки!"
    ),

    "add_tmp_event": CommandConfig(
        command="add_tmp_event",
        description="Добавить временное событие (удалится в 23:59)",
        parameters=[
            CommandParameter(
                name="keyword",
                description="Ключевое слово",
                example='"Разовая проверка"',
                required=True
            ),
            CommandParameter(
                name="deadline_time",
                description="Время дедлайна",
                example="15:00",
                required=True
            ),
            CommandParameter(
                name="min_photos",
                description="Минимум фотографий",
                example="1",
                required=False
            )
        ],
        examples=[
            '"Разовая проверка" 15:00 1',
            'Инвентаризация 18:00 3'
        ],
        note="Событие автоматически удалится в 23:59 МСК"
    ),

    "add_event_checkout": CommandConfig(
        command="add_event_checkout",
        description="Добавить двухэтапное событие",
        parameters=[
            CommandParameter(
                name="first_keyword",
                description="Первый ключ (пересчет)",
                example='"Категории"',
                required=True
            ),
            CommandParameter(
                name="first_deadline",
                description="Время первого дедлайна",
                example="10:00",
                required=True
            ),
            CommandParameter(
                name="second_keyword",
                description="Второй ключ (готово)",
                example='"Готово"',
                required=True
            ),
            CommandParameter(
                name="second_deadline",
                description="Время второго дедлайна",
                example="16:00",
                required=True
            ),
            CommandParameter(
                name="min_photos",
                description="Минимум фотографий",
                example="1",
                required=False
            ),
            CommandParameter(
                name="stats_time",
                description="Время публикации статистики",
                example="23:00",
                required=False
            )
        ],
        examples=[
            '"Категории" 10:00 "Готово" 16:00 1',
            '"Категории" 10:00 "Готово" 16:00 1 23:00',
            '"Пересчет" 09:00 "Сдано" 18:00'
        ],
        note="Формат: первый этап (утро) → второй этап (вечер)"
    ),

    "add_event_notext": CommandConfig(
        command="add_event_notext",
        description="Добавить событие без текста (только фото)",
        parameters=[
            CommandParameter(
                name="deadline_start",
                description="Начало отслеживания",
                example="09:00",
                required=True
            ),
            CommandParameter(
                name="deadline_end",
                description="Конец отслеживания",
                example="18:00",
                required=True
            )
        ],
        examples=[
            "09:00 18:00",
            "10:00 20:00"
        ],
        note="Для выходного дня пользователь пишет: выходной"
    ),

    "add_event_kw": CommandConfig(
        command="add_event_kw",
        description="Добавить событие с ключевым словом",
        parameters=[
            CommandParameter(
                name="deadline_start",
                description="Начало отслеживания",
                example="09:00",
                required=True
            ),
            CommandParameter(
                name="deadline_end",
                description="Конец отслеживания",
                example="18:00",
                required=True
            ),
            CommandParameter(
                name="keyword",
                description="Ключевое слово для поиска",
                example='"открыт"',
                required=True
            ),
            CommandParameter(
                name="photo_description",
                description="Описание эталонного фото",
                example='"Пример правильно открытого магазина"',
                required=False
            )
        ],
        examples=[
            '09:00 18:00 "открыт"',
            '10:00 20:00 "открыт" "Пример фото"'
        ],
        note="Можно прикрепить фото к команде или отправить после"
    ),

    # === УПРАВЛЕНИЕ КАНАЛАМИ ===
    "add_channel": CommandConfig(
        command="add_channel",
        description="Создать канал",
        parameters=[
            CommandParameter(
                name="title",
                description="Название канала (без пробелов)",
                example="КассовыеОтчеты",
                required=True
            )
        ],
        examples=[
            "/add_channel КассовыеОтчеты",
            "/add_channel Склад"
        ],
        note="Канал - это группа для событий"
    ),

    "rm_channel": CommandConfig(
        command="rm_channel",
        description="Удалить канал",
        parameters=[
            CommandParameter(
                name="title",
                description="Точное название канала",
                example="КассовыеОтчеты",
                required=True
            )
        ],
        examples=[
            "/rm_channel КассовыеОтчеты"
        ],
        note="Название должно совпадать точно"
    ),

    # === НАСТРОЙКИ ===
    "set_wstat": CommandConfig(
        command="set_wstat",
        description="Настроить еженедельную статистику",
        parameters=[
            CommandParameter(
                name="chat_id",
                description="ID чата для статистики",
                example="-100123456789",
                required=True
            ),
            CommandParameter(
                name="thread_id",
                description="ID ветки (0 если нет)",
                example="15",
                required=True
            ),
            CommandParameter(
                name="title",
                description="Заголовок статистики",
                example="Еженедельный отчет",
                required=True
            )
        ],
        examples=[
            "-100123456789 15 Еженедельный отчет",
            "-100123456789 0 Статистика"
        ],
        note="Используйте /get_thread_id для получения ID"
    ),
}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_command_config(command: str) -> Optional[CommandConfig]:
    """
    Получить конфигурацию команды

    Args:
        command: Название команды (с / или без)

    Returns:
        CommandConfig или None
    """
    # Убираем / если есть
    clean_command = command.lstrip('/')
    return COMMANDS_CONFIG.get(clean_command)


def format_command_help(command: str) -> str:
    """
    Форматировать справку по команде

    Args:
        command: Название команды

    Returns:
        Отформатированная справка
    """
    config = get_command_config(command)
    if not config:
        return f"❌ Команда {command} не найдена в конфигурации"

    text = f"<b>📝 Команда: /{config.command}</b>\n\n"
    text += f"<i>{config.description}</i>\n\n"

    # Параметры
    if config.parameters:
        text += "<b>Параметры:</b>\n"
        for i, param in enumerate(config.parameters, 1):
            required = "✅ обязательный" if param.required else "⭕️ опциональный"
            text += f"{i}. <b>{param.name}</b> ({required})\n"
            text += f"   {param.description}\n"
            text += f"   Пример: <code>{param.example}</code>\n"
        text += "\n"

    # Примеры
    if config.examples:
        text += "<b>Примеры использования:</b>\n"
        for example in config.examples:
            text += f"• <code>/{config.command} {example}</code>\n"
        text += "\n"

    # Заметка
    if config.note:
        text += f"💡 <i>{config.note}</i>\n"

    return text


def get_command_input_prompt(command: str) -> str:
    """
    Получить подсказку для ввода параметров команды

    Args:
        command: Название команды

    Returns:
        Текст подсказки
    """
    config = get_command_config(command)
    if not config:
        return "Введите параметры команды:"

    text = f"<b>📝 Введите параметры для /{config.command}:</b>\n\n"

    # Формат ввода
    format_parts = []
    for param in config.parameters:
        if param.required:
            format_parts.append(f"[{param.name}]")
        else:
            format_parts.append(f"[{param.name}] (опц.)")

    text += f"<b>Формат:</b> <code>{' '.join(format_parts)}</code>\n\n"

    # Описание параметров
    text += "<b>Параметры:</b>\n"
    for param in config.parameters:
        required_mark = "✅" if param.required else "⭕️"
        text += f"{required_mark} <b>{param.name}</b>: {param.description}\n"
        text += f"   Пример: <code>{param.example}</code>\n"
    text += "\n"

    # Примеры
    if config.examples:
        text += "<b>Примеры:</b>\n"
        for example in config.examples:
            text += f"• <code>{example}</code>\n"

    if config.note:
        text += f"\n💡 {config.note}"

    return text