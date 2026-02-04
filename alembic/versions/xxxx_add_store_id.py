import sa
from alembic import op


def upgrade():
    # Добавляем поле store_id
    op.add_column('users',
                  sa.Column('store_id', sa.String(50), nullable=True)
                  )

    # Делаем full_name опциональным
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('full_name',
                              existing_type=sa.String(255),
                              nullable=True
                              )

    # Создаем индекс
    op.create_index('ix_users_store_id', 'users', ['store_id'])


def downgrade():
    op.drop_index('ix_users_store_id', 'users')

    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('full_name',
                              existing_type=sa.String(255),
                              nullable=False
                              )

    op.drop_column('users', 'store_id')