"""
Хендлер для команды /list_rn с FSM и экспортом в Google Sheets/Excel
"""
import logging
from datetime import date, datetime
from typing import Optional, Dict, List, Tuple

import pytz
from aiogram import Router, html, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.crud import (
    ChannelCRUD, UserChannelCRUD, EventCRUD, TempEventCRUD,
    CheckoutEventCRUD, CheckoutSubmissionCRUD, CheckoutReportCRUD,
    ReportCRUD, NoTextEventCRUD, NoTextReportCRUD, NoTextDayOffCRUD,
    KeywordEventCRUD, KeywordReportCRUD
)
from bot.handlers.admin.utils import is_admin
from utils.user_grouping import group_users_by_store, format_store_mention

router = Router()
logger = logging.getLogger(__name__)


# ==================== FSM STATES ====================

class ListRnStates(StatesGroup):
    """Состояния для команды /list_rn"""
    waiting_for_format_choice = State()


# ==================== KEYBOARDS ====================

def get_format_choice_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора формата вывода статистики"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📱 В текущий канал",
                callback_data="list_rn_format:channel"
            )
        ],
        [
            InlineKeyboardButton(
                text="📊 Google Sheets",
                callback_data="list_rn_format:google_sheets"
            )
        ],
        [
            InlineKeyboardButton(
                text="📄 Excel файл",
                callback_data="list_rn_format:excel"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data="list_rn_format:cancel"
            )
        ]
    ])


# ==================== КОМАНДА ====================

@router.message(Command("list_rn"))
async def cmd_list_rn(message: Message, state: FSMContext, session: AsyncSession):
    """
    Показать текущую статистику по событиям с выбором формата
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

    # Сохраняем channel_id в FSM для последующего использования
    await state.update_data(channel_id=channel.id)
    await state.set_state(ListRnStates.waiting_for_format_choice)

    # Предлагаем выбрать формат
    await message.answer(
        "<b>📊 Выберите формат вывода статистики:</b>\n\n"
        "📱 <b>В текущий канал</b> - вывод сообщением в чат\n"
        "📊 <b>Google Sheets</b> - экспорт в таблицу (с очисткой)\n"
        "📄 <b>Excel файл</b> - скачать .xlsx файл\n\n"
        "<i>💡 Google Sheets позволяет сохранить красиво оформленную таблицу "
        "с автоматической очисткой перед каждым обновлением</i>",
        reply_markup=get_format_choice_keyboard()
    )


# ==================== ОБРАБОТЧИКИ CALLBACK ====================

@router.callback_query(F.data == "list_rn_format:channel")
async def process_format_channel(
        callback: CallbackQuery,
        state: FSMContext,
        session: AsyncSession
):
    """Вывод статистики в текущий канал"""
    await callback.answer()

    data = await state.get_data()
    channel_id = data.get("channel_id")

    # Получаем статистику
    stats_data = await _collect_stats_data(session, channel_id)

    # Формируем текстовое сообщение
    message_text = await _format_stats_as_text(session, channel_id, stats_data)

    # Удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Отправляем статистику
    await callback.message.answer(message_text)
    await state.clear()

    logger.info(f"Stats sent to channel by admin {callback.from_user.id}")


@router.callback_query(F.data == "list_rn_format:google_sheets")
async def process_format_google_sheets(
        callback: CallbackQuery,
        state: FSMContext,
        session: AsyncSession
):
    """Экспорт статистики в Google Sheets"""
    await callback.answer("📊 Экспортирую в Google Sheets...")

    data = await state.get_data()
    channel_id = data.get("channel_id")

    # Получаем статистику
    stats_data = await _collect_stats_data(session, channel_id)

    try:
        # Экспортируем в Google Sheets
        sheet_url = await _export_to_google_sheets(session, channel_id, stats_data)

        # Удаляем сообщение с кнопками
        try:
            await callback.message.delete()
        except Exception:
            pass

        # Отправляем ссылку
        await callback.message.answer(
            f"✅ <b>Статистика успешно экспортирована!</b>\n\n"
            f"📊 <a href='{sheet_url}'>Открыть Google Sheets</a>\n\n"
            f"<i>💡 Таблица была полностью очищена перед экспортом.\n"
            f"Данные актуальны на {datetime.now(pytz.timezone(settings.TZ)).strftime('%H:%M')}</i>",
            disable_web_page_preview=True
        )

        logger.info(f"Stats exported to Google Sheets by admin {callback.from_user.id}")

    except Exception as e:
        logger.error(f"Error exporting to Google Sheets: {e}", exc_info=True)
        await callback.message.answer(
            f"❌ <b>Ошибка при экспорте в Google Sheets:</b>\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"<i>Проверьте настройки Google Sheets API в .env</i>"
        )

    await state.clear()


@router.callback_query(F.data == "list_rn_format:excel")
async def process_format_excel(
        callback: CallbackQuery,
        state: FSMContext,
        session: AsyncSession
):
    """Экспорт статистики в Excel файл"""
    await callback.answer("📄 Создаю Excel файл...")

    data = await state.get_data()
    channel_id = data.get("channel_id")

    # Получаем статистику
    stats_data = await _collect_stats_data(session, channel_id)

    try:
        # Создаем Excel файл
        excel_path = await _create_excel_file(session, channel_id, stats_data)

        # Удаляем сообщение с кнопками
        try:
            await callback.message.delete()
        except Exception:
            pass

        # Отправляем файл
        from aiogram.types import FSInputFile

        await callback.message.answer_document(
            document=FSInputFile(excel_path),
            caption=(
                f"✅ <b>Статистика экспортирована в Excel</b>\n\n"
                f"<i>Данные актуальны на "
                f"{datetime.now(pytz.timezone(settings.TZ)).strftime('%H:%M')}</i>"
            )
        )

        # Удаляем временный файл
        import os
        os.remove(excel_path)

        logger.info(f"Stats exported to Excel by admin {callback.from_user.id}")

    except Exception as e:
        logger.error(f"Error creating Excel file: {e}", exc_info=True)
        await callback.message.answer(
            f"❌ <b>Ошибка при создании Excel файла:</b>\n\n"
            f"<code>{str(e)}</code>"
        )

    await state.clear()


@router.callback_query(F.data == "list_rn_format:cancel")
async def process_format_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена выбора формата"""
    await callback.answer()

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer("✅ Операция отменена")
    await state.clear()


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

