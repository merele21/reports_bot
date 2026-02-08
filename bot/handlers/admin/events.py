"""
Хендлеры управления событиями
Часть 1: Обычные и временные события
"""
import logging
import shlex
from datetime import time, date

from aiogram import Router, html, F
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import ChannelCRUD, EventCRUD, TempEventCRUD
from bot.handlers.admin.utils import (
    is_admin,
    EventDeletionStates,
    parse_time_string,
    validate_keyword_length
)

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("add_event"))
async def cmd_add_event(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Создание обычного события

    Формат: /add_event "Ключевое слово" ЧЧ:ММ [мин_фото]
    Примеры:
    - /add_event "Касса 1 утро" 10:00 1
    - /add_event "Склад/вечер" 18:00 2

    Поддерживает keywords с пробелами в кавычках
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event \"Ключевое слово\" ЧЧ:ММ [мин_фото]</code>\n\n"
            "<b>Примеры:</b>\n"
            "<code>/add_event \"Касса 1 утро\" 10:00 1</code>\n"
            "<code>/add_event \"Склад/вечер\" 18:00 2</code>\n\n"
            "❗️ Ключевое слово с пробелами берите в кавычки!"
        )
        return

    try:
        # Парсим аргументы с поддержкой кавычек
        parts = shlex.split(command.args)

        if len(parts) < 2:
            await message.answer("Недостаточно аргументов. Проверьте формат команды.")
            return

        keyword = parts[0]
        time_str = parts[1]
        min_photos = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1

        # Валидация длины keyword
        validation = validate_keyword_length(keyword)
        if not validation["valid"]:
            await message.answer(validation["error_message"])
            return

        # Парсинг времени
        time_parts = parse_time_string(time_str)
        if not time_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
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
            f"📸 Минимум фото: <b>{min_photos}</b>\n\n"
            f"<i>Дальнейшие шаги:</i>\n"
            f"• Добавьте отслеживаемых пользователей: <code>/add_users</code>\n"
            f"• Проверьте список: <code>/list_users</code>"
        )

        logger.info(
            f"Event created: keyword={keyword}, deadline={deadline}, "
            f"channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except ValueError as e:
        await message.answer(
            f"❌ Ошибка парсинга команды: {str(e)}\n"
            f"Проверьте формат и используйте кавычки для ключевых слов с пробелами."
        )
    except IntegrityError:
        await session.rollback()
        await message.answer("❌ Ошибка: такой ключ уже существует в этом канале.")
    except Exception as e:
        logger.error(f"Error in add_event: {e}", exc_info=True)
        await message.answer("Произошла ошибка при сохранении события.")


@router.message(Command("add_tmp_event"))
async def cmd_add_tmp_event(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Создание временного события (удаляется в 23:59 МСК)

    Формат: /add_tmp_event "Ключевое слово" ЧЧ:ММ [мин_фото]
    Пример: /add_tmp_event "Разовая проверка" 15:00 1
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_tmp_event \"Ключевое слово\" ЧЧ:ММ [мин_фото]</code>\n\n"
            "<b>Примеры:</b>\n"
            "<code>/add_tmp_event \"Разовая проверка\" 15:00 1</code>\n\n"
            "⏱ Событие автоматически удалится в 23:59 МСК"
        )
        return

    try:
        parts = shlex.split(command.args)

        if len(parts) < 2:
            await message.answer("Недостаточно аргументов. Проверьте формат команды.")
            return

        keyword = parts[0]
        time_str = parts[1]
        min_photos = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1

        # Валидация
        validation = validate_keyword_length(keyword)
        if not validation["valid"]:
            await message.answer(validation["error_message"])
            return

        # Парсинг времени
        time_parts = parse_time_string(time_str)
        if not time_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
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

    except IntegrityError:
        await session.rollback()
        await message.answer("❌ Ошибка: такое временное событие уже существует сегодня.")
    except Exception as e:
        logger.error(f"Error in add_tmp_event: {e}", exc_info=True)
        await message.answer("Произошла ошибка при сохранении временного события.")


@router.message(Command("list_events"))
async def cmd_list_events(message: Message, session: AsyncSession):
    """
    Показать список всех событий в текущей ветке
    Включает превью эталонных фото для keyword событий
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
        return

    # Получаем все типы событий
    events = await EventCRUD.get_active_by_channel(session, channel.id)
    today = date.today()
    temp_events = await TempEventCRUD.get_active_by_channel_and_date(
        session, channel.id, today
    )
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)
    notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel.id)
    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel.id)

    if not any([events, temp_events, checkout_events, notext_events, keyword_events]):
        await message.answer(
            f"📋 В канале <b>{html.quote(channel.title)}</b> пока нет событий."
        )
        return

    text = f"<b>📋 События в канале {html.quote(channel.title)}:</b>\n\n"

    # Постоянные события
    if events:
        text += "<b>📌 Постоянные события:</b>\n"
        for i, event in enumerate(events, 1):
            text += f"{i}. <b>{html.quote(event.keyword)}</b>\n"
            text += f"   ⏰ Дедлайн: {event.deadline_time.strftime('%H:%M')}\n"
            text += f"   📸 Мин. фото: {event.min_photos}\n"
            text += "\n"

    # Временные события
    if temp_events:
        text += "<b>⏱ Временные события (удалятся в 23:59):</b>\n"
        for i, temp_event in enumerate(temp_events, 1):
            text += f"{i}. <b>{html.quote(temp_event.keyword)}</b>\n"
            text += f"   ⏰ Дедлайн: {temp_event.deadline_time.strftime('%H:%M')}\n"
            text += f"   📸 Мин. фото: {temp_event.min_photos}\n"
            text += f"   📅 Дата: {temp_event.event_date.strftime('%d.%m.%Y')}\n"
            text += "\n"

    # Checkout события
    if checkout_events:
        text += "<b>🔄 Двухэтапные события (checkout):</b>\n"
        for i, checkout_event in enumerate(checkout_events, 1):
            text += (
                f"{i}. <b>{html.quote(checkout_event.first_keyword)}</b> → "
                f"<b>{html.quote(checkout_event.second_keyword)}</b>\n"
            )
            text += (
                f"   1️⃣ Первый этап: "
                f"{checkout_event.first_deadline_time.strftime('%H:%M')}\n"
            )
            text += (
                f"   2️⃣ Второй этап: "
                f"{checkout_event.second_deadline_time.strftime('%H:%M')}\n"
            )
            text += f"   📸 Мин. фото: {checkout_event.min_photos}\n"
            text += "\n"

    # NoText события
    if notext_events:
        text += "<b>📸 События без текста (notext):</b>\n"
        for i, notext_event in enumerate(notext_events, 1):
            text += (
                f"{i}. Отслеживание фото с "
                f"<b>{notext_event.deadline_start.strftime('%H:%M')}</b> "
                f"до <b>{notext_event.deadline_end.strftime('%H:%M')}</b>\n"
            )
        text += "\n"

    # Keyword события
    if keyword_events:
        text += "<b>🔑 События с ключевым словом (keyword):</b>\n"
        for i, keyword_event in enumerate(keyword_events, 1):
            text += (
                f"{i}. <b>{html.quote(keyword_event.keyword)}</b> с "
                f"<b>{keyword_event.deadline_start.strftime('%H:%M')}</b> "
                f"до <b>{keyword_event.deadline_end.strftime('%H:%M')}</b>\n"
            )
            if keyword_event.reference_photo_file_id:
                text += f"   📸 Эталонное фото: есть"
                if keyword_event.reference_photo_description:
                    text += f" ({html.quote(keyword_event.reference_photo_description)})"
                text += "\n"
            text += "\n"

    text += (
        f"<b>Всего событий:</b> "
        f"{len(events) + len(temp_events) + len(checkout_events) + len(notext_events) + len(keyword_events)}"
    )

    await message.answer(text)

    # Отправляем эталонные фото keyword событий (если есть)
    for keyword_event in keyword_events:
        if keyword_event.reference_photo_file_id:
            caption = (
                f"📸 <b>Эталонное фото для события \"{html.quote(keyword_event.keyword)}\"</b>\n"
                f"⏰ {keyword_event.deadline_start.strftime('%H:%M')} - "
                f"{keyword_event.deadline_end.strftime('%H:%M')}"
            )
            if keyword_event.reference_photo_description:
                caption += f"\n\n📝 {html.quote(keyword_event.reference_photo_description)}"

            try:
                await message.answer_photo(
                    photo=keyword_event.reference_photo_file_id,
                    caption=caption
                )
            except Exception as e:
                logger.error(
                    f"Failed to send reference photo for keyword event "
                    f"{keyword_event.id}: {e}"
                )

@router.message(Command("rm_event"))
async def cmd_rm_event(
        message: Message,
        state: FSMContext,
        session: AsyncSession
):
    """
    Удаление события (с FSM для выбора)
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )

    if not channel:
        await message.answer(
            "В этой ветке нет активного канала. Создайте его через /add_channel"
        )
        return

    # Получаем все события
    events = await EventCRUD.get_active_by_channel(session, channel.id)

    today = date.today()
    temp_events = await TempEventCRUD.get_active_by_channel_and_date(
        session, channel.id, today
    )

    from bot.database.crud import (
        CheckoutEventCRUD,
        NoTextEventCRUD,
        KeywordEventCRUD
    )
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(
        session, channel.id
    )
    notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel.id)
    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel.id)

    if not any([events, temp_events, checkout_events, notext_events, keyword_events]):
        await message.answer("В этой ветке пока нет событий.")
        return

    # Формируем список
    text = "<b>Список событий (пришлите номер для удаления):</b>\n\n"
    idx_map = {}
    counter = 1

    # Добавляем обычные события
    if events:
        text += "<b>📋 Постоянные события:</b>\n"
        for event in events:
            idx_map[str(counter)] = ('event', event.id)
            text += (
                f"{counter}. <b>{event.keyword}</b> — "
                f"{event.deadline_time.strftime('%H:%M')}\n"
            )
            counter += 1
        text += "\n"

    # Добавляем временные события
    if temp_events:
        text += "<b>⏱ Временные события (удалятся в 23:59):</b>\n"
        for temp_event in temp_events:
            idx_map[str(counter)] = ('temp_event', temp_event.id)
            text += (
                f"{counter}. <b>{temp_event.keyword}</b> — "
                f"{temp_event.deadline_time.strftime('%H:%M')}\n"
            )
            counter += 1
        text += "\n"

    # Добавляем checkout события
    if checkout_events:
        text += "<b>🔄 Двухэтапные события (checkout):</b>\n"
        for checkout_event in checkout_events:
            idx_map[str(counter)] = ('checkout_event', checkout_event.id)
            text += (
                f"{counter}. <b>{checkout_event.first_keyword}</b> → "
                f"<b>{checkout_event.second_keyword}</b> "
                f"({checkout_event.first_deadline_time.strftime('%H:%M')} → "
                f"{checkout_event.second_deadline_time.strftime('%H:%M')})\n"
            )
            counter += 1
        text += "\n"

    # Добавляем notext события
    if notext_events:
        text += "<b>📸 События без текста (notext):</b>\n"
        for notext_event in notext_events:
            idx_map[str(counter)] = ('notext_event', notext_event.id)
            text += (
                f"{counter}. Отслеживание фото с "
                f"<b>{notext_event.deadline_start.strftime('%H:%M')}</b> "
                f"до <b>{notext_event.deadline_end.strftime('%H:%M')}</b>\n"
            )
            counter += 1
        text += "\n"

    # Добавляем keyword события
    if keyword_events:
        text += "<b>🔑 События с ключевым словом (keyword):</b>\n"
        for keyword_event in keyword_events:
            idx_map[str(counter)] = ('keyword_event', keyword_event.id)
            text += (
                f"{counter}. <b>{keyword_event.keyword}</b> с "
                f"<b>{keyword_event.deadline_start.strftime('%H:%M')}</b> "
                f"до <b>{keyword_event.deadline_end.strftime('%H:%M')}</b>\n"
            )
            counter += 1

    await state.update_data(deletion_idx_map=idx_map)
    await state.set_state(EventDeletionStates.waiting_for_event_index)
    await message.answer(text)


