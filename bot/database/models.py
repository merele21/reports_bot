from datetime import datetime, date, time as dt_time
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
    JSON, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index('ix_users_store_id', 'store_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # Примеры: "MSK-001", "SPB-042", "KRD-15"
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
    checkout_submissions: Mapped[list["CheckoutSubmission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    checkout_reports: Mapped[list["CheckoutReport"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notext_reports: Mapped[list["NoTextReport"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notext_day_offs: Mapped[list["NoTextDayOff"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    keyword_reports: Mapped[list["KeywordReport"]] = relationship(
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
    stats_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="Еженедельная статистика")

    # Relationships
    events: Mapped[list["Event"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    temp_events: Mapped[list["TempEvent"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    checkout_events: Mapped[list["CheckoutEvent"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    notext_events: Mapped[list["NoTextEvent"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    keyword_events: Mapped[list["KeywordEvent"]] = relationship(
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
    deadline_time: Mapped[dt_time] = mapped_column(Time)  # Время дедлайна
    min_photos: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    channel: Mapped["Channel"] = relationship(back_populates="events")
    reports: Mapped[list["Report"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class TempEvent(Base):
    """Временное событие, которое удаляется в 23:59 МСК"""
    __tablename__ = "temp_events"
    __table_args__ = (
        UniqueConstraint("channel_id", "keyword", "event_date", name="uix_temp_channel_keyword_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))

    keyword: Mapped[str] = mapped_column(String(100))
    deadline_time: Mapped[dt_time] = mapped_column(Time)
    min_photos: Mapped[int] = mapped_column(Integer, default=1)
    event_date: Mapped[date] = mapped_column(Date, default=date.today)  # Дата события

    # Шаблон фото
    template_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    template_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    template_phash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    channel: Mapped["Channel"] = relationship(back_populates="temp_events")
    reports: Mapped[list["Report"]] = relationship(back_populates="temp_event", cascade="all, delete-orphan")


class CheckoutEvent(Base):
    """Событие с двухэтапной проверкой (пересчет -> готово)"""
    __tablename__ = "checkout_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))

    # Первый этап (например, "Пересчет")
    first_keyword: Mapped[str] = mapped_column(String(100))
    first_deadline_time: Mapped[dt_time] = mapped_column(Time)

    # Второй этап (например, "Готово")
    second_keyword: Mapped[str] = mapped_column(String(100))
    second_deadline_time: Mapped[dt_time] = mapped_column(Time)

    min_photos: Mapped[int] = mapped_column(Integer, default=1)
    
    # Время публикации статистики (опционально, по умолчанию 22:00)
    stats_time: Mapped[Optional[dt_time]] = mapped_column(Time, nullable=True, default=lambda: dt_time(22, 0))

    # Словарь допустимых ключевых слов (JSON)
    # Пример: ["элитка", "сигареты", "тихое", "водка", ...]
    allowed_keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    channel: Mapped["Channel"] = relationship(back_populates="checkout_events")
    submissions: Mapped[list["CheckoutSubmission"]] = relationship(
        back_populates="checkout_event", cascade="all, delete-orphan"
    )
    reports: Mapped[list["CheckoutReport"]] = relationship(
        back_populates="checkout_event", cascade="all, delete-orphan"
    )


class CheckoutSubmission(Base):
    """Сохранение того, что пользователь отправил на первом этапе"""
    __tablename__ = "checkout_submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "checkout_event_id", "submission_date", name="uix_user_checkout_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    checkout_event_id: Mapped[int] = mapped_column(ForeignKey("checkout_events.id", ondelete="CASCADE"))

    submission_date: Mapped[date] = mapped_column(Date, default=date.today)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # JSON список ключевых слов, которые пользователь указал
    # Пример: ["скоропорт", "тихое", "бакалея"]
    keywords: Mapped[str] = mapped_column(Text)  # JSON array

    # Relationships
    user: Mapped["User"] = relationship(back_populates="checkout_submissions")
    checkout_event: Mapped["CheckoutEvent"] = relationship(back_populates="submissions")


class CheckoutReport(Base):
    """Отчеты на втором этапе (фото + ключевые слова)"""
    __tablename__ = "checkout_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    checkout_event_id: Mapped[int] = mapped_column(ForeignKey("checkout_events.id", ondelete="CASCADE"))

    report_date: Mapped[date] = mapped_column(Date, default=date.today)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    message_id: Mapped[int] = mapped_column(Integer)
    photos_count: Mapped[int] = mapped_column(Integer)

    # JSON список ключевых слов из этого отчета
    keywords: Mapped[str] = mapped_column(Text)  # JSON array

    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)  # Все ли сдано

    # Relationships
    user: Mapped["User"] = relationship(back_populates="checkout_reports")
    checkout_event: Mapped["CheckoutEvent"] = relationship(back_populates="reports")


class NoTextEvent(Base):
    """Событие без текста - отслеживание по времени только с фото"""
    __tablename__ = "notext_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))

    deadline_start: Mapped[dt_time] = mapped_column(Time)  # Начало отслеживания
    deadline_end: Mapped[dt_time] = mapped_column(Time)  # Конец отслеживания (строгий дедлайн)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    channel: Mapped["Channel"] = relationship(back_populates="notext_events")
    reports: Mapped[list["NoTextReport"]] = relationship(
        back_populates="notext_event", cascade="all, delete-orphan"
    )
    day_offs: Mapped[list["NoTextDayOff"]] = relationship(
        back_populates="notext_event", cascade="all, delete-orphan"
    )


class NoTextReport(Base):
    """Отчеты для notext событий"""
    __tablename__ = "notext_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "notext_event_id", "report_date", name="uix_user_notext_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    notext_event_id: Mapped[int] = mapped_column(ForeignKey("notext_events.id", ondelete="CASCADE"))

    report_date: Mapped[date] = mapped_column(Date, default=date.today)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    message_id: Mapped[int] = mapped_column(Integer)
    is_on_time: Mapped[bool] = mapped_column(Boolean, default=True)  # Сдано вовремя или нет

    # Relationships
    user: Mapped["User"] = relationship(back_populates="notext_reports")
    notext_event: Mapped["NoTextEvent"] = relationship(back_populates="reports")


class NoTextDayOff(Base):
    """Выходные дни для notext событий"""
    __tablename__ = "notext_day_offs"
    __table_args__ = (
        UniqueConstraint("user_id", "notext_event_id", "day_off_date", name="uix_user_notext_dayoff"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    notext_event_id: Mapped[int] = mapped_column(ForeignKey("notext_events.id", ondelete="CASCADE"))

    day_off_date: Mapped[date] = mapped_column(Date, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="notext_day_offs")
    notext_event: Mapped["NoTextEvent"] = relationship(back_populates="day_offs")


class KeywordEvent(Base):
    """Событие с ключевым словом (для open/close)"""
    __tablename__ = "keyword_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))

    deadline_start: Mapped[dt_time] = mapped_column(Time)  # Начало отслеживания
    deadline_end: Mapped[dt_time] = mapped_column(Time)  # Конец отслеживания
    keyword: Mapped[str] = mapped_column(String(100))  # Ключевое слово для поиска (regex)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    channel: Mapped["Channel"] = relationship(back_populates="keyword_events")
    reports: Mapped[list["KeywordReport"]] = relationship(
        back_populates="keyword_event", cascade="all, delete-orphan"
    )


class KeywordReport(Base):
    """Отчеты для keyword событий"""
    __tablename__ = "keyword_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "keyword_event_id", "report_date", name="uix_user_keyword_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    keyword_event_id: Mapped[int] = mapped_column(ForeignKey("keyword_events.id", ondelete="CASCADE"))

    report_date: Mapped[date] = mapped_column(Date, default=date.today)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    message_id: Mapped[int] = mapped_column(Integer)
    message_text: Mapped[str] = mapped_column(Text)
    is_on_time: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="keyword_reports")
    keyword_event: Mapped["KeywordEvent"] = relationship(back_populates="reports")


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
    temp_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("temp_events.id", ondelete="CASCADE"), nullable=True)

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
    event: Mapped[Optional["Event"]] = relationship(back_populates="reports")
    temp_event: Mapped[Optional["TempEvent"]] = relationship(back_populates="reports")


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