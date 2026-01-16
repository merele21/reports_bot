import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from untitled.bot.config import settings
from untitled.bot.database.engine import init_db
from untitled.bot.handlers import admin, reports, stats
from untitled.bot.middlewares.database import DatabaseMiddleware
from untitled.bot.scheduler.tasks import ReportScheduler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Главная функция запуска бота"""

    # Инициализация базы данных
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Создание бота и диспетчера
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Регистрация middleware
    dp.message.middleware(DatabaseMiddleware())

    # Регистрация роутеров
    dp.include_router(admin.router)
    dp.include_router(reports.router)
    dp.include_router(stats.router)

    # Создание и запуск планировщика
    scheduler = ReportScheduler(bot)
    scheduler.start()

    logger.info("Bot started")

    try:
        # Запуск бота
        await dp.start_polling(bot)
    finally:
        # Остановка планировщика при завершении
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
