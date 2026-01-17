import logging
from datetime import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.orm import sessionmaker

from bot.config import settings
from bot.database.crud import UserCRUD, ChannelCRUD, UserChannelCRUD, PhotoTemplateCRUD
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in settings.admin_list

@router.message(Command("get_user_id"))
async def cmd_get_user_id(message: Message):
    """Узнать telegram user ID"""
    await message.answer(
        f"🆔 Telegram user ID: <code>{message.from_user.id}</code>\n"
        f"Name: {message.from_user.full_name}\n"
        f"Username: @{message.from_user.username or 'username не указан'}"
    )

@router.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message):
    """Узнать chat_id текущего чата"""
    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах или ваш чат является приватным")
        return

    await message.answer(
        f"💬 Информация о чате:\n"
        f"Chat ID: <code>{message.chat.id}</code>\n"
        f"Название: {message.chat.title or 'Без названия'}\n"
        f"Тип: {message.chat.type}"
    )

@router.message(Command("get_thread_id"))
async def cmd_get_thread_id(message: Message):
    """Узнать thread_id текущего треда (топика)"""
    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах или ваш чат является приватным")
        return

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

@router.message(Command("add_user"))
async def cmd_add_user(message: Message, session: AsyncSession):
    """
    Добавить пользователя в систему мониторинга конкретного треда (не всех сразу)
    Использование: /add_user @username или reply на сообщение
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах или ваш чат является приватным")
        return

    # Получаем thread_id
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Проверяем, зарегистрирован ли канал/тред
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer(
            "❌ Сначала зарегистрируйте этот канал/тред командой /add_ch"
        )
        return

    # Определяем целевого пользователя
    if not message.reply_to_message:
        await message.answer(
            "📝 Использование:\n" "Ответьте на сообщение пользователя командой /add_user"
        )
        return

    target_user = message.reply_to_message.from_user

    # Получаем или создаем пользователя
    user = await UserCRUD.get_or_create(
        session,
        telegram_id=target_user.id,
        username=target_user.username or "",
        full_name=target_user.full_name,
    )

    # Проверяем, не добавлен ли уже пользователь в этот канал/тред
    is_already_added = await UserChannelCRUD.in_user_in_channel(
        session, user.id, channel.id
    )

    if is_already_added:
        await message.answer(
            f"⚠️ Пользователь уже зарегистрирован в этом {'треде' if thread_id else 'канале'}!\n\n"
            f"ID: {user.telegram_id}\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username or 'username не указан'}"
        )
        return

    success, _ = await UserChannelCRUD.add_user_to_channel(
        session, user.id, channel.id
    )

    if success:
        await message.answer(
            f"✅ Пользователь добавлен в систему мониторинга:\n"
            f"ID: {user.telegram_id}\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username or 'username не указан'}\n"
            f"{'Thread ID: ' + str(thread_id) if thread_id else 'Основной чат'}"
        )

        logger.info(
            f"User {user.telegram_id} added to channel {channel.id} "
            f"(chat={channel.telegram_id}, thread={channel.thread_id}) "
            f"by admin {message.from_user.id}"
        )
    else:
        await message.answer("❌ Ошибка при добавлении пользователя")


@router.message(Command("add_ch"))
async def cmd_add_channel(message: Message, session: AsyncSession):
    """
    Зарегистрировать канал/топик для мониторинга
    Использование: /add_ch отчет1 09:00 ключевое_слово 2

    Параметры:
    - report_type: тип отчета (например, "отчет1", "отчет2")
    - deadline: время дедлайна в формате HH:MM
    - keyword: ключевое слово для поиска
    - min_photos: минимальное количество фото (по умолчанию 2)
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    # Проверяем, что команда отправлена в группе/канале
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эту команду нужно использовать в группе/канале")
        return

    # Парсим параметры
    try:
        parts = message.text.split()[1:]  # Убираем /add_ch

        if len(parts) < 3:
            await message.answer(
                "📝 Использование:\n"
                "/add_ch <тип_отчета> <HH:MM> <ключевое_слово> [мин_фото]\n\n"
                "Пример:\n"
                "/add_ch [отчет1] [09:00] [monkey business] [2]"
            )
            return

        report_type = parts[0]
        deadline_str = parts[1]
        keyword = parts[2]
        min_photos = int(parts[3]) if len(parts) > 3 else settings.MIN_PHOTOS

        # Парсим время
        hour, minute = map(int, deadline_str.split(":"))
        deadline_time = time(hour=hour, minute=minute)

        # Получаем thread_id (для топиков)
        thread_id = message.message_thread_id if message.is_topic_message else None

        # Определяем название (для топиков берем из chat, для обычных групп - title)
        if message.is_topic_message:
            # Для топиков можно попробовать получить название топика
            title = f"{message.chat.title} - Topic{thread_id}"
        else:
            title = message.chat.title or "Unknown"

        # Проверяем, не зарегистрирован ли уже канал/топик
        existing_channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )

        if existing_channel:
            await message.answer(
                "⚠️ Этот канал/топик уже зарегистрирован!\n"
                f"Chat ID: {message.chat.id}\n"
                f"Thread ID: {thread_id or 'основной чат'}"
            )
            return

        # Создаем канал
        channel = await ChannelCRUD.create(
            session,
            telegram_id=message.chat.id,
            thread_id=thread_id,
            title=title,
            report_type=report_type,
            keyword=keyword,
            deadline_time=deadline_time,
            min_photos=min_photos,
        )

        await message.answer(
            f"✅ Канал/топик зарегистрирован!\n\n"
            f"📋 Параметры:\n"
            f"• Chat ID: {message.chat.id}\n"
            f"• Thread ID: {thread_id or 'основной чат'}\n"
            f"• Тип отчета: {channel.report_type}\n"
            f"• Ключевое слово: {channel.keyword}\n"
            f"• Дедлайн: {channel.deadline_time.strftime('%H:%M')}\n"
            f"• Минимум фото: {channel.min_photos}\n\n"
            f"Теперь бот будет отслеживать отчеты в этом {'топике' if thread_id else 'канале'}!"
            f"💡 Не забудьте:\n"
            f"1. Добавить пользователей для мониторинга: /add_user (или reply message)\n"
            f"2. Настроить тред/канал для статистики: /set_stats_destination\n"
            f"3. (Опционально) Добавить шаблон отчета (в виде фото): /add_template"
        )

        logger.info(
            f"Channel registered: {channel.title} (chat_id={channel.telegram_id}, "
            f"thread_id={channel.thread_id}) by admin {message.from_user.id}"
        )

    except ValueError as e:
        await message.answer(
            f"❌ Ошибка в формате данных!\n\n"
            f"Убедитесь, что:\n"
            f"• Время указано в формате HH:MM\n"
            f"• Количество фото - число\n\n"
            f"Пример: /add_ch [название отчета(треда/топика)] [время(09:20)] [ключевое слово для отчета] [количество фото (по умолчанию - 2)]"
        )
        logger.error(f"Error parsing add_ch command: {e}")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка!")
        logger.error(f"Error in add_ch command: {e}", exc_info=True)

