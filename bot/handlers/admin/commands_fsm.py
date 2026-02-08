"""
FSM обработчики для интерактивных команд
"""
import asyncio
import logging
import shlex
from datetime import time, date

from aiogram import Router, F, html
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.cfg.commands_config import (
    get_command_config,
    get_command_input_prompt,
    format_command_help
)
from bot.database.crud import (
    UserCRUD, ChannelCRUD, UserChannelCRUD,
    EventCRUD, TempEventCRUD, CheckoutEventCRUD,
    NoTextEventCRUD, KeywordEventCRUD
)
from bot.handlers.admin.utils import (
    is_admin,
    parse_time_string,
    validate_keyword_length,
    validate_store_id_format
)

router = Router()
logger = logging.getLogger(__name__)


# ==================== FSM STATES ====================

class RegisterStates(StatesGroup):
    """Состояния для регистрации"""
    waiting_for_store_id = State()


class AddUserStates(StatesGroup):
    """Состояния для добавления пользователей"""
    waiting_for_user = State()
    waiting_for_users = State()
    waiting_for_store_id = State()


class RemoveUserStates(StatesGroup):
    """Состояния для удаления пользователей"""
    waiting_for_user = State()
    waiting_for_users = State()


class AddEventStates(StatesGroup):
    """Состояния для создания событий"""
    waiting_for_params = State()


class AddChannelStates(StatesGroup):
    """Состояния для создания канала"""
    waiting_for_title = State()


class RemoveChannelStates(StatesGroup):
    """Состояния для удаления канала"""
    waiting_for_title = State()


class SetWstatStates(StatesGroup):
    """Состояния для настройки статистики"""
    waiting_for_params = State()


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

async def delete_with_animation(
        bot,
        chat_id: int,
        message_id: int,
        animation_type: str
):
    """
    Удаление с анимацией

    Args:
        animation_type: "fire", "lightning", "collapse", "stardust", "fade"
    """
    animations = {
        "fire": ["🔥 Удаляем...", "🔥🔥 Сгораем...", "🔥🔥🔥", "💨", "✨"],
        "lightning": ["⚡", "⚡⚡", "⚡⚡⚡", "💥"],
        "collapse": ["▼ Закрываем...", "▼▼", "▼▼▼", "⏬", "🔻", "·"],
        "stardust": ["✨ Превращаемся...", "✨✨", "✨✨✨", "🌟", "⭐", "💫", "·"],
        "fade": ["Удаляем...", ".", "..", "..."]
    }

    sequence = animations.get(animation_type, animations["fade"])
    delay = 0.20 if animation_type == "fade" else 0.05

    for anim in sequence:
        try:
            await bot.edit_message_text(chat_id, message_id, anim)
            await asyncio.sleep(delay)
        except Exception:
            break

    await asyncio.sleep(delay)
    await bot.delete_message(chat_id, message_id)

async def delete_prompt_message(message: Message, state: FSMContext):
    """
    Удаляет сообщение с подсказкой FSM

    Args:
        message: Сообщение пользователя
        state: FSM контекст
    """
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")

    if prompt_message_id:
        try:
            await delete_with_animation(
                message.bot,
                message.chat.id,
                prompt_message_id,
                animation_type="fade"  # Выбор анимации
            )
        except Exception:
            pass


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]
    ])


def get_register_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора режима регистрации"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="1️⃣ Регистрация без ID магазина",
            callback_data="register_no_store"
        )],
        [InlineKeyboardButton(
            text="2️⃣ Регистрация с ID магазина",
            callback_data="register_with_store"
        )],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]
    ])


# ==================== ОБРАБОТЧИКИ РЕГИСТРАЦИИ ====================

