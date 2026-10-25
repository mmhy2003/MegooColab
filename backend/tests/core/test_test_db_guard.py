import os
import subprocess
import sys
from pathlib import Path

from app.core.db import engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_suite_runs_against_a_test_database():
    assert engine.url.database.endswith("_test")


def test_conftest_refuses_a_non_test_database():
    # The guard fires at conftest import, before any connection, so the dev DB is never touched.
    env = {**os.environ, "TEST_DATABASE_URL": "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo"}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_health.py"],
        check=False, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode != 0
    assert "Refusing to run tests" in r.stdout + r.stderr
