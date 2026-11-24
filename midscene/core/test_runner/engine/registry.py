"""Workflow node registry (upstream test-runner/engine/registry.ts)."""

from collections.abc import Iterable

from midscene.core.test_runner.errors import DuplicateNodeError, NodeNotFoundError
from midscene.core.test_runner.node.define_node import define_node
from midscene.core.test_runner.node.types import NodeDefinition


def _validate_definition(node: NodeDefinition) -> None:
    define_node(
        node.name,
        node.execute,
        title=node.title,
        description=node.description,
        string_input_key=node.string_input_key,
        input_schema=node.input_schema,
    )


class NodeRegistry:
    def __init__(self, nodes: Iterable[NodeDefinition] | None = None) -> None:
        self._nodes: dict[str, NodeDefinition] = {}
        for node in nodes or ():
            self.register(node)

    def register(self, node: NodeDefinition) -> "NodeRegistry":
        _validate_definition(node)
        if node.name in self._nodes:
            raise DuplicateNodeError(node.name)
        self._nodes[node.name] = node
        return self

    def get(self, name: str) -> NodeDefinition | None:
        return self._nodes.get(name)

    def require(self, name: str) -> NodeDefinition:
        node = self.get(name)
        if node is None:
            raise NodeNotFoundError(name)
        return node

    def has(self, name: str) -> bool:
        return name in self._nodes

    def names(self) -> list[str]:
        return list(self._nodes.keys())

    def definitions(self) -> list[NodeDefinition]:
        return list(self._nodes.values())


__all__ = ["NodeRegistry"]