@router.message(Command("set_stats_destination"))
async def set_stats_destination(message: Message, session: AsyncSession):
    """
    Настроить, куда отправлять еженедельную статистику
    Использование: вызвать команду в нужном канале/треде
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах или ваш чат является приватным")
        return

    # Получаем thread_id текущего треда
    stats_thread_id = message.message_thread_id if message.is_topic_message else None

    # Получаем канал/тред, куда нужно отправлять статистику
    # Предположительно, админ вызовет команду в том же чате, где зарегистрирован канал
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "📝 Использование:\n"
            "/set_stat_destination <chat_id> [thread_id]\n\n"
            "Или просто вызовите команду в нужном треде:\n"
            "/set_stats_destination"
        )
        return

    # Если админ указал параметры вручную
    try:
        target_chat_id = int(parts[1]) if len(parts) > 1 else message.chat.id
        target_thread_id = (
            int(parts[2]) if len(parts) > 2 else stats_thread_id
        )
    except ValueError:
        await message.answer("❌ Неверный формат ID")
        return

    # Обновляем все каналы в текущем чате
    channels = await ChannelCRUD.get_all_active(session)

    updated = 0
    for channel in channels:
        if channel.telegram_id == message.chat.id:
            await ChannelCRUD.update_stats_destination(
                session, channel.id, target_chat_id, target_thread_id
            )
            updated += 1

    if updated > 0:
        await message.answer(
            f"✅ Статистика будет отправляться в:\n"
            f"Chat ID: <code>{target_chat_id}</code>\n"
            f"Thread ID: <code>{target_thread_id or 'основной чат'}</code>\n\n"
            f"Обновлено каналов: {updated}"
        )
    else:
        await message.answer("❌ Не найдено зарегистрированных каналов в этом чате")

@router.message(Command("add_template"))
async def cmd_add_template(message: Message, session: AsyncSession):
    """
    Добавить шаблон отчета (фото) для проверки
    Использование: /add_template (с прикрепленным фото) [описание шаблона]
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах/каналах или ваш чат является приватным")
        return

    if not message.photo:
        await message.answer(
            "❌ Прикрепите фото к команде!\n\n"
            "Использование:\n"
            "/add_template [описание шаблона]"
        )
        return

    # Получаем thread_id
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Получаем канал
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer(
            "❌ Сначала зарегистрируйте этот канал/тред командой /add_ch"
        )
        return

    # Получаем описание (если указали)
    parts = message.caption.split(maxsplit=1) if message.caption else []
    description = parts[1] if len(parts) > 1 else None

    # Получаем фото
    photo = message.photo[-1] # берем максимальное качество
    file_id = photo.file_id

    # Скачиваем фото
    from aiogram import Bot

    bot = message.bot
    file = await bot.get_file(file_id)
    photo_data = await bot.download_file(file.file_path)
    photo_bytes = photo.data_read()

    # Сохраняем шаблон
    try:
        template = await PhotoTemplateCRUD.add_template(
            session, channel.id, file_id, photo_bytes, description
        )

        await message.answer(
            f"✅ Шаблон фотографии для текущего отчета добавлен!\n\n"
            f"Описание: {template.description or 'Описание не указано'}\n"
            f"Теперь все отчеты будут проверяться на соответствие данного шаблона"
        )

        logger.info(
            f"Photo template added for channel {channel.id} and thread {thread_id} "
            f"Photo ID {template.id} and Photo hash <code>{template.photo_hash}</code> "
            f"by admin {message.from_user.id}"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении шаблона!")
        logger.error(f"Error adding photo template: {e}", exc_info=True)

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
        stats_info = (
            f" Статистика → Chat: {ch.stats_chat_id}, Thread: {ch.stats_thread_id}"
            if ch.stats_chat_id
            else "Публикация статистики в отдельный тред не настроена"
        )

        # Получаем количество шаблонов
        templates = await PhotoTemplateCRUD.get_templates_for_channel(session, ch.id)
        template_count = len(templates)

        text += (
            f"• {ch.title}\n"
            f"  Chat ID: {ch.telegram_id}\n"
            f"  {thread_info}\n"
            f"  Тип: {ch.report_type}\n"
            f"  Ключевое слово: {ch.keyword}\n"
            f"  Дедлайн: {ch.deadline_time.strftime('%H:%M')} (+5 минут на случай 'не успел/забыл')\n"
            f"  Минимум фото: {ch.min_photos}\n\n"
            f"  Шаблонов: {template_count}\n"
            f"  {stats_info}\n\n"
        )

    await message.answer(text)