@router.message(Command("register"))
async def cmd_register_interactive(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Интерактивная регистрация с выбором режима"""
    is_private = message.chat.type == "private"
    thread_id = message.message_thread_id if message.is_topic_message else None

    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )
    is_reg_thread = channel and channel.title == "Регистрация"

    if not is_private and not is_reg_thread:
        bot_info = await message.bot.get_me()
        bot_link = f"https://t.me/{bot_info.username}"

        await message.answer(
            f"<b>Команда /register здесь недоступна.</b>\n\n"
            f"Пожалуйста, пройдите регистрацию в "
            f"<a href='{bot_link}'><b>личных сообщениях</b></a> бота "
            f"или перейдите в ветку <b>Регистрация</b>.",
            disable_web_page_preview=True
        )
        return

    # Показываем выбор режима
    text = (
        "<b>📝 Регистрация пользователя</b>\n\n"
        "Выберите режим регистрации:\n\n"
        "1️⃣ <b>Без ID магазина</b>\n"
        "   Для индивидуального учета\n\n"
        "2️⃣ <b>С ID магазина</b>\n"
        "   Для группировки с коллегами из вашего магазина\n\n"
        "💡 <i>Несколько человек могут использовать один ID магазина</i>"
    )

    await message.answer(
        text,
        reply_markup=get_register_keyboard()
    )


@router.callback_query(F.data == "register_no_store")
async def process_register_no_store(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
):
    """Регистрация без магазина"""
    await callback.answer()
    await state.clear()  # Очищаем состояние на всякий случай

    telegram_id = callback.from_user.id

    # Получаем или создаем пользователя
    existing_user = await UserCRUD.get_by_telegram_id(session, telegram_id)

    old_store_id = existing_user.store_id if existing_user else None
    old_username = existing_user.username if existing_user else None
    old_fullname = existing_user.full_name if existing_user else None

    user = await UserCRUD.get_or_create(
        session,
        telegram_id=telegram_id,
        username=callback.from_user.username or None,
        full_name=callback.from_user.full_name or None,
        store_id=None
    )

    # Импортируем функцию форматирования
    from bot.handlers.admin.registration import _format_registration_response

    response = await _format_registration_response(
        session, user, existing_user, old_store_id, old_username, old_fullname, telegram_id
    )

    # Удаляем сообщение с кнопками выбора
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Отправляем результат новым сообщением
    await callback.message.answer(response)


@router.callback_query(F.data == "register_with_store")
async def process_register_with_store(
    callback: CallbackQuery,
    state: FSMContext
):
    """Переход к вводу store_id"""
    await callback.answer()

    text = (
        "<b>📝 Регистрация с ID магазина</b>\n\n"
        "Введите ID вашего магазина:\n\n"
        "<b>Правильный формат:</b> <code>XXX-NNN</code>\n"
        "• XXX — латинские буквы A-Z и цифры 0-9 (от 2 до 7 символов)\n"
        "• NNN — цифры 0-9 (от 1 до 10 цифр)\n\n"
        "<b>Примеры правильных ID:</b>\n"
        "• <code>MSK-001</code>\n"
        "• <code>MSK999-001</code>\n"
        "• <code>SPB-042</code>\n"
        "• <code>SHOP-42</code>\n"
        "• <code>MOSCOW-123</code>\n\n"
        "💡 <i>Несколько человек могут использовать один ID магазина</i>"
    )

    await state.set_state(RegisterStates.waiting_for_store_id)

    # Сохраняем message_id подсказки для последующего удаления
    await state.update_data(prompt_message_id=callback.message.message_id)

    await callback.message.edit_text(
        text,
        reply_markup=get_cancel_keyboard()
    )


@router.message(RegisterStates.waiting_for_store_id, F.text)
async def process_store_id_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода store_id"""
    # Проверка на команду
    if message.text.startswith("/"):
        await state.clear()
        return

    store_id_raw = message.text.strip().upper()

    # Валидация формата
    validation_result = validate_store_id_format(store_id_raw)
    if not validation_result["valid"]:
        await message.answer(
            validation_result["error_message"],
            reply_markup=get_cancel_keyboard()
        )
        return

    store_id = store_id_raw
    telegram_id = message.from_user.id

    # Получаем или создаем пользователя
    existing_user = await UserCRUD.get_by_telegram_id(session, telegram_id)

    old_store_id = existing_user.store_id if existing_user else None
    old_username = existing_user.username if existing_user else None
    old_fullname = existing_user.full_name if existing_user else None

    user = await UserCRUD.get_or_create(
        session,
        telegram_id=telegram_id,
        username=message.from_user.username or None,
        full_name=message.from_user.full_name or None,
        store_id=store_id
    )

    # Импортируем функцию форматирования
    from bot.handlers.admin.registration import _format_registration_response

    response = await _format_registration_response(
        session, user, existing_user, old_store_id, old_username, old_fullname, telegram_id
    )

    # Удаляем сообщение с подсказкой
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")

    if prompt_message_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id,
                message_id=prompt_message_id
            )
        except Exception:
            pass

    # Удаляем сообщение пользователя с введенным store_id (опционально)
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(response)
    await state.clear()


