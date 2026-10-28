import time
from types import SimpleNamespace

import pytest

from app.ratelimit import store

# one second into a window of every size (60, 900 and 3600 all divide it): a test can never straddle a window end
FIXED_NOW = 1_800_000_000 + 1


@pytest.fixture(autouse=True)
def _pinned_window(monkeypatch):
    monkeypatch.setattr(store, "time", SimpleNamespace(time=lambda: FIXED_NOW, monotonic=time.monotonic))
