import logging
import json
from datetime import datetime, timedelta, date, time as dt_time
from typing import List, Tuple

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import settings
from bot.database.crud import (
    ChannelCRUD, UserChannelCRUD, ReportCRUD, StatsCRUD, EventCRUD,
    TempEventCRUD, CheckoutEventCRUD, CheckoutSubmissionCRUD, CheckoutReportCRUD
)
from bot.database.engine import async_session_maker
from bot.database.models import User
from bot.utils.user_grouping import (
    group_users_by_store,
    format_store_mention,
    get_store_users_list,
    has_store_submitted_report
)

logger = logging.getLogger(__name__)


class ReportScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone(settings.TZ))
        self.reminders_sent_today = set()
        self.warnings_sent_today = set()
        self.checkout_reminders_sent = set()  # Для checkout событий

    async def check_deadline_warnings(self):
        """Проверка за N минут ДО дедлайна (предупреждение)"""
        self._cleanup_old_warnings()

        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)
                now = datetime.now(pytz.timezone(settings.TZ))
                today = now.date()

                warning_minutes = getattr(settings, 'DEADLINE_WARNING_MINUTES', 5)

                for ch in channels:
                    # Обычные события
                    events = await EventCRUD.get_active_by_channel(session, ch.id)
                    users = await UserChannelCRUD.get_users_by_channel(session, ch.id)

                    for ev in events:
                        deadline = pytz.timezone(settings.TZ).localize(
                            datetime.combine(today, ev.deadline_time)
                        )
                        warning_time = deadline - timedelta(minutes=warning_minutes)

                        if warning_time <= now < warning_time + timedelta(minutes=1):
                            key = (ch.id, 'event', ev.id, today)
                            if key in self.warnings_sent_today:
                                continue

                            # Группируем по магазинам
                            store_groups = group_users_by_store(users)

                            # Проверяем какие магазины не сдали
                            stores_without_report = []
                            for store_id, store_users in store_groups.items():
                                # Проверяем хотя бы одного пользователя из магазина
                                store_has_report = False
                                for u in store_users:
                                    report = await ReportCRUD.get_today_report(
                                        session, u.id, ch.id, event_id=ev.id
                                    )
                                    if report:
                                        store_has_report = True
                                        break

                                if not store_has_report:
                                    stores_without_report.append((store_id, store_users))

                            if stores_without_report:
                                await self.send_warning_message(
                                    stores_without_report, ch, ev.keyword, ev.deadline_time,
                                    ev.min_photos, warning_minutes
                                )
                                self.warnings_sent_today.add(key)

                    # Временные события
                    temp_events = await TempEventCRUD.get_active_by_channel_and_date(
                        session, ch.id, today
                    )

                    for tev in temp_events:
                        deadline = pytz.timezone(settings.TZ).localize(
                            datetime.combine(today, tev.deadline_time)
                        )
                        warning_time = deadline - timedelta(minutes=warning_minutes)

                        if warning_time <= now < warning_time + timedelta(minutes=1):
                            key = (ch.id, 'temp_event', tev.id, today)
                            if key in self.warnings_sent_today:
                                continue

                            store_groups = group_users_by_store(users)

                            stores_without_report = []
                            for store_id, store_users in store_groups.items():
                                store_has_report = False
                                for u in store_users:
                                    report = await ReportCRUD.get_today_report(
                                        session, u.id, ch.id, temp_event_id=tev.id
                                    )
                                    if report:
                                        store_has_report = True
                                        break

                                if not store_has_report:
                                    stores_without_report.append((store_id, store_users))

                            if stores_without_report:
                                await self.send_warning_message(
                                    stores_without_report, ch, tev.keyword, tev.deadline_time,
                                    tev.min_photos, warning_minutes, is_temp=True
                                )
                                self.warnings_sent_today.add(key)

                    # === CHECKOUT СОБЫТИЯ - ПРЕДУПРЕЖДЕНИЯ ===
                    await self.check_checkout_warnings(session, ch, users, now, today, warning_minutes)

            except Exception as e:
                logger.error(f"Error in deadline warnings check: {e}", exc_info=True)

    async def send_warning_message(
            self,
            stores_without_report: List[Tuple[str, List[User]]],
            channel,
            keyword,
            deadline_time,
            min_photos,
            minutes_left,
            is_temp=False
    ):
        """
        Отправка предупреждения о приближении дедлайна.

        Args:
            stores_without_report: Список кортежей (store_id, [пользователи])
            channel: Канал для отправки
            keyword: Ключевое слово события
            deadline_time: Время дедлайна
            min_photos: Минимум фото
            minutes_left: Минут до дедлайна
            is_temp: Временное ли событие
        """
        # Формируем список магазинов
        store_list = []
        for i, (store_id, store_users) in enumerate(stores_without_report, 1):
            store_mention = format_store_mention(store_id, store_users)
            store_list.append(f"{i}. {store_mention}")

        event_type = "⏱ Временный отчет" if is_temp else "📋 Отчет"

        text = (
                f"⚠️ <b>ВНИМАНИЕ! До дедлайна осталось {minutes_left} минут!</b> ⚠️\n\n"
                f"{event_type}: <b>{channel.title}</b>\n"
                f"🔑 Ключевое слово: <code>{keyword}</code>\n"
                f"⏰ Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n"
                f"📸 Минимум фото: <b>{min_photos}</b>\n\n"
                f"<b>Еще не сдали отчет:</b>\n" + "\n".join(store_list) + "\n\n"
                f"⏱ Поторопитесь, времени мало!"
        )

        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
            logger.info(
                f"Warning sent: channel={channel.telegram_id}, "
                f"keyword={keyword}, stores={len(stores_without_report)}"
            )
        except Exception as e:
            logger.error(f"Failed to send warning: {e}", exc_info=True)

    async def check_checkout_warnings(self, session, channel, users, now, today, warning_minutes):
        """Предупреждения за N минут ДО дедлайнов checkout событий"""
        checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)

        for cev in checkout_events:
            # Предупреждение для первого дедлайна
            first_deadline = pytz.timezone(settings.TZ).localize(
                datetime.combine(today, cev.first_deadline_time)
            )
            first_warning_time = first_deadline - timedelta(minutes=warning_minutes)

            if first_warning_time <= now < first_warning_time + timedelta(minutes=1):
                key = (channel.id, 'checkout_first_warning', cev.id, today)
                if key not in self.warnings_sent_today:
                    store_groups = group_users_by_store(users)

                    stores_without_submission = []
                    for store_id, store_users in store_groups.items():
                        store_has_submission = False
                        for u in store_users:
                            submission = await CheckoutSubmissionCRUD.get_today_submission(
                                session, u.id, cev.id
                            )
                            if submission:
                                store_has_submission = True
                                break

                        if not store_has_submission:
                            stores_without_submission.append((store_id, store_users))

                    if stores_without_submission:
                        await self.send_checkout_first_warning(
                            stores_without_submission, channel, cev.first_keyword,
                            cev.first_deadline_time, warning_minutes
                        )
                        self.warnings_sent_today.add(key)

            # Предупреждение для второго дедлайна
            second_deadline = pytz.timezone(settings.TZ).localize(
                datetime.combine(today, cev.second_deadline_time)
            )
            second_warning_time = second_deadline - timedelta(minutes=warning_minutes)

            if second_warning_time <= now < second_warning_time + timedelta(minutes=1):
                key = (channel.id, 'checkout_second_warning', cev.id, today)
                if key not in self.warnings_sent_today:
                    store_groups = group_users_by_store(users)

                    incomplete_stores = []
                    for store_id, store_users in store_groups.items():
                        # Проверяем ВЕСЬ магазин
                        store_incomplete = True
                        store_remaining = None

                        for u in store_users:
                            submission = await CheckoutSubmissionCRUD.get_today_submission(
                                session, u.id, cev.id
                            )
                            if not submission:
                                continue

                            remaining = await CheckoutReportCRUD.get_remaining_keywords(
                                session, u.id, cev.id
                            )

                            # Если хотя бы один пользователь сдал все - магазин выполнил
                            if not remaining:
                                store_incomplete = False
                                break

                            # Запоминаем оставшиеся ключи
                            if store_remaining is None:
                                store_remaining = remaining

                        # Добавляем магазин только если НИ ОДИН пользователь не сдал все
                        if store_incomplete and store_remaining:
                            incomplete_stores.append((store_id, store_users, store_remaining))

                    if incomplete_stores:
                        await self.send_checkout_second_warning(
                            incomplete_stores, channel, cev.second_keyword,
                            cev.second_deadline_time, warning_minutes
                        )
                        self.warnings_sent_today.add(key)

    async def send_checkout_first_warning(
            self,
            stores_without_submission: List[Tuple[str, List[User]]],
            channel,
            keyword,
            deadline_time,
            minutes_left
    ):
        """Предупреждение о первом дедлайне checkout события"""

        store_list = []
        for i, (store_id, store_users) in enumerate(stores_without_submission, 1):
            store_mention = format_store_mention(store_id, store_users)
            store_list.append(f"{i}. {store_mention}")

        text = (
                f"⚠️ <b>ВНИМАНИЕ! До дедлайна осталось {minutes_left} минут!</b> ⚠️\n\n"
                f"1️⃣ Первый этап: <b>{channel.title}</b>\n"
                f"🔑 Ключевое слово: <code>{keyword}</code>\n"
                f"⏰ Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Еще не отправили отчет:</b>\n" + "\n".join(store_list) + "\n\n"
                f"<i>Формат: {keyword}: скоропорт + тихое + бакалея</i>\n"
                f"⏱ Поторопитесь, времени мало!"
        )

        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
            logger.info(
                f"Checkout first warning sent: channel={channel.telegram_id}, "
                f"keyword={keyword}, stores={len(stores_without_submission)}"
            )
        except Exception as e:
            logger.error(f"Failed to send checkout first warning: {e}", exc_info=True)

    async def send_checkout_second_warning(
            self,
            incomplete_stores: List[Tuple[str, List[User], List[str]]],
            channel,
            keyword,
            deadline_time,
            minutes_left
    ):
        """Предупреждение о втором дедлайне checkout события"""

        store_list = []
        for i, (store_id, store_users, remaining) in enumerate(incomplete_stores, 1):
            store_mention = format_store_mention(store_id, store_users)
            remaining_str = ", ".join(remaining)
            store_list.append(f"{i}. {store_mention} — осталось: {remaining_str}")

        text = (
                f"⚠️ <b>ВНИМАНИЕ! До дедлайна осталось {minutes_left} минут!</b> ⚠️\n\n"
                f"2️⃣ Второй этап: <b>{channel.title}</b>\n"
                f"🔑 Ключевое слово: <code>{keyword}</code>\n"
                f"⏰ Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Не сдали отчеты:</b>\n" + "\n".join(store_list) + "\n\n"
                f"⏱ Поторопитесь, времени мало!"
        )

        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
            logger.info(
                f"Checkout second warning sent: channel={channel.telegram_id}, "
                f"keyword={keyword}, stores={len(incomplete_stores)}"
            )
        except Exception as e:
            logger.error(f"Failed to send checkout second warning: {e}", exc_info=True)

    async def check_deadlines(self):
        """Проверка дедлайнов (ПОСЛЕ наступления) + напоминания"""
        self._cleanup_old_reminders()

        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)
                now = datetime.now(pytz.timezone(settings.TZ))
                today = now.date()

                for ch in channels:
                    users = await UserChannelCRUD.get_users_by_channel(session, ch.id)

                    # === ОБЫЧНЫЕ СОБЫТИЯ ===
                    events = await EventCRUD.get_active_by_channel(session, ch.id)

                    for ev in events:
                        deadline = pytz.timezone(settings.TZ).localize(
                            datetime.combine(today, ev.deadline_time)
                        )

                        # Напоминание через 5 минут после дедлайна
                        reminder_window_start = deadline + timedelta(minutes=5)
                        reminder_window_end = deadline + timedelta(minutes=5, seconds=59)

                        if reminder_window_start <= now <= reminder_window_end:
                            key = (ch.id, 'event', ev.id, today)
                            if key in self.reminders_sent_today:
                                continue

                            store_groups = group_users_by_store(users)

                            stores_without_report = []
                            for store_id, store_users in store_groups.items():
                                store_has_report = False
                                for u in store_users:
                                    if await ReportCRUD.get_today_report(session, u.id, ch.id, event_id=ev.id):
                                        store_has_report = True
                                        break

                                if not store_has_report:
                                    stores_without_report.append((store_id, store_users))

                            if stores_without_report:
                                await self.send_group_reminder(
                                    stores_without_report, ch, ev.keyword, ev.deadline_time
                                )
                                # Добавляем статистику для ВСЕХ пользователей магазина
                                for _, store_users in stores_without_report:
                                    for u in store_users:
                                        await StatsCRUD.add_reminder(session, u.id, ch.id)
                                self.reminders_sent_today.add(key)

                    # === ВРЕМЕННЫЕ СОБЫТИЯ ===
                    temp_events = await TempEventCRUD.get_active_by_channel_and_date(
                        session, ch.id, today
                    )

                    for tev in temp_events:
                        deadline = pytz.timezone(settings.TZ).localize(
                            datetime.combine(today, tev.deadline_time)
                        )

                        reminder_window_start = deadline + timedelta(minutes=5)
                        reminder_window_end = deadline + timedelta(minutes=5, seconds=59)

                        if reminder_window_start <= now <= reminder_window_end:
                            key = (ch.id, 'temp_event', tev.id, today)
                            if key in self.reminders_sent_today:
                                continue

                            store_groups = group_users_by_store(users)

                            stores_without_report = []
                            for store_id, store_users in store_groups.items():
                                store_has_report = False
                                for u in store_users:
                                    if await ReportCRUD.get_today_report(session, u.id, ch.id, temp_event_id=tev.id):
                                        store_has_report = True
                                        break

                                if not store_has_report:
                                    stores_without_report.append((store_id, store_users))

                            if stores_without_report:
                                await self.send_group_reminder(
                                    stores_without_report, ch, tev.keyword, tev.deadline_time,
                                    is_temp=True
                                )
                                for _, store_users in stores_without_report:
                                    for u in store_users:
                                        await StatsCRUD.add_reminder(session, u.id, ch.id)
                                self.reminders_sent_today.add(key)

                    # === CHECKOUT СОБЫТИЯ ===
                    await self.check_checkout_deadlines(session, ch, users, now, today)

            except Exception as e:
                logger.error(f"Error in deadline check: {e}", exc_info=True)

    async def check_checkout_deadlines(self, session, channel, users, now, today):
        """Проверка дедлайнов для checkout событий"""
        checkout_events = await CheckoutEventCRUD.get_active_by_channel(session, channel.id)

        for cev in checkout_events:
            # Первый дедлайн (пересчет)
            first_deadline = pytz.timezone(settings.TZ).localize(
                datetime.combine(today, cev.first_deadline_time)
            )
            first_reminder_start = first_deadline + timedelta(minutes=5)
            first_reminder_end = first_deadline + timedelta(minutes=5, seconds=59)

            if first_reminder_start <= now <= first_reminder_end:
                key = (channel.id, 'checkout_first', cev.id, today)
                if key not in self.checkout_reminders_sent:
                    store_groups = group_users_by_store(users)

                    stores_without_submission = []
                    for store_id, store_users in store_groups.items():
                        store_has_submission = False
                        for u in store_users:
                            submission = await CheckoutSubmissionCRUD.get_today_submission(
                                session, u.id, cev.id
                            )
                            if submission:
                                store_has_submission = True
                                break

                        if not store_has_submission:
                            stores_without_submission.append((store_id, store_users))

                    if stores_without_submission:
                        await self.send_checkout_first_reminder(
                            stores_without_submission, channel, cev.first_keyword, cev.first_deadline_time
                        )
                        for _, store_users in stores_without_submission:
                            for u in store_users:
                                await StatsCRUD.add_reminder(session, u.id, channel.id)
                        self.checkout_reminders_sent.add(key)

            # Второй дедлайн (фотоотчеты)
            second_deadline = pytz.timezone(settings.TZ).localize(
                datetime.combine(today, cev.second_deadline_time)
            )
            second_reminder_start = second_deadline + timedelta(minutes=5)
            second_reminder_end = second_deadline + timedelta(minutes=5, seconds=59)

            if second_reminder_start <= now <= second_reminder_end:
                key = (channel.id, 'checkout_second', cev.id, today)
                if key not in self.checkout_reminders_sent:
                    # Находим тех, кто не сдал все фотоотчеты
                    store_groups = group_users_by_store(users)

                    incomplete_stores = []
                    for store_id, store_users in store_groups.items():
                        store_incomplete = True
                        store_remaining = None

                        for u in store_users:
                            remaining = await CheckoutReportCRUD.get_remaining_keywords(
                                session, u.id, cev.id
                            )

                            if not remaining:
                                store_incomplete = False
                                break

                            if store_remaining is None:
                                store_remaining = remaining

                        if store_incomplete and store_remaining:
                            incomplete_stores.append((store_id, store_users, store_remaining))

                    if incomplete_stores:
                        await self.send_checkout_second_reminder(
                            incomplete_stores, channel, cev.second_keyword, cev.second_deadline_time
                        )
                        for _, store_users, _ in incomplete_stores:
                            for u in store_users:
                                await StatsCRUD.add_reminder(session, u.id, channel.id)
                        self.checkout_reminders_sent.add(key)

    async def send_checkout_first_reminder(
            self,
            stores_without_submission: List[Tuple[str, List[User]]],
            channel,
            keyword,
            deadline_time
    ):
        """Напоминание о первом этапе checkout"""

        store_list = []
        for i, (store_id, store_users) in enumerate(stores_without_submission, 1):
            store_mention = format_store_mention(store_id, store_users)
            store_list.append(f"{i}. {store_mention}")

        text = (
                f"🔴 <b>Напоминаю о необходимости отправить отчет!</b>\n\n"
                f"Канал: <b>{channel.title}</b>\n"
                f"Ключевое слово: <code>{keyword}</code>\n"
                f"Дедлайн был: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Не отправили отчет:</b>\n" + "\n".join(store_list) + "\n\n"
                f"<i>Формат: {keyword}: скоропорт + тихое + бакалея</i>"
        )

        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
        except Exception as e:
            logger.error(f"Failed to send checkout first reminder: {e}")

    async def send_checkout_second_reminder(
            self,
            incomplete_stores: List[Tuple[str, List[User], List[str]]],
            channel,
            keyword,
            deadline_time
    ):
        """Напоминание о втором этапе checkout"""

        store_list = []
        for i, (store_id, store_users, remaining) in enumerate(incomplete_stores, 1):
            store_mention = format_store_mention(store_id, store_users)
            remaining_str = ", ".join(remaining)
            store_list.append(f"{i}. {store_mention} — осталось: {remaining_str}")

        text = (
                f"🔴 <b>Напоминаю о необходимости сдать отчеты!</b>\n\n"
                f"Канал: <b>{channel.title}</b>\n"
                f"Ключевое слово: <code>{keyword}</code>\n"
                f"Дедлайн был: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Не сдали все отчеты:</b>\n" + "\n".join(store_list)
        )

        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
        except Exception as e:
            logger.error(f"Failed to send checkout second reminder: {e}")

    async def send_group_reminder(
            self,
            stores_without_report: List[Tuple[str, List[User]]],
            channel,
            keyword,
            deadline_time,
            is_temp=False
    ):
        """Отправка напоминания ПОСЛЕ дедлайна"""

        store_list = []
        for i, (store_id, store_users) in enumerate(stores_without_report, 1):
            store_mention = format_store_mention(store_id, store_users)
            store_list.append(f"{i}. {store_mention}")

        event_type = "⏱ Временный отчет" if is_temp else "📋 Отчет"

        text = (
                f"🔴 <b>Напоминаю, что необходимо сдать отчет!</b>\n\n"
                f"{event_type}: <b>{channel.title}</b>\n"
                f"Ключевое слово: <code>{keyword}</code>\n"
                f"Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Список тех, кто до сих пор не сдал:</b>\n" + "\n".join(store_list)
        )

        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
        except Exception as e:
            logger.error(f"Reminder failed: {e}")

    async def cleanup_temp_events(self):
        """Удаление временных событий в 23:59"""
        async with async_session_maker() as session:
            try:
                today = date.today()
                deleted = await TempEventCRUD.delete_old_events(session, today)
                if deleted > 0:
                    logger.info(f"Deleted {deleted} old temporary events")
            except Exception as e:
                logger.error(f"Error cleaning up temp events: {e}", exc_info=True)

    async def send_checkout_daily_stats(self):
        """Отправка ежедневной статистики checkout событий в 22:00"""
        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)
                today = date.today()

                for channel in channels:
                    checkout_events = await CheckoutEventCRUD.get_active_by_channel(
                        session, channel.id
                    )

                    if not checkout_events:
                        continue

                    for cev in checkout_events:
                        await self.send_checkout_stats_for_event(
                            session, channel, cev, today
                        )
            except Exception as e:
                logger.error(f"Error sending checkout stats: {e}", exc_info=True)

    async def send_checkout_stats_for_event(self, session, channel, checkout_event, today):
        """
        Отправка статистики для конкретного checkout события.
        Группировка по магазинам (store_id).
        """
        users = await UserChannelCRUD.get_users_by_channel(session, channel.id)
        store_groups = group_users_by_store(users)

        # Категории статистики по магазинам
        on_time_stores = []  # [(store_id, users)]
        late_stores = []  # [(store_id, users, datetime)]
        partial_stores = []  # [(store_id, users, submitted_count, total_count)]
        not_submitted_stores = []  # [(store_id, users)]

        for store_id, store_users in store_groups.items():
            # Проверяем ВЕСЬ магазин (все аккаунты пользователей)
            store_status = None  # 'on_time', 'late', 'partial', 'not_submitted'
            latest_submission = None
            partial_info = None

            for user in store_users:
                submission = await CheckoutSubmissionCRUD.get_today_submission(
                    session, user.id, checkout_event.id
                )

                if not submission:
                    # Этот пользователь вообще не отправил пересчет
                    continue

                reports = await CheckoutReportCRUD.get_today_reports(
                    session, user.id, checkout_event.id
                )

                if not reports:
                    # Отправил пересчет, но нет отчетов
                    submitted_keywords = json.loads(submission.keywords)
                    partial_info = (0, len(submitted_keywords))
                    continue

                # Проверяем, все ли сдано
                remaining = await CheckoutReportCRUD.get_remaining_keywords(
                    session, user.id, checkout_event.id
                )

                if remaining:
                    # Сдано не все
                    submitted_keywords = json.loads(submission.keywords)
                    submitted_count = len(submitted_keywords) - len(remaining)
                    partial_info = (submitted_count, len(submitted_keywords))
                    continue

                # Все сдано - проверяем время
                last_report = max(reports, key=lambda r: r.submitted_at)
                deadline = datetime.combine(today, checkout_event.second_deadline_time)
                deadline = pytz.timezone(settings.TZ).localize(deadline)

                # Обрабатываем timezone
                if last_report.submitted_at.tzinfo is None:
                    submitted_time = pytz.timezone(settings.TZ).localize(last_report.submitted_at)
                else:
                    submitted_time = last_report.submitted_at.astimezone(pytz.timezone(settings.TZ))

                if submitted_time <= deadline:
                    # Этот пользователь сдал вовремя - весь магазин считается вовремя
                    store_status = 'on_time'
                    break
                else:
                    # Опоздал, но хотя бы сдал
                    if store_status != 'on_time':
                        store_status = 'late'
                        latest_submission = submitted_time

            # Распределяем магазин по категориям
            if store_status == 'on_time':
                on_time_stores.append((store_id, store_users))
            elif store_status == 'late':
                late_stores.append((store_id, store_users, latest_submission))
            elif partial_info:
                partial_stores.append((store_id, store_users, partial_info[0], partial_info[1]))
            else:
                not_submitted_stores.append((store_id, store_users))

        # Формируем сообщение (ТОЛЬКО непустые разделы)
        text = f"📊 <b>Статистика по событию '{checkout_event.first_keyword}'</b>\n\n"
        has_content = False

        if on_time_stores:
            has_content = True
            text += "✅ <b>Сдали вовремя:</b>\n"
            for store_id, users in on_time_stores:
                mention = format_store_mention(store_id, users)
                text += f"• {mention}\n"
            text += "\n"

        if late_stores:
            has_content = True
            text += "⚠️ <b>Сдали, но с опозданием:</b>\n"
            for store_id, users, late_time in late_stores:
                mention = format_store_mention(store_id, users)
                time_str = late_time.strftime('%H:%M')
                text += f"• {mention} (сдал в {time_str})\n"
            text += "\n"

        if partial_stores:
            has_content = True
            text += "⚠️ <b>Не сдали часть отчетов:</b>\n"
            for store_id, users, submitted, total in partial_stores:
                mention = format_store_mention(store_id, users)
                not_submitted = total - submitted
                text += f"• {mention} (сдали: {submitted}, не сдали: {not_submitted})\n"
            text += "\n"

        if not_submitted_stores:
            has_content = True
            text += "❌ <b>Не сдали вообще:</b>\n"
            for store_id, users in not_submitted_stores:
                mention = format_store_mention(store_id, users)
                users_list = get_store_users_list(users)
                text += f"• {mention} ({users_list})\n"
            text += "\n"
            text += "<i>Те, которые указаны в этом списке — жду причину почему, " \
                    "остальным выражаю благодарность за вашу работу!</i>\n"

        if not has_content:
            text += "🎉 <b>Нет данных для отображения</b>"

        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
            logger.info(
                f"Checkout stats sent for channel {channel.telegram_id}, "
                f"event {checkout_event.id}"
            )
        except Exception as e:
            logger.error(f"Error sending checkout stats: {e}")

    async def check_notext_keyword_events(self):
        """Проверка и публикация статистики для notext и keyword событий"""
        async with async_session_maker() as session:
            try:
                from bot.database.crud import (
                    NoTextEventCRUD, NoTextReportCRUD, NoTextDayOffCRUD,
                    KeywordEventCRUD, KeywordReportCRUD
                )
                
                channels = await ChannelCRUD.get_all_active(session)
                now = datetime.now(pytz.timezone(settings.TZ))
                current_time = now.time()
                today = now.date()

                for channel in channels:
                    # Проверяем notext события
                    notext_events = await NoTextEventCRUD.get_active_by_channel(session, channel.id)
                    
                    for notext_event in notext_events:
                        # Проверяем, наступило ли время публикации (deadline_end)
                        deadline_end = notext_event.deadline_end
                        
                        # Публикуем в окне +/- 1 минута от deadline_end
                        time_diff = abs(
                            (current_time.hour * 60 + current_time.minute) -
                            (deadline_end.hour * 60 + deadline_end.minute)
                        )
                        
                        if time_diff <= 1:
                            await self.send_notext_stats(session, channel, notext_event, today)
                    
                    # Проверяем keyword события
                    keyword_events = await KeywordEventCRUD.get_active_by_channel(session, channel.id)
                    
                    for keyword_event in keyword_events:
                        # Проверяем, наступило ли время публикации (deadline_end)
                        deadline_end = keyword_event.deadline_end
                        
                        time_diff = abs(
                            (current_time.hour * 60 + current_time.minute) -
                            (deadline_end.hour * 60 + deadline_end.minute)
                        )
                        
                        if time_diff <= 1:
                            await self.send_keyword_stats(session, channel, keyword_event, today)
                            
            except Exception as e:
                logger.error(f"Error in check_notext_keyword_events: {e}", exc_info=True)

    async def send_notext_stats(self, session, channel, notext_event, today):
        """Отправка статистики для notext события"""
        from bot.database.crud import NoTextReportCRUD, NoTextDayOffCRUD
        
        users = await UserChannelCRUD.get_users_by_channel(session, channel.id)
        store_groups = group_users_by_store(users)
        
        on_time = []  # Сдали вовремя
        not_submitted = []  # Не сдали
        day_off = []  # Выходной

        for store_id, store_users in store_groups.items():
            # Проверяем весь магазин
            store_has_report = False
            store_has_dayoff = False

            for user in store_users:
                # Проверяем выходной
                dayoff = await NoTextDayOffCRUD.get_today_dayoff(session, user.id, notext_event.id)
                if dayoff:
                    store_has_dayoff = True
                    break

                # Проверяем отчет
                report = await NoTextReportCRUD.get_today_report(session, user.id, notext_event.id)
                if report:
                    store_has_report = True
                    break

            if store_has_dayoff:
                day_off.append((store_id, store_users))
            elif store_has_report:
                on_time.append((store_id, store_users))
            else:
                not_submitted.append((store_id, store_users))
        
        # Формируем статистику (только непустые разделы)
        text = f"📊 <b>Статистика отправки фото</b>\n\n"
        has_content = False
        
        if on_time:
            has_content = True
            text += "✅ <b>Сдали вовремя:</b>\n"
            for store_id, users in on_time:
                mention = format_store_mention(store_id, users)
                text += f"• {mention}\n"
            text += "\n"
        
        if not_submitted:
            has_content = True
            text += "❌ <b>Не сдали:</b>\n"
            for store_id, users in not_submitted:
                mention = format_store_mention(store_id, users)
                text += f"• {mention}\n"
            text += "\n"
        
        if day_off:
            has_content = True
            text += "🏖 <b>Выходной:</b>\n"
            for store_id, users in day_off:
                mention = format_store_mention(store_id, users)
                text += f"• {mention}\n"
        
        if not has_content:
            text += "<i>Нет данных для отображения</i>"
        
        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
            logger.info(f"NoText stats sent for channel {channel.telegram_id}, event {notext_event.id}")
        except Exception as e:
            logger.error(f"Error sending notext stats: {e}")

    async def send_keyword_stats(self, session, channel, keyword_event, today):
        """Отправка статистики для keyword события"""
        from bot.database.crud import KeywordReportCRUD
        
        users = await UserChannelCRUD.get_users_by_channel(session, channel.id)
        store_groups = group_users_by_store(users)
        
        on_time = []  # Сдали вовремя
        not_submitted = []  # Не сдали

        for store_id, store_users in store_groups.items():
            store_has_report = False

            for user in store_users:
                report = await KeywordReportCRUD.get_today_report(session, user.id, keyword_event.id)
                if report:
                    store_has_report = True
                    break

            if store_has_report:
                on_time.append((store_id, store_users))
            else:
                not_submitted.append((store_id, store_users))
        
        # Формируем статистику (только непустые разделы)
        text = f"📊 <b>Статистика по ключевому слову '{keyword_event.keyword}'</b>\n\n"
        
        has_content = False
        
        if on_time:
            has_content = True
            text += "✅ <b>Сдали вовремя:</b>\n"
            for store_id, users in on_time:
                mention = format_store_mention(store_id, users)
                text += f"• {mention}\n"
            text += "\n"
        
        if not_submitted:
            has_content = True
            text += "❌ <b>Не сдали:</b>\n"
            for store_id, users in not_submitted:
                mention = format_store_mention(store_id, users)
                text += f"• {mention}\n"
        
        if not has_content:
            text += "<i>Нет данных для отображения</i>"
        
        try:
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=text,
                message_thread_id=channel.thread_id
            )
            logger.info(f"Keyword stats sent for channel {channel.telegram_id}, event {keyword_event.id}")
        except Exception as e:
            logger.error(f"Error sending keyword stats: {e}")

    def _cleanup_old_reminders(self):
        """Очистка кэша напоминаний в начале нового дня"""
        self.reminders_sent_today = {
            k for k in self.reminders_sent_today if k[3] == date.today()
        }
        self.checkout_reminders_sent = {
            k for k in self.checkout_reminders_sent if k[3] == date.today()
        }

    def _cleanup_old_warnings(self):
        """Очистка кэша предупреждений в начале нового дня"""
        self.warnings_sent_today = {
            k for k in self.warnings_sent_today if k[3] == date.today()
        }

    def start(self):
        """Запуск планировщика"""
        # Проверка предупреждений ДО дедлайна (каждую минуту)
        self.scheduler.add_job(
            self.check_deadline_warnings,
            trigger=CronTrigger(minute="*", timezone=settings.TZ),
            id="check_deadline_warnings"
        )

        # Проверка напоминаний ПОСЛЕ дедлайна (каждую минуту)
        self.scheduler.add_job(
            self.check_deadlines,
            trigger=CronTrigger(minute="*", timezone=settings.TZ),
            id="check_deadlines"
        )

        # Очистка временных событий в 23:59
        self.scheduler.add_job(
            self.cleanup_temp_events,
            trigger=CronTrigger(hour=23, minute=59, timezone=settings.TZ),
            id="cleanup_temp_events"
        )

        # Статистика checkout событий в 22:00
        self.scheduler.add_job(
            self.send_checkout_daily_stats,
            trigger=CronTrigger(hour=22, minute=0, timezone=settings.TZ),
            id="send_checkout_daily_stats"
        )
        
        # Проверка и публикация статистики notext и keyword событий (каждую минуту)
        self.scheduler.add_job(
            self.check_notext_keyword_events,
            trigger=CronTrigger(minute="*", timezone=settings.TZ),
            id="check_notext_keyword_events"
        )

        self.scheduler.start()
        logger.info("✅ Scheduler started with all event types support")

    def shutdown(self):
        """Остановка планировщика"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")