# ==================== ОБРАБОТЧИКИ УПРАВЛЕНИЯ ПОЛЬЗОВАТЕЛЯМИ ====================

@router.message(Command("add_user"))
async def cmd_add_user_interactive(message: Message, state: FSMContext):
    """Интерактивное добавление пользователя"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_user")

    await state.set_state(AddUserStates.waiting_for_user)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    # Сохраняем message_id для последующего удаления
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(AddUserStates.waiting_for_user, F.text)
async def process_add_user_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для add_user"""
    if message.text.startswith("/"):
        await state.clear()
        return

    # Импортируем оригинальную логику
    from bot.handlers.admin.users import _find_user_by_identifier, _is_phantom_reply

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        await state.clear()
        return

    target_user = await _find_user_by_identifier(session, message.text.strip())

    if not target_user:
        await message.answer(
            f"Пользователь '{message.text.strip()}' не найден в базе. "
            f"Пусть нажмет /register.",
            reply_markup=get_cancel_keyboard()
        )
        return

    # Проверка, не добавлен ли уже
    in_channel = await UserChannelCRUD.in_user_in_channel(
        session, target_user.id, channel.id
    )

    # Удаляем сообщения FSM
    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

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

    await state.clear()


@router.message(Command("add_users"))
async def cmd_add_users_interactive(message: Message, state: FSMContext):
    """Интерактивное добавление нескольких пользователей"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_users")
    await state.set_state(AddUserStates.waiting_for_users)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(AddUserStates.waiting_for_users, F.text)
async def process_add_users_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для add_users"""
    if message.text.startswith("/"):
        await state.clear()
        return

    # Импортируем оригинальную логику
    from bot.handlers.admin.users import _find_user_by_identifier
    from bot.handlers.admin.utils import parse_user_list, format_user_mention

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        await state.clear()
        return

    entries = parse_user_list(message.text)

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
            f"<b>✅ Успешно добавлены для отслеживания:</b>\n" +
            "\n".join([f"• {n}" for n in added_names])
        )
    if already_in_names:
        response.append(
            f"<b>⚠️ Пропущены, уже отслеживаются:</b>\n" +
            "\n".join([f"• {n}" for n in already_in_names])
        )
    if not_found:
        response.append(
            f"<b>❌ Не найдены в базе (пусть нажмут /register):</b>\n" +
            "\n".join([f"• {n}" for n in not_found])
        )

    if not response:
        response.append("Список имен для добавления пуст.")

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer("\n\n".join(response))
    await state.clear()


@router.message(Command("add_users_by_store"))
async def cmd_add_users_by_store_interactive(message: Message, state: FSMContext):
    """Интерактивное добавление пользователей по store_id"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_users_by_store")
    await state.set_state(AddUserStates.waiting_for_store_id)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(AddUserStates.waiting_for_store_id, F.text)
async def process_add_users_by_store_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для add_users_by_store"""
    if message.text.startswith("/"):
        await state.clear()
        return

    from bot.handlers.admin.utils import format_user_mention

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не настроен. Сначала используйте /add_channel")
        await state.clear()
        return

    store_id = message.text.strip().upper()

    # Получаем всех пользователей магазина
    users = await UserCRUD.get_by_store_id(session, store_id)

    if not users:
        await message.answer(
            f"❌ Пользователей с ID магазина <code>{store_id}</code> не найдено"
        )
        await state.clear()
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

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer("\n\n".join(response))

    logger.info(
        f"Store users added: store_id={store_id}, "
        f"added={len(added_names)}, channel_id={channel.id}"
    )

    await state.clear()


