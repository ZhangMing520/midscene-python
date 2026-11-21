"""CLI argument helpers (upstream packages/cli/src/args.ts)."""

from midscene.cli.config_options import YAML_TARGET_KEYS as _TARGET_KEYS


def _kebab_to_camel(value: str) -> str:
    parts = value.split("-")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _normalize_cli_value(value: str):
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if value.isdigit():
        return int(value)
    return value


def _parse_cli_target_overrides(raw: list) -> dict:
    """Parse unknown `--web.user-agent x`, `--android.device-id id` options
    (upstream yargs dot-notation). Only known target sections are kept."""
    overrides: dict = {}
    index = 0
    while index < len(raw):
        token = raw[index]
        index += 1
        if not token.startswith("--"):
            continue
        key = token[2:]
        value: object = True
        if index < len(raw) and not raw[index].startswith("--"):
            value = _normalize_cli_value(raw[index])
            index += 1
        target, dot, rest = key.partition(".")
        if not dot or target not in _TARGET_KEYS or not rest:
            continue
        path = [_kebab_to_camel(part) for part in rest.split(".") if part]
        if not path:
            continue
        section = overrides.setdefault(target, {})
        cursor = section
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
    return overrides


def _merge_cli_target_overrides(script: dict, overrides: dict) -> dict:
    """CLI target options are defaults; keys already in the script win
    (matching the batch runner's merge order)."""
    if not overrides:
        return script
    merged = dict(script)
    for target, values in overrides.items():
        existing = merged.get(target)
        merged[target] = (
            {**values, **existing} if isinstance(existing, dict) else dict(values)
        )
    return merged
