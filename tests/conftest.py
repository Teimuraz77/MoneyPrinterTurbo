import os
import shutil
from pathlib import Path

import pytest

from wwnn.config import Settings
from wwnn.db.migrate import open_db

os.environ.setdefault("WWNN_ENV_FILE", "/nonexistent/.env")   # never pick up a developer's .env

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(env_file=Path("/nonexistent/.env"), data_dir=tmp_path / "data",
                             db_path=tmp_path / "data" / "wwnn.db", assets_dir=tmp_path / "assets",
                             dry_run=True, telegram_allowed_user_ids="111,222")


@pytest.fixture
def conn(settings):
    c = open_db(settings.db_path)
    yield c
    c.close()
