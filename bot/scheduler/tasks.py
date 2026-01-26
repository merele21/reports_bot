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


    async def check_deadlines(self):
        """Проверка дедлайнов (каждую минуту)"""
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
                        deadline = pytz.timezone(settings.TZ).localize(datetime.combine(today, ev.deadline_time))
                        # Напоминание через 5 минуты после дедлайна
                        if deadline + timedelta(minutes=5) <= now <= deadline + timedelta(minutes=5):
                            key = (ch.id, ev.id, today)
                            if key in self.reminders_sent_today: continue

                            debtors = [u for u in users if not await ReportCRUD.get_today_report(session, u.id, ch.id, ev.id)]
                            if debtors:
                                await self.send_group_reminder(debtors, ch, ev)
                                for d in debtors: await StatsCRUD.add_reminder(session, d.id, ch.id)
                                self.reminders_sent_today.add(key)
            except Exception as e:
                logger.error(f"Error in deadline check: {e}")

    async def send_group_reminder(self, debtors, channel, event):
        debt_list = [f"{i}. @{u.username}" if u.username else f"{i}. {u.full_name}" for i, u in enumerate(debtors, 1)]
        text = (
            "<b>Напоминаю, что необходимо сдать отчет!</b>\n\n"
            f"Отчет: <b>{channel.title}</b>\n"
            f"Ключевое слово: <code>{event.keyword}</code>\n"
            f"Дедлайн: <b>{event.deadline_time.strftime('%H:%M')}</b>\n\n"
            f"<b>Список, которые до сих пор не успели:</b>\n" + "\n".join(debt_list)
        )
        try:
            await self.bot.send_message(chat_id=channel.telegram_id, text=text, message_thread_id=channel.thread_id)
        except Exception as e:
            logger.error(f"Reminder failed: {e}")

    def _cleanup_old_reminders(self):
        self.reminders_sent_today = {k for k in self.reminders_sent_today if k[2] == date.today()}

    def start(self):
        self.scheduler.add_job(self.check_deadlines, trigger=CronTrigger(minute="*", timezone=settings.TZ), id="check_deadlines")
        self.scheduler.start()

    def shutdown(self):
        self.scheduler.shutdown()