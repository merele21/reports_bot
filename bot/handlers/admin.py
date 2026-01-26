import logging
from datetime import time
from typing import Dict, Optional

from aiogram import Router, F, html
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.config import settings
from bot.database.crud import UserCRUD, ChannelCRUD, UserChannelCRUD, EventCRUD
from bot.database.models import User

router = Router()
logger = logging.getLogger(__name__)


# --- Группы состояний ---
class EventDeletionStates(StatesGroup):
    waiting_for_event_index = State()


class EventCreationStates(StatesGroup):
    waiting_for_users = State()


# --- Вспомогательные функции ---
def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_list


async def finish_event_creation(message: Message, state: FSMContext, session: AsyncSession, data: dict):
    keyword = data.get("event_keyword")
    deadline_str = data.get("event_deadline")
    channel_id = data.get("current_channel_id")

    # 1. Сообщение о создании
    await message.answer(f"Событие <b>{html.quote(keyword)}</b> успешно создано")

    # 2. Карточка отчета для пользователей
    users = await UserChannelCRUD.get_users_by_channel(session, channel_id)
    user_list = []
    for i, u in enumerate(users, 1):
        name = html.quote(f"@{u.username}" if u.username else u.full_name)
        user_list.append(f"{i}. {name}")

    users_text = "\n".join(user_list) if user_list else "<i>Список пуст</i>"

    await message.answer(f"Событие <b>{html.quote(keyword)}</b> успешно создано")
    await state.clear()


# --- Обработчики ---

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.")

