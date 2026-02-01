import logging
import json
from datetime import datetime, timedelta, date, time as dt_time
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import settings
from bot.database.crud import (
    ChannelCRUD, UserChannelCRUD, ReportCRUD, StatsCRUD, EventCRUD,
    TempEventCRUD, CheckoutEventCRUD, CheckoutSubmissionCRUD, CheckoutReportCRUD
)
from bot.database.engine import async_session_maker

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

                            debtors = []
                            for u in users:
                                report = await ReportCRUD.get_today_report(
                                    session, u.id, ch.id, event_id=ev.id
                                )
                                if not report:
                                    debtors.append(u)

                            if debtors:
                                await self.send_warning_message(
                                    debtors, ch, ev.keyword, ev.deadline_time,
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

                            debtors = []
                            for u in users:
                                report = await ReportCRUD.get_today_report(
                                    session, u.id, ch.id, temp_event_id=tev.id
                                )
                                if not report:
                                    debtors.append(u)

                            if debtors:
                                await self.send_warning_message(
                                    debtors, ch, tev.keyword, tev.deadline_time,
                                    tev.min_photos, warning_minutes, is_temp=True
                                )
                                self.warnings_sent_today.add(key)

                    # === CHECKOUT СОБЫТИЯ - ПРЕДУПРЕЖДЕНИЯ ===
                    await self.check_checkout_warnings(session, ch, users, now, today, warning_minutes)

            except Exception as e:
                logger.error(f"Error in deadline warnings check: {e}", exc_info=True)

    async def send_warning_message(
            self, debtors, channel, keyword, deadline_time, min_photos,
            minutes_left, is_temp=False
    ):
        """Отправка предупреждения о приближении дедлайна"""
        debt_list = [
            f"{i}. @{u.username}" if u.username else f"{i}. {u.full_name}"
            for i, u in enumerate(debtors, 1)
        ]

        event_type = "⏱ Временный отчет" if is_temp else "📋 Отчет"

        text = (
                f"⚠️ <b>ВНИМАНИЕ! До дедлайна осталось {minutes_left} минут!</b> ⚠️\n\n"
                f"{event_type}: <b>{channel.title}</b>\n"
                f"🔑 Ключевое слово: <code>{keyword}</code>\n"
                f"⏰ Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n"
                f"📸 Минимум фото: <b>{min_photos}</b>\n\n"
                f"<b>Еще не сдали отчет:</b>\n" + "\n".join(debt_list) + "\n\n"
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
                f"keyword={keyword}, users={len(debtors)}"
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
                    debtors = []
                    for u in users:
                        submission = await CheckoutSubmissionCRUD.get_today_submission(
                            session, u.id, cev.id
                        )
                        if not submission:
                            debtors.append(u)

                    if debtors:
                        await self.send_checkout_first_warning(
                            debtors, channel, cev.first_keyword, 
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
                    incomplete_users = []
                    for u in users:
                        submission = await CheckoutSubmissionCRUD.get_today_submission(
                            session, u.id, cev.id
                        )
                        if not submission:
                            continue
                        
                        remaining = await CheckoutReportCRUD.get_remaining_keywords(
                            session, u.id, cev.id
                        )
                        if remaining:
                            incomplete_users.append((u, remaining))

                    if incomplete_users:
                        await self.send_checkout_second_warning(
                            incomplete_users, channel, cev.second_keyword,
                            cev.second_deadline_time, warning_minutes
                        )
                        self.warnings_sent_today.add(key)

    async def send_checkout_first_warning(
            self, debtors, channel, keyword, deadline_time, minutes_left
    ):
        """Предупреждение о первом дедлайне checkout события"""
        debt_list = [
            f"{i}. @{u.username}" if u.username else f"{i}. {u.full_name}"
            for i, u in enumerate(debtors, 1)
        ]

        text = (
            f"⚠️ <b>ВНИМАНИЕ! До дедлайна осталось {minutes_left} минут!</b> ⚠️\n\n"
            f"1️⃣ Первый этап: <b>{channel.title}</b>\n"
            f"🔑 Ключевое слово: <code>{keyword}</code>\n"
            f"⏰ Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
            f"<b>Еще не отправили пересчет:</b>\n" + "\n".join(debt_list) + "\n\n"
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
                f"keyword={keyword}, users={len(debtors)}"
            )
        except Exception as e:
            logger.error(f"Failed to send checkout first warning: {e}", exc_info=True)

    async def send_checkout_second_warning(
            self, incomplete_users, channel, keyword, deadline_time, minutes_left
    ):
        """Предупреждение о втором дедлайне checkout события"""
        debt_list = []
        for i, (u, remaining) in enumerate(incomplete_users, 1):
            username = f"@{u.username}" if u.username else u.full_name
            remaining_str = ", ".join(remaining)
            debt_list.append(f"{i}. {username} — осталось: {remaining_str}")

        text = (
            f"⚠️ <b>ВНИМАНИЕ! До дедлайна осталось {minutes_left} минут!</b> ⚠️\n\n"
            f"2️⃣ Второй этап: <b>{channel.title}</b>\n"
            f"🔑 Ключевое слово: <code>{keyword}</code>\n"
            f"⏰ Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
            f"<b>Не сдали все фотоотчеты:</b>\n" + "\n".join(debt_list) + "\n\n"
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
                f"keyword={keyword}, users={len(incomplete_users)}"
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

                            debtors = [
                                u for u in users
                                if not await ReportCRUD.get_today_report(
                                    session, u.id, ch.id, event_id=ev.id
                                )
                            ]

                            if debtors:
                                await self.send_group_reminder(
                                    debtors, ch, ev.keyword, ev.deadline_time
                                )
                                for d in debtors:
                                    await StatsCRUD.add_reminder(session, d.id, ch.id)
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

                            debtors = [
                                u for u in users
                                if not await ReportCRUD.get_today_report(
                                    session, u.id, ch.id, temp_event_id=tev.id
                                )
                            ]

                            if debtors:
                                await self.send_group_reminder(
                                    debtors, ch, tev.keyword, tev.deadline_time,
                                    is_temp=True
                                )
                                for d in debtors:
                                    await StatsCRUD.add_reminder(session, d.id, ch.id)
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
                    debtors = []
                    for u in users:
                        submission = await CheckoutSubmissionCRUD.get_today_submission(
                            session, u.id, cev.id
                        )
                        if not submission:
                            debtors.append(u)

                    if debtors:
                        await self.send_checkout_first_reminder(
                            debtors, channel, cev.first_keyword, cev.first_deadline_time
                        )
                        for d in debtors:
                            await StatsCRUD.add_reminder(session, d.id, channel.id)
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
                    incomplete_users = []
                    for u in users:
                        remaining = await CheckoutReportCRUD.get_remaining_keywords(
                            session, u.id, cev.id
                        )
                        if remaining:
                            incomplete_users.append((u, remaining))

                    if incomplete_users:
                        await self.send_checkout_second_reminder(
                            incomplete_users, channel, cev.second_keyword, cev.second_deadline_time
                        )
                        for u, _ in incomplete_users:
                            await StatsCRUD.add_reminder(session, u.id, channel.id)
                        self.checkout_reminders_sent.add(key)

    async def send_checkout_first_reminder(self, debtors, channel, keyword, deadline_time):
        """Напоминание о первом этапе checkout"""
        debt_list = [
            f"{i}. @{u.username}" if u.username else f"{i}. {u.full_name}"
            for i, u in enumerate(debtors, 1)
        ]

        text = (
                f"🔴 <b>Напоминаю о необходимости отправить пересчет!</b>\n\n"
                f"Канал: <b>{channel.title}</b>\n"
                f"Ключевое слово: <code>{keyword}</code>\n"
                f"Дедлайн был: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Не отправили пересчет:</b>\n" + "\n".join(debt_list) + "\n\n"
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
            self, incomplete_users, channel, keyword, deadline_time
    ):
        """Напоминание о втором этапе checkout"""
        debt_list = []
        for i, (u, remaining) in enumerate(incomplete_users, 1):
            username = f"@{u.username}" if u.username else u.full_name
            remaining_str = ", ".join(remaining)
            debt_list.append(f"{i}. {username} — осталось: {remaining_str}")

        text = (
                f"🔴 <b>Напоминаю о необходимости сдать фотоотчеты!</b>\n\n"
                f"Канал: <b>{channel.title}</b>\n"
                f"Ключевое слово: <code>{keyword}</code>\n"
                f"Дедлайн был: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Не сдали все отчеты:</b>\n" + "\n".join(debt_list)
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
            self, debtors, channel, keyword, deadline_time, is_temp=False
    ):
        """Отправка напоминания ПОСЛЕ дедлайна"""
        debt_list = [
            f"{i}. @{u.username}" if u.username else f"{i}. {u.full_name}"
            for i, u in enumerate(debtors, 1)
        ]

        event_type = "⏱ Временный отчет" if is_temp else "📋 Отчет"

        text = (
                f"🔴 <b>Напоминаю, что необходимо сдать отчет!</b>\n\n"
                f"{event_type}: <b>{channel.title}</b>\n"
                f"Ключевое слово: <code>{keyword}</code>\n"
                f"Дедлайн: <b>{deadline_time.strftime('%H:%M')}</b>\n\n"
                f"<b>Список тех, кто до сих пор не сдал:</b>\n" + "\n".join(debt_list)
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
        """Отправка ежедневной статистики checkout событий (вызывается каждую минуту)"""
        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)
                today = date.today()
                now = datetime.now(pytz.timezone(settings.TZ))
                current_time = now.time()

                for channel in channels:
                    checkout_events = await CheckoutEventCRUD.get_active_by_channel(
                        session, channel.id
                    )

                    if not checkout_events:
                        continue

                    for cev in checkout_events:
                        # Определяем время статистики (индивидуальное или дефолтное 22:00)
                        stats_time = cev.stats_time if cev.stats_time else dt_time(22, 0)
                        
                        # Проверяем, совпадает ли текущее время с временем статистики (с точностью до минуты)
                        if current_time.hour == stats_time.hour and current_time.minute == stats_time.minute:
                            await self.send_checkout_stats_for_event(
                                session, channel, cev, today
                            )
            except Exception as e:
                logger.error(f"Error sending checkout stats: {e}", exc_info=True)

    async def send_checkout_stats_for_event(self, session, channel, checkout_event, today):
        """Отправка статистики для конкретного checkout события"""
        users = await UserChannelCRUD.get_users_by_channel(session, channel.id)

        # Категории пользователей
        on_time = []  # Сдали вовремя
        late = []  # Немного опоздали
        day_off = []  # Выходной
        not_submitted = []  # Не сдали (с деталями)

        for user in users:
            submission = await CheckoutSubmissionCRUD.get_today_submission(
                session, user.id, checkout_event.id
            )

            if not submission:
                not_submitted.append((user, "не сдал пересчет", None))
                continue

            # Проверка на выходной
            submitted_keywords = json.loads(submission.keywords)
            if "выходной" in submitted_keywords:
                day_off.append(user)
                continue

            reports = await CheckoutReportCRUD.get_today_reports(
                session, user.id, checkout_event.id
            )

            if not reports:
                # Пересчет сдал, но ни одного фотоотчета нет
                categories_count = len(submitted_keywords)
                not_submitted.append((user, f"не сдал отчеты ({categories_count} категорий)", submitted_keywords))
                continue

            # Проверяем, все ли сдано
            remaining = await CheckoutReportCRUD.get_remaining_keywords(
                session, user.id, checkout_event.id
            )

            if remaining:
                # Частично сдал
                remaining_count = len(remaining)
                not_submitted.append((user, f"не сдал {remaining_count} из {len(submitted_keywords)}", remaining))
                continue

            # Проверяем время сдачи последнего отчета
            last_report = max(reports, key=lambda r: r.submitted_at)
            deadline = datetime.combine(today, checkout_event.second_deadline_time)
            deadline = pytz.timezone(settings.TZ).localize(deadline)

            if last_report.submitted_at.replace(tzinfo=pytz.UTC) <= deadline:
                on_time.append(user)
            else:
                late.append((user, last_report.submitted_at))

        # Формируем статистику
        text = f"📊 <b>Статистика по событию '{checkout_event.first_keyword}'</b>\n\n"

        if on_time:
            text += "✅ <b>Сдали отчеты вовремя:</b>\n"
            for i, u in enumerate(on_time, 1):
                username = f"@{u.username}" if u.username else u.full_name
                text += f"{i}. {username}\n"
            text += "\n"

        if late:
            text += "⚠️ <b>Немного опоздали со сдачей отчетов:</b>\n"
            for i, (u, submitted_at) in enumerate(late, 1):
                username = f"@{u.username}" if u.username else u.full_name
                time_str = submitted_at.strftime('%H:%M')
                text += f"{i}. {username} (сдал в {time_str})\n"
            text += "\n"

        if day_off:
            text += "🏖 <b>Выходной день:</b>\n"
            for i, u in enumerate(day_off, 1):
                username = f"@{u.username}" if u.username else u.full_name
                text += f"{i}. {username}\n"
            text += "\n"

        if not_submitted:
            text += "❌ <b>Не сдали отчет вообще или частично:</b>\n"
            for i, (u, status, missing_categories) in enumerate(not_submitted, 1):
                username = f"@{u.username}" if u.username else u.full_name
                if missing_categories and missing_categories != "не сдал пересчет":
                    categories_str = ", ".join(missing_categories)
                    text += f"{i}. {username} [{status}] — {categories_str}\n"
                else:
                    text += f"{i}. {username} [{status}]\n"
            text += "\n"
            text += "<i>Те, которые указаны в этом списке — жду причину почему, " \
                    "остальным выражаю благодарность за вашу работу!</i>\n"
        else:
            text += "🎉 <b>Все сдали отчеты!</b>"

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

        # Статистика checkout событий (каждую минуту, т.к. время индивидуальное)
        self.scheduler.add_job(
            self.send_checkout_daily_stats,
            trigger=CronTrigger(minute="*", timezone=settings.TZ),
            id="send_checkout_daily_stats"
        )

        self.scheduler.start()
        logger.info("✅ Scheduler started with all event types support")

    def shutdown(self):
        """Остановка планировщика"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")