import logging
from datetime import time
from typing import Dict

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import settings
from bot.database.crud import UserCRUD, ChannelCRUD, UserChannelCRUD, PhotoTemplateCRUD
from bot.database.models import User

router = Router()
logger = logging.getLogger(__name__)

# --- FSM States ---
class PhotoTemplateStates(StatesGroup):
    waiting_for_photos = State()
    waiting_for_description = State()

class EventStates(StatesGroup):
    waiting_for_event_data = State()

# Временное хранилище
template_data: Dict[int, dict] = {}

# --- Вспомогательные функции ---
def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_list

# --- Обработчики команд ---

@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
    telegram_id = message.from_user.id
    existing_user = await UserCRUD.get_by_telegram_id(session, telegram_id)
    
    user = await UserCRUD.get_or_create(
        session,
        telegram_id=telegram_id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
    )
    
    if message.chat.type == "private":
        if existing_user:
            await message.answer(
                f"ℹ️ <b>Вы уже зарегистрированы, {user.full_name}!</b>\n"
                f"Ваш ID: <code>{user.telegram_id}</code>"
            )
        else:
            await message.answer(
                f"👋 <b>Привет, {user.full_name}!</b>\n\n"
                f"Вы успешно зарегистрированы.\n"
                f"Теперь администратор может добавить вас в группы по тегу @{user.username}."
            )

@router.message(Command("help"))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    help_text = "📚 <b>Команды:</b>\n\n"
    help_text += "• /start - Регистрация/Обновление профиля\n"
    help_text += "• /get_user_id - Узнать ID (свой/reply/username)\n"
    
    if is_admin(user_id):
        help_text += "\n👨‍💼 <b>Администрирование:</b>\n"
        help_text += "• /add_ch - Создать канал/тред\n"
        help_text += "• /add_event - Настроить отчет (дедлайн, ключ)\n"
        help_text += "• /add_user - Добавить участника\n"
        help_text += "• /add_users - Массовое добавление\n"
        help_text += "• /rm_user - Удалить участника\n"
        help_text += "• /rm_users - Массовое удаление\n"
        help_text += "• /add_template - Добавить шаблон фото\n"
        help_text += "• /list_channels - Список каналов\n"

    await message.answer(help_text)

# --- Управление пользователями ---

@router.message(Command("add_user"))
async def cmd_add_user(message: Message, command: CommandObject, session: AsyncSession):
    """Добавление пользователя: Аргументы -> Reply"""
    if not is_admin(message.from_user.id): return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("❌ Канал не настроен. Сначала используйте /add_ch")
        return

    target_user = None
    args = command.args

    # 1. ПРИОРИТЕТ: АРГУМЕНТЫ
    if args:
        val = args.replace("@", "").strip()
        if not val:
            await message.answer("⚠️ Некорректный запрос. Введите ID или @username.")
            return

        if val.isdigit():
            target_user = await UserCRUD.get_by_telegram_id(session, int(val))
        else:
            res = await session.execute(select(User).where(User.username.ilike(val)))
            target_user = res.scalar_one_or_none()
            
        if not target_user:
             await message.answer(f"❌ Пользователь '{val}' не найден в базе. Пусть нажмет /start.")
             return

    # 2. ПРИОРИТЕТ: REPLY (с проверкой на фантомный ответ темы)
    elif message.reply_to_message:
        # Проверяем, не является ли это "ответом на старт топика"
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
            # Если это фантомный реплай и нет аргументов -> Ошибка
            await message.answer("⚠️ Некорректный запрос. Введите ID или @username.")
            return
    
    # 3. НЕТ ДАННЫХ
    else:
        await message.answer("⚠️ Некорректный запрос. Введите ID или @username.")
        return

    if not target_user or not target_user.telegram_id:
        # На всякий случай, если что-то пошло не так
        await message.answer("❌ Ошибка: Не удалось определить пользователя.")
        return

    in_channel = await UserChannelCRUD.in_user_in_channel(session, target_user.id, channel.id)
    if in_channel:
        await message.answer(f"⚠️ {target_user.full_name} (ID: {target_user.telegram_id}) уже в канале.")
    else:
        await UserChannelCRUD.add_user_to_channel(session, target_user.id, channel.id)
        await message.answer(f"✅ Пользователь добавлен: {target_user.full_name}")

