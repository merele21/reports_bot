"""
Pytest configuration and fixtures
"""
import asyncio
import os
from datetime import date, datetime, time
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, User as TelegramUser
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import settings
from bot.database.models import Base, Channel, Report, User, UserChannel, Event

# --- pytest configuration ---
def pytest_configure(config):
    """configure pytest"""
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["LOG_LEVEL"] = "DEBUG"

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """create event loop for async tests"""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

# --- database fixtures ---
@pytest.fixture(scope="function")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """create test database engine"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()

@pytest.fixture(scope="function")
async def async_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """create async session for test"""
    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_maker() as session:
        yield session
        await session.rollback()

# --- model fixtures ---
@pytest.fixture
async def test_user(async_session: AsyncSession) -> User:
    """create test user"""
    user = User(
        telegram_id=123456789,
        username="testuser",
        full_name="Test User",
        is_active=True,
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)
    return user

@pytest.fixture
async def test_channel(async_session: AsyncSession) -> Channel:
    """create test channel"""
    channel = Channel(
        telegram_id=-1001234567890,
        thread_id=None,
        title="TestChannel",
        is_active=True,
        stats_chat_id=-1001234567890,
        stats_thread_id=None,
    )
    async_session.add(channel)
    await async_session.commit()
    await async_session.refresh(channel)
    return channel

@pytest.fixture
async def test_event(async_session: AsyncSession, test_channel: Channel) -> Event:
    """create test event"""
    event = Event(
        channel_id=test_channel.id,
        keyword="report1",
        deadline_time=time(10, 0),
        min_photos=2
    )
    async_session.add(event)
    await async_session.commit()
    await async_session.refresh(event)
    return event

@pytest.fixture
async def test_user_channel(
        async_session: AsyncSession, test_user: User, test_channel: Channel
) -> UserChannel:
    """create test user-channel relationship"""
    user_channel = UserChannel(user_id=test_user.id, channel_id=test_channel.id)
    async_session.add(user_channel)
    await async_session.commit()
    await async_session.refresh(user_channel)
    return user_channel

# --- telegram mocks ---
@pytest.fixture
def mock_bot() -> Mock:
    """mock telegram bot"""
    bot = MagicMock(spec=Bot)
    bot.id = 987654321
    bot.token = "123456:ABC-DEF123ghIkl-zyx57W2v1u123ew11"
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.download_file = AsyncMock()

    # Mock get_file return value
    mock_file = MagicMock()
    mock_file.file_path = "test_path"
    bot.get_file = AsyncMock(return_value=mock_file)
    return bot

@pytest.fixture
def mock_telegram_user() -> MagicMock:
    """
    Mock user as MagicMock (Mutable).
    Explicitly set strings for DB fields to avoid 'MagicMock is not supported' errors.
    """
    user = MagicMock(spec=TelegramUser)
    user.id = 123456789
    user.is_bot = False
    user.first_name = "Test"
    user.last_name = "User"
    user.username = "testuser"
    user.full_name = "Test User"  # <--- THIS WAS MISSING
    user.language_code = "en"
    return user

@pytest.fixture
def mock_chat() -> MagicMock:
    """
    Mock chat as MagicMock (Mutable) instead of Chat (Frozen Pydantic).
    This allows tests to change chat.id dynamically.
    """
    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    chat.type = "supergroup"
    chat.title = "Test Group"
    return chat

@pytest.fixture
def mock_message(mock_telegram_user: TelegramUser, mock_chat: MagicMock, mock_bot: Bot) -> Message:
    """mock telegram message"""
    message = MagicMock(spec=Message)
    message.message_id = 12345
    message.from_user = mock_telegram_user
    message.chat = mock_chat
    message.bot = mock_bot
    message.text = "/test"
    message.caption = None
    message.photo = None
    message.is_topic_message = False
    message.message_thread_id = None

    # Create a dummy message to be returned by answer/reply
    sent_message = MagicMock(spec=Message)
    sent_message.message_id = 54321

    # Configure AsyncMocks for awaitable methods
    message.reply = AsyncMock(return_value=sent_message)
    message.answer = AsyncMock(return_value=sent_message)
    message.edit_text = AsyncMock(return_value=sent_message) # Added edit_text
    message.delete = AsyncMock(return_value=True)

    return message

@pytest.fixture
def mock_message_with_photo(mock_message: Message) -> Message:
    """mock telegram message with photo"""
    photo = MagicMock()
    photo.file_id = "AgACAgIAAxkBAAI..."
    photo.file_unique_id = "AQAD..."
    photo.width = 1280
    photo.height = 720
    photo.file_size = 123456

    mock_message.photo = [photo]
    mock_message.caption = "Test caption with report1"
    return mock_message

# --- helper fixtures ---
@pytest.fixture
def mock_datetime_now(monkeypatch):
    """mock datetime.now()"""
    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 1, 18, 10, 5, 0)

        @classmethod
        def today(cls):
            return date(2024, 1, 18)

    monkeypatch.setattr("datetime.datetime", MockDatetime)
    monkeypatch.setattr("datetime.date", MockDatetime)
    return MockDatetime


@pytest.mark.asyncio
async def test_add_event(async_session, mock_message, mock_state, test_channel):
    """Test /add_event (Standard)"""
    # 1. Command
    await cmd_add_event_interactive(mock_message, mock_state)

    # FIX: Expect 54321 (the bot's reply ID), NOT 12345 (the user's message ID)
    mock_state.update_data.assert_called_with(
        command="add_event",
        prompt_message_id=54321
    )

    # 2. Input
    mock_message.text = '"Regular Check" 10:00 1'
    mock_message.chat.id = test_channel.telegram_id
    mock_state.get_data.return_value = {"command": "add_event"}

    await process_event_params_input(mock_message, mock_state, async_session)

    events = await EventCRUD.get_active_by_channel(async_session, test_channel.id)
    assert len(events) == 1
    assert events[0].keyword == "Regular Check"