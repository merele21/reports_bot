import hashlib
import io
import json
import re
from datetime import date, time
from sqlalchemy.exc import IntegrityError
from typing import Optional, List

from bot.database.models import (
    User, Channel, Event, TempEvent, CheckoutEvent,
    Report, Stats, UserChannel, CheckoutSubmission, CheckoutReport,
    NoTextEvent, NoTextReport, NoTextDayOff, KeywordEvent, KeywordReport
)
from sqlalchemy import select, func, and_, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

# Словарь допустимых ключевых слов для checkout событий
ALLOWED_CHECKOUT_KEYWORDS = [
    "элитка", "сигареты", "тихое", "водка", "пиво", "игристое",
    "коктейли", "скоропорт", "сопутка", "вода", "энергетики",
    "бакалея", "мороженое", "шоколад", "нонфуд", "штучки"
]


def normalize_keyword(keyword: str) -> str:
    """
    Нормализация ключевого слова:
    - приведение к нижнему регистру
    - удаление лишних пробелов
    """
    return re.sub(r'\s+', '', keyword.lower().strip())


def extract_keywords_from_text(text: str, reference_keyword: str) -> bool:
    """
    Проверка наличия ключевого слова в тексте с нормализацией

    Args:
        text: текст сообщения
        reference_keyword: эталонное ключевое слово

    Returns:
        bool: найдено ли ключевое слово
    """
    normalized_text = normalize_keyword(text)
    normalized_reference = normalize_keyword(reference_keyword)
    return normalized_reference in normalized_text


def parse_checkout_keywords(text: str) -> List[str]:
    """
    Парсинг ключевых слов из текста для checkout событий
    Поддерживает разделители: +, /, пробел

    Args:
        text: текст вида "скоропорт+вино" или "элитка / тихое"

    Returns:
        список нормализованных ключевых слов
    """
    # Разделяем по +, /, пробелу
    words = re.split(r'[+/\s]+', text.lower().strip())

    # Фильтруем только разрешенные слова
    result = []
    for word in words:
        word_clean = word.strip()
        if word_clean in ALLOWED_CHECKOUT_KEYWORDS:
            result.append(word_clean)

    return result


