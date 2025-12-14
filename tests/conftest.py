from __future__ import annotations

import os
import tempfile
from pathlib import Path


# Ensure the global RUN_REGISTRY uses an isolated sqlite file during pytest collection/import,
# before any fixtures/monkeypatching runs.
_db_root = Path(tempfile.mkdtemp(prefix="fort_gym_test_"))
os.environ.setdefault("FORT_GYM_DB_PATH", str(_db_root / "fort_gym.sqlite3"))

