"""Imports every model module so Base.metadata is complete (Alembic, tests)."""

from app.a2a import models as a2a_models  # noqa: F401
from app.agent_runs import models as agent_runs_models  # noqa: F401
from app.agents import models as agents_models  # noqa: F401
from app.ai import models as ai_models  # noqa: F401
from app.audit import models as audit_models  # noqa: F401
from app.auth import models as auth_models  # noqa: F401
from app.git import models as git_models  # noqa: F401
from app.jobs import models as jobs_models  # noqa: F401
from app.kb import models as kb_models  # noqa: F401
from app.memory import models as memory_models  # noqa: F401
from app.notifications import models as notifications_models  # noqa: F401
from app.org import models as org_models  # noqa: F401
from app.projects import models as projects_models  # noqa: F401
from app.push import models as push_models  # noqa: F401
from app.sprints import models as sprints_models  # noqa: F401
from app.tasks import models as tasks_models  # noqa: F401
from app.teams import models as teams_models  # noqa: F401
from app.workflow import models as workflow_models  # noqa: F401
