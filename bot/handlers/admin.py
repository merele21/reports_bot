import logging
import re
import shlex
from datetime import time, date
from typing import Dict, Optional

from aiogram import Router, F, html
from aiogram.filters import Command, CommandObject, StateFilter, state
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from bot.config import settings
from bot.database.crud import (
    UserCRUD, ChannelCRUD, UserChannelCRUD, EventCRUD,
    TempEventCRUD, CheckoutEventCRUD, normalize_keyword
)
from bot.database.models import User

router = Router()
logger = logging.getLogger(__name__)


# --- Группы состояний ---
class EventDeletionStates(StatesGroup):
    waiting_for_event_index = State()


class EventCreationStates(StatesGroup):
    waiting_for_users = State()


class RegistrationStates(StatesGroup):
    waiting_for_display_name = State()


# --- Вспомогательные функции ---
def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_list


def parse_quoted_keyword(text: str) -> Optional[str]:
    """
    Извлекает keyword в кавычках из команды
    Пример: '/add_event "Касса 1 утро" 10:00 1' -> 'Касса 1 утро'
    """
    try:
        # Используем shlex для правильного парсинга кавычек
        parts = shlex.split(text)
        if len(parts) > 0:
            return parts[0]
    except ValueError:
        pass
    return None


# --- Обработчики ---

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.")


@router.message(Command("register"))
async def cmd_register(message: Message, command: CommandObject, session: AsyncSession):
    """
    Регистрация с опциональным store_id

    Форматы:
    /register - регистрация без store_id
    /register MSK-001 - регистрация с store_id
    """

    is_private = message.chat.type == "private"
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Проверяем, зарегистрирована ли текущая ветка в базе
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    is_reg_thread = channel and channel.title == "Регистрация"

    if is_private or is_reg_thread:
        telegram_id = message.from_user.id
        store_id = None
        if command.args:
            store_id = command.args.strip().upper()  # Нормализуем к верхнему регистру

            # Валидация формата (опционально)
            if not re.match(r'^[A-Z0-9\-]{3,50}$', store_id):
                await message.answer(
                    "❌ Неверный формат ID магазина.\n\n"
                    "Используйте формат: <code>MSK-001</code>, <code>SPB-042</code>\n"
                    "Только буквы, цифры и дефисы (3-50 символов)"
                )
                return

        existing_user = await UserCRUD.get_by_telegram_id(session, telegram_id)

        user = await UserCRUD.get_or_create(
            session,
            telegram_id=telegram_id,
            username=message.from_user.username or None,
            full_name=message.from_user.full_name or None,
            store_id=store_id or None
        )

        if existing_user:
            response = f"<b>Профиль обновлен, {user.full_name or 'пользователь'}!</b>\n\n"
            response += f"Telegram ID: <code>{user.telegram_id}</code>\n"
            if user.username:
                response += f"Username: @{user.username}\n"
            if user.store_id:
                response += f"ID магазина: <code>{user.store_id}</code>\n"
            else:
                response += "\n💡 Совет: укажите ID магазина для группировки:\n"
                response += "<code>/register MSK-001</code>"
        else:
            response = f"<b>Добро пожаловать, {user.full_name or 'пользователь'}!</b>\n\n"
            response += "✅ Вы успешно зарегистрированы.\n\n"
            response += f"Telegram ID: <code>{user.telegram_id}</code>\n"
            if user.username:
                response += f"Username: @{user.username}\n"
            if user.store_id:
                response += f"ID магазина: <code>{user.store_id}</code>\n"
            else:
                response += "\n💡 Чтобы указать ID магазина, используйте:\n"
                response += "<code>/register MSK-001</code>"

        await message.answer(response)
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
        help_text += "• /add_tmp_event - Добавить временное событие (удаляется в 23:59)\n"
        help_text += "• /add_event_checkout - Добавить двухэтапное событие (пересчет -> готово)\n"
        help_text += "• /rm_event - Удалить событие\n"
        help_text += "• /list_events - Список всех событий\n"
        help_text += "• /add_user - Добавить участника\n"
        help_text += "• /add_users - Добавить несколько участников сразу\n"
        help_text += "• /rm_user - Удалить участника\n"
        help_text += "• /rm_users - Удалить несколько участников сразу\n"
        help_text += "• /list_channels - Список каналов\n"
        help_text += "• /list_users - Отслеживаемые пользователи\n"
        help_text += "• /get_thread_id - Узнать ID текущей ветки\n"
        help_text += "• /set_wstat - Настройка еженедельной статистики\n"

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
            await message.answer(f"✅ Удален из отслеживания: {target_user.full_name}")
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
        await message.answer("Формат: `/rm_users @user1 @user2 @user3`")
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
        response.append(f"<b>✅ Успешно удалены из отслеживания:</b> [" + ", ".join(removed_names) + "]")
    if not_found:
        response.append(f"<b>⚠️ Не найдены в списке для отслеживания:</b> [" + ", ".join(not_found) + "]")
    if not response:
        response.append("Никто не был удален.")

    await message.answer("\n\n".join(response))


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
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)

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
        await message.answer(f"❌ Пользователей с ID магазина <code>{store_id}</code> не найдено")
        return

    added_names = []
    already_in_names = []

    for u in users:
        name = f"@{u.username}" if u.username else f"ID:{u.telegram_id}"

        if not await UserChannelCRUD.in_user_in_channel(session, u.id, channel.id):
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