class UserCRUD:
    @staticmethod
    async def get_or_create(
            session: AsyncSession,
            telegram_id: int,
            username: Optional[str] = None,
            full_name: Optional[str] = None,
            store_id: Optional[str] = None
    ) -> User:
        """
        Создает или обновляет пользователя

        Args:
            telegram_id: Обязательный Telegram ID
            username: Опциональный username
            full_name: Опциональный полное имя
            store_id: Опциональный ID магазина (например, "MSK-001")
        """

        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if username:
            stmt_check = select(User).where(
                and_(User.username == username, User.telegram_id != telegram_id)
            )
            result_check = await session.execute(stmt_check)
            other_users = result_check.scalars().all()
            for other in other_users:
                other.username = None
                session.add(other)

        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username or None,
                full_name=full_name or None,
                store_id=store_id or None
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Обновляем только если данные изменились
            updated = False

            if user.username != username:
                user.username = username
                updated = True

            if user.full_name != full_name:
                user.full_name = full_name
                updated = True

            if store_id and user.store_id != store_id:
                user.store_id = store_id
                updated = True

            if updated:
                session.add(user)
                await session.commit()
                await session.refresh(user)

        return user

    @staticmethod
    async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_store_id(
            session: AsyncSession,
            store_id: str
    ) -> List[User]:
        """Получить всех пользователей магазина"""
        stmt = select(User).where(
            User.store_id == store_id,
            User.is_active == True
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ChannelCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            telegram_id: int,
            thread_id: Optional[int],
            title: str,
    ) -> Channel:
        stmt = select(Channel).where(
            Channel.telegram_id == telegram_id,
            Channel.thread_id == thread_id
        )
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()

        if channel:
            channel.title = title
            channel.is_active = True
        else:
            channel = Channel(
                telegram_id=telegram_id, thread_id=thread_id,
                title=title, is_active=True
            )
            session.add(channel)

        await session.commit()
        await session.refresh(channel)
        return channel

    @staticmethod
    async def get_by_chat_and_thread(
            session: AsyncSession, telegram_id: int, thread_id: Optional[int] = None
    ) -> Optional[Channel]:
        stmt = select(Channel).where(
            Channel.telegram_id == telegram_id,
            Channel.thread_id == thread_id,
            Channel.is_active == True
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_active(session: AsyncSession) -> List[Channel]:
        stmt = select(Channel).where(Channel.is_active == True)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete_channel(session: AsyncSession, channel_id: int) -> bool:
        stmt = select(Channel).where(Channel.id == channel_id)
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()
        if not channel:
            return False
        await session.delete(channel)
        await session.commit()
        return True

    @staticmethod
    async def update_stats_destination(
            session: AsyncSession,
            channel_id: int,
            stats_chat_id: int,
            stats_thread_id: Optional[int],
            stats_title: str
    ) -> Channel:
        stmt = select(Channel).where(Channel.id == channel_id)
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()
        if channel:
            channel.stats_chat_id = stats_chat_id
            channel.stats_thread_id = stats_thread_id
            channel.stats_title = stats_title
            await session.commit()
            await session.refresh(channel)
        return channel


class EventCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            channel_id: int,
            keyword: str,
            deadline_time: time,
            min_photos: int = 1
    ) -> Event:
        event = Event(
            channel_id=channel_id,
            keyword=keyword,
            deadline_time=deadline_time,
            min_photos=min_photos
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    @staticmethod
    async def get_active_by_channel(session: AsyncSession, channel_id: int) -> List[Event]:
        stmt = select(Event).where(Event.channel_id == channel_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete(session: AsyncSession, event_id: int) -> bool:
        stmt = select(Event).where(Event.id == event_id)
        result = await session.execute(stmt)
        event = result.scalar_one_or_none()
        if event:
            await session.delete(event)
            await session.commit()
            return True
        return False

class TempEventCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            channel_id: int,
            keyword: str,
            deadline_time: time,
            event_date: date,
            min_photos: int = 1
    ) -> TempEvent:
        temp_event = TempEvent(
            channel_id=channel_id,
            keyword=keyword,
            deadline_time=deadline_time,
            event_date=event_date,
            min_photos=min_photos
        )
        session.add(temp_event)
        await session.commit()
        await session.refresh(temp_event)
        return temp_event

    @staticmethod
    async def get_active_by_channel_and_date(
            session: AsyncSession, channel_id: int, event_date: date
    ) -> List[TempEvent]:
        stmt = select(TempEvent).where(
            TempEvent.channel_id == channel_id,
            TempEvent.event_date == event_date
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete_old_events(session: AsyncSession, before_date: date) -> int:
        """Удаление временных событий старше указанной даты"""
        stmt = select(TempEvent).where(TempEvent.event_date < before_date)
        result = await session.execute(stmt)
        old_events = result.scalars().all()

        count = len(old_events)
        for event in old_events:
            await session.delete(event)

        await session.commit()
        return count

    @staticmethod
    async def delete(session: AsyncSession, temp_event_id: int) -> bool:
        """Удаление конкретного временного события"""
        stmt = select(TempEvent).where(TempEvent.id == temp_event_id)
        result = await session.execute(stmt)
        temp_event = result.scalar_one_or_none()
        if temp_event:
            await session.delete(temp_event)
            await session.commit()
            return True
        return False


class CheckoutEventCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            channel_id: int,
            first_keyword: str,
            first_deadline_time: time,
            second_keyword: str,
            second_deadline_time: time,
            min_photos: int = 1,
            stats_time: Optional[time] = None
    ) -> CheckoutEvent:
        if stats_time is None:
            stats_time = time(22, 0)  # По умолчанию 22:00
        
        checkout_event = CheckoutEvent(
            channel_id=channel_id,
            first_keyword=first_keyword,
            first_deadline_time=first_deadline_time,
            second_keyword=second_keyword,
            second_deadline_time=second_deadline_time,
            min_photos=min_photos,
            stats_time=stats_time,
            allowed_keywords=json.dumps(ALLOWED_CHECKOUT_KEYWORDS)
        )
        session.add(checkout_event)
        await session.commit()
        await session.refresh(checkout_event)
        return checkout_event

    @staticmethod
    async def get_active_by_channel(session: AsyncSession, channel_id: int) -> List[CheckoutEvent]:
        stmt = select(CheckoutEvent).where(CheckoutEvent.channel_id == channel_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete(session: AsyncSession, event_id: int) -> bool:
        stmt = select(CheckoutEvent).where(CheckoutEvent.id == event_id)
        result = await session.execute(stmt)
        event = result.scalar_one_or_none()
        if event:
            await session.delete(event)
            await session.commit()
            return True
        return False


class CheckoutSubmissionCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            user_id: int,
            checkout_event_id: int,
            keywords: List[str],
            submission_date: date = None
    ) -> CheckoutSubmission:
        if submission_date is None:
            submission_date = date.today()

        submission = CheckoutSubmission(
            user_id=user_id,
            checkout_event_id=checkout_event_id,
            submission_date=submission_date,
            keywords=json.dumps(keywords)
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        return submission

    @staticmethod
    async def get_today_submission(
            session: AsyncSession, user_id: int, checkout_event_id: int
    ) -> Optional[CheckoutSubmission]:
        today = date.today()
        stmt = select(CheckoutSubmission).where(
            CheckoutSubmission.user_id == user_id,
            CheckoutSubmission.checkout_event_id == checkout_event_id,
            CheckoutSubmission.submission_date == today
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_today_submissions(
            session: AsyncSession, checkout_event_id: int
    ) -> List[CheckoutSubmission]:
        today = date.today()
        stmt = select(CheckoutSubmission).where(
            CheckoutSubmission.checkout_event_id == checkout_event_id,
            CheckoutSubmission.submission_date == today
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class CheckoutReportCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            user_id: int,
            checkout_event_id: int,
            message_id: int,
            photos_count: int,
            keywords: List[str],
            is_complete: bool = False
    ) -> CheckoutReport:
        report = CheckoutReport(
            user_id=user_id,
            checkout_event_id=checkout_event_id,
            message_id=message_id,
            photos_count=photos_count,
            keywords=json.dumps(keywords),
            is_complete=is_complete
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report

    @staticmethod
    async def get_today_reports(
            session: AsyncSession, user_id: int, checkout_event_id: int
    ) -> List[CheckoutReport]:
        today = date.today()
        stmt = select(CheckoutReport).where(
            CheckoutReport.user_id == user_id,
            CheckoutReport.checkout_event_id == checkout_event_id,
            CheckoutReport.report_date == today
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_all_today_reports(
            session: AsyncSession, checkout_event_id: int
    ) -> List[CheckoutReport]:
        today = date.today()
        stmt = select(CheckoutReport).where(
            CheckoutReport.checkout_event_id == checkout_event_id,
            CheckoutReport.report_date == today
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_remaining_keywords(
            session: AsyncSession, user_id: int, checkout_event_id: int
    ) -> List[str]:
        """Получить оставшиеся не сданные ключевые слова для пользователя"""
        submission = await CheckoutSubmissionCRUD.get_today_submission(
            session, user_id, checkout_event_id
        )
        if not submission:
            return []

        submitted_keywords = set(json.loads(submission.keywords))

        # Получаем все уже сданные отчеты
        reports = await CheckoutReportCRUD.get_today_reports(
            session, user_id, checkout_event_id
        )

        reported_keywords = set()
        for report in reports:
            reported_keywords.update(json.loads(report.keywords))

        # Возвращаем разницу
        remaining = submitted_keywords - reported_keywords
        return list(remaining)


class UserChannelCRUD:
    @staticmethod
    async def add_user_to_channel(
            session: AsyncSession, user_id: int, channel_id: int
    ) -> tuple[bool, Optional[UserChannel]]:
        try:
            user_channel = UserChannel(user_id=user_id, channel_id=channel_id)
            session.add(user_channel)
            await session.commit()
            return True, user_channel
        except IntegrityError:
            await session.rollback()
            return False, None

    @staticmethod
    async def in_user_in_channel(
            session: AsyncSession, user_id: int, channel_id: int
    ) -> bool:
        stmt = select(UserChannel).where(
            and_(UserChannel.user_id == user_id, UserChannel.channel_id == channel_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_users_by_channel(
            session: AsyncSession, channel_id: int
    ) -> List[User]:
        stmt = (
            select(User)
            .join(UserChannel, UserChannel.user_id == User.id)
            .where(
                and_(
                    UserChannel.channel_id == channel_id,
                    User.is_active == True
                )
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def remove_user_from_channel(
            session: AsyncSession, user_id: int, channel_id: int
    ) -> bool:
        stmt = select(UserChannel).where(
            and_(UserChannel.user_id == user_id, UserChannel.channel_id == channel_id)
        )
        result = await session.execute(stmt)
        user_channel = result.scalar_one_or_none()
        if not user_channel:
            return False
        await session.delete(user_channel)
        await session.commit()
        return True


class ReportCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            user_id: int,
            channel_id: int,
            event_id: Optional[int] = None,
            temp_event_id: Optional[int] = None,
            message_id: int = 0,
            photos_count: int = 0,
            message_text: str = "",
            is_valid: bool = True,
            template_validated: bool = False,
    ) -> Report:
        report = Report(
            user_id=user_id,
            channel_id=channel_id,
            event_id=event_id,
            temp_event_id=temp_event_id,
            message_id=message_id,
            photos_count=photos_count,
            message_text=message_text,
            is_valid=is_valid,
            template_validated=template_validated,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report

    @staticmethod
    async def get_today_report(
            session: AsyncSession,
            user_id: int,
            channel_id: int,
            event_id: Optional[int] = None,
            temp_event_id: Optional[int] = None
    ) -> Optional[Report]:
        today = date.today()

        conditions = [
            Report.user_id == user_id,
            Report.channel_id == channel_id,
            Report.report_date == today,
            Report.is_valid == True,
        ]

        if event_id is not None:
            conditions.append(Report.event_id == event_id)
        if temp_event_id is not None:
            conditions.append(Report.temp_event_id == temp_event_id)

        stmt = select(Report).where(and_(*conditions))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class StatsCRUD:
    @staticmethod
    async def add_reminder(
            session: AsyncSession, user_id: int, channel_id: int
    ) -> Stats:
        today = date.today()
        stmt = select(Stats).where(
            and_(
                Stats.user_id == user_id,
                Stats.channel_id == channel_id,
                Stats.reminder_date == today,
            )
        )
        result = await session.execute(stmt)
        stat = result.scalar_one_or_none()

        if stat:
            stat.reminder_count += 1
        else:
            stat = Stats(user_id=user_id, channel_id=channel_id, reminder_date=today)
            session.add(stat)

        await session.commit()
        await session.refresh(stat)
        return stat

    @staticmethod
    async def get_weekly_stats(session: AsyncSession) -> List[dict]:
        from datetime import timedelta
        week_ago = date.today() - timedelta(days=7)
        stmt = (
            select(
                User.telegram_id,
                User.full_name,
                User.username,
                func.sum(Stats.reminder_count).label("total_reminders"),
            )
            .join(Stats.user)
            .where(Stats.reminder_date >= week_ago)
            .group_by(User.id, User.telegram_id, User.full_name, User.username)
            .order_by(desc("total_reminders"))
        )
        result = await session.execute(stmt)
        return [
            {
                "telegram_id": row.telegram_id,
                "full_name": row.full_name,
                "username": row.username,
                "total_reminders": row.total_reminders,
            }
            for row in result.all()
        ]


class NoTextEventCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            channel_id: int,
            deadline_start: time,
            deadline_end: time
    ) -> NoTextEvent:
        event = NoTextEvent(
            channel_id=channel_id,
            deadline_start=deadline_start,
            deadline_end=deadline_end
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    @staticmethod
    async def get_active_by_channel(session: AsyncSession, channel_id: int) -> List[NoTextEvent]:
        stmt = select(NoTextEvent).where(NoTextEvent.channel_id == channel_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete(session: AsyncSession, event_id: int):
        stmt = select(NoTextEvent).where(NoTextEvent.id == event_id)
        result = await session.execute(stmt)
        event = result.scalar_one_or_none()
        if event:
            await session.delete(event)
            await session.commit()


class NoTextReportCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            user_id: int,
            notext_event_id: int,
            message_id: int,
            is_on_time: bool = True
    ) -> NoTextReport:
        report = NoTextReport(
            user_id=user_id,
            notext_event_id=notext_event_id,
            message_id=message_id,
            is_on_time=is_on_time
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report

    @staticmethod
    async def get_today_report(
            session: AsyncSession,
            user_id: int,
            notext_event_id: int
    ) -> Optional[NoTextReport]:
        today = date.today()
        stmt = select(NoTextReport).where(
            and_(
                NoTextReport.user_id == user_id,
                NoTextReport.notext_event_id == notext_event_id,
                NoTextReport.report_date == today
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_reports_by_event_and_date(
            session: AsyncSession,
            notext_event_id: int,
            report_date: date
    ) -> List[NoTextReport]:
        stmt = select(NoTextReport).where(
            and_(
                NoTextReport.notext_event_id == notext_event_id,
                NoTextReport.report_date == report_date
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class NoTextDayOffCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            user_id: int,
            notext_event_id: int,
            day_off_date: date
    ) -> NoTextDayOff:
        day_off = NoTextDayOff(
            user_id=user_id,
            notext_event_id=notext_event_id,
            day_off_date=day_off_date
        )
        session.add(day_off)
        await session.commit()
        await session.refresh(day_off)
        return day_off

    @staticmethod
    async def get_today_dayoff(
            session: AsyncSession,
            user_id: int,
            notext_event_id: int
    ) -> Optional[NoTextDayOff]:
        today = date.today()
        stmt = select(NoTextDayOff).where(
            and_(
                NoTextDayOff.user_id == user_id,
                NoTextDayOff.notext_event_id == notext_event_id,
                NoTextDayOff.day_off_date == today
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_dayoffs_by_event_and_date(
            session: AsyncSession,
            notext_event_id: int,
            day_off_date: date
    ) -> List[NoTextDayOff]:
        stmt = select(NoTextDayOff).where(
            and_(
                NoTextDayOff.notext_event_id == notext_event_id,
                NoTextDayOff.day_off_date == day_off_date
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class KeywordEventCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            channel_id: int,
            deadline_start: time,
            deadline_end: time,
            keyword: str,
            reference_photo_file_id: Optional[str] = None,  # NEW
            reference_photo_description: Optional[str] = None  # NEW
    ) -> KeywordEvent:
        """
        Create keyword event with optional reference photo

        Args:
            session: Database session
            channel_id: Channel ID
            deadline_start: Start time for tracking
            deadline_end: End time for tracking (when stats are published)
            keyword: Keyword to search for (supports regex)
            reference_photo_file_id: Optional Telegram file_id of reference photo
            reference_photo_description: Optional description of the reference photo

        Returns:
            Created KeywordEvent
        """
        event = KeywordEvent(
            channel_id=channel_id,
            deadline_start=deadline_start,
            deadline_end=deadline_end,
            keyword=keyword,
            reference_photo_file_id=reference_photo_file_id,
            reference_photo_description=reference_photo_description
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    @staticmethod
    async def get_active_by_channel(session: AsyncSession, channel_id: int) -> List[KeywordEvent]:
        stmt = select(KeywordEvent).where(KeywordEvent.channel_id == channel_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete(session: AsyncSession, event_id: int):
        stmt = select(KeywordEvent).where(KeywordEvent.id == event_id)
        result = await session.execute(stmt)
        event = result.scalar_one_or_none()
        if event:
            await session.delete(event)
            await session.commit()


class KeywordReportCRUD:
    @staticmethod
    async def create(
            session: AsyncSession,
            user_id: int,
            keyword_event_id: int,
            message_id: int,
            message_text: str,
            is_on_time: bool = True
    ) -> KeywordReport:
        report = KeywordReport(
            user_id=user_id,
            keyword_event_id=keyword_event_id,
            message_id=message_id,
            message_text=message_text,
            is_on_time=is_on_time
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report

    @staticmethod
    async def get_today_report(
            session: AsyncSession,
            user_id: int,
            keyword_event_id: int
    ) -> Optional[KeywordReport]:
        today = date.today()
        stmt = select(KeywordReport).where(
            and_(
                KeywordReport.user_id == user_id,
                KeywordReport.keyword_event_id == keyword_event_id,
                KeywordReport.report_date == today
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_reports_by_event_and_date(
            session: AsyncSession,
            keyword_event_id: int,
            report_date: date
    ) -> List[KeywordReport]:
        stmt = select(KeywordReport).where(
            and_(
                KeywordReport.keyword_event_id == keyword_event_id,
                KeywordReport.report_date == report_date
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


def match_keyword_regex(text: str, keyword: str) -> bool:
    """
    Проверка текста на соответствие ключевому слову с поддержкой regex
    Позволяет добавить до 5 любых символов после ключевого слова
    
    Args:
        text: текст сообщения
        keyword: базовое ключевое слово
    
    Returns:
        bool: найдено ли совпадение
    """
    # Создаем паттерн: ключевое слово + до 5 любых букв
    # Используем \b для границы слова
    pattern = re.compile(rf'\b{re.escape(keyword)}\w{{0,5}}\b', re.IGNORECASE)
    return bool(pattern.search(text))