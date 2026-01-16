from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import time
from bot.config import settings
from bot.database.crud import UserCRUD, ChannelCRUD
import logging

router = Router()
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in settings.admin_list


@router.message(Command("add_user"))
async def cmd_add_user(message: Message, session: AsyncSession):
    """
    Добавить пользователя в систему мониторинга
    Использование: /add_user @username или reply на сообщение
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    # Определяем целевого пользователя
    target_user = None

    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif message.text and len(message.text.split()) > 1:
        # Попытка извлечь username (упрощенная версия)
        username = message.text.split()[1].replace("@", "")
        await message.answer(
            "⚠️ Для добавления пользователя по username, "
            "используйте reply на его сообщение"
        )
        return
    else:
        await message.answer(
            "📝 Использование:\n"
            "• Ответьте на сообщение пользователя командой /add_user\n"
            "• Или укажите: /add_user @username"
        )
        return

    if target_user:
        # Добавляем пользователя
        user = await UserCRUD.get_or_create(
            session,
            telegram_id=target_user.id,
            username=target_user.username or "",
            full_name=target_user.full_name
        )

        await message.answer(
            f"✅ Пользователь добавлен в систему мониторинга:\n"
            f"ID: {user.telegram_id}\n"
            f"Имя: {user.full_name}\n"
            f"Username: @{user.username or 'не указан'}"
        )

        logger.info(f"User added: {user.telegram_id} by admin {message.from_user.id}")


@router.message(Command("add_ch"))
async def cmd_add_channel(message: Message, session: AsyncSession):
    """
    Зарегистрировать канал для мониторинга
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
                "/add_ch отчет1 09:00 отчет1 2"
            )
            return

        report_type = parts[0]
        deadline_str = parts[1]
        keyword = parts[2]
        min_photos = int(parts[3]) if len(parts) > 3 else settings.MIN_PHOTOS

        # Парсим время
        hour, minute = map(int, deadline_str.split(":"))
        deadline_time = time(hour=hour, minute=minute)

        # Проверяем, не зарегистрирован ли уже канал
        existing_channel = await ChannelCRUD.get_by_telegram_id(session, message.chat.id)

        if existing_channel:
            await message.answer("⚠️ Этот канал уже зарегистрирован!")
            return

        # Создаем канал
        channel = await ChannelCRUD.create(
            session,
            telegram_id=message.chat.id,
            title=message.chat.title or "Unknown",
            report_type=report_type,
            keyword=keyword,
            deadline_time=deadline_time,
            min_photos=min_photos
        )

        await message.answer(
            f"✅ Канал зарегистрирован!\n\n"
            f"📋 Параметры:\n"
            f"• Тип отчета: {channel.report_type}\n"
            f"• Ключевое слово: {channel.keyword}\n"
            f"• Дедлайн: {channel.deadline_time.strftime('%H:%M')}\n"
            f"• Минимум фото: {channel.min_photos}\n\n"
            f"Теперь бот будет отслеживать отчеты в этом канале!"
        )

        logger.info(
            f"Channel registered: {channel.title} ({channel.telegram_id}) "
            f"by admin {message.from_user.id}"
        )

    except ValueError as e:
        await message.answer(
            f"❌ Ошибка в формате данных!\n\n"
            f"Убедитесь, что:\n"
            f"• Время указано в формате HH:MM\n"
            f"• Количество фото - число\n\n"
            f"Пример: /add_ch отчет1 09:00 отчет1 2"
        )
        logger.error(f"Error parsing add_ch command: {e}")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
        logger.error(f"Error in add_ch command: {e}", exc_info=True)


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

    text = "📋 Зарегистрированные каналы:\n\n"

    for ch in channels:
        text += (
            f"• {ch.title}\n"
            f"  Тип: {ch.report_type}\n"
            f"  Ключевое слово: {ch.keyword}\n"
            f"  Дедлайн: {ch.deadline_time.strftime('%H:%M')}\n"
            f"  Минимум фото: {ch.min_photos}\n\n"
        )

    await message.answer(text)