@router.message(Command("list_stores"))
async def cmd_list_stores(message: Message, session: AsyncSession):
    """Показать список всех магазинов (store_id) с количеством пользователей"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    # Запрос группировки по store_id
    stmt = (
        select(User.store_id, func.count(User.id).label('count'))
        .where(User.is_active == True, User.store_id.isnot(None))
        .group_by(User.store_id)
        .order_by(User.store_id)
    )
    result = await session.execute(stmt)
    stores = result.all()

    if not stores:
        await message.answer("📋 Магазины с ID не найдены")
        return

    text = "<b>📋 Список магазинов:</b>\n\n"
    for store_id, count in stores:
        text += f"• <code>{store_id}</code> — {count} чел.\n"

    await message.answer(text)

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
        f"✅ Вы успешно создали канал <b>'{title}'</b>!\n\n"
        "<b>Мини-справка по дальнейшим шагам:</b>\n"
        "1) Добавьте события (типы отчетов): <code>/add_event</code>\n"
        "2) Добавьте пользователей или магазин: <code>/add_users</code> или <code>/add_users_by_store</code>\n"
        "3) Настройте статистику (опционально): <code>/set_wstat</code>"
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
        await message.answer(f"✅ Канал <b>'{channel.title}'</b> успешно удален.")


@router.message(Command("add_event"))
async def cmd_add_event(message: Message, command: CommandObject, session: AsyncSession):
    """
    Формат: /add_event "Касса 1 утро" 10:00 1
    Поддерживает keywords с пробелами в кавычках
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event \"Ключевое слово\" ЧЧ:ММ [мин_фото]</code>\n\n"
            "<b>Примеры:</b>\n"
            "<code>/add_event \"Касса 1 утро\" 10:00 1</code>\n"
            "<code>/add_event \"Склад/вечер\" 18:00 2</code>\n\n"
            "❗️ Ключевое слово с пробелами берите в кавычки!"
        )
        return

    try:
        # Парсим аргументы с поддержкой кавычек
        parts = shlex.split(command.args)

        if len(parts) < 2:
            await message.answer("Недостаточно аргументов. Проверьте формат команды.")
            return

        keyword = parts[0]  # Уже без кавычек благодаря shlex
        time_str = parts[1]
        min_photos = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1

        # Валидация длины keyword
        if len(keyword) > 24:
            await message.answer("⚠️ Ключевое слово не должно превышать 24 символа.")
            return

        # Парсинг времени
        try:
            h, m = map(int, time_str.split(':'))
            deadline = time(h, m)
        except:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        # Создаем событие
        await EventCRUD.create(session, channel.id, keyword, deadline, min_photos)

        await message.answer(
            f"✅ Событие <b>{html.quote(keyword)}</b> успешно создано.\n\n"
            f"📅 Дедлайн: <b>{deadline.strftime('%H:%M')}</b>\n"
            f"📸 Минимум фото: <b>{min_photos}</b>\n\n"
            f"<i>Дальнейшие шаги:</i>\n"
            f"• Добавьте отслеживаемых пользователей: <code>/add_users</code>\n"
            f"• Проверьте список: <code>/list_users</code>"
        )
    except ValueError as e:
        await message.answer(
            f"❌ Ошибка парсинга команды: {str(e)}\nПроверьте формат и используйте кавычки для ключевых слов с пробелами.")
    except IntegrityError:
        await session.rollback()
        await message.answer("❌ Ошибка: такой ключ уже существует в этом канале.")
    except Exception as e:
        logger.error(f"Error in add_event: {e}", exc_info=True)
        await message.answer("Произошла ошибка при сохранении события.")


