"""
Хендлеры регистрации пользователей
"""
import logging
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import UserCRUD, ChannelCRUD
from bot.database.models import User
from bot.handlers.admin.utils import validate_store_id_format, is_admin, parse_user_list, format_user_mention

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("rm_store"))
async def cmd_rm_store(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Полное удаление (отвязка) магазина.
    У всех пользователей с этим store_id поле будет очищено.

    Формат: /rm_store [store_id]
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    if not command.args:
        await message.answer(
            "<b>Формат:</b> <code>/rm_store [store_id]</code>\n\n"
            "⚠️ Эта команда удалит привязку к магазину у всех пользователей этого магазина."
        )
        return

    store_id = command.args.strip().upper()

    # Проверяем, есть ли такой магазин (есть ли пользователи)
    users = await UserCRUD.get_by_store_id(session, store_id)
    if not users:
        await message.answer(f"❌ Магазин с ID <code>{store_id}</code> не найден (нет привязанных пользователей).")
        return

    # Выполняем отвязку
    count = await UserCRUD.unlink_store_from_all_users(session, store_id)

    await message.answer(
        f"✅ <b>Магазин {store_id} расформирован.</b>\n\n"
        f"Отвязано пользователей: {count}\n"
        f"Теперь у них нет привязки к этому магазину."
    )

    logger.info(f"Store {store_id} removed (unlinked {count} users) by admin {message.from_user.id}")


@router.message(Command("rm_users_by_store"))
async def cmd_rm_users_by_store(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Удаление конкретных пользователей из магазина.

    Формат: /rm_users_by_store [store_id] [targets]
    Пример: /rm_users_by_store MSK-001 @ivan @petr
    """
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    args = command.args.split() if command.args else []
    if len(args) < 2:
        await message.answer(
            "<b>Формат:</b> <code>/rm_users_by_store [store_id] [targets]</code>\n"
            "<b>Пример:</b> <code>/rm_users_by_store MSK-001 @ivan @petr</code>"
        )
        return

    store_id = args[0].strip().upper()
    targets_str = " ".join(args[1:])
    entries = parse_user_list(targets_str)

    removed_names = []
    not_found_or_wrong_store = []

    for entry in entries:
        user = await _find_user_by_identifier(session, entry)

        if user:
            name = format_user_mention(user.username, user.full_name, user.telegram_id)
            if user.store_id == store_id:
                success = await UserCRUD.unlink_store_from_user(session, user.id, store_id)
                if success:
                    removed_names.append(name)
                else:
                    not_found_or_wrong_store.append(f"{name} (ошибка)")
            else:
                current_store = user.store_id if user.store_id else "нет магазина"
                not_found_or_wrong_store.append(f"{name} (в {current_store})")
        else:
            not_found_or_wrong_store.append(f"@{entry} (не найден)")

    response = []
    response.append(f"<b>🏗 Работа с магазином {store_id}:</b>\n")

    if removed_names:
        response.append(
            f"✅ <b>Успешно отвязаны:</b>\n" +
            "\n".join([f"• {n}" for n in removed_names])
        )

    if not_found_or_wrong_store:
        response.append(
            f"\n⚠️ <b>Не обработаны (не найдены или другой магазин):</b>\n" +
            "\n".join([f"• {n}" for n in not_found_or_wrong_store])
        )

    await message.answer("\n".join(response))


async def _find_user_by_identifier(
        session: AsyncSession,
        identifier: str
) -> User | None:
    """
    Найти пользователя по ID или username
    (Копия вспомогательной функции для локального использования)
    """
    val = identifier.replace("@", "").strip()

    if val.isdigit():
        return await UserCRUD.get_by_telegram_id(session, int(val))
    else:
        res = await session.execute(select(User).where(User.username.ilike(val)))
        return res.scalar_one_or_none()

@router.message(Command("register"))
async def cmd_register(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Регистрация пользователя с опциональным store_id

    Форматы:
    /register - регистрация без store_id
    /register MSK-001 - регистрация с store_id

    ВАЖНО: Несколько пользователей МОГУТ иметь одинаковый store_id
           (это группировка по магазину, не уникальный идентификатор)
    """
    is_private = message.chat.type == "private"
    thread_id = message.message_thread_id if message.is_topic_message else None

    # Проверяем, зарегистрирована ли текущая ветка в базе
    channel = await ChannelCRUD.get_by_chat_and_thread(
        session, message.chat.id, thread_id
    )
    is_reg_thread = channel and channel.title == "Регистрация"

    if is_private or is_reg_thread:
        telegram_id = message.from_user.id
        store_id = None

        # === ОБРАБОТКА И ВАЛИДАЦИЯ STORE_ID ===
        if command.args:
            store_id_raw = command.args.strip().upper()

            # Валидация ТОЛЬКО формата (не уникальности!)
            validation_result = validate_store_id_format(store_id_raw)
            if not validation_result["valid"]:
                await message.answer(validation_result["error_message"])
                return

            store_id = store_id_raw

        # Получаем или создаем пользователя
        existing_user = await UserCRUD.get_by_telegram_id(session, telegram_id)

        old_store_id = existing_user.store_id if existing_user else None
        old_username = existing_user.username if existing_user else None
        old_fullname = existing_user.full_name if existing_user else None

        user = await UserCRUD.get_or_create(
            session,
            telegram_id=telegram_id,
            username=message.from_user.username or None,
            full_name=message.from_user.full_name or None,
            store_id=store_id or None
        )

        # === ФОРМИРОВАНИЕ ОТВЕТА ===
        response = await _format_registration_response(
            session,
            user,
            existing_user,
            old_store_id,
            old_username,
            old_fullname,
            telegram_id
        )

        await message.answer(response)
    else:
        # Отправляем в ЛС
        bot_info = await message.bot.get_me()
        bot_link = f"https://t.me/{bot_info.username}"

        await message.answer(
            f"<b>Команда /register здесь недоступна.</b>\n\n"
            f"Пожалуйста, пройдите регистрацию в "
            f"<a href='{bot_link}'><b>личных сообщениях</b></a> бота "
            f"или перейдите в ветку <b>Регистрация</b>.",
            disable_web_page_preview=True
        )


async def _format_registration_response(
        session: AsyncSession,
        user: User,
        existing_user: Optional[User],
        old_store_id: Optional[str],
        old_username: Optional[str],
        old_fullname: Optional[str],
        telegram_id: int
) -> str:
    """
    Форматирует ответ на регистрацию

    Args:
        session: Сессия БД
        user: Текущий пользователь
        existing_user: Существующий пользователь (до обновления)
        telegram_id: Telegram ID

    Returns:
        Отформатированное сообщение
    """
    if existing_user:
        # Пользователь обновляет профиль
        changes = []
        has_changes = False

        if old_store_id != user.store_id:
            has_changes = True

            if user.store_id:
                # Показываем, кто еще в этом магазине
                store_users = await UserCRUD.get_by_store_id(session, user.store_id)
                other_users = [u for u in store_users if u.telegram_id != telegram_id]

                changes.append(f"ID магазина: <code>{user.store_id}</code>")

                if other_users:
                    changes.append(
                        f"   👥 В этом магазине уже {len(other_users)} чел.: " +
                        ", ".join([
                            f"@{u.username}" if u.username else u.full_name
                            for u in other_users[:3]
                        ]) +
                        (f" и еще {len(other_users) - 3}" if len(other_users) > 3 else "")
                    )
            else:
                changes.append("ID магазина удален")

        if old_username != user.username:
            has_changes = True
            changes.append(f"Username: @{user.username}")

        if old_fullname != user.full_name:
            has_changes = True
            changes.append(f"Имя: {user.full_name}")

        if has_changes:
            response = f"<b>✅ Профиль обновлен, {user.full_name or 'пользователь'}!</b>\n\n"
            response += "<b>Изменения:</b>\n"
            response += "\n".join([f"• {change}" for change in changes])
            response += f"\n\n<b>Текущий профиль:</b>\n"
        else:
            response = f"<b>ℹ️ Профиль без изменений, {user.full_name or 'пользователь'}</b>\n\n"

        response += f"Telegram ID: <code>{user.telegram_id}</code>\n"
        if user.username:
            response += f"Username: @{user.username}\n"
        if user.store_id:
            response += f"ID магазина: <code>{user.store_id}</code>\n"
        else:
            response += f"\n💡 <b>Совет:</b> укажите ID магазина для группировки:\n"
            response += f"<code>/register MSK-001</code>"
    else:
        # Новый пользователь
        response = f"<b>🎉 Добро пожаловать, {user.full_name or 'пользователь'}!</b>\n\n"
        response += "✅ Вы успешно зарегистрированы.\n\n"
        response += f"Telegram ID: <code>{user.telegram_id}</code>\n"
        if user.username:
            response += f"Username: @{user.username}\n"

        if user.store_id:
            # Проверяем, кто еще в этом магазине
            store_users = await UserCRUD.get_by_store_id(session, user.store_id)
            other_users = [u for u in store_users if u.telegram_id != telegram_id]

            response += f"ID магазина: <code>{user.store_id}</code>\n"
            response += f"\n🏪 Вы привязаны к магазину <b>{user.store_id}</b>\n"

            if other_users:
                response += f"👥 В этом магазине уже зарегистрированы ({len(other_users)} чел.):\n"
                for i, u in enumerate(other_users[:5], 1):
                    username_str = f"@{u.username}" if u.username else u.full_name
                    response += f"   {i}. {username_str}\n"

                if len(other_users) > 5:
                    response += f"   ... и еще {len(other_users) - 5} чел.\n"

                response += f"\nВсе пользователи магазина будут группироваться в отчетах вместе."
            else:
                response += f"Вы первый пользователь в этом магазине! 🎉\n"
                response += f"Другие сотрудники могут присоединиться через:\n"
                response += f"<code>/register {user.store_id}</code>"
        else:
            response += f"\n💡 <b>Совет:</b> укажите ID магазина для группировки:\n"
            response += f"<code>/register MSK-001</code>\n\n"
            response += f"<b>Примеры ID:</b>\n"
            response += f"• <code>MSK-001</code> - Москва, магазин 1\n"
            response += f"• <code>SPB-042</code> - Санкт-Петербург, магазин 42\n"
            response += f"• <code>KRD-15</code> - Краснодар, магазин 15\n\n"
            response += f"<i>Несколько человек могут использовать один ID магазина</i>"

    return response


@router.message(Command("list_stores"))
async def cmd_list_stores(message: Message, session: AsyncSession):
    """
    Показать список всех магазинов (store_id) с количеством пользователей
    """
    from bot.handlers.admin.utils import is_admin

    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    # Запрос всех пользователей с store_id
    stmt = (
        select(User)
        .where(User.is_active == True, User.store_id.isnot(None))
        .order_by(User.store_id)
    )
    result = await session.execute(stmt)
    users = result.scalars().all()

    if not users:
        await message.answer("📋 Магазины с ID не найдены")
        return

    # Группируем пользователей по store_id
    stores_dict = {}
    for user in users:
        if user.store_id not in stores_dict:
            stores_dict[user.store_id] = []
        stores_dict[user.store_id].append(user)

    text = "<b>📋 Список магазинов:</b>\n\n"
    for store_id in sorted(stores_dict.keys()):
        store_users = stores_dict[store_id]
        count = len(store_users)

        # Формируем список пользователей с username
        usernames = []
        for user in store_users:
            if user.username:
                usernames.append(f"@{user.username}")
            else:
                usernames.append(user.full_name or f"ID:{user.telegram_id}")

        users_str = ", ".join(usernames)
        text += f"• <code>{store_id}</code> — {count} чел. ({users_str})\n"

    await message.answer(text)