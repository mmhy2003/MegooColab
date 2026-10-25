from app.core.db import engine


def test_suite_runs_against_a_test_database():
    assert engine.url.database.endswith("_test")