@router.message(Command("add_tmp_event"))
async def cmd_add_tmp_event(message: Message, command: CommandObject, session: AsyncSession):
    """
    Временное событие, удаляется в 23:59 МСК
    Формат: /add_tmp_event "Разовая проверка" 15:00 1
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_tmp_event \"Ключевое слово\" ЧЧ:ММ [мин_фото]</code>\n\n"
            "<b>Примеры:</b>\n"
            "<code>/add_tmp_event \"Разовая проверка\" 15:00 1</code>\n\n"
            "⏱ Событие автоматически удалится в 23:59 МСК"
        )
        return

    try:
        parts = shlex.split(command.args)

        if len(parts) < 2:
            await message.answer("Недостаточно аргументов. Проверьте формат команды.")
            return

        keyword = parts[0]
        time_str = parts[1]
        min_photos = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1

        if len(keyword) > 24:
            await message.answer("⚠️ Ключевое слово не должно превышать 24 символа.")
            return

        try:
            h, m = map(int, time_str.split(':'))
            deadline = time(h, m)
        except:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        today = date.today()
        await TempEventCRUD.create(
            session, channel.id, keyword, deadline, today, min_photos
        )

        await message.answer(
            f"✅ Временное событие <b>{html.quote(keyword)}</b> создано.\n\n"
            f"📅 Дедлайн: <b>{deadline.strftime('%H:%M')}</b>\n"
            f"📸 Минимум фото: <b>{min_photos}</b>\n"
            f"⏱ Удалится: <b>23:59 МСК</b>"
        )
    except IntegrityError:
        await session.rollback()
        await message.answer("❌ Ошибка: такое временное событие уже существует сегодня.")
    except Exception as e:
        logger.error(f"Error in add_tmp_event: {e}", exc_info=True)
        await message.answer("Произошла ошибка при сохранении временного события.")


@router.message(Command("add_event_checkout"))
async def cmd_add_event_checkout(message: Message, command: CommandObject, session: AsyncSession):
    """
    Двухэтапное событие: пересчет (утро) -> готово (вечер)
    Формат: /add_event_checkout "Пересчет" 10:00 "Готово" 16:00 1
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event_checkout \"Первый ключ\" ЧЧ:ММ \"Второй ключ\" ЧЧ:ММ [мин_фото]</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/add_event_checkout \"Пересчет\" 10:00 \"Готово\" 16:00 1</code>\n\n"
            "<b>Как это работает:</b>\n"
            "1️⃣ Утром люди пишут: <code>Категории: скоропорт + тихое</code>\n"
            "2️⃣ Вечером отправляют фото с: <code>Готово: скоропорт</code>\n"
            "3️⃣ Бот отслеживает, что сдано, а что нет\n\n"
            "📋 Допустимые категории:\n"
            "элитка, сигареты, тихое, водка, пиво, игристое, коктейли,\n"
            "скоропорт, сопутка, вода, энергетики, бакалея, мороженое,\n"
            "шоколад, нонфуд, штучки"
        )
        return

    try:
        parts = shlex.split(command.args)

        if len(parts) < 4:
            await message.answer("Недостаточно аргументов. Нужно: 2 ключевых слова + 2 времени.")
            return

        first_keyword = parts[0]
        first_time_str = parts[1]
        second_keyword = parts[2]
        second_time_str = parts[3]
        min_photos = int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else 1

        if len(first_keyword) > 24 or len(second_keyword) > 24:
            await message.answer("⚠️ Ключевые слова не должны превышать 24 символа.")
            return

        try:
            h1, m1 = map(int, first_time_str.split(':'))
            first_deadline = time(h1, m1)

            h2, m2 = map(int, second_time_str.split(':'))
            second_deadline = time(h2, m2)
        except:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return

        if first_deadline >= second_deadline:
            await message.answer("⚠️ Первый дедлайн должен быть раньше второго!")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        await CheckoutEventCRUD.create(
            session, channel.id,
            first_keyword, first_deadline,
            second_keyword, second_deadline,
            min_photos
        )

        await message.answer(
            f"✅ Двухэтапное событие создано!\n\n"
            f"1️⃣ <b>{html.quote(first_keyword)}</b> до {first_deadline.strftime('%H:%M')}\n"
            f"2️⃣ <b>{html.quote(second_keyword)}</b> до {second_deadline.strftime('%H:%M')}\n"
            f"📸 Минимум фото: {min_photos}\n\n"
            f"<i>Люди должны будут указывать категории из списка:\n"
            f"элитка, сигареты, тихое, водка, пиво, игристое, коктейли,\n"
            f"скоропорт, сопутка, вода, энергетики, бакалея, мороженое,\n"
            f"шоколад, нонфуд, штучки</i>"
        )
    except Exception as e:
        logger.error(f"Error in add_event_checkout: {e}", exc_info=True)
        await message.answer("Произошла ошибка при сохранении checkout события.")


