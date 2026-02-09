"""
Хендлеры управления пользователями канала
"""
import logging

from aiogram import Router, html
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import UserCRUD, ChannelCRUD, UserChannelCRUD
from bot.database.models import User
from bot.handlers.admin.utils import is_admin, parse_user_list, format_user_mention

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("add_user"))
async def cmd_add_user(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Добавить одного пользователя в канал

    Форматы:
    - /add_user (reply на сообщение пользователя)
    - /add_user @username
    - /add_user 123456789 (telegram_id)
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )
    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        return

    target_user = None
    args = command.args

    if args:
        # Через аргументы команды
        target_user = await _find_user_by_identifier(session, args)
        if not target_user:
            await message.answer(
                f"Пользователь '{args}' не найден в базе. "
                f"Пусть нажмет /register."
            )
            return
    elif message.reply_to_message:
        # Через reply
        if not _is_phantom_reply(message):
            target_user = await UserCRUD.get_or_create(
                session,
                telegram_id=message.reply_to_message.from_user.id,
                username=message.reply_to_message.from_user.username or "",
                full_name=message.reply_to_message.from_user.full_name
            )
        else:
            await message.answer("Некорректный запрос. Введите ID или @username.")
            return
    else:
        await message.answer("Некорректный запрос. Введите ID или @username.")
        return

    # Проверка, не добавлен ли уже
    in_channel = await UserChannelCRUD.in_user_in_channel(
        session, target_user.id, channel.id
    )
    if in_channel:
        await message.answer(
            f"{target_user.full_name} (ID: {target_user.telegram_id}) уже в канале."
        )
    else:
        await UserChannelCRUD.add_user_to_channel(session, target_user.id, channel.id)
        await message.answer(f"✅ Пользователь добавлен: {target_user.full_name}")
        logger.info(
            f"User added to channel: user_id={target_user.id}, "
            f"channel_id={channel.id}, by_admin={message.from_user.id}"
        )


@router.message(Command("add_users"))
async def cmd_add_users(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Массовое добавление пользователей

    Формат: /add_users @user1 @user2 @user3
    Разделители: пробел, запятая, точка с запятой
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )
    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        return

    if not command.args:
        await message.answer("Формат: `/add_users @user1 @user2 @user3`")
        return

    entries = parse_user_list(command.args)

    added_names = []
    already_in_names = []
    not_found = []

    for entry in entries:
        u = await _find_user_by_identifier(session, entry)

        if u:
            name = format_user_mention(u.username, u.full_name, u.telegram_id)
            in_channel = await UserChannelCRUD.in_user_in_channel(
                session, u.id, channel.id
            )
            if not in_channel:
                await UserChannelCRUD.add_user_to_channel(session, u.id, channel.id)
                added_names.append(name)
            else:
                already_in_names.append(name)
        else:
            not_found.append(f"@{entry}")

    response = []
    if added_names:
        response.append(
            f"<b>Успешно добавлены для отслеживания:</b> "
            f"[{', '.join(added_names)}]"
        )
    if already_in_names:
        response.append(
            f"<b>Пропущены, уже отслеживаются:</b> "
            f"[{', '.join(already_in_names)}]"
        )
    if not_found:
        response.append(
            f"<b>Не найдены в базе (пусть нажмут /register):</b> "
            f"[{', '.join(not_found)}]"
        )
    if not response:
        response.append("Список имен для добавления пуст.")

    await message.answer("\n\n".join(response))

    if added_names:
        logger.info(
            f"Bulk users added: {len(added_names)} users to channel_id={channel.id}"
        )


