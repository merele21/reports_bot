from typing import Optional, List

from aiogram.types import Message
from bot.database.models import Channel


class ReportValidator:
    """Валидатор отчетов"""

    @staticmethod
    def validate_photos(
        message: Message, min_photos: int
    ) -> tuple[bool, Optional[str]]:
        """
        Проверка количества фотографий

        Returns:
            tuple: (is_valid, error_message)
        """
        if not message.photo:
            return False, "Сообщение не содержит фотографий"

        # В aiogram 3.x message.photo это список PhotoSize
        # Но Telegram отправляет одно фото в разных размерах
        # Нужно проверять message.media_group_id для группы фото
        photos_count = 1  # По умолчанию одно фото

        if message.media_group_id:
            # Это часть медиагруппы, счетчик будет в хендлере
            return True, None

        if photos_count < min_photos:
            return (
                False,
                f"Необходимо минимум {min_photos} фотографии(й), получено: {photos_count}",
            )

        return True, None

    @staticmethod
    def validate_keyword(message: Message, keyword: str) -> tuple[bool, Optional[str]]:
        """
        Проверка наличия ключевого слова

        Returns:
            tuple: (is_valid, error_message)
        """
        if not message.text and not message.caption:
            return False, "Сообщение не содержит текста"

        text = (message.text or message.caption or "").lower()

        if keyword.lower() not in text:
            return False, f"Сообщение должно содержать ключевое слово: {keyword}"

        return True, None

    @staticmethod
    def validate_report(message: Message, channel: Channel) -> tuple[bool, List[str]]:
        """
        Полная валидация отчета

        Returns:
            tuple: (is_valid, list_of_errors)
        """
        errors = []

        # Проверка ключевого слова
        is_valid, error = ReportValidator.validate_keyword(message, channel.keyword)
        if not is_valid:
            errors.append(error)

        # Проверка фотографий (базовая)
        is_valid, error = ReportValidator.validate_photos(message, channel.min_photos)
        if not is_valid:
            errors.append(error)

        return len(errors) == 0, errors


# class PhotoTemplateValidator:
#     """
#     Заглушка для будущей валидации шаблонов фото
#     Здесь можно добавить проверку через OpenCV или API нейросетей
#     """
#
#     @staticmethod
#     async def validate_template(photo_file_id: str, template_type: str) -> bool:
#         """
#         Проверка фото на соответствие шаблону
#
#         Args:
#             photo_file_id: ID файла фото в Telegram
#             template_type: Тип шаблона (например, "касса", "склад")
#
#         Returns:
#             bool: Соответствует ли фото шаблону
#         """
#         # TODO: Реализовать проверку через OpenCV/нейросети
#         # Пример:
#         # - Загрузить фото через bot.download_file()
#         # - Проверить хеш изображения
#         # - Или отправить в API для распознавания объектов
#         return True
