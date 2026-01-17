import logging

from aiogram import Router, F
from aiogram.types import Message
from bot.database.crud import UserCRUD, ChannelCRUD, ReportCRUD, UserChannelCRUD, PhotoTemplateCRUD
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

    # Проверяем, добавлен ли пользователь к этому каналу
    is_user_registered = await UserChannelCRUD.in_user_in_channel(
        session, user.id, channel.id
    )

    if not is_user_registered:
        # Пользователь не зарегистрирован в этом канале/треде
        logger.debug(
            f"User {user.telegram_id} not registered in channel {channel.id}"
        )
        return

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
                "photo_objects": [],
                "text": message.caption or "",
                "user": user,
                "channel": channel,
                "message_id": message.message_id,
                "chat_id": message.chat.id,
                "thread_id": thread_id,
                "bot": message.bot,
            }

        media_groups[message.media_group_id]["photos"].append(message.photo[-1].file_id)
        media_groups[message.media_group_id]["photo_objects"].append(message.photo[-1])

        # Ждем все фото из группы
        from asyncio import sleep

        await sleep(1.5)  # Даем время на получение всех фото

        # Проверяем, все ли фото получены
        if message.media_group_id in media_groups:
            group_data = media_groups[message.media_group_id]
            photos_count = len(group_data["photos"])

            # Валидация
            if photos_count < channel.min_photos:
                await message.reply(
                    f"❌ Недостаточно фотографий в отчете!\n"
                    f"Требуется: {channel.min_photos}, получено: {photos_count}"
                )
                del media_groups[message.media_group_id]
                return

            # Проверяем ключевое слово
            is_valid, error = ReportValidator.validate_keyword(
                message, channel.keyword
            )

            if not is_valid:
                await message.reply(f"❌ {error}")
                del media_groups[message.media_group_id]
                return

            # Проверка шаблонов фото (если они есть)
            template_validated = False
            templates_exist = len(
                await PhotoTemplateCRUD.get_templates_for_channel(session, channel.id)
            ) > 0

            if templates_exist:
                # Проверяем первое фото из группы
                first_photo = group_data["photo_objects"][0]

                try:
                    # Скачиваем фото
                    file = await group_data["bot"].get_file(first_photo.file_id)
                    photo_data = await group_data["bot"].download_file(file.file_path)
                    photo_bytes = photo_data.read()

                    # Валидация по шаблону
                    is_template_valid, template_error = await PhotoTemplateCRUD.validate_photo(
                        session, channel.id, photo_bytes
                    )

                    if not is_template_valid:
                        await message.reply(f"❌ {template_error}")
                        del media_groups[message.media_group_id]
                        return

                    template_validated = True

                except Exception as e:
                    logger.error(f"Error validating photo template: {e}", exc_info=True)
                    await message.reply(
                        "⚠️ Ошибка при проверке фото. Свяжитесь с администратором."
                    )
                    del media_groups[message.media_group_id]
                    return

            # Сохраняем отчет
            await ReportCRUD.create(
                session,
                user_id=user.id,
                channel_id=channel.id,
                message_id=message.message_id,
                photos_count=photos_count,
                message_text=group_data["text"],
                is_valid=True,
                template_validated=template_validated,
            )

            validation_text = "✅" if template_validated else "⚠️ (без проверки шаблона)"

            await message.reply(
                f"✅ Отчет принят! {validation_text}\n"
                f"Фотографий: {photos_count}\n"
                f"Тип: {channel.report_type}"
            )

            logger.info(
                f"Report accepted: user={user.telegram_id}, "
                f"channel={channel.title}, (chat={channel.telegram_id}, "
                f"thread={channel.thread_id}), photos={photos_count}, "
                f"template_validated={template_validated}"
            )

            # Удаляем из словаря
            del media_groups[message.media_group_id]

    else:
        # Одиночное фото
        photos_count = 1

        # Проверяем количество фото
        if photos_count < channel.min_photos:
            await message.reply(
                f"❌ Недостаточно фотографий в отчете!\n"
                f"Требуется: {channel.min_photos}, получено: {photos_count}"
            )

            # Валидация
            is_valid, errors = ReportValidator.validate_report(message, channel)

            if not is_valid:
                await message.reply(
                    "❌ Ошибки в отчете:\n" + "\n".join(f"• {err}" for err in errors)
                )
                return

            # Проверяем шаблон фото (если он есть)
            template_validated = False
            templates_exist = len(
                await PhotoTemplateCRUD.get_templates_for_channel(session, channel.id)
            ) > 0

            if templates_exist:
                photo = message.photo[-1]

                try:
                    # Скачиваем фото
                    file = await message.bot.get_file(photo.file_id)
                    photo_data = await message.bot.download_file(file.file_path)
                    photo_bytes = photo_data.read()

                    # Валидация по шаблону
                    is_template_valid, template_error = await PhotoTemplateCRUD.validate_photo(
                        session, channel.id, photo_bytes
                    )

                    if not is_template_valid:
                        await message.reply(f"❌ {template_error}")
                        return

                    template_validated = True

                except Exception as e:
                    logger.error(f"Error validating photo template: {e}", exc_info=True)
                    await message.reply(
                        "⚠️ Ошибка при проверке фото. Свяжитесь с администратором."
                    )
                    return

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

            validation_text = "✅" if template_validated else "⚠️ (без проверки шаблона)"

            await message.reply(f"✅ Отчет принят!\n" f"Тип: {channel.report_type}")

            logger.info(
                f"Report accepted: user={user.telegram_id}, "
                f"channel={channel.title} (chat={channel.telegram_id}, "
                f"thread={channel.thread_id}), photos={photos_count}, "
                f"template_validated={template_validated}"
            )