"""agent task assignee

Revision ID: 5f4b106b4fe3
Revises: 7325f73429e3
Create Date: 2026-10-23 03:24:10.103546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f4b106b4fe3'
down_revision: Union[str, Sequence[str], None] = '7325f73429e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tasks', sa.Column('assignee_agent_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_tasks_assignee_agent_id'), 'tasks', ['assignee_agent_id'], unique=False)
    op.create_foreign_key(
        'tasks_assignee_agent_id_fkey', 'tasks', 'agents', ['assignee_agent_id'], ['id'], ondelete='SET NULL'
    )
    op.create_check_constraint(
        'ck_tasks_single_assignee',
        'tasks',
        'NOT (assignee_user_id IS NOT NULL AND assignee_agent_id IS NOT NULL)',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_tasks_single_assignee', 'tasks', type_='check')
    op.drop_constraint('tasks_assignee_agent_id_fkey', 'tasks', type_='foreignkey')
    op.drop_index(op.f('ix_tasks_assignee_agent_id'), table_name='tasks')
    op.drop_column('tasks', 'assignee_agent_id')