async def _collect_stats_data(
        session: AsyncSession,
        channel_id: int
) -> Dict:
    """
    Собирает все данные статистики в структурированный словарь

    Returns:
        {
            'channel': Channel,
            'users': List[User],
            'timestamp': datetime,
            'events': {
                'regular': [...],
                'temp': [...],
                'checkout': [...],
                'notext': [...],
                'keyword': [...]
            }
        }
    """
    from bot.database.models import Channel

    channel = await session.get(Channel, channel_id)
    users = await UserChannelCRUD.get_users_by_channel(session, channel_id)
    store_groups = group_users_by_store(users)

    today = date.today()
    now = datetime.now(pytz.timezone(settings.TZ))

    stats_data = {
        'channel': channel,
        'users': users,
        'timestamp': now,
        'events': {
            'regular': [],
            'temp': [],
            'checkout': [],
            'notext': [],
            'keyword': []
        }
    }

    # === ОБЫЧНЫЕ СОБЫТИЯ ===
    events = await EventCRUD.get_active_by_channel(session, channel_id)
    for event in events:
        not_submitted = await _get_stores_without_regular_report(
            session, store_groups, channel_id, event.id, None
        )

        if not_submitted:
            stats_data['events']['regular'].append({
                'event': event,
                'not_submitted': not_submitted
            })

    # === ВРЕМЕННЫЕ СОБЫТИЯ ===
    temp_events = await TempEventCRUD.get_active_by_channel_and_date(
        session, channel_id, today
    )
    for temp_event in temp_events:
        not_submitted = await _get_stores_without_regular_report(
            session, store_groups, channel_id, None, temp_event.id
        )

        if not_submitted:
            stats_data['events']['temp'].append({
                'event': temp_event,
                'not_submitted': not_submitted
            })

    # === CHECKOUT СОБЫТИЯ ===
    checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel_id)
    for cev in checkout_events:
        checkout_stats = await _get_checkout_event_stats(
            session, store_groups, cev, now, today
        )

        if any([
            checkout_stats['not_submitted_first'],
            checkout_stats['not_submitted_second'],
            checkout_stats['partial_second'],
            checkout_stats['not_submitted_anything']
        ]):
            stats_data['events']['checkout'].append({
                'event': cev,
                'stats': checkout_stats
            })

    # === NOTEXT СОБЫТИЯ ===
    notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel_id)
    for notext_event in notext_events:
        not_submitted = []

        for store_id, store_users in store_groups.items():
            store_has_report = False
            store_has_dayoff = False

            for user in store_users:
                dayoff = await NoTextDayOffCRUD.get_today_dayoff(
                    session, user.id, notext_event.id
                )
                if dayoff:
                    store_has_dayoff = True
                    break

                report = await NoTextReportCRUD.get_today_report(
                    session, user.id, notext_event.id
                )
                if report:
                    store_has_report = True
                    break

            if not store_has_report and not store_has_dayoff:
                not_submitted.append((store_id, store_users))

        if not_submitted:
            stats_data['events']['notext'].append({
                'event': notext_event,
                'not_submitted': not_submitted
            })

    # === KEYWORD СОБЫТИЯ ===
    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel_id)
    for keyword_event in keyword_events:
        not_submitted = []

        for store_id, store_users in store_groups.items():
            store_has_report = False

            for user in store_users:
                report = await KeywordReportCRUD.get_today_report(
                    session, user.id, keyword_event.id
                )
                if report:
                    store_has_report = True
                    break

            if not store_has_report:
                not_submitted.append((store_id, store_users))

        if not_submitted:
            stats_data['events']['keyword'].append({
                'event': keyword_event,
                'not_submitted': not_submitted
            })

    return stats_data


