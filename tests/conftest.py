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
from sqlalchemy import event
from sqlalchemy.ext.asyncio import(
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import settings
from bot.database.models import Base, Channel, PhotoTemplate, Report, Stats, User, UserChannel

# --- pytest configuration ---
def pytest_configure(config):
    """configure pytest"""
    # set test environment
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory"
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
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
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
        title="Test Channel",
        report_type="report1",
        keyword="report1",
        deadline_time=time(10, 0),
        min_photos=2,
        is_active=True,
        stats_chat_id=-1001234567890,
        stats_thread_id=None,
    )
    async_session.add(channel)
    async_session.commit()
    await async_session.refresh(channel)
    return channel

@pytest.fixture
async def test_channel_with_thread(async_session: AsyncSession) -> Channel:
    """create test channel with thread"""
    channel = Channel(
        telegram_id=-1001234567890,
        thread_id=42,
        title="Test Channel - Topic 42",
        report_type="report2",
        keyword="report2",
        deadline_time=time(14, 0),
        min_photos=1,
        is_active=True,
        stats_chat_id=-1001234567890,
        stats_thread_id=50,
    )
    async_session.add(channel)
    async_session.commit()
    await async_session.refresh(channel)
    return channel

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

@pytest.fixture
async def test_report(
        async_session: AsyncSession, test_user: User, test_channel: Channel
) -> Report:
    """create test report"""
    report = Report(
        user_id=test_user.id,
        channel_id=test_channel.id,
        report_date=date.today(),
        message_id=12345,
        photos_count=2,
        message_text="Test report with keyword report1",
        is_valid=True,
        template_validated=False,
    )
    async_session.add(report)
    async_session.commit()
    await async_session.refresh(report)
    return report

@pytest.fixture
async def test_photo_template(
        async_session: AsyncSession, test_channel: Channel
) -> PhotoTemplate:
    """create test photo template"""
    template = PhotoTemplate(
        channel_id=test_channel.id,
        file_id="AgACAgIAAxkBAAI...",
        photo_hash="abc123def456",
        perceptual_hash="0123456789abcdef",
        description="Test template",
    )
    async_session.add(template)
    await async_session.commit()
    await async_session.refresh(template)
    return template

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
    bot.get_file = AsyncMock()
    return bot

@pytest.fixture
def mock_telegram_user() -> TelegramUser:
    """mock telegram user"""
    return TelegramUser(
        id=123456789,
        is_bot=False,
        first_name="Test",
        last_name="User",
        username="testuser",
        language_code="en",
    )

@pytest.fixture
def mock_chat() -> Chat:
    """mock telegram chat"""
    return Chat(
        id=-1001234567890,
        type="supergroup",
        title="Test Group",
    )

@pytest.fixture
def mock_message(mock_telegram_user: TelegramUser, mock_chat: Chat, mock_bot: Bot) -> Message:
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
    message.reply = AsyncMock()
    message.answer = AsyncMock()
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

@pytest.fixture
def mock_message_topic(mock_message: Message) -> Message:
    """mock telegram message in topic"""
    mock_message.is_topic_message = True
    mock_message.message_thread_id = 42
    return mock_message

# --- dispatcher mock ---
@pytest.fixture
def mock_dispatcher() -> Dispatcher:
    """mock aiogram dispatcher"""
    dp = MagicMock(spec=Dispatcher)
    dp.message = MagicMock()
    return dp

# --- helper fixtures ---
@pytest.fixture
def sample_photo_bytes() -> bytes:
    """sample photo data for testing"""
    # minimal valid JPEG
    return (
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c'
        b'\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c'
        b'\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00'
        b'\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\t\xff\xc4\x00\x14\x10\x01'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff'
        b'\xda\x00\x08\x01\x01\x00\x00?\x00\xd2\xcf \xff\xd9'
    )

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

# --- markers ---
def pytest_collection_modifyitems(config, items):
    """automatically mark test"""
    for item in items:
        # mark async tests
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)

        # mark by directory
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)

# --- utilities ---
class AsyncIterator:
    """helper for mocking async iterators"""
    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item