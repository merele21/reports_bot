import logging
from asyncio import sleep

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import UserCRUD, ChannelCRUD, ReportCRUD, UserChannelCRUD, PhotoTemplateCRUD
from bot.utils.validators import ReportValidator

router = Router()
logger = logging.getLogger(__name__)

# Словарь для сбора медиагрупп
media_groups = {}

@router.message(F.chat.type.in_(["group", "supergroup"]), F.photo)
async def handle_photo_message(message: Message, session: AsyncSession):
    """Обработка сообщений с фотографиями в группах/каналах"""

    thread_id = message.message_thread_id if message.is_topic_message else None

    # 1. Проверяем, зарегистрирован ли канал
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel or not channel.is_active:
        return

    # 2. Регистрируем/получаем автора сообщения
    user = await UserCRUD.get_or_create(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
    )

    # 3. Проверяем, есть ли юзер в списке участников треда
    is_user_registered = await UserChannelCRUD.in_user_in_channel(session, user.id, channel.id)
    if not is_user_registered:
        return

    # 4. Проверяем, не сдан ли уже отчет сегодня
    if await ReportCRUD.get_today_report(session, user.id, channel.id):
        return

    # === ОБРАБОТКА МЕДИАГРУППЫ (НЕСКОЛЬКО ФОТО) ===
    if message.media_group_id:
        if message.media_group_id not in media_groups:
            media_groups[message.media_group_id] = {
                "photos": [],
                "photo_objects": [],
                "text": message.caption or "",
                "user": user,
                "channel": channel,
                "message_id": message.message_id,
                "bot": message.bot,
            }

        media_groups[message.media_group_id]["photos"].append(message.photo[-1].file_id)
        media_groups[message.media_group_id]["photo_objects"].append(message.photo[-1])

        await sleep(1.5)  # Ждем остальные фото

        if message.media_group_id in media_groups:
            group_data = media_groups[message.media_group_id]
            photos_count = len(group_data["photos"])

            # Проверки
            if photos_count < channel.min_photos:
                await message.reply(f"❌ Мало фото! Надо {channel.min_photos}, а тут {photos_count}.")
                del media_groups[message.media_group_id]
                return

            is_valid, error = ReportValidator.validate_keyword(message, channel.keyword)
            if not is_valid:
                await message.reply(f"❌ {error}")
                del media_groups[message.media_group_id]
                return

            # Проверка шаблона
            template_validated = False
            templates = await PhotoTemplateCRUD.get_templates_for_channel(session, channel.id)
            
            if templates:
                try:
                    first_photo = group_data["photo_objects"][0]
                    file = await group_data["bot"].get_file(first_photo.file_id)
                    photo_data = await group_data["bot"].download_file(file.file_path)
                    
                    valid, err = await PhotoTemplateCRUD.validate_photo(session, channel.id, photo_data.read())
                    if not valid:
                        await message.reply(f"❌ {err}")
                        del media_groups[message.media_group_id]
                        return
                    template_validated = True
                except Exception as e:
                    logger.error(f"Template error: {e}")

            # Сохранение
            await ReportCRUD.create(
                session, user.id, channel.id, message.message_id,
                photos_count, group_data["text"], True, template_validated
            )
            
            check_mark = "✅" if template_validated else "⚠️"
            await message.reply(f"✅ Отчет принят! {check_mark}\nВсего фото: {photos_count}")
            del media_groups[message.media_group_id]

    # === ОБРАБОТКА ОДИНОЧНОГО ФОТО ===
    else:
        photos_count = 1

        # 1. Проверка количества
        if photos_count < channel.min_photos:
            await message.reply(f"❌ Мало фото! Надо {channel.min_photos}, а вы прислали 1.")
            return

        # 2. Валидация текста
        is_valid, errors = ReportValidator.validate_report(message, channel)
        if not is_valid:
            await message.reply("❌ Ошибки:\n" + "\n".join(errors))
            return

        # 3. Валидация шаблона
        template_validated = False
        templates = await PhotoTemplateCRUD.get_templates_for_channel(session, channel.id)

        if templates:
            try:
                photo = message.photo[-1]
                file = await message.bot.get_file(photo.file_id)
                photo_data = await message.bot.download_file(file.file_path)
                
                valid, err = await PhotoTemplateCRUD.validate_photo(session, channel.id, photo_data.read())
                if not valid:
                    await message.reply(f"❌ {err}")
                    return
                template_validated = True
            except Exception as e:
                logger.error(f"Template error: {e}")
                await message.reply("⚠️ Ошибка проверки шаблона")
                return

        # 4. СОХРАНЕНИЕ (теперь выполняется всегда при успехе)
        await ReportCRUD.create(
            session, user.id, channel.id, message.message_id,
            photos_count, message.caption or "", True, template_validated
        )

        check_mark = "✅" if template_validated else "⚠️"
        await message.reply(f"✅ Отчет принят! {check_mark}\nТип: {channel.report_type}")