async def _format_stats_as_text(
        session: AsyncSession,
        channel_id: int,
        stats_data: Dict
) -> str:
    """Форматирует статистику как текстовое сообщение"""

    channel = stats_data['channel']
    now = stats_data['timestamp']
    events = stats_data['events']

    # Проверяем, есть ли что-то для вывода
    has_content = any([
        events['regular'],
        events['temp'],
        events['checkout'],
        events['notext'],
        events['keyword']
    ])

    if not has_content:
        return (
            f"🎉 <b>Отлично!</b>\n\n"
            f"В канале <b>{html.quote(channel.title)}</b> все отчеты сданы!"
        )

    sections = []

    # === ОБЫЧНЫЕ СОБЫТИЯ ===
    for item in events['regular']:
        event = item['event']
        not_submitted = item['not_submitted']

        section = f"<b>📋 Событие: {html.quote(event.keyword)}</b>\n"
        section += f"⏰ Дедлайн: {event.deadline_time.strftime('%H:%M')}\n\n"
        section += "<b>❌ Не сдали:</b>\n"
        for i, (store_id, users_list) in enumerate(not_submitted, 1):
            mention = format_store_mention(store_id, users_list)
            section += f"{i}. {mention}\n"
        sections.append(section)

    # === ВРЕМЕННЫЕ СОБЫТИЯ ===
    for item in events['temp']:
        temp_event = item['event']
        not_submitted = item['not_submitted']

        section = f"<b>⏱ Временное событие: {html.quote(temp_event.keyword)}</b>\n"
        section += f"⏰ Дедлайн: {temp_event.deadline_time.strftime('%H:%M')}\n\n"
        section += "<b>❌ Не сдали:</b>\n"
        for i, (store_id, users_list) in enumerate(not_submitted, 1):
            mention = format_store_mention(store_id, users_list)
            section += f"{i}. {mention}\n"
        sections.append(section)

    # === CHECKOUT СОБЫТИЯ ===
    for item in events['checkout']:
        cev = item['event']
        checkout_stats = item['stats']

        section = f"<b>🔄 Двухэтапное событие: {html.quote(cev.first_keyword)}</b>\n"
        section += f"1️⃣ Первый этап: {cev.first_deadline_time.strftime('%H:%M')}\n"
        section += f"2️⃣ Второй этап: {cev.second_deadline_time.strftime('%H:%M')}\n\n"

        if checkout_stats['not_submitted_first']:
            section += "<b>⚠️ Не сдали первый этап:</b>\n"
            for i, (store_id, users_list) in enumerate(checkout_stats['not_submitted_first'], 1):
                mention = format_store_mention(store_id, users_list)
                section += f"{i}. {mention}\n"
            section += "\n"

        if checkout_stats['not_submitted_second']:
            section += "<b>⚠️ Сдали первый этап, но не начали второй:</b>\n"
            for i, (store_id, users_list) in enumerate(checkout_stats['not_submitted_second'], 1):
                mention = format_store_mention(store_id, users_list)
                section += f"{i}. {mention}\n"
            section += "\n"

        if checkout_stats['partial_second']:
            section += "<b>⚠️ Сдали не все из второго этапа:</b>\n"
            for i, (store_id, users_list, remaining) in enumerate(checkout_stats['partial_second'], 1):
                mention = format_store_mention(store_id, users_list)
                remaining_str = ", ".join(remaining)
                section += f"{i}. {mention} — осталось: {remaining_str}\n"
            section += "\n"

        if checkout_stats['not_submitted_anything']:
            section += "<b>❌ Не сдали ничего:</b>\n"
            for i, (store_id, users_list) in enumerate(checkout_stats['not_submitted_anything'], 1):
                mention = format_store_mention(store_id, users_list)
                section += f"{i}. {mention}\n"
            section += "\n"

        sections.append(section.rstrip())

    # === NOTEXT СОБЫТИЯ ===
    for item in events['notext']:
        notext_event = item['event']
        not_submitted = item['not_submitted']

        section = f"<b>📸 Событие без текста (NoText)</b>\n"
        section += f"⏰ Отслеживание: {notext_event.deadline_start.strftime('%H:%M')} - "
        section += f"{notext_event.deadline_end.strftime('%H:%M')}\n\n"
        section += "<b>❌ Не сдали:</b>\n"
        for i, (store_id, users_list) in enumerate(not_submitted, 1):
            mention = format_store_mention(store_id, users_list)
            section += f"{i}. {mention}\n"
        sections.append(section)

    # === KEYWORD СОБЫТИЯ ===
    for item in events['keyword']:
        keyword_event = item['event']
        not_submitted = item['not_submitted']

        section = f"<b>🔑 Событие с ключевым словом: {html.quote(keyword_event.keyword)}</b>\n"
        section += f"⏰ Отслеживание: {keyword_event.deadline_start.strftime('%H:%M')} - "
        section += f"{keyword_event.deadline_end.strftime('%H:%M')}\n\n"
        section += "<b>❌ Не сдали:</b>\n"
        for i, (store_id, users_list) in enumerate(not_submitted, 1):
            mention = format_store_mention(store_id, users_list)
            section += f"{i}. {mention}\n"
        sections.append(section)

    # === ИТОГОВОЕ СООБЩЕНИЕ ===
    header = f"📊 <b>Текущая статистика: {html.quote(channel.title)}</b>\n"
    header += f"🕐 На момент: {now.strftime('%H:%M')}\n\n"

    return header + "\n\n".join(sections)