@router.message(Command("add_users"))
async def cmd_add_users(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id): return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel:
        await message.answer("❌ Нет канала.")
        return

    if not command.args:
        await message.answer("📝 Формат: `/add_users @user1; @user2`")
        return

    raw_entries = command.args.split(";")
    entries = [e.replace("@", "").strip() for e in raw_entries if e.strip()]
    
    added = 0
    not_found = []

    for entry in entries:
        u = None
        if entry.isdigit():
            u = await UserCRUD.get_by_telegram_id(session, int(entry))
        else:
            res = await session.execute(select(User).where(User.username.ilike(entry)))
            u = res.scalar_one_or_none()
        
        if u:
            if not await UserChannelCRUD.in_user_in_channel(session, u.id, channel.id):
                await UserChannelCRUD.add_user_to_channel(session, u.id, channel.id)
                added += 1
        else:
            not_found.append(entry)

    msg = f"✅ Добавлено: {added}"
    if not_found: msg += f"\n❌ Не найдены (нужен /start): {', '.join(not_found)}"
    await message.answer(msg)

@router.message(Command("rm_user"))
async def cmd_rm_user(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id): return
    
    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel: 
        await message.answer("❌ Канал не найден.")
        return

    target_user = None
    args = command.args

    # 1. АРГУМЕНТЫ
    if args:
        val = args.replace("@", "").strip()
        if not val:
            await message.answer("⚠️ Некорректный запрос. Введите ID или @username.")
            return

        if val.isdigit():
            target_user = await UserCRUD.get_by_telegram_id(session, int(val))
        else:
            res = await session.execute(select(User).where(User.username.ilike(val)))
            target_user = res.scalar_one_or_none()
            
    # 2. REPLY
    elif message.reply_to_message:
        # Проверяем на фантомный реплай
        is_phantom_reply = False
        if message.is_topic_message and message.message_thread_id:
            if message.reply_to_message.message_id == message.message_thread_id:
                is_phantom_reply = True
        
        if not is_phantom_reply:
            target_user = await UserCRUD.get_by_telegram_id(session, message.reply_to_message.from_user.id)
        else:
            await message.answer("⚠️ Некорректный запрос. Введите ID или @username.")
            return
    
    else:
        await message.answer("⚠️ Некорректный запрос. Введите ID или @username.")
        return

    if target_user:
        removed = await UserChannelCRUD.remove_user_from_channel(session, target_user.id, channel.id)
        if removed:
            await message.answer(f"✅ Удален: {target_user.full_name}")
        else:
            await message.answer(f"⚠️ Пользователь {target_user.full_name} не был в этом канале.")
    else:
        await message.answer("❌ Пользователь не найден в базе.")

@router.message(Command("rm_users"))
async def cmd_rm_users(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id): return
    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    
    if not command.args: return
    
    raw_entries = command.args.split(";")
    entries = [e.replace("@", "").strip() for e in raw_entries if e.strip()]

    count = 0
    for entry in entries:
        u = None
        if entry.isdigit():
            u = await UserCRUD.get_by_telegram_id(session, int(entry))
        else:
            res = await session.execute(select(User).where(User.username.ilike(entry)))
            u = res.scalar_one_or_none()
        
        if u and await UserChannelCRUD.remove_user_from_channel(session, u.id, channel.id):
            count += 1
    await message.answer(f"✅ Удалено: {count}")

# --- Управление Каналами и Событиями ---

@router.message(Command("add_ch"))
async def cmd_add_channel(message: Message, command: CommandObject, session: AsyncSession):
    if not is_admin(message.from_user.id): return
    if message.chat.type == "private": return

    title = command.args if command.args else message.chat.title

    thread_id = message.message_thread_id if message.is_topic_message else None
    
    existing = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if existing:
        await message.answer("⚠️ Канал уже есть.")
        return

    await ChannelCRUD.create(
        session,
        telegram_id=message.chat.id,
        thread_id=thread_id,
        title=title,
        report_type="Не настроено",
        keyword="",
        deadline_time=time(0,0),
        min_photos=settings.MIN_PHOTOS
    )
    await message.answer(f"✅ Канал '{title}' создан!\nТеперь используйте /add_event для настройки.")

@router.message(Command("add_event"))
async def cmd_add_event(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(EventStates.waiting_for_event_data)
    await message.answer(
        "📝 Введите настройки события:\n"
        "<code>Тип;КлючевоеСлово;Время(ЧЧ:ММ);МинФото</code>"
    )

@router.message(EventStates.waiting_for_event_data)
async def process_add_event(message: Message, state: FSMContext, session: AsyncSession):
    try:
        parts = message.text.split(';')
        if len(parts) < 4: raise ValueError
        
        r_type, keyw, d_time, min_p = parts[0].strip(), parts[1].strip(), parts[2].strip(), int(parts[3])
        h, m = map(int, d_time.split(':'))
        
        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
        
        if channel:
            await ChannelCRUD.update_event(session, channel.id, r_type, keyw, time(h, m), min_p)
            await message.answer(f"✅ Настройки сохранены:\nТип: {r_type}\nКлюч: {keyw}")
        else:
            await message.answer("❌ Канал не найден.")
        
    except Exception:
        await message.answer("❌ Ошибка формата! Пример: Уборка;чисто;21:00;2")
    finally:
        await state.clear()

@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id): return
    channels = await ChannelCRUD.get_all_active(session)
    text = "📋 <b>Каналы:</b>\n"
    for ch in channels:
        text += f"• {ch.title} (Thread: {ch.thread_id or 'Main'})\n"
    await message.answer(text)

