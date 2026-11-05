"""merge_confirmation_waits

Revision ID: 9293a24ba936
Revises: d082f107a91d
Create Date: 2026-11-05 16:05:45.342981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9293a24ba936'
down_revision: Union[str, Sequence[str], None] = 'd082f107a91d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Rounds stuck on a human code review although an agent already merged the pull request move to the quiet
# merge_confirmation wait. One statement (the CTE), so it runs through a single execute.
MOVE_SQL = """
WITH moved AS (
    UPDATE task_workflows w
    SET needs = 'merge_confirmation', waiting_since = now()
    WHERE w.status = 'waiting_human' AND w.needs = 'human_code_review'
      AND w.stage = 'done' AND w.finish_pr_review = 'agent'
      AND w.back_merge_pr_url IS NULL
      AND EXISTS (
          SELECT 1 FROM task_pull_requests p
          WHERE p.task_id = w.task_id AND p.kind = 'main'
            AND p.connection_id IS NOT NULL AND p.error IS DISTINCT FROM 'branch_mismatch'
      )
      AND (
          SELECT r.data->>'merged' FROM task_events r
          WHERE r.task_id = w.task_id AND r.kind = 'pr.agent_reviewed'
          ORDER BY r.created_at DESC LIMIT 1
      ) = 'true'
      AND NOT EXISTS (
          SELECT 1 FROM task_events e
          WHERE e.task_id = w.task_id AND e.kind = 'workflow.escalated'
            AND e.created_at > (
                SELECT max(r.created_at) FROM task_events r
                WHERE r.task_id = w.task_id AND r.kind = 'pr.agent_reviewed'
            )
      )
    RETURNING w.task_id
)
UPDATE task_pull_requests p
SET failures = 0, next_check_at = now()
FROM moved
WHERE p.task_id = moved.task_id AND p.kind = 'main'
"""

DOWN_SQL = """
UPDATE task_workflows SET needs = 'human_code_review' WHERE needs = 'merge_confirmation'
"""


def upgrade() -> None:
    op.execute(MOVE_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
