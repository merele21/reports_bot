import logging
from datetime import datetime, timedelta, date

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bot.config import settings
from bot.database.crud import ChannelCRUD, UserChannelCRUD, ReportCRUD, StatsCRUD
from bot.database.engine import async_session_maker
from bot.handlers.stats import send_weekly_stats
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ReportScheduler:
    """Планировщик проверки отчетов"""

    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone(settings.TZ))
        self.reminders_sent_today = set()

    async def check_deadlines(self):
        """Проверка дедлайнов и отправка напоминаний"""
        logger.info("Starting deadline check")

        self._cleanup_old_reminders()

        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)

                current_time = datetime.now(pytz.timezone(settings.TZ))
                today = current_time.date()

                for channel in channels:
                    # Пропускаем каналы без настроенных событий
                    if not channel.deadline_time or channel.deadline_time == datetime.min.time():
                        continue

                    deadline_dt = datetime.combine(today, channel.deadline_time)
                    deadline_dt = pytz.timezone(settings.TZ).localize(deadline_dt)

                    check_start = deadline_dt + timedelta(minutes=4)
                    check_end = check_start + timedelta(seconds=59)

                    if check_start <= current_time <= check_end:
                        logger.info(f"Checking deadline for channel: {channel.title}")

                        # Получаем пользователей КОНКРЕТНОГО треда
                        users = await UserChannelCRUD.get_users_by_channel(
                            session, channel.id
                        )

                        for user in users:
                            reminder_key = (user.id, channel.id, today)

                            report = await ReportCRUD.get_today_report(
                                session, user.id, channel.id
                            )

                            already_reminded = reminder_key in self.reminders_sent_today

                            if not report and not already_reminded:
                                await self.send_reminder(session, user, channel)

                                await StatsCRUD.add_reminder(
                                    session, user.id, channel.id
                                )

                                self.reminders_sent_today.add(reminder_key)

                                logger.info(
                                    f"Reminder sent: user={user.telegram_id}, "
                                    f"channel={channel.title}"
                                )

            except Exception as e:
                logger.error(f"Error in deadline check: {e}", exc_info=True)

    def _cleanup_old_reminders(self):
        """Очистить cache от старых напоминаний"""
        today = date.today()
        self.reminders_sent_today = {
            key for key in self.reminders_sent_today
            if key[2] == today
        }

    async def send_reminder(self, session: AsyncSession, user, channel):
        """Отправка напоминания пользователю в канал/топик"""
        try:
            username_mention = f"@{user.username}" if user.username else user.full_name

            reminder_text = (
                f"⚠️ {username_mention}\n\n"
                f"Напоминаю: необходимо сдать отчет!\n"
                f"Тип: {channel.report_type}\n"
                f"Ключевое слово: {channel.keyword}\n"
                f"Дедлайн: {channel.deadline_time.strftime('%H:%M')}"
            )

            if channel.thread_id:
                await self.bot.send_message(
                    chat_id=channel.telegram_id,
                    text=reminder_text,
                    message_thread_id=channel.thread_id,
                )
            else:
                await self.bot.send_message(
                    chat_id=channel.telegram_id, text=reminder_text
                )

        except Exception as e:
            logger.error(
                f"Error sending reminder to user {user.telegram_id}: {e}",
                exc_info=True,
            )

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
        logger.info(
            f"Scheduler started. Weekly stats: "
            f"{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][settings.STATS_DAY]} "
            f"at {settings.STATS_HOUR:02d}:{settings.STATS_MINUTE:02d}"
        )

    def shutdown(self):
        """Остановка планировщика"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")