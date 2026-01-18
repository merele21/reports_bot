import hashlib
import io
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
        # 1. Ищем пользователя по ID (это самый надежный идентификатор)
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        # 2. Логика "Кражи юзернейма" (если username указан и он не пустой)
        if username:
            # Ищем, занят ли этот username кем-то ДРУГИМ в базе
            stmt_check = select(User).where(
                and_(User.username == username, User.telegram_id != telegram_id)
            )
            result_check = await session.execute(stmt_check)
            other_user_with_same_username = result_check.scalars().all()

            # Если нашли других людей с этим юзернеймом — отбираем его у них
            for other in other_user_with_same_username:
                other.username = None  # Или ставим пустую строку ""
                session.add(other) # Помечаем для обновления

        if not user:
            # Создаем нового пользователя
            user = User(telegram_id=telegram_id, username=username, full_name=full_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Если пользователь найден — обновляем его данные
            if user.username != username or user.full_name != full_name:
                user.username = username
                user.full_name = full_name
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
    ) -> Channel:
        stmt = select(Channel).where(Channel.id == channel_id)
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()

        channel.stats_chat_id = stats_chat_id
        channel.stats_thread_id = stats_thread_id

        await session.commit()
        await session.refresh(channel)
        return channel

    @staticmethod
    async def update_event(
        session: AsyncSession,
        channel_id: int,
        report_type: Optional[str] = None,
        keyword: Optional[str] = None,
        deadline_time: Optional[time] = None,
        min_photos: Optional[int] = None,
    ) -> Channel:
        stmt = select(Channel).where(Channel.id == channel_id)
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()

        if not channel:
            return None

        if report_type is not None:
            channel.report_type = report_type
        if keyword is not None:
            channel.keyword = keyword
        if deadline_time is not None:
            channel.deadline_time = deadline_time
        if min_photos is not None:
            channel.min_photos = min_photos

        await session.commit()
        await session.refresh(channel)
        return channel

    @staticmethod
    async def delete_channel(session: AsyncSession, channel_id: int) -> bool:
        stmt = select(Channel).where(Channel.id == channel_id)
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()

        if not channel:
            return False

        channel.is_active = False
        await session.commit()
        return True


class UserChannelCRUD:
    @staticmethod
    async def add_user_to_channel(
        session: AsyncSession, user_id: int, channel_id: int
    ) -> tuple[bool, Optional[UserChannel]]:
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


class PhotoTemplateCRUD:
    @staticmethod
    async def add_template(
        session: AsyncSession,
        channel_id: int,
        file_id: str,
        photo_data: bytes,
        description: Optional[str] = None,
    ) -> PhotoTemplate:
        photo_hash = hashlib.md5(photo_data).hexdigest()

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
        stmt = select(PhotoTemplate).where(PhotoTemplate.channel_id == channel_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def validate_photo(
        session: AsyncSession, channel_id: int, photo_data: bytes
    ) -> tuple[bool, Optional[str]]:
        templates = await PhotoTemplateCRUD.get_templates_for_channel(
            session, channel_id
        )

        if not templates:
            return True, None

        photo_hash = hashlib.md5(photo_data).hexdigest()

        for template in templates:
            if template.photo_hash == photo_hash:
                return True, None

        try:
            from PIL import Image
            import imagehash

            img = Image.open(io.BytesIO(photo_data))
            photo_phash = imagehash.phash(img)

            for template in templates:
                if template.perceptual_hash:
                    template_phash = imagehash.hex_to_hash(template.perceptual_hash)
                    if photo_phash - template_phash <= 10:
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