from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from bot.config import settings
from bot.database.engine import async_session_maker
from bot.database.crud import ChannelCRUD, UserCRUD, ReportCRUD, StatsCRUD
from bot.handlers.stats import send_weekly_stats
import logging
import pytz

logger = logging.getLogger(__name__)


class ReportScheduler:
    """Планировщик проверки отчетов"""

    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone(settings.TZ))

    async def check_deadlines(self):
        """Проверка дедлайнов и отправка напоминаний"""
        logger.info("Starting deadline check")

        async with async_session_maker() as session:
            try:
                # Получаем все активные каналы
                channels = await ChannelCRUD.get_all_active(session)

                # Получаем всех активных пользователей
                users = await UserCRUD.get_all_active(session)

                current_time = datetime.now(pytz.timezone(settings.TZ)).time()

                for channel in channels:
                    # Проверяем, наступил ли дедлайн
                    if current_time >= channel.deadline_time:
                        logger.info(f"Checking deadline for channel: {channel.title}")

                        # Проверяем каждого пользователя
                        for user in users:
                            # Проверяем, сдан ли отчет
                            report = await ReportCRUD.get_today_report(
                                session,
                                user.id,
                                channel.id
                            )

                            if not report:
                                # Отчет не сдан - отправляем напоминание
                                await self.send_reminder(
                                    session,
                                    user,
                                    channel
                                )

                                # Записываем статистику
                                await StatsCRUD.add_reminder(
                                    session,
                                    user.id,
                                    channel.id
                                )

                                logger.info(
                                    f"Reminder sent: user={user.telegram_id}, "
                                    f"channel={channel.title}"
                                )

            except Exception as e:
                logger.error(f"Error in deadline check: {e}", exc_info=True)

    async def send_reminder(self, session: AsyncSession, user, channel):
        """Отправка напоминания пользователю в канал"""
        try:
            # Формируем текст напоминания
            username_mention = f"@{user.username}" if user.username else user.full_name

            reminder_text = (
                f"⚠️ {username_mention}\n\n"
                f"Напоминаю: необходимо сдать отчет!\n"
                f"Тип: {channel.report_type}\n"
                f"Ключевое слово: {channel.keyword}\n"
                f"Минимум фото: {channel.min_photos}\n"
                f"Дедлайн: {channel.deadline_time.strftime('%H:%M')}"
            )

            # Отправляем в канал
            await self.bot.send_message(
                chat_id=channel.telegram_id,
                text=reminder_text
            )

        except Exception as e:
            logger.error(
                f"Error sending reminder to user {user.telegram_id} "
                f"in channel {channel.telegram_id}: {e}",
                exc_info=True
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
        # Проверка дедлайнов каждую минуту
        self.scheduler.add_job(
            self.check_deadlines,
            trigger=CronTrigger(minute="*", timezone=settings.TZ),
            id="check_deadlines",
            replace_existing=True
        )

        # Еженедельная статистика
        self.scheduler.add_job(
            self.send_weekly_stats_job,
            trigger=CronTrigger(
                day_of_week=settings.STATS_DAY,
                hour=settings.STATS_HOUR,
                minute=settings.STATS_MINUTE,
                timezone=settings.TZ
            ),
            id="weekly_stats",
            replace_existing=True
        )

        self.scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self):
        """Остановка планировщика"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")