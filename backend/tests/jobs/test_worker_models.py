"""The worker process knows every table: a job that touches tasks needs the tables their foreign keys point at."""

import subprocess
import sys

CHECK = (
    "from app.worker import load_handlers; load_handlers(); "
    "from app.core.db import Base; from app.tasks.models import Task; "
    "assert 'chats' in Base.metadata.tables; "
    "[fk.column for c in Task.__table__.c for fk in c.foreign_keys]"
)


def test_the_worker_loads_every_model():
    done = subprocess.run([sys.executable, "-c", CHECK], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
