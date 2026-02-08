"""
Хендлеры управления специальными событиями
Часть 2: Checkout, NoText, Keyword события
"""
import logging
import shlex
from datetime import time
from typing import Optional

from aiogram import Router, html, F
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message, PhotoSize
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import ChannelCRUD, CheckoutEventCRUD
from bot.handlers.admin.utils import (
    is_admin,
    parse_time_string,
    validate_keyword_length
)

router = Router()
logger = logging.getLogger(__name__)

class KeywordEventStates(StatesGroup):
    """States for keyword event creation with photo"""
    waiting_for_photo = State()

@router.message(Command("add_event_checkout"))
async def cmd_add_event_checkout(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Двухэтапное событие: пересчет (утро) -> готово (вечер)

    Формат: /add_event_checkout "Первый ключ" ЧЧ:ММ "Второй ключ" ЧЧ:ММ [мин_фото] [время_статистики]

    Примеры:
    - /add_event_checkout "Категории" 10:00 "Готово" 16:00 1
    - /add_event_checkout "Категории" 10:00 "Готово" 16:00 1 23:00
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event_checkout \"Первый ключ\" ЧЧ:ММ \"Второй ключ\" "
            "ЧЧ:ММ [мин_фото] [время_статистики]</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/add_event_checkout \"Категории\" 10:00 \"Готово\" 16:00 1</code>\n"
            "<b>или</b>\n"
            "<code>/add_event_checkout \"Категории\" 10:00 \"Готово\" 16:00 1 23:00</code>\n\n"
            "<b>Как это работает:</b>\n"
            "1️⃣ Утром люди пишут: <code>Категории: скоропорт + тихое</code>\n"
            "2️⃣ Вечером отправляют фото с: <code>Готово: скоропорт</code>\n"
            "3️⃣ Бот отслеживает, что сдано, а что нет\n"
            "4️⃣ Статистика публикуется в указанное время "
            "(по умолчанию 22:00 MSK)\n\n"
            "📋 Допустимые категории:\n"
            "элитка, сигареты, тихое, водка, пиво, игристое, коктейли,\n"
            "скоропорт, сопутка, вода, энергетики, бакалея, мороженое,\n"
            "шоколад, нонфуд, штучки"
        )
        return

    try:
        parts = shlex.split(command.args)

        if len(parts) < 4:
            await message.answer(
                "Недостаточно аргументов. Нужно: 2 ключевых слова + 2 времени."
            )
            return

        first_keyword = parts[0]
        first_time_str = parts[1]
        second_keyword = parts[2]
        second_time_str = parts[3]
        min_photos = int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else 1

        # Парсим время статистики (опциональный параметр)
        stats_time = None
        if len(parts) >= 6 and ':' in parts[5]:
            stats_time_parts = parse_time_string(parts[5])
            if not stats_time_parts:
                await message.answer(
                    "❌ Ошибка формата времени статистики! Используйте ЧЧ:ММ."
                )
                return
            stats_time = time(*stats_time_parts)

        # Валидация ключевых слов
        for keyword in [first_keyword, second_keyword]:
            validation = validate_keyword_length(keyword)
            if not validation["valid"]:
                await message.answer(validation["error_message"])
                return

        # Парсинг времени дедлайнов
        first_time_parts = parse_time_string(first_time_str)
        if not first_time_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return
        first_deadline = time(*first_time_parts)

        second_time_parts = parse_time_string(second_time_str)
        if not second_time_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return
        second_deadline = time(*second_time_parts)

        if first_deadline >= second_deadline:
            await message.answer("⚠️ Первый дедлайн должен быть раньше второго!")
            return

        # Получаем канал
        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        await CheckoutEventCRUD.create(
            session, channel.id,
            first_keyword, first_deadline,
            second_keyword, second_deadline,
            min_photos,
            stats_time
        )

        stats_time_str = stats_time.strftime('%H:%M') if stats_time else "22:00"
        await message.answer(
            f"✅ Двухэтапное событие создано!\n\n"
            f"1️⃣ <b>{html.quote(first_keyword)}</b> до "
            f"{first_deadline.strftime('%H:%M')}\n"
            f"2️⃣ <b>{html.quote(second_keyword)}</b> до "
            f"{second_deadline.strftime('%H:%M')}\n"
            f"📸 Минимум фото: {min_photos}\n"
            f"📊 Статистика публикуется в: <b>{stats_time_str} MSK</b>\n\n"
            f"<i>Люди должны будут указывать категории из списка:\n"
            f"элитка, сигареты, тихое, водка, пиво, игристое, коктейли,\n"
            f"скоропорт, сопутка, вода, энергетики, бакалея, мороженое,\n"
            f"шоколад, нонфуд, штучки</i>"
        )

        logger.info(
            f"Checkout event created: first={first_keyword}, second={second_keyword}, "
            f"channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in add_event_checkout: {e}", exc_info=True)
        await message.answer("Произошла ошибка при сохранении checkout события.")


