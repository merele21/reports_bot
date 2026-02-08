"""add stats_time to checkout_events

Revision ID: add_stats_time_001
Revises: xxxx_add_store_id
Create Date: 2025-02-05 12:00:00.000000

"""
from typing import Sequence, Union
from datetime import time

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_stats_time_001'
down_revision: Union[str, None] = 'xxxx_add_store_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем новую колонку stats_time с default значением 22:00
    op.add_column('checkout_events', 
                  sa.Column('stats_time', sa.Time(), nullable=True))
    
    # Устанавливаем значение по умолчанию для существующих записей
    op.execute("UPDATE checkout_events SET stats_time = '22:00:00' WHERE stats_time IS NULL")


def downgrade() -> None:
    # Удаляем колонку stats_time
    op.drop_column('checkout_events', 'stats_time')
