import logging
import json
from asyncio import sleep
from datetime import date, datetime
import pytz

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.crud import (
    UserCRUD, ChannelCRUD, ReportCRUD, UserChannelCRUD, EventCRUD,
    TempEventCRUD, CheckoutEventCRUD, CheckoutSubmissionCRUD, CheckoutReportCRUD,
    extract_keywords_from_text, normalize_keyword, parse_checkout_keywords
)

router = Router()
logger = logging.getLogger(__name__)

media_groups = {}


@router.message(F.chat.type.in_(["group", "supergroup"]), F.text, ~F.photo)
async def handle_checkout_first_phase(message: Message, session: AsyncSession):
    """
    Обработка первого этапа checkout событий (утренний пересчет)
    Только для ТЕКСТОВЫХ сообщений БЕЗ фото
    Пример: "Категории: скоропорт + тихое + бакалея"

    Если пересчет с фото - обрабатывается в handle_photo_message
    """
    thread_id = message.message_thread_id if message.is_topic_message else None

    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel or not channel.is_active:
        logger.debug(f"Channel not found or inactive for chat {message.chat.id}, thread {thread_id}")
        return

    # Получаем текст из сообщения
    text = message.text or ""

    # Если нет текста, выходим
    if not text:
        logger.debug("No text in message")
        return

    logger.info(f"Processing text message: '{text}' from user {message.from_user.id}")

    # Регистрируем пользователя с возможным store_id
    existing_user = await UserCRUD.get_by_telegram_id(session, message.from_user.id)
    user = await UserCRUD.get_or_create(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username or None,
        full_name=message.from_user.full_name or None,
        store_id=existing_user.store_id if existing_user else None,
    )

    # Проверяем права
    if not await UserChannelCRUD.in_user_in_channel(session, user.id, channel.id):
        logger.debug(f"User {user.id} not in channel {channel.id}")
        return

    # === ПРОВЕРКА NOTEXT ВЫХОДНЫХ ===
    from bot.database.crud import NoTextEventCRUD, NoTextDayOffCRUD
    
    text_lower = text.lower().strip()
    
    # Проверяем на слово "выходной"
    if "выходной" in text_lower or "выходная" in text_lower:
        notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel.id)
        
        for notext_event in notext_events:
            # Проверяем, не отметил ли пользователь уже выходной
            existing_dayoff = await NoTextDayOffCRUD.get_today_dayoff(session, user.id, notext_event.id)
            if existing_dayoff:
                await message.reply("✅ Вы уже отметили выходной на сегодня.")
                return
            
            # Сохраняем выходной
            from datetime import date
            today = date.today()
            await NoTextDayOffCRUD.create(session, user.id, notext_event.id, today)
            
            await message.reply("✅ Выходной отмечен!")
            logger.info(f"NoText day off: user={user.telegram_id}, event={notext_event.id}")
            return

    # === ПРОВЕРКА KEYWORD СОБЫТИЙ ===
    from bot.database.crud import KeywordEventCRUD, KeywordReportCRUD, match_keyword_regex
    
    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel.id)
    now = datetime.now(pytz.timezone(settings.TZ))
    current_time = now.time()
    
    for keyword_event in keyword_events:
        # Проверяем, находимся ли мы в окне отслеживания
        if keyword_event.deadline_start <= current_time <= keyword_event.deadline_end:
            # Проверяем ключевое слово с regex
            if match_keyword_regex(text, keyword_event.keyword):
                # Проверка на повтор
                if await KeywordReportCRUD.get_today_report(session, user.id, keyword_event.id):
                    await message.reply("❌ Вы уже отправили сообщение с этим ключевым словом сегодня.")
                    return
                
                # Сохраняем отчет
                await KeywordReportCRUD.create(
                    session, user.id, keyword_event.id, message.message_id, text, is_on_time=True
                )
                
                await message.reply(f"✅ Сообщение с ключевым словом '{keyword_event.keyword}' принято!")
                logger.info(f"Keyword event report: user={user.telegram_id}, event={keyword_event.id}")
                return

    # === ПРОВЕРКА CHECKOUT СОБЫТИЙ ===
    # Получаем все checkout события для канала
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)
    if not checkout_events:
        logger.debug(f"No checkout events for channel {channel.id}")
        return

    # Ищем подходящее checkout событие по first_keyword
    for checkout_event in checkout_events:
        logger.info(f"Checking checkout event {checkout_event.id}: first_keyword='{checkout_event.first_keyword}'")

        if not extract_keywords_from_text(text, checkout_event.first_keyword):
            logger.debug(f"Keyword '{checkout_event.first_keyword}' not found in text '{text}'")
            continue

        logger.info(f"Found keyword '{checkout_event.first_keyword}' in text")

        # Проверка на повтор
        existing = await CheckoutSubmissionCRUD.get_today_submission(
            session, user.id, checkout_event.id
        )
        if existing:
            await message.reply(f"❌ Вы уже отправили отчет по '{checkout_event.first_keyword}' сегодня.")
            return

        # Парсим ключевые слова после first_keyword
        # Ищем ключевое слово в нижнем регистре оригинала
        text_lower = text.lower()
        keyword_lower = checkout_event.first_keyword.lower()
        real_pos = text_lower.find(keyword_lower)

        if real_pos == -1:
            # Если не нашли точное совпадение, пропускаем
            continue

        # Берем текст после ключевого слова
        after_keyword = text[real_pos + len(checkout_event.first_keyword):].strip()

        # Убираем разделители в начале
        for sep in [':', '-', '—', '–']:
            if after_keyword.startswith(sep):
                after_keyword = after_keyword[1:].strip()
                break

        # Парсим категории
        keywords = parse_checkout_keywords(after_keyword)

        if not keywords:
            await message.reply(
                f"⚠️ Не найдены допустимые категории.\n\n"
                f"Пожалуйста, используйте слова из списка:\n"
                f"элитка, сигареты, тихое, водка, пиво, игристое, коктейли,\n"
                f"скоропорт, сопутка, вода, энергетики, бакалея, мороженое,\n"
                f"шоколад, нонфуд, штучки"
            )
            return

        # Сохраняем submission
        await CheckoutSubmissionCRUD.create(
            session, user.id, checkout_event.id, keywords
        )

        keywords_str = ", ".join(keywords)
        await message.reply(
            f"✅ Категории приняты!\n\n"
            f"📋 Категории: <b>{keywords_str}</b>\n"
            f"⏰ До {checkout_event.second_deadline_time.strftime('%H:%M')} "
            f"отправьте отчеты с указанием:\n"
            f"<code>{checkout_event.second_keyword}: [Категория(-и)]</code>"
        )

        logger.info(
            f"Checkout submission (text only): user={user.telegram_id}, "
            f"event={checkout_event.id}, keywords={keywords}"
        )
        return


