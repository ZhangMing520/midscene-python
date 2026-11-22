"""Env helpers: run dir, language, cache flags (upstream packages/shared/src/env/utils.ts)."""

try:  # Python >= 3.9
    import zoneinfo  # noqa: F401

    _HAS_ZONEINFO = True
except ImportError:  # pragma: no cover
    _HAS_ZONEINFO = False

import os
import time

from midscene.shared.common import (
    get_midscene_run_base_dir,
    get_midscene_run_sub_dir,
)
from midscene.shared.env.constants import (
    MIDSCENE_CACHE,
    MIDSCENE_PREFERRED_LANGUAGE,
    MIDSCENE_REPLANNING_CYCLE_LIMIT,
)


def get_midscene_run_dir(sub_dir: str = "") -> str:
    """Return (and create) the midscene output directory (MIDSCENE_RUN_DIR)."""
    if sub_dir:
        return get_midscene_run_sub_dir(sub_dir)
    return get_midscene_run_base_dir()


def get_preferred_language() -> str:
    prefer = os.environ.get(MIDSCENE_PREFERRED_LANGUAGE)
    if prefer:
        return prefer

    is_china = False
    if _HAS_ZONEINFO:
        try:
            tz = time.tzname
            _ = tz  # time.tzname alone is insufficient; try env TZ first
        except Exception:  # pragma: no cover
            pass
    tz_env = os.environ.get("TZ", "")
    # Match upstream behaviour: China timezone defaults to Chinese prompts.
    if tz_env == "Asia/Shanghai":
        is_china = True
    else:
        try:
            import datetime as _dt

            now = _dt.datetime.now().astimezone()
            offset = now.utcoffset() or _dt.timedelta(0)
            # CST (China Standard Time) is UTC+8 with no DST
            is_china = offset == _dt.timedelta(hours=8)
        except Exception:  # pragma: no cover
            is_china = False
    return "Chinese" if is_china else "English"


def is_cache_enabled() -> bool:
    value = os.environ.get(MIDSCENE_CACHE, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def get_replanning_cycle_limit(default: int = 20) -> int:
    raw = os.environ.get(MIDSCENE_REPLANNING_CYCLE_LIMIT)
    if not raw:
        return default
    try:
        value = int(float(raw))
        return value if value > 0 else default
    except ValueError:
        return default
