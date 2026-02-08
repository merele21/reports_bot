import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.strategy import FSMStrategy  # Импортируем стратегию

from bot.config import settings
from bot.database.engine import init_db
from bot.handlers.admin import router as admin_router
from bot.handlers import reports, stats
from bot.middlewares.database import DatabaseMiddleware
from bot.scheduler.tasks import ReportScheduler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # ВАЖНО: Устанавливаем стратегию USER_IN_TOPIC для изоляции состояний по веткам
    dp = Dispatcher(fsm_strategy=FSMStrategy.USER_IN_TOPIC)

    # Регистрация middleware
    dp.message.middleware(DatabaseMiddleware())

    # Регистрация роутеров
    dp.include_router(admin_router)
    dp.include_router(reports.router)
    dp.include_router(stats.router)

    # Запуск планировщика
    scheduler = ReportScheduler(bot)
    scheduler.start()

    logger.info("🤖 Bot started successfully with Topic Isolation!")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")