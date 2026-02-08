"""Add photo support to keyword events

Revision ID: add_photo_kw_001
Revises: add_stats_time_001
Create Date: 2025-02-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_photo_kw_001'
down_revision: Union[str, None] = 'add_stats_time_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add photo fields to keyword_events table"""
    # Add reference_photo_file_id column
    op.add_column(
        'keyword_events',
        sa.Column('reference_photo_file_id', sa.String(255), nullable=True)
    )

    # Add reference_photo_description column
    op.add_column(
        'keyword_events',
        sa.Column('reference_photo_description', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Remove photo fields from keyword_events table"""
    op.drop_column('keyword_events', 'reference_photo_description')
    op.drop_column('keyword_events', 'reference_photo_file_id')