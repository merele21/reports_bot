import hashlib
from datetime import date, time
from sqlite3 import IntegrityError
from typing import Optional, List

from bot.database.models import User, Channel, Report, Stats, UserChannel, PhotoTemplate
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
        stats_chat_id: Optional[int] = None,
        stats_thread_id: Optional[int] = None,
    ) -> Channel:
        channel = Channel(
            telegram_id=telegram_id,
            thread_id=thread_id,
            title=title,
            report_type=report_type,
            keyword=keyword,
            deadline_time=deadline_time,
            min_photos=min_photos,
            stats_chat_id=stats_chat_id,
            stats_thread_id=stats_thread_id,
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

    @staticmethod
    async def update_stats_destination(
            session: AsyncSession,
            channel_id: int,
            stats_chat_id: int,
            stats_thread_id: Optional[int],
    )-> Channel:
        """Обновить место для отправки еженедельной статистики"""
        stmt = select(Channel).where(Channel.id == channel_id)
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()

        channel.stats_chat_id = stats_chat_id
        channel.thread_id = stats_thread_id

        await session.commit()
        await session.refresh(channel)
        return channel

class UserChannelCRUD:
    @staticmethod
    async def add_user_to_channel(
            session: AsyncSession, user_id: int, channel_id: int
    ) -> tuple[bool, Optional[UserChannel]]:
        """
        Добавить пользователя к каналу
        Returns: (success, user_channel or None)
        """
        try:
            user_channel = UserChannel(user_id=user_id, channel_id=channel_id)
            session.add(user_channel)
            await session.commit()
            await session.refresh(user_channel)
            return True, user_channel
        except IntegrityError:
            await session.rollback()
            return False, None

    @staticmethod
    async def in_user_in_channel(
            session: AsyncSession, user_id: int, channel_id: int
    ) -> bool:
        """ Проверить, добавлен ли пользователь в канал"""
        stmt = select(UserChannel).where(
            and_(UserChannel.user_id == user_id, UserChannel.channel_id == channel_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

class PhotoTemplateCRUD:
    @staticmethod
    async def add_template(
            session: AsyncSession,
            channel_id: int,
            file_id: str,
            photo_data: bytes,
            description: Optional[str] = None,
    ) -> PhotoTemplate:
        """Добавить шаблон фотографии"""
        # Вычисляем MD5 hash
        photo_hash = hashlib.md5(photo_data).hexdigest()

        # Вычисляем perceptual hash (требуется PIL)
        try:
            from PIL import Image
            import imagehash

            img = Image.open(io.BytesIO(photo_data))
            perceptual_hash = str(imagehash.phash(img))
        except ImportError:
            perceptual_hash = None

        template = PhotoTemplate(
            channel_id=channel_id,
            file_id=file_id,
            photo_hash=photo_hash,
            perceptual_hash=perceptual_hash,
            description=description,
        )
        session.add(template)
        await session.commit()
        await session.refresh(template)
        return template

    @staticmethod
    async def get_templates_for_channel(
            session: AsyncSession, channel_id: int
    ) -> List[PhotoTemplate]:
        """Получить все шаблоны для канала"""
        stmt = select(PhotoTemplate).where(PhotoTemplate.channel_id == channel_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def validate_photo(
            session: AsyncSession, channel_id: int, photo_data: bytes
    ) -> tuple[bool, Optional[str]]:
        """
        Проверить, соответствует ли фото шаблону
        Returns: (is_valid, error_message)
        """
        templates = await PhotoTemplateCRUD.get_templates_for_channel(
            session, channel_id
        )

        if not templates:
            # Если шаблонов нет -- фото валидно
            return True, None

        # Вычисляем hash проверяемого фото
        photo_hash = hashlib.md5(photo_data).hexdigest()

        # Точное совпадение по MD5
        for template in templates:
            if template.photo_hash == photo_hash:
                return True, None

        # Проверка по perceptual hash (если проверка доступна)
        try:
            from PIL import Image
            import imagehash

            img = Image.open(io.BytesIO(photo_data))
            photo_hash = imagehash.phash(img)

            for template in templates:
                if template.perceptual_hash:
                    template_phash = imagehash.hex_to_hash(template.perceptual_hash)
                    # Разница <= 10 считается похожим фото
                    if photo_hash - template_phash <= 10:
                        return True, None

        except ImportError:
            pass

        return False, "Фото не соответствует заданному шаблону для этого треда"


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
        template_validated: bool = False,
    ) -> Report:
        report = Report(
            user_id=user_id,
            channel_id=channel_id,
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
