"""
Хендлеры настройки статистики и служебные команды
"""
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import ChannelCRUD
from bot.handlers.admin.utils import is_admin

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("set_wstat"))
async def cmd_set_wstat(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Настройка еженедельной статистики

    Формат: /set_wstat [ID канала] [ID треда (0 если нет)] [Заголовок]
    Пример: /set_wstat -100123456789 15 Еженедельный отчет
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Инструкция:</b>\n"
            "Используйте: <code>/set_wstat [ID канала] [ID треда (0 если нет)] "
            "[Заголовок]</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/set_wstat -100123456789 15 Еженедельный отчет</code>"
        )
        return

    parts = command.args.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Ошибка: укажите ID чата, ID треда и Заголовок.")
        return

    try:
        target_chat_id = int(parts[0])
        target_thread_id = int(parts[1])
        if target_thread_id == 0:
            target_thread_id = None
        custom_title = parts[2]
    except ValueError:
        await message.answer("ID чата и треда должны быть числами.")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer(
            "В этом чате/ветке нет активного канала. "
            "Сначала создайте его через /add_channel"
        )
        return

    await ChannelCRUD.update_stats_destination(
        session, channel.id, target_chat_id, target_thread_id, custom_title
    )

    thread_info = f" (ветка {target_thread_id})" if target_thread_id else ""
    await message.answer(
        f"✅ Настройки статистики обновлены!\n\n"
        f"<b>Куда:</b> ID {target_chat_id}{thread_info}\n"
        f"<b>Заголовок:</b> {custom_title}"
    )

    logger.info(
        f"Stats destination updated: channel_id={channel.id}, "
        f"stats_chat_id={target_chat_id}, stats_thread_id={target_thread_id}, "
        f"by_user={message.from_user.id}"
    )


@router.message(Command("get_thread_id"))
async def cmd_get_thread_id(message: Message):
    """
    Показывает ID текущего чата и ветки (thread)
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    chat_id = message.chat.id
    thread_id = (
        message.message_thread_id if message.is_topic_message
        else "Основной чат (0)"
    )

    response = (
        f"<b>📍 Данные для настройки статистики:</b>\n\n"
        f"ID группы: <code>{chat_id}</code>\n"
        f"ID ветки (thread_id): <code>{thread_id}</code>\n\n"
    )
    await message.answer(response)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """
    Показать справку по командам
    """
    user_id = message.from_user.id
    help_text = "<b>Команды для пользователей:</b>\n\n"
    help_text += "• /register - Регистрация/Обновление профиля\n"
    help_text += "• /get_user_id - Узнать ID (свой/reply/username)\n"

    if is_admin(user_id):
        help_text += "\n<b>Команды для администраторов:</b>\n"
        help_text += "\n<b>📋 Управление каналами:</b>\n"
        help_text += "• /add_channel - Создать канал\n"
        help_text += "• /rm_channel - Удалить канал\n"
        help_text += "• /list_channels - Список каналов\n"

        help_text += "\n<b>📅 Управление событиями:</b>\n"
        help_text += "• /add_event - Добавить обычное событие\n"
        help_text += "• /add_tmp_event - Добавить временное событие\n"
        help_text += "• /add_event_checkout - Двухэтапное событие\n"
        help_text += "• /add_event_notext - Событие без текста\n"
        help_text += "• /add_event_kw - Событие с ключевым словом\n"
        help_text += "• /rm_event - Удалить событие\n"
        help_text += "• /list_events - Список всех событий\n"

        help_text += "\n<b>👥 Управление пользователями:</b>\n"
        help_text += "• /add_user - Добавить участника\n"
        help_text += "• /add_users - Добавить несколько участников\n"
        help_text += "• /add_users_by_store - Добавить по ID магазина\n"
        help_text += "• /rm_user - Удалить участника\n"
        help_text += "• /rm_users - Удалить несколько участников\n"
        help_text += "• /list_users - Список участников\n"
        help_text += "• /list_stores - Список магазинов\n"

        help_text += "\n<b>⚙️ Настройки:</b>\n"
        help_text += "• /set_wstat - Настройка еженедельной статистики\n"
        help_text += "• /get_thread_id - Узнать ID текущей ветки\n"

    await message.answer(help_text)