@router.message(Command("rm_event"))
async def cmd_rm_event(message: Message, state: FSMContext, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)

    if not channel:
        await message.answer("В этой ветке нет активного канала. Создайте его через /add_channel")
        return

    # Получаем обычные события
    events = await EventCRUD.get_active_by_channel(session, channel.id)
    
    # Получаем временные события
    today = date.today()
    temp_events = await TempEventCRUD.get_active_by_channel_and_date(session, channel.id, today)
    
    # Получаем checkout события
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)
    
    # Получаем notext события
    from bot.database.crud import NoTextEventCRUD, KeywordEventCRUD
    notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel.id)
    
    # Получаем keyword события (open/close)
    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel.id)

    if not events and not temp_events and not checkout_events and not notext_events and not keyword_events:
        await message.answer("В этой ветке пока нет событий.")
        return

    text = "<b>Список событий (пришлите номер для удаления):</b>\n\n"
    idx_map = {}
    counter = 1

    # Добавляем обычные события
    if events:
        text += "<b>📋 Постоянные события:</b>\n"
        for event in events:
            idx_map[str(counter)] = ('event', event.id)
            text += f"{counter}. <b>{event.keyword}</b> — {event.deadline_time.strftime('%H:%M')}\n"
            counter += 1
        text += "\n"

    # Добавляем временные события
    if temp_events:
        text += "<b>⏱ Временные события (удалятся в 23:59):</b>\n"
        for temp_event in temp_events:
            idx_map[str(counter)] = ('temp_event', temp_event.id)
            text += f"{counter}. <b>{temp_event.keyword}</b> — {temp_event.deadline_time.strftime('%H:%M')}\n"
            counter += 1
        text += "\n"
    
    # Добавляем checkout события
    if checkout_events:
        text += "<b>🔄 Двухэтапные события (checkout):</b>\n"
        for checkout_event in checkout_events:
            idx_map[str(counter)] = ('checkout_event', checkout_event.id)
            text += (f"{counter}. <b>{checkout_event.first_keyword}</b> → <b>{checkout_event.second_keyword}</b> "
                    f"({checkout_event.first_deadline_time.strftime('%H:%M')} → "
                    f"{checkout_event.second_deadline_time.strftime('%H:%M')})\n")
            counter += 1
        text += "\n"
    
    # Добавляем notext события
    if notext_events:
        text += "<b>📸 События без текста (notext):</b>\n"
        for notext_event in notext_events:
            idx_map[str(counter)] = ('notext_event', notext_event.id)
            text += (f"{counter}. Отслеживание фото с <b>{notext_event.deadline_start.strftime('%H:%M')}</b> "
                    f"до <b>{notext_event.deadline_end.strftime('%H:%M')}</b>\n")
            counter += 1
        text += "\n"
    
    # Добавляем keyword события
    if keyword_events:
        text += "<b>🔑 События с ключевым словом (open/close):</b>\n"
        for keyword_event in keyword_events:
            idx_map[str(counter)] = ('keyword_event', keyword_event.id)
            text += (f"{counter}. <b>{keyword_event.keyword}</b> с <b>{keyword_event.deadline_start.strftime('%H:%M')}</b> "
                    f"до <b>{keyword_event.deadline_end.strftime('%H:%M')}</b>\n")
            counter += 1

    await state.update_data(deletion_idx_map=idx_map)
    await state.set_state(EventDeletionStates.waiting_for_event_index)
    await message.answer(text)


