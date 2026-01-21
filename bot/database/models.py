from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    Date,
    Time,
    Boolean,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    reports: Mapped[list["Report"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    stats: Mapped[list["Stats"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    user_channels: Mapped[list["UserChannel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Channel(Base):
    """Канал теперь выступает только как контейнер/группа"""
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("telegram_id", "thread_id", name="uix_chat_thread"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)  # chat id
    thread_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )  # thread (topic) id
    title: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Настройки статистики (куда именно отправлять еженедельную статистику)
    stats_chat_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stats_thread_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # НОВОЕ ПОЛЕ: Заголовок статистики
    stats_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="Еженедельная статистика")

    # Relationships
    events: Mapped[list["Event"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    user_channels: Mapped[list["UserChannel"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class Event(Base):
    """Конкретное событие/тип отчета внутри канала (например, Утренний отчет)"""
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("channel_id", "keyword", name="uix_channel_keyword"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))

    keyword: Mapped[str] = mapped_column(String(100))  # Ключевое слово для поиска
    deadline_time: Mapped[datetime.time] = mapped_column(Time)  # Время дедлайна
    min_photos: Mapped[int] = mapped_column(Integer, default=1)

    # Шаблон фото
    template_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    template_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # MD5
    template_phash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Perceptual Hash

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    channel: Mapped["Channel"] = relationship(back_populates="events")
    reports: Mapped[list["Report"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class UserChannel(Base):
    """Связь пользователей с каналами"""
    __tablename__ = "user_channels"
    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uix_user_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="user_channels")
    channel: Mapped["Channel"] = relationship(back_populates="user_channels")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=True)

    report_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    message_id: Mapped[int] = mapped_column(Integer)
    photos_count: Mapped[int] = mapped_column(Integer)
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    template_validated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="reports")
    channel: Mapped["Channel"] = relationship(back_populates="reports")
    event: Mapped["Event"] = relationship(back_populates="reports")


class Stats(Base):
    __tablename__ = "stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE")
    )
    reminder_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="stats")
    channel: Mapped["Channel"] = relationship()