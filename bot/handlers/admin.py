import logging
import io
from datetime import time
from typing import Dict

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.crud import UserCRUD, ChannelCRUD, UserChannelCRUD, PhotoTemplateCRUD

router = Router()
logger = logging.getLogger(__name__)

# FSM States для добавления шаблона
class PhotoTemplateStates(StatesGroup):
    waiting_for_photos = State()
    waiting_for_description = State()

# Временное хранилище для данных шаблона
template_data: Dict[int, dict] = {}

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in settings.admin_list

def is_super_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь суперадмином"""
    return user_id in settings.super_admin_list

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Показать доступные команды"""
    user_id = message.from_user.id
    
    help_text = "📚 <b>Доступные команды:</b>\n\n"
    
    # Команды для всех
    help_text += "👥 <b>Для всех пользователей:</b>\n"
    help_text += "• /get_user_id - Узнать свой Telegram ID\n"
    help_text += "• /get_chat_id - Узнать Chat ID (1 раз в день)\n"
    help_text += "• /get_thread_id - Узнать Thread ID (1 раз в день)\n\n"
    
    if is_admin(user_id):
        help_text += "👨‍💼 <b>Для администраторов:</b>\n"
        help_text += "• /add_ch - Зарегистрировать канал/тред\n"
        help_text += "• /add_event - Добавить событие отчета\n"
        help_text += "• /edit_event - Редактировать событие\n"
        help_text += "• /rm_event - Удалить событие\n"
        help_text += "• /add_user - Добавить пользователя\n"
        help_text += "• /add_users - Добавить несколько пользователей\n"
        help_text += "• /rm_user - Удалить пользователя\n"
        help_text += "• /rm_users - Удалить несколько пользователей\n"
        help_text += "• /rm_ch - Удалить канал из отслеживания\n"
        help_text += "• /add_template - Добавить шаблон фото\n"
        help_text += "• /set_stats_destination - Настроить место статистики\n"
        help_text += "• /edit_wstat - Редактировать еженедельную статистику\n"
        help_text += "• /list_channels - Показать список каналов\n"
        help_text += "• /stats - Статистика напоминаний\n\n"
    
    if is_super_admin(user_id):
        help_text += "⭐ <b>Для суперадминистраторов:</b>\n"
        help_text += "• /add_admin - Добавить администратора\n"
        help_text += "• /rm_admin - Удалить администратора\n"
        help_text += "• /list_admins - Список администраторов\n\n"
    
    await message.answer(help_text)

@router.message(Command("get_user_id"))
async def cmd_get_user_id(message: Message):
    """Узнать telegram user ID"""
    await message.answer(
        f"🆔 Telegram user ID: <code>{message.from_user.id}</code>\n"
        f"Name: {message.from_user.full_name}\n"
        f"Username: @{message.from_user.username or 'username не указан'}"
    )

@router.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message, session: AsyncSession):
    """Узнать chat_id текущего чата (ограничение: 1 раз в день)"""
    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах")
        return

    # TODO: Добавить проверку rate limit (1 раз в день)
    
    await message.answer(
        f"💬 Информация о чате:\n"
        f"Chat ID: <code>{message.chat.id}</code>\n"
        f"Название: {message.chat.title or 'Без названия'}\n"
        f"Тип: {message.chat.type}"
    )

@router.message(Command("get_thread_id"))
async def cmd_get_thread_id(message: Message):
    """Узнать thread_id текущего треда (ограничение: 1 раз в день)"""
    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах")
        return

    # TODO: Добавить проверку rate limit (1 раз в день)
    
    thread_id = message.message_thread_id if message.is_topic_message else None

    if thread_id:
        await message.answer(
            f"🧵 Информация о треде:\n"
            f"Thread ID: <code>{thread_id}</code>\n"
            f"Chat ID: <code>{message.chat.id}</code>"
        )
    else:
        await message.answer(
            f"📝 Это основной чат (не тред/топик)\n"
            f"Chat ID: <code>{message.chat.id}</code>"
        )