@router.message(Command("register"))
async def cmd_register(message: Message, session: AsyncSession):
    is_private = message.chat.type == "private"
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Проверяем, зарегистрирована ли текущая ветка в базе
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    is_reg_thread = channel and channel.title == "Регистрация"

    if is_private or is_reg_thread:
        telegram_id = message.from_user.id
        existing_user = await UserCRUD.get_by_telegram_id(session, telegram_id)

        user = await UserCRUD.get_or_create(
            session,
            telegram_id=telegram_id,
            username=message.from_user.username or "",
            full_name=message.from_user.full_name,
        )

        if existing_user:
            await message.answer(
                f"<b>Вы уже зарегистрированы, {user.full_name}!</b>\n"
                f"Ваш ID: <code>{user.telegram_id}</code>"
            )
        else:
            await message.answer(
                f"<b>Привет, {user.full_name}!</b>\n\n"
                f"Вы успешно зарегистрированы."
            )
    else:
        bot_info = await message.bot.get_me()
        bot_link = f"https://t.me/{bot_info.username}"

        await message.answer(
            f"<b>Команда /register здесь недоступна.</b>\n\n"
            f"Пожалуйста, пройдите регистрацию в <a href='{bot_link}'><b>личных сообщениях</b></a> бота "
            f"или перейдите в ветку <b>Регистрация</b>.",
            disable_web_page_preview=True
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    help_text = "<b>Команды для пользователей:</b>\n\n"
    help_text += "• /register - Регистрация/Обновление профиля\n"
    help_text += "• /get_user_id - Узнать ID (свой/reply/username)\n"

    if is_admin(user_id):
        help_text += "\n<b>Команды для администраторов:</b>\n"
        help_text += "• /add_channel - Создать канал\n"
        help_text += "• /rm_channel - Удалить канал\n"
        help_text += "• /add_event - Добавить событие (отчет)\n"
        help_text += "• /rm_event - Удалить событие\n"
        help_text += "• /add_user - Добавить участника\n"
        help_text += "• /add_users - Добавить несколько участников сразу\n"
        help_text += "• /rm_user - Удалить участника\n"
        help_text += "• /rm_users - Удалить несколько участников сразу\n"
        help_text += "• /list_channels - Список каналов\n"

    await message.answer(help_text)


# --- Управление пользователями ---

@router.message(Command("add_user"))
async def cmd_add_user(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        return

    target_user = None
    args = command.args

    if args:
        val = args.replace("@", "").strip()
        if not val:
            await message.answer("Некорректный запрос. Введите ID или @username.")
            return

        if val.isdigit():
            target_user = await UserCRUD.get_by_telegram_id(session, int(val))
        else:
            res = await session.execute(select(User).where(User.username.ilike(val)))
            target_user = res.scalar_one_or_none()

        if not target_user:
            await message.answer(f"Пользователь '{val}' не найден в базе. Пусть нажмет /register.")
            return

    elif message.reply_to_message:
        is_phantom_reply = False
        if message.is_topic_message and message.message_thread_id:
            if message.reply_to_message.message_id == message.message_thread_id:
                is_phantom_reply = True

        if not is_phantom_reply:
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

    in_channel = await UserChannelCRUD.in_user_in_channel(session, target_user.id, channel.id)
    if in_channel:
        await message.answer(f"{target_user.full_name} (ID: {target_user.telegram_id}) уже в канале.")
    else:
        await UserChannelCRUD.add_user_to_channel(session, target_user.id, channel.id)
        await message.answer(f"Пользователь добавлен: {target_user.full_name}")


@router.message(Command("add_users"))
async def cmd_add_users(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        return

    if not command.args:
        await message.answer("Формат: `/add_users @user1 @user2 @user3`")
        return

    processed_args = command.args.replace(",", " ").replace(";", " ")
    entries = [e.replace("@", "").strip() for e in processed_args.split() if e.strip()]

    added_names = []
    already_in_names = []
    not_found = []

    for entry in entries:
        u = None
        if entry.isdigit():
            u = await UserCRUD.get_by_telegram_id(session, int(entry))
        else:
            res = await session.execute(select(User).where(User.username.ilike(entry)))
            u = res.scalar_one_or_none()

        if u:
            name = f"@{u.username}" if u.username else u.full_name
            if not await UserChannelCRUD.in_user_in_channel(session, u.id, channel.id):
                await UserChannelCRUD.add_user_to_channel(session, u.id, channel.id)
                added_names.append(name)
            else:
                already_in_names.append(name)
        else:
            not_found.append(f"@{entry}")

    response = []
    if added_names:
        response.append(f"<b>Успешно добавлены для отслеживания:</b> [" + ", ".join(added_names) + "]")
    if already_in_names:
        response.append(f"<b>Пропущены, уже отслеживаются:</b> [" + ", ".join(already_in_names) + "]")
    if not_found:
        response.append(f"<b>Не найдены в базе (пусть нажмут /register):</b> [" + ", ".join(not_found) + "]")
    if not response:
        response.append("Список имен для добавления пуст.")

    await message.answer("\n\n".join(response))


@router.message(Command("rm_user"))
async def cmd_rm_user(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("Канал не найден.")
        return

    target_user = None
    args = command.args

    if args:
        val = args.replace("@", "").strip()
        if not val:
            await message.answer("⚠Некорректный запрос. Введите ID или @username.")
            return
        if val.isdigit():
            target_user = await UserCRUD.get_by_telegram_id(session, int(val))
        else:
            res = await session.execute(select(User).where(User.username.ilike(val)))
            target_user = res.scalar_one_or_none()
    elif message.reply_to_message:
        is_phantom_reply = False
        if message.is_topic_message and message.message_thread_id:
            if message.reply_to_message.message_id == message.message_thread_id:
                is_phantom_reply = True

        if not is_phantom_reply:
            target_user = await UserCRUD.get_by_telegram_id(session, message.reply_to_message.from_user.id)
        else:
            await message.answer("Некорректный запрос. Введите ID или @username.")
            return
    else:
        await message.answer("Некорректный запрос. Введите ID или @username.")
        return

    if target_user:
        removed = await UserChannelCRUD.remove_user_from_channel(session, target_user.id, channel.id)
        if removed:
            await message.answer(f"Удален: {target_user.full_name}")
        else:
            await message.answer(f"Пользователь {target_user.full_name} не был в этом канале.")
    else:
        await message.answer("Пользователь не найден в базе.")


@router.message(Command("rm_users"))
async def cmd_rm_users(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)

    if not channel:
        await message.answer("Канал не найден.")
        return

    if not command.args:
        await message.answer("Формат: `/rm_users @user1 @user2`")
        return

    processed_args = command.args.replace(",", " ").replace(";", " ")
    entries = [e.replace("@", "").strip() for e in processed_args.split() if e.strip()]

    removed_names = []
    not_found = []

    for entry in entries:
        u = None
        if entry.isdigit():
            u = await UserCRUD.get_by_telegram_id(session, int(entry))
        else:
            res = await session.execute(select(User).where(User.username.ilike(entry)))
            u = res.scalar_one_or_none()

        if u:
            name = f"@{u.username}" if u.username else u.full_name
            if await UserChannelCRUD.remove_user_from_channel(session, u.id, channel.id):
                removed_names.append(name)
            else:
                not_found.append(name)
        else:
            not_found.append(f"@{entry}")

    response = []
    if removed_names:
        response.append(f"<b>Успешно удалены из отслеживания:</b> [" + ", ".join(removed_names) + "]")
    if not_found:
        response.append(f"<b>Не найдены в списке для отслеживания:</b> [" + ", ".join(not_found) + "]")
    if not response:
        response.append("Никто не был удален.")

    await message.answer("\n\n".join(response))


# --- Управление Каналами и Событиями ---

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, command: CommandObject, session: AsyncSession):
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

    existing = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if existing:
        await message.answer(f"Ошибка: в этом чате уже зарегистрирован канал '{existing.title}'.")
        return

    await ChannelCRUD.create(session, message.chat.id, thread_id, title)

    await message.answer(
        f"Вы успешно создали канал <b>'{title}'</b>!\n\n"
        "<b>Мини-справка по дальнейшим шагам:</b>\n"
        "1) Добавьте события (типы отчетов): <code>/add_event</code>\n"
        "2) Добавьте пользователей: <code>/add_users</code>\n"
        "3) Настройте статистику: <code>/set_wstat</code>"
    )


@router.message(Command("rm_channel"))
async def cmd_rm_channel(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer("<b>Инструкция:</b>\nИспользуйте: <code>/rm_channel [название канала]</code>")
        return

    target_title = command.args.strip()
    thread_id = message.message_thread_id if message.is_topic_message else None

    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)

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
        await message.answer(f"Канал <b>'{channel.title}'</b> успешно удален.")


@router.message(Command("add_event"))
async def cmd_add_event(message: Message, command: CommandObject, state: FSMContext, session: AsyncSession):
    if not is_admin(message.from_user.id): return

    args = command.args.split() if command.args else []
    if len(args) < 2:
        await message.answer("Используйте: <code>/add_event [ключ] [время] [мин_фото]</code>")
        return

    keyword, time_str = args[0], args[1]
    min_photos = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 1

    try:
        h, m = map(int, time_str.split(':'))
        deadline = time(h, m)
    except:
        await message.answer("Ошибка формата времени! Используйте ЧЧ:ММ.")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
        return

    photo_bytes, file_id = None, None
    if message.photo:
        file_id = message.photo[-1].file_id
        file = await message.bot.get_file(file_id)
        photo_file = await message.bot.download_file(file.file_path)
        photo_bytes = photo_file.read()

    try:
        # Создаем событие
        await EventCRUD.create(session, channel.id, keyword, deadline, min_photos, photo_bytes, file_id)

        # Получаем список тех, кто уже в канале для отображения
        current_users = await UserChannelCRUD.get_users_by_channel(session, channel.id)
        users_names = [html.quote(f"@{u.username}" if u.username else u.full_name) for u in current_users]
        users_str = ", ".join(users_names) if users_names else "нет"

        await state.update_data(
            current_channel_id=channel.id,
            event_keyword=keyword,
            event_deadline=deadline.strftime('%H:%M')
        )
        await state.set_state(EventCreationStates.waiting_for_users)

        await message.answer(
            f"Событие настроено. Теперь добавьте отслеживаемых пользователей (отправьте список @username или ID через пробел).\n\n"
            f"Или введите /skip\n"
            f"Пользователи которые отслеживаются сейчас: [{users_str}]"
        )
    except IntegrityError:
        await message.answer("Ошибка: такой ключ уже существует в этом канале.")
    except Exception as e:
        logger.error(f"Error in add_event: {e}")
        await message.answer("Произошла ошибка при сохранении события.")


@router.message(EventCreationStates.waiting_for_users, Command("skip"))
async def skip_event_users(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    await finish_event_creation(message, state, session, data)


@router.message(EventCreationStates.waiting_for_users, F.text)
async def process_event_users(message: Message, state: FSMContext, session: AsyncSession):
    if message.text.startswith("/"): return

    data = await state.get_data()
    channel_id = data.get("current_channel_id")

    entries = [e.replace("@", "").strip() for e in message.text.replace(",", " ").replace(";", " ").split() if
               e.strip()]
    for entry in entries:
        u = None
        if entry.isdigit():
            u = await UserCRUD.get_by_telegram_id(session, int(entry))
        else:
            res = await session.execute(select(User).where(User.username.ilike(entry)))
            u = res.scalar_one_or_none()

        if u and not await UserChannelCRUD.in_user_in_channel(session, u.id, channel_id):
            await UserChannelCRUD.add_user_to_channel(session, u.id, channel_id)

    await finish_event_creation(message, state, session, data)

@router.message(Command("rm_event"))
async def cmd_rm_event(message: Message, state: FSMContext, session: AsyncSession):
    if not is_admin(message.from_user.id):
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)

    if not channel:
        await message.answer("В этой ветке нет активного канала. Создайте его через /add_channel")
        return

    events = await EventCRUD.get_active_by_channel(session, channel.id)
    if not events:
        await message.answer("В этой ветке пока нет событий.")
        return

    text = "<b>Список событий (пришлите номер для удаления):</b>\n\n"
    idx_map = {}
    for i, event in enumerate(events, 1):
        idx_map[str(i)] = event.id
        text += f"{i}. <b>{event.keyword}</b> — {event.deadline_time.strftime('%H:%M')}\n"

    # Сохраняем данные в состояние ЭТОЙ ветки
    await state.update_data(deletion_idx_map=idx_map)
    await state.set_state(EventDeletionStates.waiting_for_event_index)
    await message.answer(text)

@router.message(EventDeletionStates.waiting_for_event_index, F.text)
async def process_rm_event_index(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка цифры. Сработает только в той ветке, где был вызван /rm_event"""
    val = message.text.strip()

    # Если введена другая команда — игнорируем здесь, чтобы сработал основной хэндлер команды
    if val.startswith("/"):
        # Но чтобы состояние не «висело», если введена команда — сбрасываем его
        await state.clear()
        return

    if not val.isdigit():
        await message.answer("Пришлите цифру номера или /cancel.")
        return

    data = await state.get_data()
    user_map = data.get("deletion_idx_map", {})

    if val not in user_map:
        await message.answer("Неверный номер. Попробуйте снова.")
        return

    event_id = user_map[val]
    if await EventCRUD.delete(session, event_id):
        await message.answer("Событие успешно удалено.")
    else:
        await message.answer("Ошибка при удалении из базы.")

    await state.clear()

@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    channels = await ChannelCRUD.get_all_active(session)
    if not channels:
        await message.answer("Список активных каналов пуст.")
        return

    text = "<b>Список активных каналов:</b>\n\n"
    for ch in channels:
        thread_info = f" (Ветка ID: {ch.thread_id})" if ch.thread_id else " (Основной чат)"
        text += f"• <b>{ch.title}</b>{thread_info}\n"

    await message.answer(text)


@router.message(Command("list_users"))
async def cmd_list_users(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id): return
    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("Канал не настроен.")
        return
    users = await UserChannelCRUD.get_users_by_channel(session, channel.id)
    text = f"<b>Отслеживаемые пользователи ({html.quote(channel.title)}):</b>\n\n"
    for i, user in enumerate(users, 1):
        username = html.quote(f"@{user.username}") if user.username else "<i>(без username)</i>"
        text += f"{i}. {html.quote(user.full_name)} — {username} (ID: <code>{user.telegram_id}</code>)\n"
    await message.answer(text)


@router.message(Command("get_user_id"))
async def cmd_get_user_id(message: Message, command: CommandObject, session: AsyncSession):
    if command.args:
        val = command.args.replace("@", "").strip()
        if not val:
            await message.answer("Вы ввели пустой username.")
            return

        u_db = None
        if val.isdigit():
            u_db = await UserCRUD.get_by_telegram_id(session, int(val))
        else:
            res = await session.execute(select(User).where(User.username.ilike(val)))
            u_db = res.scalar_one_or_none()

        if u_db:
            await message.answer(
                f" <b>Пользователь (из базы):</b>\n"
                f"ID: <code>{u_db.telegram_id}</code>\n"
                f"Имя: {u_db.full_name}\n"
                f"Username: @{u_db.username}"
            )
        else:
            await message.answer(f"Пользователь '{val}' не найден в базе.")
        return

    reply_valid = False
    if message.reply_to_message:
        reply_valid = True
        if message.is_topic_message and message.message_thread_id:
            if message.reply_to_message.message_id == message.message_thread_id:
                reply_valid = False

    if reply_valid:
        u_reply = message.reply_to_message.from_user
        await message.answer(
            f"<b>Пользователь (Reply):</b>\n"
            f"ID: <code>{u_reply.id}</code>\n"
            f"Имя: {u_reply.full_name}\n"
            f"Username: @{u_reply.username}\n"
        )
        return

    u = message.from_user
    await message.answer(
        f"<b>Ваш профиль:</b>\n"
        f"ID: <code>{u.id}</code>\n"
        f"Имя: {u.full_name}\n"
        f"Username: @{u.username}"
    )


@router.message(Command("set_wstat"))
async def cmd_set_wstat(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Инструкция:</b>\n"
            "Используйте: <code>/set_wstat [ID канала] [ID треда (0 если нет)] [Заголовок]</code>\n\n"
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
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)

    if not channel:
        await message.answer("В этом чате/ветке нет активного канала. Сначала создайте его через /add_channel")
        return

    await ChannelCRUD.update_stats_destination(
        session, channel.id, target_chat_id, target_thread_id, custom_title
    )

    thread_info = f" (ветка {target_thread_id})" if target_thread_id else ""
    await message.answer(
        f"Настройки статистики обновлены!\n\n"
        f"<b>Куда:</b> ID {target_chat_id}{thread_info}\n"
        f"<b>Заголовок:</b> {custom_title}"
    )

@router.message(Command("get_thread_id"))
async def cmd_get_thread_id(message: Message):
    """Показывает ID текущего чата и ветки (thread)"""
    if not is_admin(message.from_user.id):
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id if message.is_topic_message else "Основной чат (0)"

    response = (
        f"<b>Данные для настройки статистики:</b>\n\n"
        f"ID группы: <code>{chat_id}</code>\n"
        f"ID ветки (thread_id): <code>{thread_id}</code>\n\n"
        )
    await message.answer(response)