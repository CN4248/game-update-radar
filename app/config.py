"""Runtime paths and constants. Everything persistent lives under CONFIG_DIR."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Game Update Radar"
APP_VERSION = "1.0.0"
BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_DIR = Path(os.getenv("CONFIG_DIR") or (BASE_DIR / "data")).resolve()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CONFIG_DIR / "radar.db"
SECRET_PATH = CONFIG_DIR / "secret.key"
LOG_PATH = CONFIG_DIR / "radar.log"
WEB_DIR = BASE_DIR / "web"

DEFAULT_TZ = os.getenv("TZ", "Asia/Shanghai")
HTTP_TIMEOUT = 30.0
MAX_ITEMS_PER_SCAN = 80
MAX_NEW_ITEMS_TO_CLASSIFY = 25
MASK = "••••••••"
KEEP = "__KEEP__"
CLEAR = "__CLEAR__"
