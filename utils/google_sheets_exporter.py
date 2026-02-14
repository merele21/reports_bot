"""
Экспортер статистики в Google Sheets
"""
import asyncio
import os
import logging
from typing import Dict, List
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

logger = logging.getLogger(__name__)


class GoogleSheetsExporter:
    """Класс для экспорта статистики в Google Sheets"""

    # Цвета для форматирования (RGB в hex)
    COLORS = {
        'header': {'red': 0.26, 'green': 0.52, 'blue': 0.96},  # Синий
        'event_title': {'red': 0.95, 'green': 0.95, 'blue': 0.95},  # Светло-серый
        'warning': {'red': 1.0, 'green': 0.95, 'blue': 0.8},  # Светло-желтый
        'error': {'red': 1.0, 'green': 0.9, 'blue': 0.9},  # Светло-красный
        'success': {'red': 0.85, 'green': 0.95, 'blue': 0.85},  # Светло-зеленый
    }

    def __init__(self):
        self.credentials_path = os.getenv('GOOGLE_SHEETS_CREDENTIALS_PATH')
        self.spreadsheet_id = os.getenv('GOOGLE_SHEETS_STATS_SPREADSHEET_ID')
        self.client = None  # Initialize as None first

        if not self.spreadsheet_id:
            logger.error("No Google Sheet ID provided in env vars")
            return  # Returns, but self.client now exists (as None)

        # Инициализация клиента
        self.client = self._init_client()

    def _init_client(self) -> gspread.Client:
        """Инициализация клиента Google Sheets"""
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        credentials = Credentials.from_service_account_file(
            self.credentials_path,
            scopes=scopes
        )

        return gspread.authorize(credentials)

    async def export_stats(self, stats_data: Dict) -> str:
        """Асинхронная обертка для экспорта"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_export, stats_data)

    def _sync_export(self, stats_data: Dict) -> str:
        """Синхронная логика экспорта (Batch Update)"""
        try:
            spreadsheet = self.client.open_by_key(self.spreadsheet_id)

            # Получаем или создаем лист
            try:
                worksheet = spreadsheet.sheet1
            except:
                worksheet = spreadsheet.add_worksheet("Статистика", 1000, 20)

            worksheet.clear()
            worksheet.clear_basic_filter()

            # 1. Подготовка данных в памяти (список списков)
            all_rows = []

            # Заголовок
            channel = stats_data['channel']
            timestamp = stats_data['timestamp']

            all_rows.append([f"📊 Статистика: {channel.title}", f"На момент: {timestamp.strftime('%d.%m.%Y %H:%M')}"])
            all_rows.append([])  # Пустая строка
            all_rows.append(["Событие", "Тип", "Дедлайн", "Статус", "Магазин/Пользователь", "Детали"])

            # Данные событий
            data_rows = self._prepare_data_rows(stats_data['events'])
            all_rows.extend(data_rows)

            if not data_rows:
                all_rows.append(["🎉 Все отчеты сданы!"])

            # 2. Массовая вставка данных (Один API запрос вместо сотен)
            # update ожидает список списков. A1 - начало вставки.
            worksheet.update(values=all_rows, range_name='A1')

            # 3. Форматирование (можно оставить как есть или упростить)
            self._apply_formatting(worksheet, len(all_rows))
            self._auto_resize_columns(worksheet)

            return spreadsheet.url

        except Exception as e:
            logger.error(f"Error exporting to Google Sheets: {e}", exc_info=True)
            raise

    def _prepare_data_rows(self, events: Dict) -> List[List[str]]:
        """Преобразует события в список строк для таблицы"""
        rows = []

        # Helper для добавления строк
        def add_row(evt_name, evt_type, deadline, status, store, details):
            rows.append([evt_name, evt_type, deadline, status, store, details])

        # === REGULAR ===
        for item in events.get('regular', []):
            evt = item['event']
            for store_id, users in item['not_submitted']:
                add_row(
                    evt.keyword, "Обычное", evt.deadline_time.strftime('%H:%M'),
                    "❌ Не сдали", self._format_store_for_excel(store_id, users),
                    f"Требуется: {evt.min_photos} фото"
                )

        # === TEMPORARY ===
        for item in events.get('temp', []):
            evt = item['event']
            for store_id, users in item['not_submitted']:
                add_row(
                    evt.keyword, "Временное", evt.deadline_time.strftime('%H:%M'),
                    "❌ Не сдали", self._format_store_for_excel(store_id, users),
                    "Удалится в 23:59"
                )

        # === CHECKOUT ===
        for item in events.get('checkout', []):
            cev = item['event']
            stats = item['stats']

            for store_id, users in stats['not_submitted_first']:
                add_row(cev.first_keyword, "Checkout (1)", cev.first_deadline_time.strftime('%H:%M'),
                        "⚠️ Не сдали 1 этап", self._format_store_for_excel(store_id, users), "Ждем список")

            for store_id, users in stats['not_submitted_second']:
                add_row(cev.second_keyword, "Checkout (2)", cev.second_deadline_time.strftime('%H:%M'),
                        "⚠️ Не начали 2 этап", self._format_store_for_excel(store_id, users), "1 этап сдан")

            for store_id, users, rem in stats['partial_second']:
                add_row(cev.second_keyword, "Checkout (2)", cev.second_deadline_time.strftime('%H:%M'),
                        "⚠️ Частично", self._format_store_for_excel(store_id, users), f"Осталось: {', '.join(rem)}")

            for store_id, users in stats['not_submitted_anything']:
                add_row(cev.first_keyword, "Checkout", cev.first_deadline_time.strftime('%H:%M'),
                        "❌ Ничего", self._format_store_for_excel(store_id, users), "Полный провал")


        # === NOTEXT ===
        for item in events.get('notext', []):
            evt = item['event']
            for store_id, users in item['not_submitted']:
                add_row(
                    evt.keyword, "Без текста", evt.deadline_time.strftime('%H:%M'),
                    "❌ Не сдали", self._format_store_for_excel(store_id, users),
                    f"Требуется: {evt.min_photos} фото"
                )

        # === KEYWORD ===
        for item in events.get('keyword', []):
            evt = item['event']
            for store_id, users in item['not_submitted']:
                add_row(
                    evt.keyword, "По ключевому слову", evt.deadline_time.strftime('%H:%M'),
                    "❌ Не сдали", self._format_store_for_excel(store_id, users),
                    f"Требуется: {evt.keyword}"
                )

        return rows

    def _apply_formatting(self, worksheet, total_rows):
        """Применяет форматы пакетно"""
        # Заголовок
        worksheet.format('A1:B1', {
            'backgroundColor': self.COLORS['header'],
            'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}
        })
        # Шапка таблицы
        worksheet.format('A3:F3', {
            'backgroundColor': self.COLORS['event_title'],
            'textFormat': {'bold': True},
            'horizontalAlignment': 'CENTER'
        })

        pass

    async def _apply_formatting(self, worksheet, stats_data: Dict):
        """Применяет форматирование к таблице"""

        # Заголовок
        worksheet.format('A1:B1', {
            'backgroundColor': self.COLORS['header'],
            'textFormat': {
                'bold': True,
                'fontSize': 14,
                'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}
            },
            'horizontalAlignment': 'LEFT'
        })

        # Заголовки колонок
        worksheet.format('A3:F3', {
            'backgroundColor': self.COLORS['event_title'],
            'textFormat': {
                'bold': True,
                'fontSize': 11
            },
            'horizontalAlignment': 'CENTER',
            'verticalAlignment': 'MIDDLE'
        })

        # Границы для всей таблицы
        last_row = len(worksheet.get_all_values())
        if last_row > 3:
            worksheet.format(f'A3:F{last_row}', {
                'borders': {
                    'top': {'style': 'SOLID'},
                    'bottom': {'style': 'SOLID'},
                    'left': {'style': 'SOLID'},
                    'right': {'style': 'SOLID'}
                }
            })

        # Цветовое кодирование по статусу
        for i, row in enumerate(worksheet.get_all_values()[3:], start=4):
            if len(row) > 3:
                status = row[3]

                if "❌" in status:
                    color = self.COLORS['error']
                elif "⚠️" in status:
                    color = self.COLORS['warning']
                elif "✅" in status or "🎉" in status:
                    color = self.COLORS['success']
                else:
                    continue

                worksheet.format(f'A{i}:F{i}', {
                    'backgroundColor': color
                })

    def _auto_resize_columns(self, worksheet):
        """Автоматический подбор ширины колонок"""
        try:
            # Устанавливаем фиксированную ширину для каждой колонки
            requests = [
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': worksheet.id,
                            'dimension': 'COLUMNS',
                            'startIndex': 0,
                            'endIndex': 1
                        },
                        'properties': {'pixelSize': 200}  # Событие
                    },
                    'fields': 'pixelSize'
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': worksheet.id,
                            'dimension': 'COLUMNS',
                            'startIndex': 1,
                            'endIndex': 2
                        },
                        'properties': {'pixelSize': 150}  # Тип
                    },
                    'fields': 'pixelSize'
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': worksheet.id,
                            'dimension': 'COLUMNS',
                            'startIndex': 2,
                            'endIndex': 3
                        },
                        'properties': {'pixelSize': 100}  # Дедлайн
                    },
                    'fields': 'pixelSize'
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': worksheet.id,
                            'dimension': 'COLUMNS',
                            'startIndex': 3,
                            'endIndex': 4
                        },
                        'properties': {'pixelSize': 150}  # Статус
                    },
                    'fields': 'pixelSize'
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': worksheet.id,
                            'dimension': 'COLUMNS',
                            'startIndex': 4,
                            'endIndex': 5
                        },
                        'properties': {'pixelSize': 200}  # Магазин
                    },
                    'fields': 'pixelSize'
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': worksheet.id,
                            'dimension': 'COLUMNS',
                            'startIndex': 5,
                            'endIndex': 6
                        },
                        'properties': {'pixelSize': 250}  # Детали
                    },
                    'fields': 'pixelSize'
                }
            ]

            worksheet.spreadsheet.batch_update({'requests': requests})
        except Exception as e:
            logger.warning(f"Could not auto-resize columns: {e}")

    def _format_store_for_excel(self, store_id: str, users_list: List) -> str:
        """Форматирует упоминание магазина для Excel"""
        if store_id.startswith("no_store_"):
            user = users_list[0]
            return f"@{user.username}" if user.username else str(user.full_name)

        # Для магазина: "MSK-001 (@user1, @user2)"
        usernames = [f"@{u.username}" if u.username else u.full_name for u in users_list]
        return f"{store_id} ({', '.join(usernames)})" if usernames else store_id