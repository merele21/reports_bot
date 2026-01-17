from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: str
    TECH_CHANNEL_ID: int
    DATABASE_URL: str
    TZ: str
    MIN_PHOTOS: int
    STATS_DAY: int
    STATS_HOUR: int
    STATS_MINUTE: int

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def admin_list(self) -> List[int]:
        """Преобразование строки админов в список int"""
        return [int(admin_id.strip()) for admin_id in self.ADMIN_IDS.split(",")]


settings = Settings()