@router.message(Command("rm_user"))
async def cmd_rm_user_interactive(message: Message, state: FSMContext):
    """Интерактивное удаление пользователя"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("rm_user")
    await state.set_state(RemoveUserStates.waiting_for_user)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(RemoveUserStates.waiting_for_user, F.text)
async def process_rm_user_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для rm_user"""
    if message.text.startswith("/"):
        await state.clear()
        return

    from bot.handlers.admin.users import _find_user_by_identifier

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не найден.")
        await state.clear()
        return

    target_user = await _find_user_by_identifier(session, message.text.strip())

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

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

    await state.clear()


@router.message(Command("rm_users"))
async def cmd_rm_users_interactive(message: Message, state: FSMContext):
    """Интерактивное удаление нескольких пользователей"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("rm_users")
    await state.set_state(RemoveUserStates.waiting_for_users)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(RemoveUserStates.waiting_for_users, F.text)
async def process_rm_users_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для rm_users"""
    if message.text.startswith("/"):
        await state.clear()
        return

    from bot.handlers.admin.users import _find_user_by_identifier
    from bot.handlers.admin.utils import parse_user_list, format_user_mention

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не найден.")
        await state.clear()
        return

    entries = parse_user_list(message.text)

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
            f"<b>✅ Успешно удалены из отслеживания:</b>\n" +
            "\n".join([f"• {n}" for n in removed_names])
        )
    if not_found:
        response.append(
            f"<b>⚠️ Не найдены в списке для отслеживания:</b>\n" +
            "\n".join([f"• {n}" for n in not_found])
        )

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

    if not response:
        response.append("Никто не был удален.")

    await message.answer("\n\n".join(response))
    await state.clear()


# ==================== ОБРАБОТЧИКИ СОБЫТИЙ ====================

@router.message(Command("add_event"))
async def cmd_add_event_interactive(message: Message, state: FSMContext):
    """Интерактивное создание обычного события"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_event")
    await state.set_state(AddEventStates.waiting_for_params)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(command="add_event", prompt_message_id=sent_message.message_id)


@router.message(Command("add_tmp_event"))
async def cmd_add_tmp_event_interactive(message: Message, state: FSMContext):
    """Интерактивное создание временного события"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_tmp_event")
    await state.set_state(AddEventStates.waiting_for_params)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(command="add_tmp_event", prompt_message_id=sent_message.message_id)


@router.message(Command("add_event_checkout"))
async def cmd_add_event_checkout_interactive(message: Message, state: FSMContext):
    """Интерактивное создание checkout события"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_event_checkout")
    await state.set_state(AddEventStates.waiting_for_params)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(command="add_event_checkout", prompt_message_id=sent_message.message_id)


@router.message(Command("add_event_notext"))
async def cmd_add_event_notext_interactive(message: Message, state: FSMContext):
    """Интерактивное создание notext события"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_event_notext")
    await state.set_state(AddEventStates.waiting_for_params)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(command="add_event_notext", prompt_message_id=sent_message.message_id)


@router.message(Command("add_event_kw"))
async def cmd_add_event_kw_interactive(message: Message, state: FSMContext):
    """Интерактивное создание keyword события"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("add_event_kw")
    await state.set_state(AddEventStates.waiting_for_params)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(command="add_event_kw", prompt_message_id=sent_message.message_id)


@router.message(AddEventStates.waiting_for_params, F.text)
async def process_event_params_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода параметров для событий"""
    if message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    command = data.get("command")

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

    # Передаем обработку в соответствующие хендлеры
    if command == "add_event":
        await _process_add_event(message, session)
    elif command == "add_tmp_event":
        await _process_add_tmp_event(message, session)
    elif command == "add_event_checkout":
        await _process_add_checkout_event(message, session)
    elif command == "add_event_notext":
        await _process_add_notext_event(message, session)
    elif command == "add_event_kw":
        await _process_add_keyword_event(message, session)

    await state.clear()


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОБРАБОТКИ СОБЫТИЙ ====================

