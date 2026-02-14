import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from datetime import time, date

from bot.database.models import User, Channel, Event, TempEvent, CheckoutEvent, NoTextEvent, KeywordEvent
from bot.database.crud import UserCRUD, ChannelCRUD, EventCRUD, UserChannelCRUD, TempEventCRUD, CheckoutEventCRUD, \
    NoTextEventCRUD, KeywordEventCRUD
from bot.handlers.admin.commands_fsm import (
    process_register_no_store, process_register_with_store, process_store_id_input,
    cmd_add_user_interactive, process_add_user_input,
    cmd_add_users_interactive, process_add_users_input,
    cmd_add_users_by_store_interactive, process_add_users_by_store_input,
    cmd_rm_user_interactive, process_rm_user_input,
    cmd_rm_users_interactive, process_rm_users_input,
    cmd_add_channel_interactive, process_add_channel_input,
    cmd_rm_channel_interactive, process_rm_channel_input,
    cmd_add_event_interactive, process_event_params_input,
    cmd_add_tmp_event_interactive, cmd_add_event_checkout_interactive,
    cmd_add_event_notext_interactive, cmd_add_event_kw_interactive,
    cmd_set_wstat_interactive, process_set_wstat_input
)
from bot.handlers.admin.commands_fsm import (
    RegisterStates, AddUserStates, RemoveUserStates,
    AddChannelStates, RemoveChannelStates, AddEventStates, SetWstatStates
)


@pytest.fixture
def mock_state():
    state = AsyncMock(spec=FSMContext)
    state.get_data.return_value = {}
    return state


@pytest.fixture(autouse=True)
def mock_is_admin():
    with patch("bot.handlers.admin.commands_fsm.is_admin", return_value=True):
        yield


# === REGISTRATION ===

@pytest.mark.asyncio
async def test_register_no_store(async_session, mock_message, mock_state):
    callback = MagicMock()
    callback.from_user.id = 12345
    callback.from_user.username = "new_user"
    callback.from_user.full_name = "New User"
    callback.message = mock_message
    callback.answer = AsyncMock()

    await process_register_no_store(callback, mock_state, async_session)

    user = await UserCRUD.get_by_telegram_id(async_session, 12345)
    assert user is not None
    assert user.store_id is None


@pytest.mark.asyncio
async def test_register_with_store(async_session, mock_message, mock_state):
    callback = MagicMock()
    callback.message = mock_message
    callback.answer = AsyncMock()

    await process_register_with_store(callback, mock_state)
    mock_state.set_state.assert_called_with(RegisterStates.waiting_for_store_id)

    mock_message.text = "MSK-001"
    mock_message.from_user.id = 999
    mock_message.from_user.username = "store_user"
    mock_message.from_user.full_name = "Store User"

    await process_store_id_input(mock_message, mock_state, async_session)

    user = await UserCRUD.get_by_telegram_id(async_session, 999)
    assert user.store_id == "MSK-001"


# === USER MANAGEMENT ===

@pytest.mark.asyncio
async def test_add_user(async_session, mock_message, mock_state, test_channel, test_user):
    await cmd_add_user_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(AddUserStates.waiting_for_user)

    mock_message.text = f"@{test_user.username}"
    mock_message.chat.id = test_channel.telegram_id

    await process_add_user_input(mock_message, mock_state, async_session)
    assert await UserChannelCRUD.in_user_in_channel(async_session, test_user.id, test_channel.id)


@pytest.mark.asyncio
async def test_add_users_batch(async_session, mock_message, mock_state, test_channel):
    u1 = User(telegram_id=11, username="u1", full_name="U1")
    u2 = User(telegram_id=22, username="u2", full_name="U2")
    async_session.add_all([u1, u2])
    await async_session.commit()

    await cmd_add_users_interactive(mock_message, mock_state)

    mock_state.set_state.assert_called_with(AddUserStates.waiting_for_users)

    mock_message.text = "@u1 @u2"
    mock_message.chat.id = test_channel.telegram_id

    await process_add_users_input(mock_message, mock_state, async_session)

    assert await UserChannelCRUD.in_user_in_channel(async_session, u1.id, test_channel.id)
    assert await UserChannelCRUD.in_user_in_channel(async_session, u2.id, test_channel.id)


