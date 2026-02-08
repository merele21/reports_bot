"""
Хендлеры управления каналами
"""
import logging

from aiogram import Router, html
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import ChannelCRUD
from bot.handlers.admin.utils import is_admin

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("add_channel"))
async def cmd_add_channel(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Создание канала

    Формат: /add_channel [название_без_пробелов]
    Пример: /add_channel КассовыеОтчеты
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("Команда недоступна в ЛС.")
        return

    args = command.args.strip() if command.args else ""
    if not args or len(args.split()) > 1:
        await message.answer(
            "<b>Инструкция по добавлению канала:</b>\n\n"
            "В новой версии бота канал — это группа для событий.\n"
            "Формат: <code>/add_channel [название_без_пробелов]</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/add_channel КассовыеОтчеты</code>\n\n"
            "<i>После создания добавляйте события через /add_event</i>"
        )
        return

    title = args
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Проверка на дубликат
    existing = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )
    if existing:
        await message.answer(
            f"Ошибка: в этом чате уже зарегистрирован канал '{existing.title}'."
        )
        return

    # Создание канала
    await ChannelCRUD.create(session, message.chat.id, thread_id, title)

    await message.answer(
        f"✅ Вы успешно создали канал <b>'{title}'</b>!\n\n"
        "<b>Мини-справка по дальнейшим шагам:</b>\n"
        "1) Добавьте события (типы отчетов):\n"
        "<code>/add_event</code> (обычные события)\n"
        "<code>/add_event_kw</code> (события по ключевому слову)\n"
        "<code>/add_event_notext</code> (события без текста)\n"
        "<code>/add_event_checkout</code> (двухэтапные события)\n"
        "<code>/add_tmp_event</code> (временные события)\n"
        "2) Добавьте пользователей или магазин: "
        "<code>/add_users</code> или <code>/add_users_by_store</code>\n"
        "3) Настройте статистику (опционально): <code>/set_wstat</code>"
    )

    logger.info(
        f"Channel created: title={title}, chat_id={message.chat.id}, "
        f"thread_id={thread_id}, by_user={message.from_user.id}"
    )


@router.message(Command("rm_channel"))
async def cmd_rm_channel(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Удаление канала

    Формат: /rm_channel [название канала]
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Инструкция:</b>\n"
            "Используйте: <code>/rm_channel [название канала]</code>"
        )
        return

    target_title = command.args.strip()
    thread_id = message.message_thread_id if message.is_topic_message else None

    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("В этом чате/ветке нет активных каналов.")
        return

    if channel.title.strip().lower() != target_title.lower():
        await message.answer(
            f"Название '<code>{target_title}</code>' не совпадает.\n"
            f"Текущий канал называется: '<code>{channel.title}</code>'\n"
            f"<i>(Скопируйте название целиком)</i>"
        )
        return

    success = await ChannelCRUD.delete_channel(session, channel.id)
    if success:
        await message.answer(f"✅ Канал <b>'{channel.title}'</b> успешно удален.")
        logger.info(
            f"Channel deleted: id={channel.id}, title={channel.title}, "
            f"by_user={message.from_user.id}"
        )


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, session: AsyncSession):
    """
    Список всех активных каналов
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    channels = await ChannelCRUD.get_all_active(session)
    if not channels:
        await message.answer("📋 Список активных каналов пуст.")
        return

    text = "<b>📋 Список активных каналов:</b>\n\n"
    for ch in channels:
        thread_info = (
            f" (Ветка ID: {ch.thread_id})" if ch.thread_id else " (Основной чат)"
        )
        text += f"• <b>{html.quote(ch.title)}</b>{thread_info}\n"

    await message.answer(text)