@router.message(EventDeletionStates.waiting_for_event_index, F.text)
async def process_rm_event_index(
        message: Message,
        state: FSMContext,
        session: AsyncSession
):
    """
    Обработка выбора события для удаления
    """
    val = message.text.strip()

    if val.startswith("/"):
        await state.clear()
        return

    if not val.isdigit():
        await message.answer("Пришлите цифру номера или /cancel.")
        return

    data = await state.get_data()
    user_map = data.get("deletion_idx_map", {})

    if val not in user_map:
        await message.answer("Неверный номер. Попробуйте снова.")
        return

    event_type, event_id = user_map[val]

    from bot.database.crud import NoTextEventCRUD, KeywordEventCRUD

    success = False
    if event_type == 'event':
        success = await EventCRUD.delete(session, event_id)
        event_name = "Событие"
    elif event_type == 'temp_event':
        success = await TempEventCRUD.delete(session, event_id)
        event_name = "Временное событие"
    elif event_type == 'checkout_event':
        from bot.database.crud import CheckoutEventCRUD
        success = await CheckoutEventCRUD.delete(session, event_id)
        event_name = "Двухэтапное событие"
    elif event_type == 'notext_event':
        await NoTextEventCRUD.delete(session, event_id)
        success = True
        event_name = "Событие без текста"
    elif event_type == 'keyword_event':
        await KeywordEventCRUD.delete(session, event_id)
        success = True
        event_name = "Событие с ключевым словом"

    if success:
        await message.answer(f"✅ {event_name} успешно удалено.")
        logger.info(f"Event deleted: type={event_type}, id={event_id}")
    else:
        await message.answer("❌ Ошибка при удалении из базы.")

    await state.clear()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущей операции"""
    await state.clear()
    await message.answer("Операция отменена.")