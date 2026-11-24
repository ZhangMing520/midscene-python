"""Define a workflow node (upstream test-runner/node/define-node.ts)."""

from collections.abc import Callable
from typing import Any

from midscene.core.test_runner.errors import NodeDefinitionError
from midscene.core.test_runner.node.types import NodeDefinition


def _validate_optional_text(value: Any, field: str, node: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise NodeDefinitionError(
            f'Node "{node}" {field} must be a non-empty string.',
            {"node": node, "field": field},
        )


def _validate_input_schema(schema: Any, node: str) -> None:
    if schema is None:
        return
    if not isinstance(schema, dict):
        raise NodeDefinitionError(
            f'Node "{node}" inputSchema must be an object schema.',
            {"node": node, "field": "inputSchema"},
        )
    if "$" in schema:
        raise NodeDefinitionError(
            f'Node "{node}" inputSchema must not declare "$" as an input property.',
            {"node": node, "field": "inputSchema.$"},
        )


def define_node(
    name: str,
    execute: Callable[..., Any],
    title: str | None = None,
    description: str | None = None,
    string_input_key: str | None = None,
    input_schema: dict[str, Any] | None = None,
) -> NodeDefinition:
    """Validate and build a node definition."""
    if not isinstance(name, str) or not name.strip():
        raise NodeDefinitionError("Node name must be a non-empty string.")
    _validate_optional_text(title, "title", name)
    _validate_optional_text(description, "description", name)
    if string_input_key is not None and (
        not isinstance(string_input_key, str) or not string_input_key.strip()
    ):
        raise NodeDefinitionError(
            f'Node "{name}" stringInputKey must be a non-empty string or false.',
            {"node": name, "field": "stringInputKey"},
        )
    _validate_input_schema(input_schema, name)
    if (
        isinstance(string_input_key, str)
        and isinstance(input_schema, dict)
        and string_input_key not in input_schema
    ):
        raise NodeDefinitionError(
            f'Node "{name}" stringInputKey must reference a field in inputSchema.',
            {"node": name, "field": "stringInputKey"},
        )
    if not callable(execute):
        raise NodeDefinitionError(
            f'Node "{name}" must provide an execute function.', {"node": name}
        )
    return NodeDefinition(
        name=name,
        execute=execute,
        title=title,
        description=description,
        string_input_key=string_input_key,
        input_schema=input_schema,
    )
