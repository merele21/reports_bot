from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: str
    TECH_CHANNEL_ID: int
    DATABASE_URL: str = "sqlite+aiosqlite:///./bot_data.db"
    TZ: str = "Europe/Moscow"
    MIN_PHOTOS: int = 2
    STATS_DAY: int = 0  # Monday
    STATS_HOUR: int = 9
    STATS_MINUTE: int = 0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def admin_list(self) -> List[int]:
        """Преобразование строки админов в список int"""
        return [int(admin_id.strip()) for admin_id in self.ADMIN_IDS.split(',')]


settings = Settings()