@router.message(Command("add_users_by_store"))
async def cmd_add_users_by_store(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Добавить всех пользователей с определенным store_id

    Формат: /add_users_by_store MSK-001
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        return

    if not command.args:
        await message.answer(
            "<b>Формат:</b> <code>/add_users_by_store MSK-001</code>\n\n"
            "Добавит всех пользователей с указанным ID магазина"
        )
        return

    store_id = command.args.strip().upper()

    # Получаем всех пользователей магазина
    users = await UserCRUD.get_by_store_id(session, store_id)

    if not users:
        await message.answer(
            f"❌ Пользователей с ID магазина <code>{store_id}</code> не найдено"
        )
        return

    added_names = []
    already_in_names = []

    for u in users:
        name = format_user_mention(u.username, u.full_name, u.telegram_id)

        in_channel = await UserChannelCRUD.in_user_in_channel(
            session, u.id, channel.id
        )
        if not in_channel:
            await UserChannelCRUD.add_user_to_channel(session, u.id, channel.id)
            added_names.append(name)
        else:
            already_in_names.append(name)

    response = []
    if added_names:
        response.append(
            f"<b>✅ Успешно добавлены из магазина {store_id}:</b>\n" +
            "\n".join([f"• {n}" for n in added_names])
        )
    if already_in_names:
        response.append(
            f"<b>⚠️ Уже были добавлены:</b>\n" +
            "\n".join([f"• {n}" for n in already_in_names])
        )
    if not response:
        response.append("Никто не был добавлен.")

    await message.answer("\n\n".join(response))

    logger.info(
        f"Store users added: store_id={store_id}, "
        f"added={len(added_names)}, channel_id={channel.id}"
    )


@router.message(Command("rm_user"))
async def cmd_rm_user(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Удалить пользователя из канала

    Форматы:
    - /rm_user (reply на сообщение)
    - /rm_user @username
    - /rm_user 123456789
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )
    if not channel:
        await message.answer("Канал не найден.")
        return

    target_user = None
    args = command.args

    if args:
        target_user = await _find_user_by_identifier(session, args)
    elif message.reply_to_message:
        if not _is_phantom_reply(message):
            target_user = await UserCRUD.get_by_telegram_id(
                session, message.reply_to_message.from_user.id
            )
        else:
            await message.answer("Некорректный запрос. Введите ID или @username.")
            return
    else:
        await message.answer("Некорректный запрос. Введите ID или @username.")
        return

    if target_user:
        removed = await UserChannelCRUD.remove_user_from_channel(
            session, target_user.id, channel.id
        )
        if removed:
            await message.answer(f"✅ Удален из отслеживания: {target_user.full_name}")
            logger.info(
                f"User removed from channel: user_id={target_user.id}, "
                f"channel_id={channel.id}"
            )
        else:
            await message.answer(
                f"Пользователь {target_user.full_name} не был в этом канале."
            )
    else:
        await message.answer("Пользователь не найден в базе.")


@router.message(Command("rm_users"))
async def cmd_rm_users(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Массовое удаление пользователей

    Формат: /rm_users @user1 @user2 @user3
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не найден.")
        return

    if not command.args:
        await message.answer("Формат: `/rm_users @user1 @user2 @user3`")
        return

    entries = parse_user_list(command.args)

    removed_names = []
    not_found = []

    for entry in entries:
        u = await _find_user_by_identifier(session, entry)

        if u:
            name = format_user_mention(u.username, u.full_name, u.telegram_id)
            if await UserChannelCRUD.remove_user_from_channel(
                    session, u.id, channel.id
            ):
                removed_names.append(name)
            else:
                not_found.append(name)
        else:
            not_found.append(f"@{entry}")

    response = []
    if removed_names:
        response.append(
            f"<b>✅ Успешно удалены из отслеживания:</b> "
            f"[{', '.join(removed_names)}]"
        )
    if not_found:
        response.append(
            f"<b>⚠️ Не найдены в списке для отслеживания:</b> "
            f"[{', '.join(not_found)}]"
        )
    if not response:
        response.append("Никто не был удален.")

    await message.answer("\n\n".join(response))


@router.message(Command("list_users"))
async def cmd_list_users(message: Message, session: AsyncSession):
    """
    Показать список пользователей в текущей ветке
    Теперь с отображением store_id (если есть)
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer(
            "В этой ветке нет активного канала. Создайте его через /add_channel"
        )
        return

    users = await UserChannelCRUD.get_users_by_channel(session, channel.id)

    if not users:
        await message.answer(
            f"📋 В канале <b>{html.quote(channel.title)}</b> пока нет пользователей.\n\n"
            f"Добавьте их через:\n"
            f"• /add_user — один пользователь\n"
            f"• /add_users — несколько пользователей\n"
            f"• /add_users_by_store — по ID магазина"
        )
        return

    text = f"<b>👥 Пользователи в канале {html.quote(channel.title)}:</b>\n\n"

    # Группируем пользователей по наличию store_id
    users_with_store = []
    users_without_store = []

    for user in users:
        if user.store_id:
            users_with_store.append(user)
        else:
            users_without_store.append(user)

    # Показываем пользователей с магазинами
    if users_with_store:
        text += "<b>🏪 С привязкой к магазину:</b>\n"
        # Сортируем по store_id для удобства
        users_with_store.sort(key=lambda u: u.store_id or "")

        for user in users_with_store:
            # Формируем строку пользователя
            user_line = f"• <b>{html.quote(user.full_name)}</b>"

            if user.username:
                user_line += f" — @{user.username}"

            user_line += f" (id: <code>{user.telegram_id}</code>, store: <b>{html.quote(user.store_id)}</b>)"

            text += user_line + "\n"

        text += "\n"

    # Показываем пользователей без магазинов
    if users_without_store:
        text += "<b>👤 Без привязки к магазину:</b>\n"

        for user in users_without_store:
            user_line = f"• <b>{html.quote(user.full_name)}</b>"

            if user.username:
                user_line += f" — @{user.username}"

            user_line += f" (id: <code>{user.telegram_id}</code>)"

            text += user_line + "\n"

        text += "\n"

    # Статистика
    text += f"<b>Всего:</b> {len(users)} "
    if users_with_store:
        text += f"(🏪 {len(users_with_store)} с магазином, "
        text += f"👤 {len(users_without_store)} без)"

    # Подсказка
    text += "\n\n<i>💡 Для редактирования используйте /register или /rm_user</i>"

    await message.answer(text)


@router.message(Command("get_user_id"))
async def cmd_get_user_id(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Получить Telegram ID пользователя

    Форматы:
    - /get_user_id (свой ID)
    - /get_user_id (reply на сообщение)
    - /get_user_id @username
    - /get_user_id 123456789
    """
    if command.args:
        # Поиск по username или ID
        val = command.args.replace("@", "").strip()
        if not val:
            await message.answer("Вы ввели пустой username.")
            return

        u_db = await _find_user_by_identifier(session, val)

        if u_db:
            await message.answer(
                f"👤 <b>Пользователь (из базы):</b>\n"
                f"ID: <code>{u_db.telegram_id}</code>\n"
                f"Имя: {u_db.full_name}\n"
                f"Username: @{u_db.username}"
            )
        else:
            await message.answer(f"Пользователь '{val}' не найден в базе.")
        return

    # Через reply
    if message.reply_to_message and not _is_phantom_reply(message):
        u_reply = message.reply_to_message.from_user
        await message.answer(
            f"<b>Пользователь (Reply):</b>\n"
            f"ID: <code>{u_reply.id}</code>\n"
            f"Имя: {u_reply.full_name}\n"
            f"Username: @{u_reply.username}\n"
        )
        return

    # Свой ID
    u = message.from_user
    await message.answer(
        f"<b>Ваш профиль:</b>\n"
        f"ID: <code>{u.id}</code>\n"
        f"Имя: {u.full_name}\n"
        f"Username: @{u.username}"
    )


# ==================== Вспомогательные функции ====================

async def _find_user_by_identifier(
        session: AsyncSession,
        identifier: str
) -> User | None:
    """
    Найти пользователя по ID или username

    Args:
        session: Сессия БД
        identifier: ID или username (без @)

    Returns:
        User или None
    """
    val = identifier.replace("@", "").strip()

    if val.isdigit():
        return await UserCRUD.get_by_telegram_id(session, int(val))
    else:
        res = await session.execute(select(User).where(User.username.ilike(val)))
        return res.scalar_one_or_none()


def _is_phantom_reply(message: Message) -> bool:
    """
    Проверка на фантомный reply (reply на начало топика)

    Args:
        message: Сообщение для проверки

    Returns:
        True если это phantom reply
    """
    if message.is_topic_message and message.message_thread_id:
        if message.reply_to_message:
            return message.reply_to_message.message_id == message.message_thread_id
    return False