@router.message(Command("get_user_id"))
async def cmd_get_user_id(message: Message, command: CommandObject, session: AsyncSession):
    """
    Узнать ID.
    Приоритет:
    1. Аргумент (command.args)
    2. Reply (реальный, а не фантомный ответ темы)
    3. Свой ID
    """
    
    # 1. ПРИОРИТЕТ: АРГУМЕНТЫ
    if command.args:
        val = command.args.replace("@", "").strip()
        
        if not val:
            await message.answer("⚠️ Вы ввели пустой username.")
            return

        u_db = None
        if val.isdigit():
            u_db = await UserCRUD.get_by_telegram_id(session, int(val))
        else:
            res = await session.execute(select(User).where(User.username.ilike(val)))
            u_db = res.scalar_one_or_none()
        
        if u_db:
            await message.answer(
                f"🗃 <b>Пользователь (из базы):</b>\n"
                f"ID: <code>{u_db.telegram_id}</code>\n"
                f"Имя: {u_db.full_name}\n"
                f"Username: @{u_db.username}"
            )
        else:
            await message.answer(f"❌ Пользователь '{val}' не найден в базе данных бота.\nПусть нажмет /start.")
        return

    # 2. ПРИОРИТЕТ: REPLY (с проверкой на фантомный ответ темы)
    reply_valid = False
    
    if message.reply_to_message:
        reply_valid = True
        # Проверяем, не является ли это "ответом на старт топика" (обычное поведение в форумах)
        if message.is_topic_message and message.message_thread_id:
            if message.reply_to_message.message_id == message.message_thread_id:
                reply_valid = False  # Это просто привязка к теме, игнорируем как реплай
    
    if reply_valid:
        u_reply = message.reply_to_message.from_user
        
        # Сохраняем в базу (как в add_user)
        user = await UserCRUD.get_or_create(
            session,
            telegram_id=u_reply.id,
            username=u_reply.username or "",
            full_name=u_reply.full_name
        )
        
        await message.answer(
            f"👤 <b>Пользователь (Reply):</b>\n"
            f"ID: <code>{user.telegram_id}</code>\n"
            f"Имя: {user.full_name}\n"
            f"Username: @{user.username}\n"
            f"<i>(Сохранен в базе)</i>"
        )
        return

    # 3. ПРИОРИТЕТ: СВОЙ ID (Если аргументов нет и реплай был фантомным или отсутствовал)
    u = message.from_user
    await message.answer(
        f"🆔 <b>Ваш профиль:</b>\n"
        f"ID: <code>{u.id}</code>\n"
        f"Имя: {u.full_name}\n"
        f"Username: @{u.username}"
    )


# --- Шаблоны ---

@router.message(Command("add_template"))
async def cmd_add_template(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    
    thread_id = message.message_thread_id if message.is_topic_message else None
    template_data[message.from_user.id] = {
        'chat_id': message.chat.id, 'thread_id': thread_id, 'photos': []
    }
    await state.set_state(PhotoTemplateStates.waiting_for_photos)
    await message.answer("📸 Шлите фото. В конце напишите /done")

@router.message(PhotoTemplateStates.waiting_for_photos, F.photo)
async def receive_template_photos(message: Message):
    data = template_data.get(message.from_user.id)
    if data:
        data['photos'].append(message.photo[-1].file_id)
        await message.answer(f"Фото {len(data['photos'])} принято.")

@router.message(PhotoTemplateStates.waiting_for_photos, Command("done"))
async def template_photos_done(message: Message, state: FSMContext):
    data = template_data.get(message.from_user.id)
    if not data or not data['photos']:
        await message.answer("❌ Нет фото.")
        return
    await state.set_state(PhotoTemplateStates.waiting_for_description)
    await message.answer("📝 Введите описание шаблона (или /skip)")

@router.message(PhotoTemplateStates.waiting_for_description)
async def receive_template_desc(message: Message, state: FSMContext, session: AsyncSession):
    data = template_data.get(message.from_user.id)
    desc = None if message.text == "/skip" else message.text
    
    if data:
        channel = await ChannelCRUD.get_by_chat_and_thread(session, data['chat_id'], data['thread_id'])
        if channel:
            for fid in data['photos']:
                f = await message.bot.get_file(fid)
                b = await message.bot.download_file(f.file_path)
                await PhotoTemplateCRUD.add_template(session, channel.id, fid, b.read(), desc)
            await message.answer("✅ Шаблоны сохранены.")
    
    del template_data[message.from_user.id]
    await state.clear()