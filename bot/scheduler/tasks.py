import logging
from datetime import datetime, timedelta, date

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bot.config import settings
from bot.database.crud import ChannelCRUD, UserChannelCRUD, ReportCRUD, StatsCRUD, EventCRUD
from bot.database.engine import async_session_maker
from bot.handlers.stats import send_weekly_stats
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ReportScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone(settings.TZ))
        self.reminders_sent_today = set()

    async def check_deadlines(self):
        self._cleanup_old_reminders()

        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)
                current_time = datetime.now(pytz.timezone(settings.TZ))
                today = current_time.date()

                for channel in channels:
                    # Получаем все события канала
                    events = await EventCRUD.get_active_by_channel(session, channel.id)
                    users = await UserChannelCRUD.get_users_by_channel(session, channel.id)

                    for event in events:
                        # Проверка времени дедлайна конкретного события
                        deadline_dt = datetime.combine(today, event.deadline_time)
                        deadline_dt = pytz.timezone(settings.TZ).localize(deadline_dt)

                        check_start = deadline_dt + timedelta(minutes=4)
                        check_end = check_start + timedelta(seconds=59)

                        if check_start <= current_time <= check_end:
                            for user in users:
                                # Ключ теперь включает ID события
                                reminder_key = (user.id, event.id, today)

                                report = await ReportCRUD.get_today_report(
                                    session, user.id, channel.id, event.id
                                )

                                if not report and reminder_key not in self.reminders_sent_today:
                                    await self.send_reminder(session, user, channel, event)
                                    # Статистика остается общей на канал
                                    await StatsCRUD.add_reminder(session, user.id, channel.id)
                                    self.reminders_sent_today.add(reminder_key)

            except Exception as e:
                logger.error(f"Error in deadline check: {e}", exc_info=True)

    def _cleanup_old_reminders(self):
        today = date.today()
        # Очищаем ключи не сегодняшнего дня
        self.reminders_sent_today = {k for k in self.reminders_sent_today if k[2] == today}

    async def send_reminder(self, session: AsyncSession, user, channel, event):
        try:
            username_mention = f"@{user.username}" if user.username else user.full_name
            text = (
                f"⚠️ {username_mention}\n\n"
                f"Напоминаю: необходимо сдать отчет!\n"
                f"Событие: {event.keyword}\n"
                f"Дедлайн: {event.deadline_time.strftime('%H:%M')}"
            )

            if channel.thread_id:
                await self.bot.send_message(
                    chat_id=channel.telegram_id,
                    text=text,
                    message_thread_id=channel.thread_id,
                )
            else:
                await self.bot.send_message(
                    chat_id=channel.telegram_id, text=text
                )
        except Exception as e:
            logger.error(f"Error sending reminder: {e}")

    # ... (send_weekly_stats_job и start/shutdown остаются без изменений) ...
    async def send_weekly_stats_job(self):
        """Задача для отправки еженедельной статистики"""
        logger.info("Starting weekly stats job")
        async with async_session_maker() as session:
            try:
                await send_weekly_stats(self.bot, session)
            except Exception as e:
                logger.error(f"Error in weekly stats job: {e}", exc_info=True)

    def start(self):
        """Запуск планировщика"""
        self.scheduler.add_job(
            self.check_deadlines,
            trigger=CronTrigger(minute="*", timezone=settings.TZ),
            id="check_deadlines",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self.send_weekly_stats_job,
            trigger=CronTrigger(
                day_of_week=settings.STATS_DAY,
                hour=settings.STATS_HOUR,
                minute=settings.STATS_MINUTE,
                timezone=settings.TZ,
            ),
            id="weekly_stats",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("Scheduler started.")

    def shutdown(self):
        self.scheduler.shutdown()