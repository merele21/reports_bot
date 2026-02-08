from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat, BotCommandScopeAllGroupChats, \
    BotCommandScopeAllChatAdministrators
from bot.config import settings


async def set_ui_commands(bot: Bot):
    # 1. Команды для ВСЕХ пользователей
    user_commands = [
        BotCommand(command="get_user_id", description="👋 Узнать telegram ID (свой/reply/username)"),
        BotCommand(command="register", description="📝 Регистрация/обновление профиля"),
        BotCommand(command="help", description="❓ Инструкция"),
    ]
    await bot.set_my_commands(commands=user_commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(commands=user_commands, scope=BotCommandScopeAllGroupChats())

    # 2. Команды только для АДМИНИСТРАТОРОВ
    # Мы проходим циклом по списку ID админов из твоего конфига
    admin_commands = user_commands + [
        BotCommand(command="add_channel", description="⚙️ Создать канал"),
        BotCommand(command="rm_channel", description="📊 Удалить канал"),
        BotCommand(command="list_channels", description=" Список каналов"),
        BotCommand(command="add_event", description="Добавить обычное событие"),
        BotCommand(command="add_tmp_event", description="Добавить временное событие"),
        BotCommand(command="add_event_checkout", description="Двухэтапное событие"),
        BotCommand(command="add_event_notext", description="Событие без текста"),
        BotCommand(command="add_event_kw", description="Событие по ключевому слову"),
        BotCommand(command="rm_event", description="Удалить событие"),
        BotCommand(command="list_events", description="📊 Список всех событий"),
        BotCommand(command="add_user", description="Добавить участника"),
        BotCommand(command="add_users", description="Добавить несколько участников"),
        BotCommand(command="add_users_by_store", description="Добавить по ID магазина"),
        BotCommand(command="rm_user", description="Удалить участника"),
        BotCommand(command="rm_users", description="Удалить несколько участников"),
        BotCommand(command="list_users", description="Список участников"),
        BotCommand(command="list_stores", description="Список магазинов"),
        BotCommand(command="set_wstat", description="Настройка еженедельной статистики"),
        BotCommand(command="get_thread_id", description="Узнать ID текущей ветки"),
    ]

    for admin_id in settings.admin_list:
        try:
            await bot.set_my_commands(
                commands=admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id)
            )
            await bot.set_my_commands(
                commands=admin_commands,
                scope=BotCommandScopeAllChatAdministrators()
            )
        except Exception:
            # Игнорируем ошибки, если админ еще не запускал бота
            continue