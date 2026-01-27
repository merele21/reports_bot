import logging
from datetime import datetime, timedelta, date
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bot.config import settings
from bot.database.crud import ChannelCRUD, UserChannelCRUD, ReportCRUD, StatsCRUD, EventCRUD
from bot.database.engine import async_session_maker

logger = logging.getLogger(__name__)


class ReportScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone(settings.TZ))
        self.reminders_sent_today = set()
        self.warnings_sent_today = set()  # ДЛЯ ПРЕДУПРЕЖДЕНИЙ ДО ДЕДЛАЙНА

    async def check_deadline_warnings(self):
        """
        Проверка за N минут ДО дедлайна (предупреждение)
        Запускается каждую минуту
        """
        self._cleanup_old_warnings()

        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)
                now = datetime.now(pytz.timezone(settings.TZ))
                today = now.date()

                # За сколько минут предупреждать (можно сделать настройкой)
                warning_minutes = getattr(settings, 'DEADLINE_WARNING_MINUTES', 5)

                for ch in channels:
                    events = await EventCRUD.get_active_by_channel(session, ch.id)
                    users = await UserChannelCRUD.get_users_by_channel(session, ch.id)

                    for ev in events:
                        # Время дедлайна сегодня
                        deadline = pytz.timezone(settings.TZ).localize(
                            datetime.combine(today, ev.deadline_time)
                        )

                        # Время предупреждения (за N минут до дедлайна)
                        warning_time = deadline - timedelta(minutes=warning_minutes)

                        # Проверяем, находимся ли мы в минуте предупреждения
                        # Например, если warning_time = 12:33, то срабатываем в 12:33:00-12:33:59
                        if warning_time <= now < warning_time + timedelta(minutes=1):
                            key = (ch.id, ev.id, today)
                            if key in self.warnings_sent_today:
                                continue

                            # Находим тех, кто ещё не сдал отчет
                            debtors = []
                            for u in users:
                                report = await ReportCRUD.get_today_report(
                                    session, u.id, ch.id, ev.id
                                )
                                if not report:
                                    debtors.append(u)

                            if debtors:
                                await self.send_warning_message(
                                    debtors, ch, ev, warning_minutes
                                )
                                self.warnings_sent_today.add(key)
                                logger.info(
                                    f"Warning sent for channel {ch.title}, "
                                    f"event {ev.keyword}, {len(debtors)} users"
                                )

            except Exception as e:
                logger.error(f"Error in deadline warnings check: {e}", exc_info=True)

    async def send_warning_message(self, debtors, channel, event, minutes_left):
        """
        Отправка предупреждения о приближении дедлайна
        """
        debt_list = [
            f"{i}. @{u.username}" if u.username else f"{i}. {u.full_name}"
            for i, u in enumerate(debtors, 1)
        ]

        text = (
                f"⚠️ <b>ВНИМАНИЕ! До дедлайна осталось {minutes_left} минут!</b> ⚠️\n\n"
                f"📋 Отчет: <b>{channel.title}</b>\n"
                f"🔑 Ключевое слово: <code>{event.keyword}</code>\n"
                f"⏰ Дедлайн: <b>{event.deadline_time.strftime('%H:%M')}</b>\n"
                f"📸 Минимум фото: <b>{event.min_photos}</b>\n\n"
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
                f"Warning message sent to channel {channel.telegram_id}, "
                f"thread {channel.thread_id}"
            )
        except Exception as e:
            logger.error(f"Failed to send warning message: {e}", exc_info=True)

    async def check_deadlines(self):
        """Проверка дедлайнов (каждую минуту) - ПОСЛЕ наступления"""
        self._cleanup_old_reminders()
        async with async_session_maker() as session:
            try:
                channels = await ChannelCRUD.get_all_active(session)
                now = datetime.now(pytz.timezone(settings.TZ))
                today = now.date()

                for ch in channels:
                    events = await EventCRUD.get_active_by_channel(session, ch.id)
                    users = await UserChannelCRUD.get_users_by_channel(session, ch.id)
                    for ev in events:
                        deadline = pytz.timezone(settings.TZ).localize(
                            datetime.combine(today, ev.deadline_time)
                        )
                        # Напоминание через 5 минут после дедлайна
                        if deadline + timedelta(minutes=5) <= now <= deadline + timedelta(minutes=5, seconds=59):
                            key = (ch.id, ev.id, today)
                            if key in self.reminders_sent_today:
                                continue

                            debtors = [
                                u for u in users
                                if not await ReportCRUD.get_today_report(session, u.id, ch.id, ev.id)
                            ]

                            if debtors:
                                await self.send_group_reminder(debtors, ch, ev)
                                for d in debtors:
                                    await StatsCRUD.add_reminder(session, d.id, ch.id)
                                self.reminders_sent_today.add(key)
            except Exception as e:
                logger.error(f"Error in deadline check: {e}")

    async def send_group_reminder(self, debtors, channel, event):
        """Отправка напоминания ПОСЛЕ дедлайна"""
        debt_list = [
            f"{i}. @{u.username}" if u.username else f"{i}. {u.full_name}"
            for i, u in enumerate(debtors, 1)
        ]
        text = (
                "🔴 <b>Напоминаю, что необходимо сдать отчет!</b>\n\n"
                f"Отчет: <b>{channel.title}</b>\n"
                f"Ключевое слово: <code>{event.keyword}</code>\n"
                f"Дедлайн: <b>{event.deadline_time.strftime('%H:%M')}</b>\n\n"
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

    def _cleanup_old_reminders(self):
        """Очистка кэша напоминаний в начале нового дня"""
        self.reminders_sent_today = {
            k for k in self.reminders_sent_today if k[2] == date.today()
        }

    def _cleanup_old_warnings(self):
        """Очистка кэша предупреждений в начале нового дня"""
        self.warnings_sent_today = {
            k for k in self.warnings_sent_today if k[2] == date.today()
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

        self.scheduler.start()
        logger.info("✅ Scheduler started with deadline warnings and reminders")

    def shutdown(self):
        """Остановка планировщика"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")