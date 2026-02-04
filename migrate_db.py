"""
Скрипт миграции базы данных
Запуск: python migrate_db.py
"""

import asyncio
import logging
from sqlalchemy import text
from bot.database.engine import engine, async_session_maker
from bot.database.models import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_table_exists(table_name: str) -> bool:
    """Проверить, существует ли таблица"""
    async with async_session_maker() as session:
        if "sqlite" in str(engine.url):
            query = text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"
            )
        else: # PostgreSQL
            query = text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=:table_name"
            )

        result = await session.execute(query, {"table_name": table_name})
        return result.scalar() is not None

async def migrate_channels_table():
    """Добавить новые колонки в таблицу channels"""
    async with async_session_maker() as session:
        try:
            # Проверяем, существует ли колонка stats_chat_id
            if "sqlite" in str(engine.url):
                # SQLite
                result = await session.execute(text("PRAGMA table_info(channels)"))
                columns = [row[1] for row in result.fetchall()]

                if "stats_chat_id" not in columns:
                    logger.info("Adding stats_chat_id column to channels table...")
                    await session.execute(
                        text("ALTER TABLE channels ADD COLUMN stats_chat_id INTEGER")
                    )

                if "stats_thread_id" not in columns:
                    logger.info("Adding stats_thread_id column to channels table...")
                    await session.execute(
                        text("ALTER TABLE channels ADD COLUMN stats_thread_id INTEGER")
                    )

            else:
                # PostgreSQL
                await session.execute(
                    text(
                            """
                        ALTER TABLE channels
                        ADD COLUMN IF NOT EXISTS stats_chat_id INTEGER,
                        ADD COLUMN IF NOT EXISTS stats_thread_id INTEGER
                    """
                    )
                )

            await session.commit()
            logger.info("✅ Channels table migrated successfully.")

        except Exception as e:
            await session.rollback()
            logger.error(f"Error migrating channels table: {e}")
            raise

async def migrate_reports_table():
    """Добавить колонку template_validated в таблицу reports"""
    async with async_session_maker() as session:
        try:
            if "sqlite" in str(engine.url):
                # SQLite
                result = await session.execute(text("PRAGMA table_info(reports)"))
                columns = [row[1] for row in result.fetchall()]

                if "template_validated" not in columns:
                    logger.info(
                        "Adding template_validated column to reports table..."
                    )
                    await session.execute(
                        text(
                            "ALTER TABLE reports ADD COLUMN template_validated BOOLEAN DEFAULT 0"
                        )
                    )

            else:
                # PostgreSQL
                await session.execute(
                    text(
                        """
                    ALTER TABLE reports 
                    ADD COLUMN IF NOT EXISTS template_validated BOOLEAN DEFAULT FALSE
                """
                    )
                )

            await session.commit()
            logger.info("✅ Reports table migrated successfully")

        except Exception as e:
            await session.rollback()
            logger.error(f"Error migrating reports table: {e}")
            raise


async def create_new_tables():
    """Создать новые таблицы (user_channels, photo_templates, notext_events, keyword_events)"""
    async with engine.begin() as conn:
        logger.info("Creating new tables...")

        # Создаем только новые таблицы
        await conn.run_sync(Base.metadata.create_all)

        logger.info("✅ New tables created successfully")


async def migrate():
    """Основная функция миграции"""
    logger.info("Starting database migration...")

    try:
        # 1. Проверяем существующие таблицы и мигрируем их
        if await check_table_exists("channels"):
            await migrate_channels_table()

        if await check_table_exists("reports"):
            await migrate_reports_table()

        # 2. Создаем новые таблицы
        await create_new_tables()

        logger.info("=" * 50)
        logger.info("✅ Migration completed successfully!")
        logger.info("=" * 50)
        logger.info("\nNew tables created:")
        logger.info("- notext_events: события без текста")
        logger.info("- notext_reports: отчеты для notext событий")
        logger.info("- notext_day_offs: выходные дни для notext событий")
        logger.info("- keyword_events: события с ключевым словом (open/close)")
        logger.info("- keyword_reports: отчеты для keyword событий")
        logger.info("\nNext steps:")
        logger.info("1. Restart your bot")
        logger.info("2. Use /add_event_notext for photo tracking events")
        logger.info("3. Use /add_event_open or /add_event_close for keyword events")
        logger.info("4. Use /rm_event to remove any type of event")

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(migrate())