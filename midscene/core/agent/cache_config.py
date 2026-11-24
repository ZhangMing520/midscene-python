"""Cache configuration (upstream agent/cache-config.ts)."""

from typing import Any

from midscene.core.agent.task_cache import TaskCache
from midscene.core.utils import process_cache_config

_CACHE_STRATEGIES = ("read-only", "read-write", "write-only")
_CACHE_STRATEGY_VALUES = ", ".join(f'"{value}"' for value in _CACHE_STRATEGIES)


def _option(opts: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(opts, dict):
            if key in opts:
                return opts[key]
        elif hasattr(opts, key):
            return getattr(opts, key)
    return default


def validate_agent_cache_input(cache: Any) -> None:
    """Reject cache configs that cannot identify an explicit cache id."""
    if cache is True:
        raise ValueError(
            "cache: true requires an explicit cache ID. Please provide:\n"
            'Example: cache: { id: "my-cache-id" }'
        )

    if not cache or not isinstance(cache, dict):
        return

    if not cache.get("id"):
        raise ValueError(
            "cache configuration requires an explicit id.\n"
            'Example: cache: { id: "my-cache-id" }'
        )

    cache_dir = cache.get("cacheDir", cache.get("cache_dir"))
    if cache_dir is not None and (
        not isinstance(cache_dir, str) or not cache_dir.strip()
    ):
        raise ValueError(
            "cache.cacheDir must be a non-empty string when provided.\n"
            'Example: cache: { id: "my-cache-id", cacheDir: "./my-cache-dir" }'
        )

    strategy = cache.get("strategy")
    if strategy is not None and not isinstance(strategy, str):
        raise ValueError(
            "cache.strategy must be a string when provided, but received "
            f"type {type(strategy).__name__}"
        )
    if strategy is not None and strategy not in _CACHE_STRATEGIES:
        raise ValueError(
            f"cache.strategy must be one of {_CACHE_STRATEGY_VALUES}, "
            f'but received "{strategy}"'
        )


def normalize_agent_cache_config(opts: Any) -> dict[str, Any] | None:
    """Return the normalized cache settings for an Agent's options."""
    cache = _option(opts, "cache")
    cache_id = _option(opts, "cacheId", "cache_id")
    validate_agent_cache_input(cache)

    if isinstance(cache, str) and cache.strip():
        return {
            "id": cache.strip(),
            "enabled": True,
            "readOnly": False,
            "writeOnly": False,
            "cacheDir": None,
        }

    cache_config = process_cache_config(cache, cache_id or "default")
    if not cache_config and cache_id:
        cache_config = {"id": cache_id}
    if not cache_config:
        return None

    if isinstance(cache_config, dict):
        config_id = cache_config.get("id")
        strategy = cache_config.get("strategy") or "read-write"
        read_only = strategy == "read-only"
        write_only = strategy == "write-only"
        cache_dir = cache_config.get("cacheDir", cache_config.get("cache_dir"))
        return {
            "id": config_id,
            "enabled": not write_only,
            "readOnly": read_only,
            "writeOnly": write_only,
            "cacheDir": cache_dir.strip() if isinstance(cache_dir, str) else None,
        }
    return None


def get_task_cache(agent) -> TaskCache | None:
    if agent._task_cache is not None:
        return agent._task_cache

    config = normalize_agent_cache_config(agent.options)
    if config is None:
        return None

    agent._task_cache = TaskCache(
        cache_id=config["id"] or "midscene-python",
        enabled=config["enabled"],
        read_only_mode=config["readOnly"],
        write_only_mode=config["writeOnly"],
        cache_dir=config["cacheDir"],
    )
    return agent._task_cache


__all__ = [
    "normalize_agent_cache_config",
    "validate_agent_cache_input",
    "get_task_cache",
]
