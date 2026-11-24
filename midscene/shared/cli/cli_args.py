"""CLI argument parsing and schema validation (upstream cli/cli-args.ts)."""

from typing import Any

from midscene.shared.cli.cli_error import CLIError
from midscene.shared.cli.cli_value import (
    _accepts_value,
    _type_names,
    parse_cli_value,
    parse_value,
)
from midscene.shared.key_alias_utils import get_key_aliases

__all__ = [
    "canonicalize_cli_arg_keys",
    "format_cli_validation_error",
    "get_cli_option_display",
    "parse_cli_args",
    "parse_value",
]


def _walk_cli_args(args: list[str], set_arg_value: Any) -> None:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("--"):
            index += 1
            continue

        body = arg[2:]
        eq_index = body.find("=")

        if eq_index >= 0:
            set_arg_value(body[:eq_index], body[eq_index + 1 :])
        elif index + 1 < len(args) and not args[index + 1].startswith("--"):
            index += 1
            set_arg_value(body, args[index])
        else:
            set_arg_value(body, True)
        index += 1


def _schema_of(defn: Any) -> dict[str, dict[str, Any]]:
    return getattr(defn, "schema", None) or {}


def _cli_options_of(defn: Any) -> dict[str, Any]:
    cli = getattr(defn, "cli", None)
    if cli is None:
        return {}
    if isinstance(cli, dict):
        return cli.get("options") or {}
    return getattr(cli, "options", None) or {}


def _option_attr(option: Any, name: str, default: Any = None) -> Any:
    if option is None:
        return default
    if isinstance(option, dict):
        if name in option:
            return option[name]
        snake = _camel_to_snake(name)
        return option.get(snake, default)
    if hasattr(option, name):
        return getattr(option, name)
    return getattr(option, _camel_to_snake(name), default)


def _camel_to_snake(name: str) -> str:
    result = []
    for char in name:
        if char.isupper():
            result.append("_")
            result.append(char.lower())
        else:
            result.append(char)
    return "".join(result)


def _build_cli_field_index(defn: Any) -> dict[str, dict[str, Any]]:
    field_by_cli_name: dict[str, dict[str, Any]] = {}
    options = _cli_options_of(defn)
    for schema_key, field in _schema_of(defn).items():
        for cli_name in _get_accepted_cli_option_names(
            schema_key, options.get(schema_key)
        ):
            field_by_cli_name[cli_name] = field
    return field_by_cli_name


def parse_cli_args(args: list[str], defn: Any | None = None) -> dict[str, Any]:
    field_by_cli_name = _build_cli_field_index(defn) if defn else None
    tokens_by_name: dict[str, list[Any]] = {}
    _walk_cli_args(
        args,
        lambda key, raw: tokens_by_name.setdefault(key, []).append(raw),
    )

    result: dict[str, Any] = {}
    for key, tokens in tokens_by_name.items():
        element_index = 0
        for raw in tokens:
            existing = result.get(key)
            field = field_by_cli_name.get(key) if field_by_cli_name else None
            if raw is True:
                value: Any = True
            else:
                value = parse_cli_value(
                    raw,
                    field,
                    element_index if len(tokens) > 1 else None,
                )
            if existing is None:
                result[key] = value
            elif isinstance(existing, list):
                existing.append(value)
            else:
                result[key] = [existing, value]
            element_index = len(result[key]) if isinstance(result[key], list) else 1

    return result


def _format_cli_option_name(name: str) -> str:
    return f"--{name}"


def get_cli_option_display(key: str, cli_option: Any | None = None) -> dict[str, Any]:
    preferred = _option_attr(cli_option, "preferredName", None) if cli_option else None
    label = _format_cli_option_name(preferred or key)
    raw_aliases = (_option_attr(cli_option, "aliases", []) or []) if cli_option else []
    aliases: list[str] = []
    for alias in dict.fromkeys(raw_aliases):
        formatted = _format_cli_option_name(alias)
        if formatted != label:
            aliases.append(formatted)
    return {"label": label, "aliases": aliases}


