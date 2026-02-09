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


def format_store_mention(store_id: str, username: str = None, full_name: str = None) -> str:
    """Format store mention for messages"""
    if username:
        return f"{store_id} (@{username})"
    elif full_name:
        return f"{store_id} ({full_name})"
    return store_id


@router.message(F.chat.type.in_(["group", "supergroup"]), F.text, ~F.photo)
async def handle_checkout_first_phase(message: Message, session: AsyncSession):
    """
    Обработка текстовых сообщений:
    1. Checkout (первый этап)
    2. NoText выходные
    3. Keyword события (текстовые)
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

    # Регистрируем пользователя
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
            # STORE-BASED VALIDATION
            if user.store_id:
                existing = await NoTextDayOffCRUD.get_today_dayoff_by_store(
                    session, user.store_id, notext_event.id
                )
                if existing:
                    dayoff_record, original_user = existing
                    store_mention = format_store_mention(
                        user.store_id,
                        original_user.username,
                        original_user.full_name
                    )
                    await message.reply(
                        f"✅ Выходной для магазина <b>{store_mention}</b> уже отмечен "
                        f"(отметил {original_user.full_name or '@' + original_user.username})."
                    )
                    return
            else:
                # Без store_id - проверяем индивидуально
                existing_dayoff = await NoTextDayOffCRUD.get_today_dayoff(session, user.id, notext_event.id)
                if existing_dayoff:
                    await message.reply("✅ Вы уже отметили выходной на сегодня.")
                    return

            # Сохраняем выходной
            from datetime import date
            today = date.today()
            await NoTextDayOffCRUD.create(session, user.id, notext_event.id, today)

            if user.store_id:
                await message.reply(f"✅ Выходной отмечен для магазина <b>{user.store_id}</b>!")
            else:
                await message.reply("✅ Выходной отмечен!")
            logger.info(f"NoText day off: user={user.telegram_id}, event={notext_event.id}, store={user.store_id}")
            return

    # === ПРОВЕРКА KEYWORD СОБЫТИЙ (ТЕКСТ) ===
    from bot.database.crud import KeywordEventCRUD, KeywordReportCRUD, match_keyword_regex

    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel.id)
    now = datetime.now(pytz.timezone(settings.TZ))
    current_time = now.time()

    for keyword_event in keyword_events:
        # Check if we are in the tracking window
        if keyword_event.deadline_start <= current_time <= keyword_event.deadline_end:
            # Check the TEXT for the keyword
            if match_keyword_regex(text, keyword_event.keyword):

                # STORE-BASED VALIDATION
                if user.store_id:
                    existing = await KeywordReportCRUD.get_today_report_by_store(
                        session, user.store_id, keyword_event.id
                    )
                    if existing:
                        report, original_user = existing
                        store_mention = format_store_mention(
                            user.store_id,
                            original_user.username,
                            original_user.full_name
                        )
                        await message.reply(
                            f"❌ Отчет для магазина <b>{store_mention}</b> уже отправлен "
                            f"(отправил {original_user.full_name or '@' + original_user.username})."
                        )
                        return
                else:
                    # Без store_id - проверяем индивидуально
                    if await KeywordReportCRUD.get_today_report(session, user.id, keyword_event.id):
                        await message.reply("❌ Вы уже отправили отчет по этому событию сегодня.")
                        return

                # Save the report
                await KeywordReportCRUD.create(
                    session,
                    user.id,
                    keyword_event.id,
                    message.message_id,
                    message_text=text,
                    is_on_time=True
                )

                if user.store_id:
                    await message.reply(
                        f"✅ Сообщение с ключевым словом '{keyword_event.keyword}' принято для магазина <b>{user.store_id}</b>!")
                else:
                    await message.reply(f"✅ Сообщение с ключевым словом '{keyword_event.keyword}' принято!")
                logger.info(
                    f"Keyword event report (text): user={user.telegram_id}, event={keyword_event.id}, store={user.store_id}")
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
            continue

        logger.info(f"Found keyword '{checkout_event.first_keyword}' in text")

        # === VALIDATION LOGIC ===
        if user.store_id:
            # 1. Store-based check
            existing_store = await CheckoutSubmissionCRUD.get_today_submission_by_store(
                session, user.store_id, checkout_event.id
            )
            if existing_store:
                submission, original_user = existing_store
                # If someone else from the store started it
                if original_user.id != user.id:
                    mention = format_store_mention(user.store_id, original_user.username, original_user.full_name)
                    await message.reply(
                        f"⛔ <b>Ошибка!</b>\n\n"
                        f"Отчет для магазина <b>{user.store_id}</b> уже начал сдавать {mention}.\n"
                        f"Вам не нужно отправлять отчет повторно."
                    )
                    return
                else:
                    await message.reply(
                        f"❌ Вы уже отправили список категорий для '{checkout_event.first_keyword}' сегодня.")
                    return
        else:
            # 2. Individual check (if no store_id)
            existing = await CheckoutSubmissionCRUD.get_today_submission(
                session, user.id, checkout_event.id
            )
            if existing:
                await message.reply(f"❌ Вы уже отправили отчет по '{checkout_event.first_keyword}' сегодня.")
                return

        # Проверка на повтор
        existing = await CheckoutSubmissionCRUD.get_today_submission(
            session, user.id, checkout_event.id
        )
        if existing:
            await message.reply(f"❌ Вы уже отправили отчет по '{checkout_event.first_keyword}' сегодня.")
            return

        # Парсим ключевые слова после first_keyword
        text_lower = text.lower()
        keyword_lower = checkout_event.first_keyword.lower()
        real_pos = text_lower.find(keyword_lower)

        if real_pos == -1:
            continue

        after_keyword = text[real_pos + len(checkout_event.first_keyword):].strip()

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
            f"отправьте отчеты с указанием:\n"
            f"<code>{checkout_event.second_keyword}: [Категория(-и)]</code>"
        )

        logger.info(
            f"Checkout submission (text only): user={user.telegram_id}, "
            f"event={checkout_event.id}, keywords={keywords}, store={user.store_id}"
        )
        return


@router.message(F.chat.type.in_(["group", "supergroup"]), F.photo)
async def handle_photo_message(message: Message, session: AsyncSession):
    """
    Обработка отчетов:
    1. Обычные события (Event) - STORE-BASED
    2. Временные события (TempEvent) - STORE-BASED
    3. Checkout события (оба этапа)
    4. NoText события - STORE-BASED
    5. Keyword события (с фото) - STORE-BASED
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

    # === ПОЛУЧАЕМ ВСЕ CHECKOUT СОБЫТИЯ ОДИН РАЗ ===
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)

    logger.info(f"Processing photo from user {user.telegram_id}, caption: '{caption}', store: {user.store_id}")

    # === ПРОВЕРКА CHECKOUT СОБЫТИЙ (ПЕРВЫЙ ЭТАП С ФОТО) ===
    for checkout_event in checkout_events:
        if not extract_keywords_from_text(caption, checkout_event.first_keyword):
            continue

        # === NEW VALIDATION LOGIC START ===
        if user.store_id:
            existing_store = await CheckoutSubmissionCRUD.get_today_submission_by_store(
                session, user.store_id, checkout_event.id
            )
            if existing_store:
                submission, original_user = existing_store
                if original_user.id != user.id:
                    mention = format_store_mention(original_user.username, original_user.full_name)
                    await message.reply(
                        f"⛔ <b>Ошибка!</b>\n\n"
                        f"Отчет для магазина <b>{user.store_id}</b> уже начал сдавать {mention}.\n"
                        f"Вам не нужно отправлять отчет повторно."
                    )
                    return
                else:
                    await message.reply(f"❌ Вы уже отправили отчет по '{checkout_event.first_keyword}' сегодня.")
                    return
        else:
            existing = await CheckoutSubmissionCRUD.get_today_submission(
                session, user.id, checkout_event.id
            )
            if existing:
                await message.reply(f"❌ Вы уже отправили отчет по '{checkout_event.first_keyword}' сегодня.")
                return

        # Парсим ключевые слова после first_keyword
        caption_lower = caption.lower()
        keyword_lower = checkout_event.first_keyword.lower()
        real_pos = caption_lower.find(keyword_lower)

        if real_pos == -1: continue

        after_keyword = caption[real_pos + len(checkout_event.first_keyword):].strip()

        for sep in [':', '-', '—', '–']:
            if after_keyword.startswith(sep):
                after_keyword = after_keyword[1:].strip()
                break

        keywords = parse_checkout_keywords(after_keyword)

        if not keywords:
            await message.reply(
                f"⚠️ Не найдены допустимые категории.\n\n"
                f"Используйте слова из списка: элитка, сигареты, тихое, водка, ..."
            )
            return

        await CheckoutSubmissionCRUD.create(
            session, user.id, checkout_event.id, keywords
        )

        keywords_str = ", ".join(keywords)
        await message.reply(
            f"✅ Первый этап принят!\n\n"
            f"📋 Категории: <b>{keywords_str}</b>\n"
            f"⏰ До {checkout_event.second_deadline_time.strftime('%H:%M')} "
            f"отправьте отчеты."
        )
        return

    # === ПРОВЕРКА CHECKOUT СОБЫТИЙ (ВТОРОЙ ЭТАП) ===
    for checkout_event in checkout_events:
        if not extract_keywords_from_text(caption, checkout_event.second_keyword):
            continue

        if user.store_id:
            existing_store_sub = await CheckoutSubmissionCRUD.get_today_submission_by_store(
                session, user.store_id, checkout_event.id
            )
            # If ANYONE from this store started the report
            if existing_store_sub:
                store_submission, original_user = existing_store_sub

                # If the person who started it is NOT the current user
                if original_user.id != user.id:
                    mention = format_store_mention(original_user.username, original_user.full_name)
                    await message.reply(
                        f"⛔ <b>Ошибка!</b>\n\n"
                        f"Отчет для магазина <b>{user.store_id}</b> ведет {mention}.\n"
                        f"Только этот пользователь может сдать вторую часть ('{checkout_event.second_keyword}')."
                    )
                    return

        submission = await CheckoutSubmissionCRUD.get_today_submission(
            session, user.id, checkout_event.id
        )

        if not submission:
            await message.reply(
                f"❌ Сначала нужно отправить отчет с указанием категорий:\n"
                f"<code>{checkout_event.first_keyword}: [Категория(-и)]</code>"
            )
            return

        caption_lower = caption.lower()
        keyword_lower = checkout_event.second_keyword.lower()
        real_pos = caption_lower.find(keyword_lower)

        if real_pos == -1: continue

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

        remaining = await CheckoutReportCRUD.get_remaining_keywords(
            session, user.id, checkout_event.id
        )

        submitted_keywords = set(json.loads(submission.keywords))
        invalid_keywords = [kw for kw in report_keywords if kw not in submitted_keywords]

        if invalid_keywords:
            await message.reply(
                f"⚠️ Вы не заявляли эти категории: {', '.join(invalid_keywords)}\n"
                f"Ваши категории: {', '.join(submitted_keywords)}"
            )
            return

        new_remaining = set(remaining) - set(report_keywords)
        is_complete = len(new_remaining) == 0

        await CheckoutReportCRUD.create(
            session, user.id, checkout_event.id,
            message.message_id, 1, report_keywords, is_complete
        )

        mention = user.store_id if user.store_id else (f"@{user.username}" if user.username else user.full_name)
        if is_complete:
            await message.reply(f"✅ <b>{mention}</b> сдал все отчеты, спасибо! 🎉")
        else:
            await message.reply(
                f"✅ <b>{mention}</b> успешно сдал: <b>{', '.join(report_keywords)}</b>\n\n"
                f"📋 Осталось: <b>{', '.join(new_remaining)}</b>"
            )
        return

    # === ПРОВЕРКА ОБЫЧНЫХ СОБЫТИЙ - STORE-BASED ===
    events = await EventCRUD.get_active_by_channel(session, channel.id)
    for event in events:
        if extract_keywords_from_text(caption, event.keyword):
            # STORE-BASED VALIDATION
            if user.store_id:
                existing = await ReportCRUD.get_today_report_by_store(
                    session, user.store_id, channel.id, event_id=event.id
                )
                if existing:
                    report, original_user = existing
                    store_mention = format_store_mention(
                        user.store_id,
                        original_user.username,
                        original_user.full_name
                    )
                    await message.reply(
                        f"❌ Отчет '{event.keyword}' для магазина <b>{store_mention}</b> уже сдан "
                        f"(сдал {original_user.full_name or '@' + original_user.username})."
                    )
                    return
            else:
                # Без store_id - проверяем индивидуально
                if await ReportCRUD.get_today_report(session, user.id, channel.id, event_id=event.id):
                    await message.reply(f"❌ Вы уже сдали отчет '{event.keyword}' сегодня.")
                    return

            await ReportCRUD.create(
                session, user.id, channel.id, event_id=event.id,
                message_id=message.message_id, photos_count=1,
                message_text=caption, is_valid=True
            )

            if user.store_id:
                await message.reply(f"✅ Отчет '{event.keyword}' принят для магазина <b>{user.store_id}</b>!")
            else:
                await message.reply(f"✅ Отчет '{event.keyword}' принят!")
            logger.info(f"Regular event report: user={user.telegram_id}, event={event.id}, store={user.store_id}")
            return

    # === ПРОВЕРКА ВРЕМЕННЫХ СОБЫТИЙ - STORE-BASED ===
    temp_events = await TempEventCRUD.get_active_by_channel_and_date(session, channel.id, today)
    for temp_event in temp_events:
        if extract_keywords_from_text(caption, temp_event.keyword):
            # STORE-BASED VALIDATION
            if user.store_id:
                existing = await ReportCRUD.get_today_report_by_store(
                    session, user.store_id, channel.id, temp_event_id=temp_event.id
                )
                if existing:
                    report, original_user = existing
                    store_mention = format_store_mention(
                        user.store_id,
                        original_user.username,
                        original_user.full_name
                    )
                    await message.reply(
                        f"❌ Временный отчет '{temp_event.keyword}' для магазина <b>{store_mention}</b> уже сдан "
                        f"(сдал {original_user.full_name or '@' + original_user.username})."
                    )
                    return
            else:
                # Без store_id - проверяем индивидуально
                if await ReportCRUD.get_today_report(session, user.id, channel.id, temp_event_id=temp_event.id):
                    await message.reply(f"❌ Вы уже сдали временный отчет '{temp_event.keyword}'.")
                    return

            await ReportCRUD.create(
                session, user.id, channel.id, temp_event_id=temp_event.id,
                message_id=message.message_id, photos_count=1,
                message_text=caption, is_valid=True
            )

            if user.store_id:
                await message.reply(
                    f"✅ Временный отчет '{temp_event.keyword}' принят для магазина <b>{user.store_id}</b>!")
            else:
                await message.reply(f"✅ Временный отчет '{temp_event.keyword}' принят!")
            logger.info(f"Temp event report: user={user.telegram_id}, event={temp_event.id}, store={user.store_id}")
            return

    # === ПРОВЕРКА KEYWORD СОБЫТИЙ (ФОТО) - STORE-BASED ===
    from bot.database.crud import KeywordEventCRUD, KeywordReportCRUD, match_keyword_regex

    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel.id)
    now = datetime.now(pytz.timezone(settings.TZ))
    current_time = now.time()

    for keyword_event in keyword_events:
        if keyword_event.deadline_start <= current_time <= keyword_event.deadline_end:
            if match_keyword_regex(caption, keyword_event.keyword):

                # STORE-BASED VALIDATION
                if user.store_id:
                    existing = await KeywordReportCRUD.get_today_report_by_store(
                        session, user.store_id, keyword_event.id
                    )
                    if existing:
                        report, original_user = existing
                        store_mention = format_store_mention(
                            user.store_id,
                            original_user.username,
                            original_user.full_name
                        )
                        await message.reply(
                            f"❌ Отчет для магазина <b>{store_mention}</b> уже отправлен "
                            f"(отправил {original_user.full_name or '@' + original_user.username})."
                        )
                        return
                else:
                    # Без store_id - проверяем индивидуально
                    if await KeywordReportCRUD.get_today_report(session, user.id, keyword_event.id):
                        await message.reply("❌ Вы уже отправили отчет по этому событию сегодня.")
                        return

                await KeywordReportCRUD.create(
                    session,
                    user.id,
                    keyword_event.id,
                    message.message_id,
                    message_text=caption,
                    is_on_time=True
                )

                if user.store_id:
                    await message.reply(
                        f"✅ Фото с ключевым словом '{keyword_event.keyword}' принято для магазина <b>{user.store_id}</b>!")
                else:
                    await message.reply(f"✅ Фото с ключевым словом '{keyword_event.keyword}' принято!")
                logger.info(
                    f"Keyword event report (photo): user={user.telegram_id}, event={keyword_event.id}, store={user.store_id}")
                return

    # === ПРОВЕРКА NOTEXT СОБЫТИЙ - STORE-BASED ===
    from bot.database.crud import NoTextEventCRUD, NoTextReportCRUD, NoTextDayOffCRUD

    notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel.id)
    for notext_event in notext_events:
        if notext_event.deadline_start <= current_time <= notext_event.deadline_end:
            # STORE-BASED VALIDATION FOR DAY OFF
            if user.store_id:
                dayoff = await NoTextDayOffCRUD.get_today_dayoff_by_store(
                    session, user.store_id, notext_event.id
                )
                if dayoff:
                    return  # Store has day off, silently ignore

                # STORE-BASED VALIDATION FOR REPORT
                existing = await NoTextReportCRUD.get_today_report_by_store(
                    session, user.store_id, notext_event.id
                )
                if existing:
                    report, original_user = existing
                    store_mention = format_store_mention(
                        user.store_id,
                        original_user.username,
                        original_user.full_name
                    )
                    await message.reply(
                        f"❌ Фото для магазина <b>{store_mention}</b> уже отправлено "
                        f"(отправил {original_user.full_name or '@' + original_user.username})."
                    )
                    return
            else:
                # Без store_id - проверяем индивидуально
                if await NoTextDayOffCRUD.get_today_dayoff(session, user.id, notext_event.id):
                    return

                if await NoTextReportCRUD.get_today_report(session, user.id, notext_event.id):
                    await message.reply("❌ Вы уже отправили фото сегодня.")
                    return

            await NoTextReportCRUD.create(
                session, user.id, notext_event.id, message.message_id, is_on_time=True
            )

            if user.store_id:
                await message.reply(f"✅ Фото принято для магазина <b>{user.store_id}</b>!")
            else:
                await message.reply("✅ Фото принято!")
            logger.info(f"NoText event report: user={user.telegram_id}, event={notext_event.id}, store={user.store_id}")
            return