async def _process_add_event(message: Message, session: AsyncSession):
    """Обработка создания обычного события"""
    try:
        parts = shlex.split(message.text)

        if len(parts) < 2:
            await message.answer("❌ Недостаточно параметров. Проверьте формат.")
            return

        keyword = parts[0]
        time_str = parts[1]
        min_photos = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1

        # Валидация
        validation = validate_keyword_length(keyword)
        if not validation["valid"]:
            await message.answer(validation["error_message"])
            return

        time_parts = parse_time_string(time_str)
        if not time_parts:
            await message.answer("❌ Неправильный формат времени! Используйте ЧЧ:ММ.")
            return

        deadline = time(*time_parts)

        # Получаем канал
        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        # Создаем событие
        await EventCRUD.create(session, channel.id, keyword, deadline, min_photos)

        await message.answer(
            f"✅ Событие <b>{html.quote(keyword)}</b> успешно создано.\n\n"
            f"📅 Дедлайн: <b>{deadline.strftime('%H:%M')}</b>\n"
            f"📸 Минимум фото: <b>{min_photos}</b>"
        )

        logger.info(
            f"Event created: keyword={keyword}, deadline={deadline}, "
            f"channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in _process_add_event: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при создании события.")


async def _process_add_tmp_event(message: Message, session: AsyncSession):
    """Обработка создания временного события"""
    try:
        parts = shlex.split(message.text)

        if len(parts) < 2:
            await message.answer("❌ Недостаточно параметров. Проверьте формат.")
            return

        keyword = parts[0]
        time_str = parts[1]
        min_photos = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1

        validation = validate_keyword_length(keyword)
        if not validation["valid"]:
            await message.answer(validation["error_message"])
            return

        time_parts = parse_time_string(time_str)
        if not time_parts:
            await message.answer("❌ Неправильный формат времени! Используйте ЧЧ:ММ.")
            return

        deadline = time(*time_parts)

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
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

        logger.info(
            f"Temp event created: keyword={keyword}, deadline={deadline}, "
            f"date={today}, channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in _process_add_tmp_event: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при создании временного события.")


async def _process_add_checkout_event(message: Message, session: AsyncSession):
    """Обработка создания checkout события"""
    try:
        parts = shlex.split(message.text)

        if len(parts) < 4:
            await message.answer("❌ Недостаточно параметров. Проверьте формат.")
            return

        first_keyword = parts[0]
        first_time_str = parts[1]
        second_keyword = parts[2]
        second_time_str = parts[3]
        min_photos = int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else 1

        stats_time = None
        if len(parts) >= 6 and ':' in parts[5]:
            stats_time_parts = parse_time_string(parts[5])
            if stats_time_parts:
                stats_time = time(*stats_time_parts)

        # Валидация ключевых слов
        for kw in [first_keyword, second_keyword]:
            validation = validate_keyword_length(kw)
            if not validation["valid"]:
                await message.answer(validation["error_message"])
                return

        # Парсинг времени
        first_time_parts = parse_time_string(first_time_str)
        if not first_time_parts:
            await message.answer("❌ Неправильный формат первого времени!")
            return
        first_deadline = time(*first_time_parts)

        second_time_parts = parse_time_string(second_time_str)
        if not second_time_parts:
            await message.answer("❌ Неправильный формат второго времени!")
            return
        second_deadline = time(*second_time_parts)

        if first_deadline >= second_deadline:
            await message.answer("⚠️ Первый дедлайн должен быть раньше второго!")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        await CheckoutEventCRUD.create(
            session, channel.id,
            first_keyword, first_deadline,
            second_keyword, second_deadline,
            min_photos,
            stats_time
        )

        stats_time_str = stats_time.strftime('%H:%M') if stats_time else "22:00"
        await message.answer(
            f"✅ Двухэтапное событие создано!\n\n"
            f"1️⃣ <b>{html.quote(first_keyword)}</b> до {first_deadline.strftime('%H:%M')}\n"
            f"2️⃣ <b>{html.quote(second_keyword)}</b> до {second_deadline.strftime('%H:%M')}\n"
            f"📸 Минимум фото: {min_photos}\n"
            f"📊 Статистика: <b>{stats_time_str} МСК</b>"
        )

        logger.info(
            f"Checkout event created: first={first_keyword}, second={second_keyword}, "
            f"channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in _process_add_checkout_event: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при создании checkout события.")