@pytest.mark.asyncio
async def test_add_users_by_store(async_session, mock_message, mock_state, test_channel):
    u1 = User(telegram_id=10, store_id="STORE-1", full_name="U1")
    u2 = User(telegram_id=11, store_id="STORE-1", full_name="U2")
    async_session.add_all([u1, u2])
    await async_session.commit()

    await cmd_add_users_by_store_interactive(mock_message, mock_state)

    mock_message.text = "STORE-1"
    mock_message.chat.id = test_channel.telegram_id
    await process_add_users_by_store_input(mock_message, mock_state, async_session)

    assert await UserChannelCRUD.in_user_in_channel(async_session, u1.id, test_channel.id)
    assert await UserChannelCRUD.in_user_in_channel(async_session, u2.id, test_channel.id)


@pytest.mark.asyncio
async def test_rm_user(async_session, mock_message, mock_state, test_channel, test_user):
    await UserChannelCRUD.add_user_to_channel(async_session, test_user.id, test_channel.id)

    await cmd_rm_user_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(RemoveUserStates.waiting_for_user)

    mock_message.text = f"@{test_user.username}"
    mock_message.chat.id = test_channel.telegram_id
    await process_rm_user_input(mock_message, mock_state, async_session)

    assert not await UserChannelCRUD.in_user_in_channel(async_session, test_user.id, test_channel.id)


@pytest.mark.asyncio
async def test_rm_users_batch(async_session, mock_message, mock_state, test_channel):
    """Test /rm_users (Batch Removal)"""
    # Setup: Add 2 users
    u1 = User(telegram_id=11, username="u1", full_name="U1")
    u2 = User(telegram_id=22, username="u2", full_name="U2")
    async_session.add_all([u1, u2])
    await async_session.commit()

    # Link them
    await UserChannelCRUD.add_user_to_channel(async_session, u1.id, test_channel.id)
    await UserChannelCRUD.add_user_to_channel(async_session, u2.id, test_channel.id)

    # 1. Command
    await cmd_rm_users_interactive(mock_message, mock_state)

    mock_state.set_state.assert_called_with(RemoveUserStates.waiting_for_users)

    # 2. Input
    mock_message.text = "@u1 @u2"
    mock_message.chat.id = test_channel.telegram_id
    await process_rm_users_input(mock_message, mock_state, async_session)

    assert not await UserChannelCRUD.in_user_in_channel(async_session, u1.id, test_channel.id)
    assert not await UserChannelCRUD.in_user_in_channel(async_session, u2.id, test_channel.id)


# === EVENT MANAGEMENT (ALL TYPES) ===

@pytest.mark.asyncio
async def test_add_event(async_session, mock_message, mock_state, test_channel):
    await cmd_add_event_interactive(mock_message, mock_state)

    mock_state.update_data.assert_called_with(command="add_event", prompt_message_id=54321)
    mock_state.set_state.assert_called_with(AddEventStates.waiting_for_params)

    mock_message.text = '"Regular Check" 10:00 1'
    mock_message.chat.id = test_channel.telegram_id
    mock_state.get_data.return_value = {"command": "add_event"}

    await process_event_params_input(mock_message, mock_state, async_session)

    events = await EventCRUD.get_active_by_channel(async_session, test_channel.id)
    assert len(events) == 1
    assert isinstance(events[0], Event)
    assert events[0].keyword == "Regular Check"


