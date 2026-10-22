"""Writes the OpenAPI schema to the given path (used by the frontend's `npm run gen:api`)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "openapi-export")

from app.main import app  # noqa: E402

Path(sys.argv[1]).write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
