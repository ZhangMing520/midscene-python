"""Cache configuration (upstream agent/cache-config.ts)."""

from typing import Optional

from midscene.core.agent.task_cache import TaskCache
from midscene.shared.env import is_cache_enabled


def get_task_cache(agent) -> Optional[TaskCache]:
    if agent._task_cache is not None:
        return agent._task_cache

    cache_config = getattr(agent.options, "cache", None)
    cache_id = getattr(agent.options, "cache_id", None)
    enabled = is_cache_enabled()
    read_only = False
    write_only = False
    cache_dir: Optional[str] = None

    if isinstance(cache_config, dict):
        strategy = cache_config.get("strategy") or "read-write"
        if strategy not in ("read-only", "read-write", "write-only"):
            raise ValueError(
                'cache.strategy must be one of "read-only", "read-write", '
                f'"write-only", but received "{strategy}"'
            )
        read_only = strategy == "read-only"
        write_only = strategy == "write-only"
        cache_id = cache_config.get("id") or cache_id
        cache_dir = cache_config.get("cacheDir") or cache_config.get("cache_dir")
        enabled = True
    elif isinstance(cache_config, str):
        cache_id = cache_config
        enabled = True
    elif cache_config is False:
        return None

    if not enabled and not cache_id:
        return None
    agent._task_cache = TaskCache(
        cache_id=cache_id or "midscene-python",
        enabled=True,
        read_only_mode=read_only,
        write_only_mode=write_only,
        cache_dir=cache_dir,
    )
    return agent._task_cache
