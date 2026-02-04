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
from bot.utils.user_grouping import (
    group_users_by_display_name,
    filter_one_user_per_display_name,
    format_user_mention
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

                            # Группируем пользователей по display_name
                            user_groups = group_users_by_display_name(users)
                            
                            debtors = []
                            for group_key, group_users in user_groups.items():
                                # Проверяем, сдал ли ХОТЯ БЫ ОДИН аккаунт из группы
                                group_has_report = False
                                for u in group_users:
                                    report = await ReportCRUD.get_today_report(
                                        session, u.id, ch.id, event_id=ev.id
                                    )
                                    if report:
                                        group_has_report = True
                                        break
                                
                                # Если НИ ОДИН аккаунт из группы не сдал - добавляем первого представителя
                                if not group_has_report:
                                    debtors.append(group_users[0])

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

                            user_groups = group_users_by_display_name(users)
                            
                            debtors = []
                            for group_key, group_users in user_groups.items():
                                group_has_report = False
                                for u in group_users:
                                    report = await ReportCRUD.get_today_report(
                                        session, u.id, ch.id, temp_event_id=tev.id
                                    )
                                    if report:
                                        group_has_report = True
                                        break
                                
                                if not group_has_report:
                                    debtors.append(group_users[0])

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
        # Фильтруем должников - оставляем только одного представителя на display_name
        unique_debtors = filter_one_user_per_display_name(debtors)
        
        debt_list = [
            f"{i}. {format_user_mention(u)}"
            for i, u in enumerate(unique_debtors, 1)
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
                    user_groups = group_users_by_display_name(users)
                    
                    debtors = []
                    for group_key, group_users in user_groups.items():
                        group_has_submission = False
                        for u in group_users:
                            submission = await CheckoutSubmissionCRUD.get_today_submission(
                                session, u.id, cev.id
                            )
                            if submission:
                                group_has_submission = True
                                break
                        
                        if not group_has_submission:
                            debtors.append(group_users[0])

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
                    user_groups = group_users_by_display_name(users)
                    
                    incomplete_users = []
                    for group_key, group_users in user_groups.items():
                        # Проверяем каждый аккаунт в группе
                        group_incomplete = True
                        group_remaining = None
                        representative = None
                        
                        for u in group_users:
                            submission = await CheckoutSubmissionCRUD.get_today_submission(
                                session, u.id, cev.id
                            )
                            if not submission:
                                continue
                            
                            remaining = await CheckoutReportCRUD.get_remaining_keywords(
                                session, u.id, cev.id
                            )
                            
                            # Если хотя бы один аккаунт сдал все - группа полностью выполнила
                            if not remaining:
                                group_incomplete = False
                                break
                            
                            # Запоминаем оставшиеся ключи и представителя
                            if representative is None:
                                representative = u
                                group_remaining = remaining
                        
                        # Добавляем группу в список только если НИ ОДИН аккаунт не сдал все
                        if group_incomplete and representative and group_remaining:
                            incomplete_users.append((representative, group_remaining))

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
        unique_debtors = filter_one_user_per_display_name(debtors)
        
        debt_list = [
            f"{i}. {format_user_mention(u)}"
            for i, u in enumerate(unique_debtors, 1)
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
        # Группируем пользователей по display_name
        grouped = {}
        for u, remaining in incomplete_users:
            key = u.display_name if u.display_name else f"unique_{u.telegram_id}"
            if key not in grouped:
                grouped[key] = (u, remaining)  # Берем первого представителя группы

        debt_list = []
        for i, (u, remaining) in enumerate(grouped.values(), 1):
            username = format_user_mention(u)
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

                            user_groups = group_users_by_display_name(users)
                            
                            debtors = []
                            for group_key, group_users in user_groups.items():
                                group_has_report = False
                                for u in group_users:
                                    if await ReportCRUD.get_today_report(session, u.id, ch.id, event_id=ev.id):
                                        group_has_report = True
                                        break
                                if not group_has_report:
                                    debtors.append(group_users[0])

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

                            user_groups = group_users_by_display_name(users)
                            
                            debtors = []
                            for group_key, group_users in user_groups.items():
                                group_has_report = False
                                for u in group_users:
                                    if await ReportCRUD.get_today_report(session, u.id, ch.id, temp_event_id=tev.id):
                                        group_has_report = True
                                        break
                                if not group_has_report:
                                    debtors.append(group_users[0])

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
                    user_groups = group_users_by_display_name(users)
                    
                    debtors = []
                    for group_key, group_users in user_groups.items():
                        group_has_submission = False
                        for u in group_users:
                            submission = await CheckoutSubmissionCRUD.get_today_submission(
                                session, u.id, cev.id
                            )
                            if submission:
                                group_has_submission = True
                                break
                        if not group_has_submission:
                            debtors.append(group_users[0])

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
                    user_groups = group_users_by_display_name(users)
                    
                    incomplete_users = []
                    for group_key, group_users in user_groups.items():
                        group_incomplete = True
                        group_remaining = None
                        representative = None
                        
                        for u in group_users:
                            remaining = await CheckoutReportCRUD.get_remaining_keywords(
                                session, u.id, cev.id
                            )
                            
                            if not remaining:
                                group_incomplete = False
                                break
                            
                            if representative is None:
                                representative = u
                                group_remaining = remaining
                        
                        if group_incomplete and representative and group_remaining:
                            incomplete_users.append((representative, group_remaining))

                    if incomplete_users:
                        await self.send_checkout_second_reminder(
                            incomplete_users, channel, cev.second_keyword, cev.second_deadline_time
                        )
                        for u, _ in incomplete_users:
                            await StatsCRUD.add_reminder(session, u.id, channel.id)
                        self.checkout_reminders_sent.add(key)

    async def send_checkout_first_reminder(self, debtors, channel, keyword, deadline_time):
        """Напоминание о первом этапе checkout"""
        unique_debtors = filter_one_user_per_display_name(debtors)
        
        debt_list = [
            f"{i}. {format_user_mention(u)}"
            for i, u in enumerate(unique_debtors, 1)
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
        grouped = {}
        for u, remaining in incomplete_users:
            key = u.display_name if u.display_name else f"unique_{u.telegram_id}"
            if key not in grouped:
                grouped[key] = (u, remaining)

        debt_list = []
        for i, (u, remaining) in enumerate(grouped.values(), 1):
            username = format_user_mention(u)
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
        unique_debtors = filter_one_user_per_display_name(debtors)
        
        debt_list = [
            f"{i}. {format_user_mention(u)}"
            for i, u in enumerate(unique_debtors, 1)
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
        """Отправка статистики для конкретного checkout события"""
        users = await UserChannelCRUD.get_users_by_channel(session, channel.id)

        # Категории пользователей
        on_time = []  # Сдали вовремя
        late = []  # Немного опоздали
        not_submitted = []  # Не сдали

        user_groups = group_users_by_display_name(users)

        for group_key, group_users in user_groups.items():
            # Проверяем все аккаунты в группе
            group_status = None  # None, 'on_time', 'late', 'not_submitted'
            group_representative = group_users[0]
            latest_submission_time = None
            
            for user in group_users:
                submission = await CheckoutSubmissionCRUD.get_today_submission(
                    session, user.id, checkout_event.id
                )

                if not submission:
                    continue

                reports = await CheckoutReportCRUD.get_today_reports(
                    session, user.id, checkout_event.id
                )

                if not reports:
                    continue

                # Проверяем, все ли сдано
                remaining = await CheckoutReportCRUD.get_remaining_keywords(
                    session, user.id, checkout_event.id
                )

                if remaining:
                    continue

                # Этот аккаунт сдал все - проверяем время
                last_report = max(reports, key=lambda r: r.submitted_at)
                deadline = datetime.combine(today, checkout_event.second_deadline_time)
                deadline = pytz.timezone(settings.TZ).localize(deadline)

                submitted_time = last_report.submitted_at.astimezone(pytz.timezone(settings.TZ))

                # Обновляем статус группы на лучший
                if submitted_time <= deadline:
                    group_status = 'on_time'
                    group_representative = user
                    break  # on_time - лучший статус, можно прервать
                elif group_status != 'on_time':
                    group_status = 'late'
                    group_representative = user
                    latest_submission_time = submitted_time
            
            # Добавляем группу в соответствующую категорию
            if group_status == 'on_time':
                on_time.append(group_representative)
            elif group_status == 'late':
                late.append((group_representative, latest_submission_time))
            else:
                not_submitted.append(group_representative)

        # Формируем статистику
        text = f"📊 <b>Статистика по событию '{checkout_event.first_keyword}'</b>\n\n"

        if on_time:
            text += "✅ <b>Сдали отчеты вовремя:</b>\n"
            for i, u in enumerate(on_time, 1):
                username = format_user_mention(u)
                text += f"{i}. {username}\n"
            text += "\n"

        if late:
            text += "⚠️ <b>Немного опоздали со сдачей отчетов:</b>\n"
            for i, (u, submitted_at) in enumerate(late, 1):
                username = format_user_mention(u)
                time_str = submitted_at.strftime('%H:%M')
                text += f"{i}. {username} (сдал в {time_str})\n"
            text += "\n"

        if not_submitted:
            text += "❌ <b>До сих пор не сдали отчет (или отчеты):</b>\n"
            for i, u in enumerate(not_submitted, 1):
                username = format_user_mention(u)
                text += f"{i}. {username}\n"
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
        
        on_time = []  # Сдали вовремя
        not_submitted = []  # Не сдали
        day_offs = []  # Выходной
        
        for user in users:
            # Проверяем выходной
            dayoff = await NoTextDayOffCRUD.get_today_dayoff(session, user.id, notext_event.id)
            if dayoff:
                day_offs.append(user)
                continue
            
            # Проверяем отчет
            report = await NoTextReportCRUD.get_today_report(session, user.id, notext_event.id)
            
            if report:
                on_time.append(user)
            else:
                not_submitted.append(user)
        
        # Формируем статистику (только непустые разделы)
        text = f"📊 <b>Статистика отправки фото</b>\n\n"
        
        has_content = False
        
        if on_time:
            has_content = True
            text += "✅ <b>Сдали вовремя:</b>\n"
            for u in on_time:
                username = f"@{u.username}" if u.username else u.full_name
                text += f"- {username}\n"
            text += "\n"
        
        if not_submitted:
            has_content = True
            text += "❌ <b>Не сдали:</b>\n"
            for u in not_submitted:
                username = f"@{u.username}" if u.username else u.full_name
                text += f"- {username}\n"
            text += "\n"
        
        if day_offs:
            has_content = True
            text += "🏖 <b>Выходной:</b>\n"
            for u in day_offs:
                username = f"@{u.username}" if u.username else u.full_name
                text += f"- {username}\n"
        
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
        
        on_time = []  # Сдали вовремя
        not_submitted = []  # Не сдали
        
        for user in users:
            report = await KeywordReportCRUD.get_today_report(session, user.id, keyword_event.id)
            
            if report:
                on_time.append(user)
            else:
                not_submitted.append(user)
        
        # Формируем статистику (только непустые разделы)
        text = f"📊 <b>Статистика по ключевому слову '{keyword_event.keyword}'</b>\n\n"
        
        has_content = False
        
        if on_time:
            has_content = True
            text += "✅ <b>Сдали вовремя:</b>\n"
            for u in on_time:
                username = f"@{u.username}" if u.username else u.full_name
                text += f"- {username}\n"
            text += "\n"
        
        if not_submitted:
            has_content = True
            text += "❌ <b>Не сдали:</b>\n"
            for u in not_submitted:
                username = f"@{u.username}" if u.username else u.full_name
                text += f"- {username}\n"
        
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