@router.message(EventDeletionStates.waiting_for_event_index, F.text)
async def process_rm_event_index(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка цифры. Сработает только в той ветке, где был вызван /rm_event"""
    val = message.text.strip()

    if val.startswith("/"):
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

    event_type, event_id = user_map[val]
    
    from bot.database.crud import NoTextEventCRUD, KeywordEventCRUD
    
    success = False
    if event_type == 'event':
        success = await EventCRUD.delete(session, event_id)
        event_name = "Событие"
    elif event_type == 'temp_event':
        success = await TempEventCRUD.delete(session, event_id)
        event_name = "Временное событие"
    elif event_type == 'checkout_event':
        success = await CheckoutEventCRUD.delete(session, event_id)
        event_name = "Двухэтапное событие"
    elif event_type == 'notext_event':
        await NoTextEventCRUD.delete(session, event_id)
        success = True
        event_name = "Событие без текста"
    elif event_type == 'keyword_event':
        await KeywordEventCRUD.delete(session, event_id)
        success = True
        event_name = "Событие с ключевым словом"
    
    if success:
        await message.answer(f"✅ {event_name} успешно удалено.")
    else:
        await message.answer("❌ Ошибка при удалении из базы.")

    await state.clear()


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    channels = await ChannelCRUD.get_all_active(session)
    if not channels:
        await message.answer("📋 Список активных каналов пуст.")
        return

    text = "<b>📋 Список активных каналов:</b>\n\n"
    for ch in channels:
        thread_info = f" (Ветка ID: {ch.thread_id})" if ch.thread_id else " (Основной чат)"
        text += f"• <b>{ch.title}</b>{thread_info}\n"

    await message.answer(text)


@router.message(Command("list_events"))
async def cmd_list_events(message: Message, session: AsyncSession):
    """Показать список всех событий в текущей ветке"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)

    if not channel:
        await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
        return

    # Получаем все типы событий
    events = await EventCRUD.get_active_by_channel(session, channel.id)
    today = date.today()
    temp_events = await TempEventCRUD.get_active_by_channel_and_date(session, channel.id, today)
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)

    if not events and not temp_events and not checkout_events:
        await message.answer(f"📋 В канале <b>{html.quote(channel.title)}</b> пока нет событий.")
        return

    text = f"<b>📋 События в канале {html.quote(channel.title)}:</b>\n\n"

    # Постоянные события
    if events:
        text += "<b>📌 Постоянные события:</b>\n"
        for i, event in enumerate(events, 1):
            text += f"{i}. <b>{html.quote(event.keyword)}</b>\n"
            text += f"   ⏰ Дедлайн: {event.deadline_time.strftime('%H:%M')}\n"
            text += f"   📸 Мин. фото: {event.min_photos}\n"
            text += "\n"

    # Временные события
    if temp_events:
        text += "<b>⏱ Временные события (удалятся в 23:59):</b>\n"
        for i, temp_event in enumerate(temp_events, 1):
            text += f"{i}. <b>{html.quote(temp_event.keyword)}</b>\n"
            text += f"   ⏰ Дедлайн: {temp_event.deadline_time.strftime('%H:%M')}\n"
            text += f"   📸 Мин. фото: {temp_event.min_photos}\n"
            text += f"   📅 Дата: {temp_event.event_date.strftime('%d.%m.%Y')}\n"
            text += "\n"

    # Checkout события
    if checkout_events:
        text += "<b>🔄 Двухэтапные события (checkout):</b>\n"
        for i, checkout_event in enumerate(checkout_events, 1):
            text += f"{i}. <b>{html.quote(checkout_event.first_keyword)}</b> → <b>{html.quote(checkout_event.second_keyword)}</b>\n"
            text += f"   1️⃣ Первый этап: {checkout_event.first_deadline_time.strftime('%H:%M')}\n"
            text += f"   2️⃣ Второй этап: {checkout_event.second_deadline_time.strftime('%H:%M')}\n"
            text += f"   📸 Мин. фото: {checkout_event.min_photos}\n"
            text += "\n"

    text += f"<b>Всего событий:</b> {len(events) + len(temp_events) + len(checkout_events)}"

    await message.answer(text)


@router.message(Command("list_users"))
async def cmd_list_users(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("Канал не настроен.")
        return

    users = await UserChannelCRUD.get_users_by_channel(session, channel.id)
    text = f"<b>👥 Отслеживаемые пользователи ({html.quote(channel.title)}):</b>\n\n"
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
                f"👤 <b>Пользователь (из базы):</b>\n"
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
        f"✅ Настройки статистики обновлены!\n\n"
        f"<b>Куда:</b> ID {target_chat_id}{thread_info}\n"
        f"<b>Заголовок:</b> {custom_title}"
    )


