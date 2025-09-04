from __future__ import annotations
import os
from datetime import datetime, timezone

APP_VERSION = os.getenv("APP_VERSION", "0.1.0-dev")
GIT_SHA = os.getenv("GIT_SHA", "local")
BUILD_TIME_UTC = os.getenv("BUILD_TIME_UTC") or datetime.now(timezone.utc).isoformat()