async def _export_to_google_sheets(
        session: AsyncSession,
        channel_id: int,
        stats_data: Dict
) -> str:
    """
    Экспортирует статистику в Google Sheets

    Returns:
        URL таблицы
    """
    # Этот файл будет создан отдельно
    from utils.google_sheets_exporter import GoogleSheetsExporter

    exporter = GoogleSheetsExporter()
    sheet_url = await exporter.export_stats(stats_data)

    return sheet_url


async def _create_excel_file(
        session: AsyncSession,
        channel_id: int,
        stats_data: Dict
) -> str:
    """
    Создает Excel файл со статистикой

    Returns:
        Путь к созданному файлу
    """
    # Этот файл будет создан отдельно
    from utils.excel_exporter import ExcelExporter

    exporter = ExcelExporter()
    file_path = await exporter.export_stats(stats_data)

    return file_path


# Копируем вспомогательные функции из оригинальной версии
async def _get_stores_without_regular_report(
        session: AsyncSession,
        store_groups: dict,
        channel_id: int,
        event_id: int = None,
        temp_event_id: int = None
) -> list:
    """Получить список магазинов без отчета"""
    stores_without_report = []

    for store_id, store_users in store_groups.items():
        store_has_report = False

        for user in store_users:
            report = await ReportCRUD.get_today_report(
                session, user.id, channel_id, event_id, temp_event_id
            )
            if report:
                store_has_report = True
                break

        if not store_has_report:
            stores_without_report.append((store_id, store_users))

    return stores_without_report


async def _get_checkout_event_stats(
        session: AsyncSession,
        store_groups: dict,
        checkout_event,
        now: datetime,
        today: date
) -> dict:
    """Получить статистику по checkout событию"""
    first_deadline = pytz.timezone(settings.TZ).localize(
        datetime.combine(today, checkout_event.first_deadline_time)
    )

    first_deadline_passed = now > first_deadline

    result = {
        'not_submitted_first': [],
        'not_submitted_second': [],
        'partial_second': [],
        'not_submitted_anything': []
    }

    for store_id, store_users in store_groups.items():
        store_has_first_submission = False
        store_has_all_second = False
        store_remaining = None

        for user in store_users:
            submission = await CheckoutSubmissionCRUD.get_today_submission(
                session, user.id, checkout_event.id
            )

            if submission:
                store_has_first_submission = True

                remaining = await CheckoutReportCRUD.get_remaining_keywords(
                    session, user.id, checkout_event.id
                )

                if not remaining:
                    store_has_all_second = True
                    break

                if store_remaining is None:
                    store_remaining = remaining

        if not store_has_first_submission:
            if first_deadline_passed:
                result['not_submitted_anything'].append((store_id, store_users))
            else:
                result['not_submitted_first'].append((store_id, store_users))
        elif not store_has_all_second:
            if store_remaining:
                reports = []
                for user in store_users:
                    user_reports = await CheckoutReportCRUD.get_today_reports(
                        session, user.id, checkout_event.id
                    )
                    reports.extend(user_reports)

                if not reports:
                    result['not_submitted_second'].append((store_id, store_users))
                else:
                    result['partial_second'].append((store_id, store_users, store_remaining))

    return result