@router.message(Command("add_event_notext"))
async def cmd_add_event_notext(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Событие без текста - отслеживание только фото по расписанию

    Формат: /add_event_notext ЧЧ:ММ ЧЧ:ММ
    Пример: /add_event_notext 09:00 18:00
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event_notext [начало] [конец]</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/add_event_notext 09:00 18:00</code>\n\n"
            "Бот будет отслеживать отправку фото (желательно) от "
            "зарегистрированных пользователей "
            "в указанный промежуток времени. "
            "Статистика публикуется строго в время [конец].\n\n"
            "Для выходного дня пользователь пишет: <code>выходной</code>"
        )
        return

    try:
        parts = command.args.split()
        if len(parts) < 2:
            await message.answer("Недостаточно аргументов. Укажите время начала и конца.")
            return

        start_str = parts[0]
        end_str = parts[1]

        # Парсинг времени
        start_parts = parse_time_string(start_str)
        if not start_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return
        deadline_start = time(*start_parts)

        end_parts = parse_time_string(end_str)
        if not end_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return
        deadline_end = time(*end_parts)

        if deadline_start >= deadline_end:
            await message.answer("⚠️ Время начала должно быть раньше времени конца!")
            return

        # Получаем канал
        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        from bot.database.crud import NoTextEventCRUD
        await NoTextEventCRUD.create(
            session, channel.id, deadline_start, deadline_end
        )

        await message.answer(
            f"✅ Событие без текста создано!\n\n"
            f"⏰ Отслеживание: с <b>{deadline_start.strftime('%H:%M')}</b> "
            f"до <b>{deadline_end.strftime('%H:%M')}</b>\n"
            f"📊 Статистика будет опубликована в "
            f"<b>{deadline_end.strftime('%H:%M')}</b>\n\n"
            f"📝 Для выходного дня пользователь пишет: <code>выходной</code>"
        )

        logger.info(
            f"NoText event created: start={deadline_start}, end={deadline_end}, "
            f"channel_id={channel.id}, by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in add_event_notext: {e}", exc_info=True)
        await message.answer("Произошла ошибка при создании события.")