@pytest.mark.asyncio
async def test_add_tmp_event(async_session, mock_message, mock_state, test_channel):
    await cmd_add_tmp_event_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(AddEventStates.waiting_for_params)

    mock_message.text = '"Spot Check" 12:00 1'
    mock_message.chat.id = test_channel.telegram_id
    mock_state.get_data.return_value = {"command": "add_tmp_event"}

    await process_event_params_input(mock_message, mock_state, async_session)

    events = await TempEventCRUD.get_active_by_channel_and_date(async_session, test_channel.id, date.today())
    assert len(events) == 1
    assert isinstance(events[0], TempEvent)
    assert events[0].keyword == "Spot Check"


@pytest.mark.asyncio
async def test_add_event_checkout(async_session, mock_message, mock_state, test_channel):
    await cmd_add_event_checkout_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(AddEventStates.waiting_for_params)

    mock_message.text = '"Count" 10:00 "Done" 20:00 1 22:00'
    mock_message.chat.id = test_channel.telegram_id
    mock_state.get_data.return_value = {"command": "add_event_checkout"}

    await process_event_params_input(mock_message, mock_state, async_session)

    events = await CheckoutEventCRUD.get_active_by_channel(async_session, test_channel.id)
    assert len(events) == 1
    assert isinstance(events[0], CheckoutEvent)
    assert events[0].first_keyword == "Count"


@pytest.mark.asyncio
async def test_add_event_notext(async_session, mock_message, mock_state, test_channel):
    await cmd_add_event_notext_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(AddEventStates.waiting_for_params)

    mock_message.text = "09:00 18:00"
    mock_message.chat.id = test_channel.telegram_id
    mock_state.get_data.return_value = {"command": "add_event_notext"}

    await process_event_params_input(mock_message, mock_state, async_session)

    events = await NoTextEventCRUD.get_active_by_channel(async_session, test_channel.id)
    assert len(events) == 1
    assert isinstance(events[0], NoTextEvent)
    assert events[0].deadline_start == time(9, 0)


@pytest.mark.asyncio
async def test_add_event_kw(async_session, mock_message, mock_state, test_channel):
    await cmd_add_event_kw_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(AddEventStates.waiting_for_params)

    mock_message.text = '09:00 18:00 "SOS"'
    mock_message.chat.id = test_channel.telegram_id
    mock_state.get_data.return_value = {"command": "add_event_kw"}

    await process_event_params_input(mock_message, mock_state, async_session)

    events = await KeywordEventCRUD.get_active_by_channel(async_session, test_channel.id)
    assert len(events) == 1
    assert isinstance(events[0], KeywordEvent)
    assert events[0].keyword == "SOS"


# === CHANNEL MANAGEMENT ===

@pytest.mark.asyncio
async def test_add_rm_channel(async_session, mock_message, mock_state):

    await cmd_add_channel_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(AddChannelStates.waiting_for_title)

    mock_message.text = "MyChannel"
    mock_message.chat.id = -500
    mock_message.is_topic_message = False
    await process_add_channel_input(mock_message, mock_state, async_session)

    channel = await ChannelCRUD.get_by_chat_and_thread(async_session, -500, None)
    assert isinstance(channel, Channel)
    assert channel.title == "MyChannel"

    # Remove
    await cmd_rm_channel_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(RemoveChannelStates.waiting_for_title)

    mock_message.text = "MyChannel"
    mock_message.chat.id = -500
    await process_rm_channel_input(mock_message, mock_state, async_session)

    channel = await ChannelCRUD.get_by_chat_and_thread(async_session, -500, None)
    assert channel is None


@pytest.mark.asyncio
async def test_set_wstat(async_session, mock_message, mock_state, test_channel):
    await cmd_set_wstat_interactive(mock_message, mock_state)
    mock_state.set_state.assert_called_with(SetWstatStates.waiting_for_params)

    mock_message.text = "-100 0 Weekly Stats"
    mock_message.chat.id = test_channel.telegram_id
    await process_set_wstat_input(mock_message, mock_state, async_session)

    await async_session.refresh(test_channel)
    assert test_channel.stats_chat_id == -100
    assert test_channel.stats_title == "Weekly Stats"