"""Namespaced init-arg helpers (upstream agent-tools/init-arg-utils.ts)."""

from typing import Any, Dict, List, Optional

from midscene.shared.agent_tools.types import ToolSchema
from midscene.shared.key_alias_utils import get_key_aliases, is_record


def _read_aliased_value(args: Dict[str, Any], key: str) -> Any:
    for alias in get_key_aliases(key):
        if alias in args:
            return args[alias]
    return None


def _read_namespaced_arg(
    args: Dict[str, Any], namespace: str, key: str
) -> Any:
    """Read namespace object first, then flat dotted form, then bare key."""
    namespaced_args = _read_aliased_value(args, namespace)
    if is_record(namespaced_args):
        nested_value = _read_aliased_value(namespaced_args, key)
        if nested_value is not None:
            return nested_value

    dotted_value = _read_aliased_value(args, f"{namespace}.{key}")
    if dotted_value is not None:
        return dotted_value

    return _read_aliased_value(args, key)


def extract_namespaced_args(
    args: Dict[str, Any], namespace: str, keys: List[str]
) -> Optional[Dict[str, Any]]:
    extracted: Dict[str, Any] = {}
    for key in keys:
        value = _read_namespaced_arg(args, namespace, key)
        if value is not None:
            extracted[key] = value
    return extracted or None


def sanitize_namespaced_args(
    args: Dict[str, Any], namespace: str, keys: List[str]
) -> Dict[str, Any]:
    excluded = set(get_key_aliases(namespace))
    for key in keys:
        excluded.update(get_key_aliases(key))
        excluded.update(get_key_aliases(f"{namespace}.{key}"))
    return {key: value for key, value in args.items() if key not in excluded}


def create_namespaced_init_arg_schema(
    namespace: str, shape: Dict[str, Dict[str, Any]]
) -> ToolSchema:
    """Build a flat schema keyed by dotted ``"<namespace>.<field>"`` names."""
    return {
        f"{namespace}.{key}": value for key, value in shape.items()
    }


__all__ = [
    "create_namespaced_init_arg_schema",
    "extract_namespaced_args",
    "sanitize_namespaced_args",
]
