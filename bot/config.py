from typing import List
import json
import os
from pathlib import Path

# 1. Добавьте импорт SettingsConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: str
    TECH_CHANNEL_ID: str = ""
    SUPER_ADMIN_IDS: str = ""
    DATABASE_URL: str
    TZ: str
    MIN_PHOTOS: int
    STATS_DAY: int
    STATS_HOUR: int
    STATS_MINUTE: int

    # 2. УДАЛИТЕ старый class Config:
    # class Config:
    #     env_file = ".env"
    #     env_file_encoding = "utf-8"

    # 3. ДОБАВЬТЕ новую конфигурацию для Pydantic v2:
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Игнорировать лишние переменные в файле
    )

    @property
    def admin_list(self) -> List[int]:
        """Преобразование строки админов в список int"""
        if not self.ADMIN_IDS:
            return []
        # Добавлена проверка на валидность чисел, чтобы не падало при опечатках
        try:
            return [int(admin_id.strip()) for admin_id in self.ADMIN_IDS.split(",") if admin_id.strip().isdigit()]
        except ValueError:
            return []

    # ... остальной код (методы super_admin_list, add_admin и т.д.) оставьте без изменений
    @property
    def super_admin_list(self) -> List[int]:
        if not self.SUPER_ADMIN_IDS:
            return [self.admin_list[0]] if self.admin_list else []
        return [int(admin_id.strip()) for admin_id in self.SUPER_ADMIN_IDS.split(",")]

    async def add_admin(self, user_id: int) -> bool:
        current_admins = self.admin_list
        if user_id in current_admins:
            return False

        current_admins.append(user_id)
        self.ADMIN_IDS = ','.join(map(str, current_admins))
        self._save_to_env()
        return True

    async def remove_admin(self, user_id: int) -> bool:
        current_admins = self.admin_list
        if user_id not in current_admins:
            return False

        current_admins.remove(user_id)
        self.ADMIN_IDS = ','.join(map(str, current_admins))
        self._save_to_env()
        return True

    def _save_to_env(self):
        env_path = Path(".env")
        if not env_path.exists():
            return

        with open(env_path, 'r') as f:
            lines = f.readlines()

        with open(env_path, 'w') as f:
            for line in lines:
                if line.startswith('ADMIN_IDS='):
                    f.write(f'ADMIN_IDS={self.ADMIN_IDS}\n')
                elif line.startswith('SUPER_ADMIN_IDS='):
                    f.write(f'SUPER_ADMIN_IDS={self.SUPER_ADMIN_IDS}\n')
                else:
                    f.write(line)


settings = Settings()