@router.message(F.chat.type.in_(["group", "supergroup"]), F.photo)
async def handle_photo_message(message: Message, session: AsyncSession):
    """
    Обработка отчетов:
    1. Обычные события (Event)
    2. Временные события (TempEvent)
    3. Checkout события (второй этап)
    """
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Проверяем канал
    channel = await ChannelCRUD.get_by_chat_and_thread(session, message.chat.id, thread_id)
    if not channel or not channel.is_active:
        return

    caption = message.caption or ""
    today = date.today()

    # Регистрируем автора с возможным store_id
    existing_user = await UserCRUD.get_by_telegram_id(session, message.from_user.id)
    user = await UserCRUD.get_or_create(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username or None,
        full_name=message.from_user.full_name or None,
        store_id=existing_user.store_id if existing_user else None,
    )

    # Проверка прав
    if not await UserChannelCRUD.in_user_in_channel(session, user.id, channel.id):
        return

    # === ПРОВЕРКА CHECKOUT СОБЫТИЙ (второй этап) ===
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)

    logger.info(f"Processing photo from user {user.telegram_id}, caption: '{caption}'")
    logger.info(f"Found {len(checkout_events)} checkout events for channel {channel.id}")

    for checkout_event in checkout_events:
        logger.info(f"Checking checkout event {checkout_event.id}: second_keyword='{checkout_event.second_keyword}'")
        logger.info(f"Checking checkout event {checkout_event.id}: second_keyword='{checkout_event.second_keyword}'")

        if not extract_keywords_from_text(caption, checkout_event.second_keyword):
            logger.debug(f"Second keyword '{checkout_event.second_keyword}' not found in caption '{caption}'")
            continue

        logger.info(f"Found second keyword '{checkout_event.second_keyword}' in caption")

        # Проверяем, есть ли submission на сегодня
        submission = await CheckoutSubmissionCRUD.get_today_submission(
            session, user.id, checkout_event.id
        )

        if not submission:
            await message.reply(
                f"❌ Сначала нужно отправить отчет с указанием категорий:\n"
                f"<code>{checkout_event.first_keyword}: [Категория(-и)]</code>"
            )
            return

        # Парсим категории из текущего отчета
        # Ищем позицию second_keyword в caption с учетом нормализации
        normalized_second = normalize_keyword(checkout_event.second_keyword)
        normalized_caption = normalize_keyword(caption)

        # Ищем в нормализованном тексте
        pos = normalized_caption.find(normalized_second)
        if pos == -1:
            continue

        # Теперь нужно найти реальную позицию в оригинальном caption
        # Для этого считаем, сколько символов до этой позиции в оригинале
        # Проще всего - искать само ключевое слово напрямую (без учета пробелов внутри)
        caption_lower = caption.lower()

        # Ищем ключевое слово в нижнем регистре оригинала
        # Используем гибкий поиск - ищем начало слова
        keyword_lower = checkout_event.second_keyword.lower()
        real_pos = caption_lower.find(keyword_lower)

        if real_pos == -1:
            # Если не нашли точное совпадение, пропускаем
            continue

        # Берем текст после ключевого слова
        after_keyword = caption[real_pos + len(checkout_event.second_keyword):].strip()

        for sep in [':', '-', '—', '–']:
            if after_keyword.startswith(sep):
                after_keyword = after_keyword[1:].strip()
                break

        report_keywords = parse_checkout_keywords(after_keyword)

        if not report_keywords:
            await message.reply(
                f"⚠️ Укажите категорию(-и) после '{checkout_event.second_keyword}'.\n"
                f"Например: <code>{checkout_event.second_keyword}: скоропорт</code>"
            )
            return

        # Получаем оставшиеся категории
        remaining = await CheckoutReportCRUD.get_remaining_keywords(
            session, user.id, checkout_event.id
        )

        # Проверяем, что отчитываемые категории были в submission
        submitted_keywords = set(json.loads(submission.keywords))
        invalid_keywords = [kw for kw in report_keywords if kw not in submitted_keywords]

        if invalid_keywords:
            await message.reply(
                f"⚠️ Вы не заявляли эти категории в пересчете: {', '.join(invalid_keywords)}\n"
                f"Ваши категории: {', '.join(submitted_keywords)}"
            )
            return

        # Проверка количества фото
        if checkout_event.min_photos > 1:
            # TODO: реализовать проверку медиагруппы
            pass

        # Сохраняем отчет
        new_remaining = set(remaining) - set(report_keywords)
        is_complete = len(new_remaining) == 0

        await CheckoutReportCRUD.create(
            session, user.id, checkout_event.id,
            message.message_id, 1, report_keywords, is_complete
        )

        # Формируем ответ
        if is_complete:
            # Определяем, что показывать - store_id или username
            mention = user.store_id if user.store_id else (f"@{user.username}" if user.username else user.full_name)
            await message.reply(
                f"✅ <b>{mention}</b> сдал все отчеты, спасибо! 🎉"
            )
        else:
            completed_str = ", ".join(report_keywords)
            remaining_str = ", ".join(new_remaining)
            # Определяем, что показывать - store_id или username
            mention = user.store_id if user.store_id else (f"@{user.username}" if user.username else user.full_name)
            await message.reply(
                f"✅ <b>{mention}</b> успешно сдал отчет по: <b>{completed_str}</b>\n\n"
                f"📋 Еще осталось сдать отчет по: <b>{remaining_str}</b>"
            )

        logger.info(
            f"Checkout report: user={user.telegram_id}, event={checkout_event.id}, "
            f"keywords={report_keywords}, complete={is_complete}"
        )
        return

    # === ПРОВЕРКА CHECKOUT СОБЫТИЙ (первый этап с фото) ===
    # Если фото содержит first_keyword, обрабатываем как первый этап
    logger.info("Checking checkout events for first phase (with photo)")
    for checkout_event in checkout_events:
        logger.info(f"Checking first_keyword '{checkout_event.first_keyword}' in caption")

        if not extract_keywords_from_text(caption, checkout_event.first_keyword):
            logger.debug(f"First keyword '{checkout_event.first_keyword}' not found")
            continue

        logger.info(f"Found first keyword '{checkout_event.first_keyword}' with photo")

        # Проверка на повтор
        existing = await CheckoutSubmissionCRUD.get_today_submission(
            session, user.id, checkout_event.id
        )
        if existing:
            await message.reply(f"❌ Вы уже отправили отчет по '{checkout_event.first_keyword}' сегодня.")
            return

        # Парсим ключевые слова после first_keyword
        # Ищем ключевое слово в нижнем регистре оригинала
        caption_lower = caption.lower()
        keyword_lower = checkout_event.first_keyword.lower()
        real_pos = caption_lower.find(keyword_lower)

        if real_pos == -1:
            # Если не нашли точное совпадение, пропускаем
            continue

        # Берем текст после ключевого слова
        after_keyword = caption[real_pos + len(checkout_event.first_keyword):].strip()

        for sep in [':', '-', '—', '–']:
            if after_keyword.startswith(sep):
                after_keyword = after_keyword[1:].strip()
                break

        keywords = parse_checkout_keywords(after_keyword)

        if not keywords:
            await message.reply(
                f"⚠️ Не найдены допустимые категории.\n\n"
                f"Пожалуйста, используйте слова из списка:\n"
                f"элитка, сигареты, тихое, водка, пиво, игристое, коктейли,\n"
                f"скоропорт, сопутка, вода, энергетики, бакалея, мороженое,\n"
                f"шоколад, нонфуд, штучки"
            )
            return

        # Сохраняем submission
        await CheckoutSubmissionCRUD.create(
            session, user.id, checkout_event.id, keywords
        )

        keywords_str = ", ".join(keywords)
        await message.reply(
            f"✅ Категории приняты!\n\n"
            f"📋 Категории: <b>{keywords_str}</b>\n"
            f"⏰ До {checkout_event.second_deadline_time.strftime('%H:%M')} "
            f"отправьте фото с указанием:\n"
            f"<code>{checkout_event.second_keyword}: [Категория(-и)]</code>"
        )

        logger.info(
            f"Checkout submission (with photo): user={user.telegram_id}, "
            f"event={checkout_event.id}, keywords={keywords}"
        )
        return

    # === ПРОВЕРКА ОБЫЧНЫХ СОБЫТИЙ ===
    events = await EventCRUD.get_active_by_channel(session, channel.id)

    for event in events:
        if not extract_keywords_from_text(caption, event.keyword):
            continue

        # Проверка на повтор
        if await ReportCRUD.get_today_report(session, user.id, channel.id, event_id=event.id):
            await message.reply(f"❌ Вы уже сдали отчет '{event.keyword}' сегодня.")
            return

        # Проверка количества фото
        if event.min_photos > 1:
            # TODO: Реализовать проверку медиагруппы (как в оригинале)
            pass

        # Сохраняем отчет
        await ReportCRUD.create(
            session, user.id, channel.id, event_id=event.id,
            message_id=message.message_id, photos_count=1,
            message_text=caption, is_valid=True
        )

        await message.reply(f"✅ Отчет '{event.keyword}' принят!")

        logger.info(f"Event report: user={user.telegram_id}, event={event.id}")
        return

    # === ПРОВЕРКА ВРЕМЕННЫХ СОБЫТИЙ ===
    temp_events = await TempEventCRUD.get_active_by_channel_and_date(session, channel.id, today)

    for temp_event in temp_events:
        if not extract_keywords_from_text(caption, temp_event.keyword):
            continue

        # Проверка на повтор
        if await ReportCRUD.get_today_report(session, user.id, channel.id, temp_event_id=temp_event.id):
            await message.reply(f"❌ Вы уже сдали временный отчет '{temp_event.keyword}' сегодня.")
            return

        # Проверка количества фото
        if temp_event.min_photos > 1:
            pass

        # Сохраняем отчет
        await ReportCRUD.create(
            session, user.id, channel.id, temp_event_id=temp_event.id,
            message_id=message.message_id, photos_count=1,
            message_text=caption, is_valid=True
        )

        await message.reply(f"✅ Временный отчет '{temp_event.keyword}' принят! ⏱")

        logger.info(f"Temp event report: user={user.telegram_id}, temp_event={temp_event.id}")
        return
    
    # === ПРОВЕРКА NOTEXT СОБЫТИЙ ===
    from bot.database.crud import NoTextEventCRUD, NoTextReportCRUD, NoTextDayOffCRUD
    
    notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel.id)
    now = datetime.now(pytz.timezone(settings.TZ))
    current_time = now.time()
    
    for notext_event in notext_events:
        # Проверяем, находимся ли мы в окне отслеживания
        if notext_event.deadline_start <= current_time <= notext_event.deadline_end:
            # Проверяем, не в выходном ли пользователь
            if await NoTextDayOffCRUD.get_today_dayoff(session, user.id, notext_event.id):
                logger.debug(f"User {user.telegram_id} is on day off for notext event {notext_event.id}")
                return
            
            # Проверка на повтор
            if await NoTextReportCRUD.get_today_report(session, user.id, notext_event.id):
                await message.reply("❌ Вы уже отправили фото сегодня.")
                return
            
            # Сохраняем отчет (is_on_time будет определен при публикации статистики)
            await NoTextReportCRUD.create(
                session, user.id, notext_event.id, message.message_id, is_on_time=True
            )
            
            await message.reply("✅ Фото принято!")
            logger.info(f"NoText event report: user={user.telegram_id}, event={notext_event.id}")
            return