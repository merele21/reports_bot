from datetime import date, time
from typing import Optional, List

from bot.database.models import User, Channel, Report, Stats
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession


class UserCRUD:
    @staticmethod
    async def get_or_create(
        session: AsyncSession, telegram_id: int, username: str, full_name: str
    ) -> User:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            user = User(telegram_id=telegram_id, username=username, full_name=full_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user

    @staticmethod
    async def get_all_active(session: AsyncSession) -> List[User]:
        stmt = select(User).where(User.is_active == True)
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ChannelCRUD:
    @staticmethod
    async def create(
        session: AsyncSession,
        telegram_id: int,
        thread_id: Optional[int],
        title: str,
        report_type: str,
        keyword: str,
        deadline_time: time,
        min_photos: int = 2,
    ) -> Channel:
        channel = Channel(
            telegram_id=telegram_id,
            thread_id=thread_id,
            title=title,
            report_type=report_type,
            keyword=keyword,
            deadline_time=deadline_time,
            min_photos=min_photos,
        )
        session.add(channel)
        await session.commit()
        await session.refresh(channel)
        return channel

    @staticmethod
    async def get_by_chat_and_thread(
        session: AsyncSession, telegram_id: int, thread_id: Optional[int] = None
    ) -> Optional[Channel]:
        """получить канал по telegram_id и thread_id"""
        stmt = select(Channel).where(
            Channel.telegram_id == telegram_id, Channel.thread_id == thread_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_active(session: AsyncSession) -> List[Channel]:
        stmt = select(Channel).where(Channel.is_active == True)
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ReportCRUD:
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        channel_id: int,
        message_id: int,
        photos_count: int,
        message_text: str,
        is_valid: bool = True,
    ) -> Report:
        report = Report(
            user_id=user_id,
            channel_id=channel_id,
            message_id=message_id,
            photos_count=photos_count,
            message_text=message_text,
            is_valid=is_valid,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report

    @staticmethod
    async def get_today_report(
        session: AsyncSession, user_id: int, channel_id: int
    ) -> Optional[Report]:
        today = date.today()
        stmt = select(Report).where(
            and_(
                Report.user_id == user_id,
                Report.channel_id == channel_id,
                Report.report_date == today,
                Report.is_valid == True,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class StatsCRUD:
    @staticmethod
    async def add_reminder(
        session: AsyncSession, user_id: int, channel_id: int
    ) -> Stats:
        today = date.today()

        # Проверяем, есть ли уже запись за сегодня
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
        """Получить статистику за неделю с группировкой по пользователям"""
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