@router.message(Command("add_event_kw"))
async def cmd_add_event_kw(
        message: Message,
        command: CommandObject,
        session: AsyncSession,
        state: FSMContext
):
    """
    Событие с ключевым словом (например, "открыт")

    Формат: /add_event_kw ЧЧ:ММ ЧЧ:ММ "ключевое слово" [описание фото]

    Способы использования:
    1. Команда в тексте: /add_event_kw 09:00 18:00 "открыт"
    2. Команда в подписи к фото: отправьте фото с подписью /add_event_kw 09:00 18:00 "открыт"
    3. Команда + ожидание фото: /add_event_kw 09:00 18:00 "открыт" "Пример правильно открытого магазина"
       → бот попросит отправить фото
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат команды:</b>\n"
            "<code>/add_event_kw [начало] [конец] \"ключевое слово\" [описание фото]</code>\n\n"
            "<b>Примеры:</b>\n"
            "1️⃣ Без фото:\n"
            "<code>/add_event_kw 09:00 18:00 \"открыт\"</code>\n\n"
            "2️⃣ С фото (отправьте фото с этой командой в подписи):\n"
            "📸 + <code>/add_event_kw 09:00 18:00 \"открыт\"</code>\n\n"
            "3️⃣ С фото (бот попросит отправить):\n"
            "<code>/add_event_kw 09:00 18:00 \"открыт\" \"Пример правильно открытого магазина\"</code>\n\n"
            "Ключевое слово может быть в любом месте сообщения и поддерживает вариации:\n"
            "открыт, открыта, открыто, открытие "
            "(до 5 символов после базового слова)"
        )
        return

    try:
        parts = shlex.split(command.args)
        if len(parts) < 3:
            await message.answer("Недостаточно аргументов. Проверьте формат команды.")
            return

        start_str = parts[0]
        end_str = parts[1]
        keyword = parts[2]
        photo_description = parts[3] if len(parts) >= 4 else None

        # Валидация
        validation = validate_keyword_length(keyword)
        if not validation["valid"]:
            await message.answer(validation["error_message"])
            return

        # Парсинг времени
        start_parts = parse_time_string(start_str)
        if not start_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return
        deadline_start = time(*start_parts)

        end_parts = parse_time_string(end_str)
        if not end_parts:
            await message.answer("❌ Ошибка формата времени! Используйте ЧЧ:ММ.")
            return
        deadline_end = time(*end_parts)

        if deadline_start >= deadline_end:
            await message.answer("⚠️ Время начала должно быть раньше времени конца!")
            return

        # Получаем канал
        thread_id = message.message_thread_id if message.is_topic_message else None
        channel = await ChannelCRUD.get_by_chat_and_thread(
            session, message.chat.id, thread_id
        )
        if not channel:
            await message.answer("Канал не настроен в этой ветке. Сначала /add_channel")
            return

        # Проверяем наличие фото
        photo_file_id: Optional[str] = None

        if message.photo:
            # Фото прикреплено к команде (в подписи)
            photo_file_id = message.photo[-1].file_id  # Берем самое большое фото
            logger.info(f"Photo attached to command: {photo_file_id}")

        elif photo_description:
            # Описание указано - ждем фото
            await state.update_data(
                channel_id=channel.id,
                deadline_start=deadline_start,
                deadline_end=deadline_end,
                keyword=keyword,
                photo_description=photo_description
            )
            await state.set_state(KeywordEventStates.waiting_for_photo)

            await message.answer(
                f"📸 <b>Отправьте эталонное фото</b>\n\n"
                f"Описание: <i>{html.quote(photo_description)}</i>\n\n"
                f"Событие будет создано после получения фото.\n"
                f"Или отправьте /cancel для отмены."
            )
            return

        # Создаем событие
        await KeywordEventCRUD.create(
            session,
            channel.id,
            deadline_start,
            deadline_end,
            keyword,
            reference_photo_file_id=photo_file_id,
            reference_photo_description=photo_description
        )

        # Формируем ответ
        response = (
            f"✅ Событие с ключевым словом создано!\n\n"
            f"🔑 Ключевое слово: <b>{html.quote(keyword)}</b>\n"
            f"⏰ Отслеживание: с <b>{deadline_start.strftime('%H:%M')}</b> "
            f"до <b>{deadline_end.strftime('%H:%M')}</b>\n"
            f"📊 Статистика будет опубликована в "
            f"<b>{deadline_end.strftime('%H:%M')}</b>\n"
        )

        if photo_file_id:
            response += f"\n📸 Эталонное фото прикреплено"
            if photo_description:
                response += f"\n📝 Описание: <i>{html.quote(photo_description)}</i>"

        response += f"\n\n💡 Поддерживаются вариации: {keyword}, {keyword}а, {keyword}о и т.д."

        await message.answer(response)

        logger.info(
            f"Keyword event created: keyword={keyword}, start={deadline_start}, "
            f"end={deadline_end}, channel_id={channel.id}, "
            f"has_photo={photo_file_id is not None}, "
            f"by_user={message.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Error in add_event_kw: {e}", exc_info=True)
        await message.answer("Произошла ошибка при создании события.")


@router.message(KeywordEventStates.waiting_for_photo, F.photo)
async def process_keyword_event_photo(
        message: Message,
        state: FSMContext,
        session: AsyncSession
):
    """Process photo for keyword event creation"""
    data = await state.get_data()

    # Получаем самое большое фото
    photo: PhotoSize = message.photo[-1]
    photo_file_id = photo.file_id

    # Создаем событие с фото
    await KeywordEventCRUD.create(
        session,
        channel_id=data["channel_id"],
        deadline_start=data["deadline_start"],
        deadline_end=data["deadline_end"],
        keyword=data["keyword"],
        reference_photo_file_id=photo_file_id,
        reference_photo_description=data.get("photo_description")
    )

    # Формируем ответ
    response = (
        f"✅ Событие с ключевым словом создано!\n\n"
        f"🔑 Ключевое слово: <b>{html.quote(data['keyword'])}</b>\n"
        f"⏰ Отслеживание: с <b>{data['deadline_start'].strftime('%H:%M')}</b> "
        f"до <b>{data['deadline_end'].strftime('%H:%M')}</b>\n"
        f"📸 Эталонное фото: прикреплено\n"
    )

    if data.get("photo_description"):
        response += f"📝 Описание: <i>{html.quote(data['photo_description'])}</i>\n"

    response += (
        f"\n📊 Статистика будет опубликована в "
        f"<b>{data['deadline_end'].strftime('%H:%M')}</b>\n"
        f"\n💡 Поддерживаются вариации: {data['keyword']}, {data['keyword']}а, "
        f"{data['keyword']}о и т.д."
    )

    await message.answer(response)
    await state.clear()

    logger.info(
        f"Keyword event created with photo: keyword={data['keyword']}, "
        f"photo_id={photo_file_id}"
    )


@router.message(KeywordEventStates.waiting_for_photo, ~F.photo)
async def process_invalid_photo_input(message: Message, state: FSMContext):
    """Handle invalid input when waiting for photo"""
    if message.text and message.text.startswith("/"):
        # Команда - выходим из состояния
        await state.clear()
        return

    await message.answer(
        "⚠️ Пожалуйста, отправьте фото или /cancel для отмены."
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel current FSM operation"""
    current_state = await state.get_state()
    if current_state is None:
        return

    await state.clear()
    await message.answer("✅ Операция отменена.")