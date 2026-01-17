import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from alembic import command
from alembic.config import Config

from bot.config import settings
from bot.database.engine import init_db
from bot.handlers import admin, reports, stats
from bot.middlewares.database import DatabaseMiddleware
from bot.scheduler.tasks import ReportScheduler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def run_migrations():
    """Применяет все миграции 'на лету' при запуске бота"""
    try:
        logger.info("🔄 Running database migrations...")
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Database migrations completed successfully")
    except FileNotFoundError:
        logger.warning("⚠️ Alembic configuration not found, creating tables directly...")
        # Если миграций нет, создаем таблицы напрямую
        asyncio.run(init_db())
    except Exception as e:
        logger.error(f"❌ Error during migration: {e}")
        logger.info("📦 Falling back to direct table creation...")
        asyncio.run(init_db())


async def main():
    """Главная функция запуска бота"""

    # Автоматическое применение миграций
    run_migrations()

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

    logger.info("🤖 Bot started successfully!")
    logger.info(f"📊 Stats schedule: Every {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][settings.STATS_DAY]} at {settings.STATS_HOUR:02d}:{settings.STATS_MINUTE:02d}")

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