@router.message(Command("get_thread_id"))
async def cmd_get_thread_id(message: Message):
    """Показывает ID текущего чата и ветки (thread)"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id if message.is_topic_message else "Основной чат (0)"

    response = (
        f"<b>📍 Данные для настройки статистики:</b>\n\n"
        f"ID группы: <code>{chat_id}</code>\n"
        f"ID ветки (thread_id): <code>{thread_id}</code>\n\n"
    )
    await message.answer(response)


@router.message(Command("add_event_notext"))
async def cmd_add_event_notext(message: Message, command: CommandObject, session: AsyncSession):
    """
    Событие без текста - отслеживание только фото по расписанию
    Формат: /add_event_notext ЧЧ:ММ ЧЧ:ММ
    Пример: /add_event_notext 09:00 18:00
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event_notext [начало] [конец]</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/add_event_notext 09:00 18:00</code>\n\n"
            "Бот будет отслеживать отправку фото (желательно) от зарегистрированных пользователей "
            "в указанный промежуток времени. Статистика публикуется строго в время [конец].\n\n"
            "Для выходного дня пользователь пишет: <code>выходной</code>"
        )
        return

    try:
        parts = command.args.split()
        if len(parts) < 2:
            await message.answer("Недостаточно аргументов. Укажите время начала и конца.")
            return

        start_str = parts[0]
        end_str = parts[1]

        try:
            h1, m1 = map(int, start_str.split(':'))
            deadline_start = time(h1, m1)

            h2, m2 = map(int, end_str.split(':'))
            deadline_end = time(h2, m2)
        except:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return

        if deadline_start >= deadline_end:
            await message.answer("⚠️ Время начала должно быть раньше времени конца!")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        from bot.database.crud import NoTextEventCRUD
        await NoTextEventCRUD.create(
            session, channel.id, deadline_start, deadline_end
        )

        await message.answer(
            f"✅ Событие без текста создано!\n\n"
            f"⏰ Отслеживание: с <b>{deadline_start.strftime('%H:%M')}</b> до <b>{deadline_end.strftime('%H:%M')}</b>\n"
            f"📊 Статистика будет опубликована в <b>{deadline_end.strftime('%H:%M')}</b>\n\n"
            f"📝 Для выходного дня пользователь пишет: <code>выходной</code>"
        )
    except Exception as e:
        logger.error(f"Error in add_event_notext: {e}", exc_info=True)
        await message.answer("Произошла ошибка при создании события.")


@router.message(Command("add_event_kw"))
async def cmd_add_event_kw(message: Message, command: CommandObject, session: AsyncSession):
    """
    Событие с ключевым словом (например, "открыт")
    Формат: /add_event_kw ЧЧ:ММ ЧЧ:ММ "ключевое слово"
    Пример: /add_event_kw 09:00 18:00 "открыт"
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event_kw [начало] [конец] \"ключевое слово\"</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/add_event_kw 09:00 18:00 \"открыт\"</code>\n\n"
            "Ключевое слово может быть в любом месте сообщения и поддерживает вариации:\n"
            "открыт, открыта, открыто, открытие (до 5 символов после базового слова)"
        )
        return

    try:
        parts = shlex.split(command.args)
        if len(parts) < 3:
            await message.answer("Недостаточно аргументов. Проверьте формат команды.")
            return

        start_str = parts[0]
        end_str = parts[1]
        keyword = parts[2]

        if len(keyword) > 24:
            await message.answer("⚠️ Ключевое слово не должно превышать 24 символа.")
            return

        try:
            h1, m1 = map(int, start_str.split(':'))
            deadline_start = time(h1, m1)

            h2, m2 = map(int, end_str.split(':'))
            deadline_end = time(h2, m2)
        except:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return

        if deadline_start >= deadline_end:
            await message.answer("⚠️ Время начала должно быть раньше времени конца!")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        from bot.database.crud import KeywordEventCRUD
        await KeywordEventCRUD.create(
            session, channel.id, deadline_start, deadline_end, keyword
        )

        await message.answer(
            f"✅ Событие с ключевым словом создано!\n\n"
            f"🔑 Ключевое слово: <b>{html.quote(keyword)}</b>\n"
            f"⏰ Отслеживание: с <b>{deadline_start.strftime('%H:%M')}</b> до <b>{deadline_end.strftime('%H:%M')}</b>\n"
            f"📊 Статистика будет опубликована в <b>{deadline_end.strftime('%H:%M')}</b>\n\n"
            f"💡 Поддерживаются вариации: {keyword}, {keyword}а, {keyword}о и т.д."
        )
    except Exception as e:
        logger.error(f"Error in add_event_kw: {e}", exc_info=True)
        await message.answer("Произошла ошибка при создании события.")