from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from bot.config import settings
from bot.database.crud import StatsCRUD, ChannelCRUD
import logging

router = Router()
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in settings.admin_list


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession):
    """Показать статистику напоминаний за неделю"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для выполнения этой команды")
        return

    stats = await StatsCRUD.get_weekly_stats(session)

    if not stats:
        await message.answer("📊 Статистика за последнюю неделю пуста")
        return

    # Формируем сообщение
    text = "📊 Статистика напоминаний за последние 7 дней:\n\n"

    for i, stat in enumerate(stats, 1):
        username_str = f"@{stat['username']}" if stat['username'] else "без username"
        text += (
            f"{i}. {stat['full_name']} ({username_str})\n"
            f"   Напоминаний: {stat['total_reminders']}\n\n"
        )

    await message.answer(text)
    logger.info(f"Stats requested by admin {message.from_user.id}")


async def send_weekly_stats(bot, session: AsyncSession):
    """
    Отправка еженедельной статистики в технический канал
    Вызывается планировщиком
    """
    try:
        stats = await StatsCRUD.get_weekly_stats(session)

        if not stats:
            text = "📊 Статистика за прошедшую неделю:\n\nНапоминаний не было! 🎉"
        else:
            text = "📊 Статистика за прошедшую неделю:\n\n"
            text += "👥 Топ по количеству напоминаний:\n\n"

            for i, stat in enumerate(stats[:10], 1):  # Топ-10
                username_str = f"@{stat['username']}" if stat['username'] else "без username"

                # Медали для топ-3
                medal = ""
                if i == 1:
                    medal = "🥇 "
                elif i == 2:
                    medal = "🥈 "
                elif i == 3:
                    medal = "🥉 "

                text += (
                    f"{medal}{i}. {stat['full_name']} ({username_str})\n"
                    f"   Напоминаний: {stat['total_reminders']}\n\n"
                )

        # Получаем все каналы с настроенной статистикой
        channels = await ChannelCRUD.get_all_active(session)

        sent_count = 0
        for channel in channels:
            try:
                # Отправляем в настроенный чат/тред
                if channel.stats_thread_id:
                    await bot.send_message(
                        chat_id=channel.stats_chat_id,
                        text=text,
                        message_thread_id=channel.stats_thread_id,
                    )
                else:
                    await bot.send_message(
                        chat_id=channel.stats_chat_id, text=text
                    )

                sent_count += 1
                logger.info(
                    f"Weekly stats sent to chat {channel.stats_chat_id}, "
                    f"thread {channel.stats_thread_id}"
                )

            except Exception as e:
                logger.error(
                    f"Error sending stats to chat {channel.stats_chat_id}: {e}"
                )

        if sent_count == 0:
            logger.warning(
                "No channels with configured stats destination. "
                "Use /set_stats_destination to configure"
            )

    except Exception as e:
        logger.error(f"Error sending weekly stats: {e}", exc_info=True)