async def _process_add_notext_event(message: Message, session: AsyncSession):
    """Обработка создания notext события"""
    try:
        parts = message.text.split()

        if len(parts) < 2:
            await message.answer("❌ Недостаточно параметров. Проверьте формат.")
            return

        start_str = parts[0]
        end_str = parts[1]

        start_parts = parse_time_string(start_str)
        if not start_parts:
            await message.answer("❌ Неправильный формат начального времени!")
            return
        deadline_start = time(*start_parts)

        end_parts = parse_time_string(end_str)
        if not end_parts:
            await message.answer("❌ Неправильный формат конечного времени!")
            return
        deadline_end = time(*end_parts)

        if deadline_start >= deadline_end:
            await message.answer("⚠️ Время начала должно быть раньше времени конца!")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        await NoTextEventCRUD.create(
            session, channel.id, deadline_start, deadline_end
        )

        await message.answer(
            f"✅ Событие без текста создано!\n\n"
            f"⏰ Отслеживание: с <b>{deadline_start.strftime('%H:%M')}</b> "
            f"до <b>{deadline_end.strftime('%H:%M')}</b>\n"
            f"📊 Статистика: <b>{deadline_end.strftime('%H:%M')}</b>"
        )

        logger.info(
            f"NoText event created: start={deadline_start}, end={deadline_end}, "
            f"channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in _process_add_notext_event: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при создании события.")


async def _process_add_keyword_event(message: Message, session: AsyncSession):
    """Обработка создания keyword события"""
    try:
        parts = shlex.split(message.text)

        if len(parts) < 3:
            await message.answer("❌ Недостаточно параметров. Проверьте формат.")
            return

        start_str = parts[0]
        end_str = parts[1]
        keyword = parts[2]
        photo_description = parts[3] if len(parts) >= 4 else None

        validation = validate_keyword_length(keyword)
        if not validation["valid"]:
            await message.answer(validation["error_message"])
            return

        start_parts = parse_time_string(start_str)
        if not start_parts:
            await message.answer("❌ Неправильный формат начального времени!")
            return
        deadline_start = time(*start_parts)

        end_parts = parse_time_string(end_str)
        if not end_parts:
            await message.answer("❌ Неправильный формат конечного времени!")
            return
        deadline_end = time(*end_parts)

        if deadline_start >= deadline_end:
            await message.answer("⚠️ Время начала должно быть раньше времени конца!")
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        await KeywordEventCRUD.create(
            session,
            channel.id,
            deadline_start,
            deadline_end,
            keyword,
            reference_photo_file_id=None,
            reference_photo_description=photo_description
        )

        response = (
            f"✅ Событие с ключевым словом создано!\n\n"
            f"🔑 Ключевое слово: <b>{html.quote(keyword)}</b>\n"
            f"⏰ Отслеживание: с <b>{deadline_start.strftime('%H:%M')}</b> "
            f"до <b>{deadline_end.strftime('%H:%M')}</b>\n"
            f"📊 Статистика: <b>{deadline_end.strftime('%H:%M')}</b>"
        )

        if photo_description:
            response += f"\n\n💡 <i>Можно прикрепить эталонное фото позже</i>"

        await message.answer(response)

        logger.info(
            f"Keyword event created: keyword={keyword}, start={deadline_start}, "
            f"end={deadline_end}, channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in _process_add_keyword_event: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при создании события.")


# ==================== ОБРАБОТЧИКИ КАНАЛОВ ====================