@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message, session: AsyncSession):
    """Добавить администратора (только для суперадминов)"""
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if not message.reply_to_message:
        await message.answer(
            "📝 Использование:\n"
            "Ответьте на сообщение пользователя командой /add_admin"
        )
        return

    target_user = message.reply_to_message.from_user
    
    # Добавляем в список админов (через CRUD или config)
    success = await settings.add_admin(target_user.id)
    
    if success:
        await message.answer(
            f"✅ Пользователь назначен администратором:\n"
            f"ID: {target_user.id}\n"
            f"Name: {target_user.full_name}\n"
            f"Username: @{target_user.username or 'не указан'}"
        )
        logger.info(f"Admin added: {target_user.id} by {message.from_user.id}")
    else:
        await message.answer("❌ Пользователь уже является администратором")

@router.message(Command("add_user"))
async def cmd_add_user(message: Message, session: AsyncSession):
    """Добавить пользователя в систему мониторинга"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None

    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer(
            "❌ Сначала зарегистрируйте этот канал/тред командой /add_ch"
        )
        return

    if not message.reply_to_message:
        await message.answer(
            "📝 Использование:\n"
            "Ответьте на сообщение пользователя командой /add_user"
        )
        return

    target_user = message.reply_to_message.from_user

    user = await UserCRUD.get_or_create(
        session,
        telegram_id=target_user.id,
        username=target_user.username or "",
        full_name=target_user.full_name,
    )

    is_already_added = await UserChannelCRUD.in_user_in_channel(
        session, user.id, channel.id
    )

    if is_already_added:
        await message.answer(
            f"⚠️ Пользователь уже зарегистрирован в этом {'треде' if thread_id else 'канале'}!"
        )
        return

    success, _ = await UserChannelCRUD.add_user_to_channel(
        session, user.id, channel.id
    )

    if success:
        await message.answer(
            f"✅ Пользователь добавлен:\n"
            f"ID: {user.telegram_id}\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username or 'не указан'}"
        )
        logger.info(f"User {user.telegram_id} added to channel {channel.id}")

@router.message(Command("add_users"))
async def cmd_add_users(message: Message, session: AsyncSession):
    """Добавить нескольких пользователей через разделитель ;"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("❌ Сначала зарегистрируйте канал командой /add_ch")
        return

    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "📝 Использование:\n"
                "/add_users @user1;@user2;@user3\n"
                "или\n"
                "/add_users 123456;789012;345678"
            )
            return

        usernames = parts[1].split(';')
        added = 0
        errors = []

        for username in usernames:
            username = username.strip().replace('@', '')
            # TODO: Реализовать поиск пользователя по username или ID
            # Это требует дополнительной логики
            
        await message.answer(
            f"✅ Добавлено пользователей: {added}\n"
            f"❌ Ошибок: {len(errors)}"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении пользователей")
        logger.error(f"Error in add_users: {e}", exc_info=True)

@router.message(Command("add_ch"))
async def cmd_add_channel(message: Message, session: AsyncSession):
    """Зарегистрировать канал/топик для мониторинга"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эту команду нужно использовать в группе/канале")
        return

    try:
        parts = message.text.split()[1:]
        if len(parts) < 1:
            await message.answer(
                "📝 Использование:\n"
                "/add_ch <название_треда>\n\n"
                "После этого используйте /add_event для добавления событий"
            )
            return

        thread_id = message.message_thread_id if message.is_topic_message else None
        title = ' '.join(parts)

        existing_channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )

        if existing_channel:
            await message.answer("⚠️ Этот канал/топик уже зарегистрирован!")
            return

        # Создаем канал без events (events добавляются отдельно)
        channel = await ChannelCRUD.create(
            session,
            telegram_id=message.chat.id,
            thread_id=thread_id,
            title=title,
            report_type="",  # Будет задано через /add_event
            keyword="",
            deadline_time=time(0, 0),
            min_photos=settings.MIN_PHOTOS,
        )

        await message.answer(
            f"✅ Канал/тред зарегистрирован: {title}\n\n"
            f"💡 Следующие шаги:\n"
            f"1. Добавьте событие: /add_event\n"
            f"2. Добавьте пользователей: /add_user\n"
            f"3. Настройте статистику: /set_stats_destination"
        )

        logger.info(f"Channel registered: {title} by {message.from_user.id}")

    except Exception as e:
        await message.answer("❌ Произошла ошибка!")
        logger.error(f"Error in add_ch: {e}", exc_info=True)

@router.message(Command("add_template"))
async def cmd_add_template(message: Message, state: FSMContext):
    """Добавить шаблон фото (шаг 1: запрос фотографий)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    
    # Сохраняем контекст
    template_data[message.from_user.id] = {
        'chat_id': message.chat.id,
        'thread_id': thread_id,
        'photos': []
    }
    
    await state.set_state(PhotoTemplateStates.waiting_for_photos)
    await message.answer(
        "📸 Отправьте одно или несколько фото для шаблона.\n"
        "После отправки всех фото напишите /done"
    )

@router.message(PhotoTemplateStates.waiting_for_photos, F.photo)
async def receive_template_photos(message: Message, state: FSMContext):
    """Получение фотографий для шаблона"""
    user_data = template_data.get(message.from_user.id)
    if not user_data:
        await message.answer("❌ Ошибка: данные не найдены. Начните заново с /add_template")
        await state.clear()
        return
    
    photo = message.photo[-1]
    user_data['photos'].append(photo.file_id)
    
    await message.answer(f"✅ Фото добавлено ({len(user_data['photos'])}). Отправьте еще или /done")

@router.message(PhotoTemplateStates.waiting_for_photos, Command("done"))
async def template_photos_done(message: Message, state: FSMContext):
    """Завершение добавления фото, переход к описанию"""
    user_data = template_data.get(message.from_user.id)
    if not user_data or not user_data['photos']:
        await message.answer("❌ Вы не отправили ни одного фото!")
        return
    
    await state.set_state(PhotoTemplateStates.waiting_for_description)
    await message.answer(
        f"📝 Получено фотографий: {len(user_data['photos'])}\n\n"
        "Теперь отправьте описание шаблона (или /skip для пропуска)"
    )

@router.message(PhotoTemplateStates.waiting_for_description)
async def receive_template_description(message: Message, state: FSMContext, session: AsyncSession):
    """Получение описания и сохранение шаблона"""
    user_data = template_data.get(message.from_user.id)
    if not user_data:
        await message.answer("❌ Ошибка: данные не найдены")
        await state.clear()
        return
    
    description = None if message.text == "/skip" else message.text
    
    # Получаем канал
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, user_data['chat_id'], user_data['thread_id']
    )
    
    if not channel:
        await message.answer("❌ Канал не найден. Зарегистрируйте его через /add_ch")
        await state.clear()
        del template_data[message.from_user.id]
        return
    
    # Сохраняем все фото как шаблоны
    try:
        for file_id in user_data['photos']:
            file = await message.bot.get_file(file_id)
            photo_io = await message.bot.download_file(file.file_path)
            photo_bytes = photo_io.read()
            
            await PhotoTemplateCRUD.add_template(
                session, channel.id, file_id, photo_bytes, description
            )
        
        await message.answer(
            f"✅ Шаблон добавлен!\n"
            f"Фотографий: {len(user_data['photos'])}\n"
            f"Описание: {description or 'не указано'}"
        )
        
        logger.info(f"Template added for channel {channel.id} by {message.from_user.id}")
        
    except Exception as e:
        await message.answer("❌ Ошибка при сохранении шаблона")
        logger.error(f"Error saving template: {e}", exc_info=True)
    
    finally:
        await state.clear()
        del template_data[message.from_user.id]

@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, session: AsyncSession):
    """Показать список зарегистрированных каналов"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    channels = await ChannelCRUD.get_all_active(session)

    if not channels:
        await message.answer("📭 Нет зарегистрированных каналов")
        return

    text = "📋 Зарегистрированные каналы/топики:\n\n"

    for ch in channels:
        thread_info = f"Thread: {ch.thread_id}" if ch.thread_id else "Основной чат"
        
        text += (
            f"• {ch.title}\n"
            f"  Chat ID: {ch.telegram_id}\n"
            f"  {thread_info}\n\n"
        )

    await message.answer(text)