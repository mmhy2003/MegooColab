"""Imports every model module so Base.metadata is complete (Alembic, tests)."""

from app.audit import models as audit_models  # noqa: F401
from app.auth import models as auth_models  # noqa: F401
from app.org import models as org_models  # noqa: F401
from app.projects import models as projects_models  # noqa: F401
from app.tasks import models as tasks_models  # noqa: F401
from app.teams import models as teams_models  # noqa: F401
