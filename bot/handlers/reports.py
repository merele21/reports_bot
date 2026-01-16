import logging

from aiogram import Router, F
from aiogram.types import Message
from bot.database.crud import UserCRUD, ChannelCRUD, ReportCRUD
from bot.utils.validators import ReportValidator
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()
logger = logging.getLogger(__name__)

# Словарь для сбора медиагрупп
media_groups = {}


@router.message(F.chat.type.in_(["group", "supergroup"]), F.photo)
async def handle_photo_message(message: Message, session: AsyncSession):
    """Обработка сообщений с фотографиями в группах/каналах"""

    # Получаем thread_id
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Получаем канал из БД по chat_id и thread_id
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel or not channel.is_active:
        # Канал/топик не зарегистрирован или неактивен
        logger.debug(
            f"Message ignored: chat_id={message.chat.id}, "
            f"thread_id]{thread_id} - not registered or inactive"
        )
        return

    # Получаем или создаем пользователя
    user = await UserCRUD.get_or_create(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
    )

    # Проверяем, не сдан ли уже отчет сегодня
    existing_report = await ReportCRUD.get_today_report(session, user.id, channel.id)
    if existing_report:
        logger.debug(
            f"Report already submitted today: user={user.telegram_id}, "
            f"channel={channel.id}"
        )
        return  # Отчет уже сдан

    # Обработка медиагруппы
    if message.media_group_id:
        # Добавляем в словарь медиагрупп
        if message.media_group_id not in media_groups:
            media_groups[message.media_group_id] = {
                "photos": [],
                "text": message.caption or "",
                "user": user,
                "channel": channel,
                "message_id": message.message_id,
                "chat_id": message.chat.id,
                "thread_id": thread_id,
            }

        media_groups[message.media_group_id]["photos"].append(message.photo[-1].file_id)

        # Ждем все фото из группы
        from asyncio import sleep

        await sleep(1)  # Даем время на получение всех фото

        # Проверяем, все ли фото получены
        if message.media_group_id in media_groups:
            group_data = media_groups[message.media_group_id]
            photos_count = len(group_data["photos"])

            # Валидация
            if photos_count >= channel.min_photos:
                # Проверяем ключевое слово
                is_valid, error = ReportValidator.validate_keyword(
                    message, channel.keyword
                )

                if is_valid:
                    # Сохраняем отчет
                    await ReportCRUD.create(
                        session,
                        user_id=user.id,
                        channel_id=channel.id,
                        message_id=message.message_id,
                        photos_count=photos_count,
                        message_text=group_data["text"],
                        is_valid=True,
                    )

                    await message.reply(
                        f"✅ Отчет принят!\n"
                        f"Фотографий: {photos_count}\n"
                        f"Тип: {channel.report_type}"
                    )

                    logger.info(
                        f"Report accepted: user={user.telegram_id}, "
                        f"channel={channel.title}, (chat={channel.telegram_id}, "
                        f"thread={channel.thread_id}), photos={photos_count}"
                    )
                else:
                    await message.reply(f"❌ {error}")
            else:
                await message.reply(
                    f"❌ Недостаточно фотографий!\n"
                    f"Требуется: {channel.min_photos}, получено: {photos_count}"
                )

            # Удаляем из словаря
            del media_groups[message.media_group_id]

    else:
        # Одиночное фото
        photos_count = 1

        # Валидация
        is_valid, errors = ReportValidator.validate_report(message, channel)

        if photos_count >= channel.min_photos and is_valid:
            # Сохраняем отчет
            await ReportCRUD.create(
                session,
                user_id=user.id,
                channel_id=channel.id,
                message_id=message.message_id,
                photos_count=photos_count,
                message_text=message.caption or "",
                is_valid=True,
            )

            await message.reply(f"✅ Отчет принят!\n" f"Тип: {channel.report_type}")

            logger.info(
                f"Report accepted: user={user.telegram_id}, "
                f"channel={channel.title} (chat={channel.telegram_id}, "
                f"thread={channel.thread_id})"
            )
        elif errors:
            await message.reply(
                "❌ Ошибки в отчете:\n" + "\n".join(f"• {err}" for err in errors)
            )