def _get_accepted_cli_option_names(
    key: str, cli_option: Any | None = None
) -> list[str]:
    if cli_option is not None:
        preferred = _option_attr(cli_option, "preferredName", None) or key
        aliases = _option_attr(cli_option, "aliases", []) or []
        return list(dict.fromkeys([preferred, *aliases]))
    return list(dict.fromkeys([key, *get_key_aliases(key)]))


def _is_optional(field: dict[str, Any]) -> bool:
    return bool(field.get("optional", False))


def _describe_expected(field: dict[str, Any]) -> str:
    names = _type_names(field)
    return " or ".join(names) if names else "value"


def _build_disallowed_cli_spellings(defn: Any) -> set:
    disallowed = set()
    options = _cli_options_of(defn)

    for key in _schema_of(defn):
        cli_option = options.get(key)
        accepted_names = set(_get_accepted_cli_option_names(key, cli_option))
        known_spellings = {key, *get_key_aliases(key)}
        preferred = (
            _option_attr(cli_option, "preferredName", None) if cli_option else None
        )
        if preferred:
            known_spellings.update(get_key_aliases(preferred))
        known_spellings.update(_option_attr(cli_option, "aliases", []) or [])

        for spelling in known_spellings:
            if spelling not in accepted_names:
                disallowed.add(spelling)

    return disallowed


def format_cli_validation_error(
    script_name: str,
    command_name: str,
    defn: Any,
    raw_args: dict[str, Any],
) -> str | None:
    schema = _schema_of(defn)
    if not schema:
        return None

    accepted_by_key = {
        key: _get_accepted_cli_option_names(key, _cli_options_of(defn).get(key))
        for key in schema
    }
    accepted_names = {name for names in accepted_by_key.values() for name in names}

    disallowed_spellings = _build_disallowed_cli_spellings(defn)
    unknown_keys = [key for key in raw_args if key not in accepted_names]
    if unknown_keys:
        messages = []
        for key in unknown_keys:
            if key in disallowed_spellings:
                messages.append(
                    f'Unsupported option "--{key}" for {script_name} {command_name}.'
                )
            else:
                messages.append(
                    f'Unknown option "--{key}" for {script_name} {command_name}.'
                )
        return "\n".join(messages)

    for key, field in schema.items():
        names = accepted_by_key[key]
        present = [name for name in names if name in raw_args]
        if not present:
            if not _is_optional(field):
                return (
                    f'Invalid value for "--{key}" in {script_name} '
                    f"{command_name}: Required"
                )
            continue
        for name in present:
            if _accepts_value(field, raw_args[name]) is False:
                return (
                    f'Invalid value for "--{name}" in {script_name} '
                    f"{command_name}: Expected {_describe_expected(field)}, "
                    f"received {_describe_value(raw_args[name])}"
                )

    return None


def _describe_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def canonicalize_cli_arg_keys(
    script_name: str,
    command_name: str,
    defn: Any,
    raw_args: dict[str, Any],
) -> dict[str, Any]:
    """Move accepted alias spellings onto the schema's canonical key.

    Throws ``CLIError`` on conflicting double-spellings (e.g. both
    ``--imageName`` and ``--image-name``).
    """
    schema = _schema_of(defn)
    if not schema:
        return raw_args

    result = dict(raw_args)
    options = _cli_options_of(defn)

    for schema_key in schema:
        accepted_spellings = _get_accepted_cli_option_names(
            schema_key, options.get(schema_key)
        )

        chosen_spelling: str | None = None
        chosen_value: Any = None

        for spelling in accepted_spellings:
            if spelling == schema_key or spelling not in result:
                continue
            if chosen_spelling is not None:
                raise CLIError(
                    f'Conflicting CLI options "--{chosen_spelling}" and '
                    f'"--{spelling}" for {script_name} {command_name}: both '
                    f'target "{schema_key}". Use one spelling.'
                )
            chosen_spelling = spelling
            chosen_value = result[spelling]

        if chosen_spelling is None:
            continue

        if schema_key in result and result[schema_key] != chosen_value:
            raise CLIError(
                f'Conflicting CLI options "--{schema_key}" and '
                f'"--{chosen_spelling}" for {script_name} {command_name}: both '
                f'target "{schema_key}". Use one spelling.'
            )

        result[schema_key] = chosen_value
        del result[chosen_spelling]

    return result