@router.message(Command("add_channel"))
async def cmd_add_channel_interactive(message: Message, state: FSMContext):
    """Интерактивное создание канала"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("Команда недоступна в ЛС.")
        return

    prompt = get_command_input_prompt("add_channel")
    await state.set_state(AddChannelStates.waiting_for_title)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(AddChannelStates.waiting_for_title, F.text)
async def process_add_channel_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для add_channel"""
    if message.text.startswith("/"):
        await state.clear()
        return

    title = message.text.strip()

    if not title or len(title.split()) > 1:
        await message.answer(
            "❌ Название должно быть одним словом без пробелов.",
            reply_markup=get_cancel_keyboard()
        )
        return

    thread_id = message.message_thread_id if message.is_topic_message else None

    # Проверка на дубликат
    existing = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )
    if existing:
        await message.answer(
            f"❌ В этом чате уже зарегистрирован канал '{existing.title}'."
        )
        await state.clear()
        return

    # Создание канала
    await ChannelCRUD.create(session, message.chat.id, thread_id, title)

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        f"✅ Вы успешно создали канал <b>'{title}'</b>!\n\n"
        "<b>Дальнейшие шаги:</b>\n"
        "1) Добавьте события: <code>/add_event</code>\n"
        "2) Добавьте пользователей: <code>/add_users</code>\n"
        "3) Настройте статистику (опционально): <code>/set_wstat</code>"
    )

    logger.info(
        f"Channel created: title={title}, chat_id={message.chat.id}, "
        f"thread_id={thread_id}, by_user={message.from_user.id}"
    )

    await state.clear()


@router.message(Command("rm_channel"))
async def cmd_rm_channel_interactive(message: Message, state: FSMContext):
    """Интерактивное удаление канала"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("rm_channel")
    await state.set_state(RemoveChannelStates.waiting_for_title)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(RemoveChannelStates.waiting_for_title, F.text)
async def process_rm_channel_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для rm_channel"""
    if message.text.startswith("/"):
        await state.clear()
        return

    target_title = message.text.strip()
    thread_id = message.message_thread_id if message.is_topic_message else None

    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("В этом чате/ветке нет активных каналов.")
        await state.clear()
        return

    if channel.title.strip().lower() != target_title.lower():
        await message.answer(
            f"❌ Название '<code>{target_title}</code>' не совпадает.\n"
            f"Текущий канал: '<code>{channel.title}</code>'\n"
            f"<i>(Скопируйте название целиком)</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    success = await ChannelCRUD.delete_channel(session, channel.id)

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

    if success:
        await message.answer(f"✅ Канал <b>'{channel.title}'</b> успешно удален.")
        logger.info(
            f"Channel deleted: id={channel.id}, title={channel.title}, "
            f"by_user={message.from_user.id}"
        )

    await state.clear()


# ==================== ОБРАБОТЧИКИ НАСТРОЕК ====================

@router.message(Command("set_wstat"))
async def cmd_set_wstat_interactive(message: Message, state: FSMContext):
    """Интерактивная настройка статистики"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    prompt = get_command_input_prompt("set_wstat")
    await state.set_state(SetWstatStates.waiting_for_params)

    sent_message = await message.answer(prompt, reply_markup=get_cancel_keyboard())
    await state.update_data(prompt_message_id=sent_message.message_id)


@router.message(SetWstatStates.waiting_for_params, F.text)
async def process_set_wstat_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Обработка ввода для set_wstat"""
    if message.text.startswith("/"):
        await state.clear()
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        await message.answer(
            "❌ Недостаточно параметров. Укажите ID чата, ID треда и Заголовок.",
            reply_markup=get_cancel_keyboard()
        )
        return

    try:
        target_chat_id = int(parts[0])
        target_thread_id = int(parts[1])
        if target_thread_id == 0:
            target_thread_id = None
        custom_title = parts[2]
    except ValueError:
        await message.answer(
            "❌ ID чата и треда должны быть числами.",
            reply_markup=get_cancel_keyboard()
        )
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
        await state.clear()
        return

    await ChannelCRUD.update_stats_destination(
        session, channel.id, target_chat_id, target_thread_id, custom_title
    )

    thread_info = f" (ветка {target_thread_id})" if target_thread_id else ""

    await delete_prompt_message(message, state)
    try:
        await message.delete()
    except Exception:
        pass

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

    await state.clear()


# ==================== ОБРАБОТЧИК ОТМЕНЫ ====================

@router.callback_query(F.data == "cancel")
async def process_cancel_callback(
    callback: CallbackQuery,
    state: FSMContext
):
    """Обработка кнопки отмены через callback"""
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("✅ Операция отменена.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущей операции через команду"""
    current_state = await state.get_state()
    if current_state is None:
        return

    await state.clear()
    await message.answer("✅ Операция отменена.")