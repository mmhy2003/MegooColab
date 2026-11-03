"""pr review

Revision ID: ad7d0be526cf
Revises: d4690e2f6292
Create Date: 2026-11-03 22:09:49.829523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad7d0be526cf'
down_revision: Union[str, Sequence[str], None] = 'd4690e2f6292'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Pull request review (piece 4): None, Human or Agent, replacing the human review checkbox; existing projects keep
    what they had (on: human, off: none), as does the default for new ones."""
    op.add_column('org_settings', sa.Column('default_pr_review', sa.String(length=10), server_default='none', nullable=False))
    op.execute("UPDATE org_settings SET default_pr_review = 'human' WHERE default_require_human_code_review")
    op.drop_column('org_settings', 'default_require_human_code_review')
    op.add_column('projects', sa.Column('pr_review', sa.String(length=10), server_default='none', nullable=False))
    op.add_column('projects', sa.Column('pr_reviewer_agent_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('projects_pr_reviewer_agent_id_fkey', 'projects', 'agents', ['pr_reviewer_agent_id'], ['id'],
                          ondelete='SET NULL')
    op.execute("UPDATE projects SET pr_review = 'human' WHERE require_human_code_review")
    op.drop_column('projects', 'require_human_code_review')
    op.add_column('task_workflows', sa.Column('finish_pr_review', sa.String(length=10), nullable=True))


def downgrade() -> None:
    """Back to the checkbox: a human or an agent review was a review."""
    op.drop_column('task_workflows', 'finish_pr_review')
    op.add_column('projects', sa.Column('require_human_code_review', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.execute("UPDATE projects SET require_human_code_review = (pr_review <> 'none')")
    op.drop_constraint('projects_pr_reviewer_agent_id_fkey', 'projects', type_='foreignkey')
    op.drop_column('projects', 'pr_reviewer_agent_id')
    op.drop_column('projects', 'pr_review')
    op.add_column('org_settings', sa.Column('default_require_human_code_review', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.execute("UPDATE org_settings SET default_require_human_code_review = (default_pr_review <> 'none')")
    op.drop_column('org_settings', 'default_pr_review')
