"""Base class for platform-specific Midscene tools.

Port of upstream agent-tools/base-tools.ts. The Python port keeps the same
declarative init-arg spec, action-space tool generation and lazy agent
lifecycle.
"""

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from midscene.shared.agent_tools.cli_report_session import (
    generate_cli_report_session,
    read_cli_report_session,
    write_cli_report_session,
)
from midscene.shared.agent_tools.init_arg_utils import (
    create_namespaced_init_arg_schema,
    extract_namespaced_args,
    sanitize_namespaced_args,
)
from midscene.shared.agent_tools.tool_defaults import (
    ToolDefaults,
    merge_tool_defaults,
)
from midscene.shared.agent_tools.tool_generator import (
    generate_common_tools,
    generate_tools_from_action_space,
)
from midscene.shared.agent_tools.types import (
    BaseAgent,
    BaseDevice,
    ToolCliMetadata,
    ToolDefinition,
    ToolResult,
    ToolSchema,
)
from midscene.shared.img import parse_base64
from midscene.shared.key_alias_utils import camel_to_kebab, get_key_aliases
from midscene.shared.logger import get_logger

debug = get_logger("agent-tools:base-tools")


@dataclass
class InitArgSpec:
    """Declarative description of a platform's agent init args."""

    namespace: str
    shape: ToolSchema
    cli: Optional[Dict[str, Any]] = None
    adapt: Optional[Callable[[Optional[Dict[str, Any]]], Any]] = None


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def resolve_device_action_space(device: Any) -> List[Any]:
    """Read an action space from a temporary device.

    Platform devices may expose primitive method names instead of
    DeviceActions; those are mapped back onto the interface action space.
    """
    getter = getattr(device, "action_space", None)
    if getter is None:
        return _action_space_for_interface(device)

    result = await _maybe_await(getter())
    if not isinstance(result, list) or not result:
        return _action_space_for_interface(device)
    if not isinstance(result[0], str):
        return result

    full = _action_space_for_interface(device)
    wanted = set(result)
    matched = [
        action
        for action in full
        if getattr(action, "name", None) in wanted
        or getattr(action, "primitive", None) in wanted
        or str(getattr(action, "name", "")).lower() in wanted
    ]
    return matched or full


def _action_space_for_interface(device: Any) -> List[Any]:
    interface_type = getattr(device, "interface_type", None)
    if interface_type is None:
        return []
    from midscene.core.device import build_action_space_for

    value = (
        interface_type.value
        if hasattr(interface_type, "value")
        else str(interface_type)
    )
    return list(build_action_space_for(value))


class BaseMidsceneTools(ABC):
    """Base class for platform-specific Midscene tools."""

    init_arg_spec: Optional[InitArgSpec] = None

    def __init__(self) -> None:
        self.agent: Optional[BaseAgent] = None
        self.tool_definitions: List[ToolDefinition] = []
        self.tool_defaults: ToolDefaults = {}

    # -- init args ---------------------------------------------------------

    def _get_init_arg_keys(self) -> List[str]:
        return list(self.init_arg_spec.shape) if self.init_arg_spec else []

    def extract_agent_init_param(
        self, args: Dict[str, Any]
    ) -> Any:
        if not self.init_arg_spec:
            return None
        extracted = extract_namespaced_args(
            args, self.init_arg_spec.namespace, self._get_init_arg_keys()
        )
        if self.init_arg_spec.adapt:
            return self.init_arg_spec.adapt(extracted)
        return extracted

    def sanitize_tool_args(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not self.init_arg_spec:
            return args
        return sanitize_namespaced_args(
            args, self.init_arg_spec.namespace, self._get_init_arg_keys()
        )

    def get_agent_init_arg_schema(self) -> ToolSchema:
        if not self.init_arg_spec:
            return {}
        return create_namespaced_init_arg_schema(
            self.init_arg_spec.namespace, self.init_arg_spec.shape
        )

    def get_agent_init_arg_cli_metadata(
        self,
    ) -> Optional[ToolCliMetadata]:
        if not self.init_arg_spec or not self.init_arg_spec.cli:
            return None

        cli = self.init_arg_spec.cli
        prefer_bare_keys = bool(cli.get("preferBareKeys"))
        preferred_names = cli.get("preferredNames") or {}
        options: Dict[str, Any] = {}

        for key in self._get_init_arg_keys():
            canonical_key = f"{self.init_arg_spec.namespace}.{key}"
            preferred_name = preferred_names.get(key) or (
                camel_to_kebab(key) if prefer_bare_keys else canonical_key
            )
            accepted_names = {
                preferred_name,
                *(
                    get_key_aliases(key)
                    if prefer_bare_keys
                    else get_key_aliases(canonical_key)
                ),
            }
            accepted_names.discard(preferred_name)
            options[canonical_key] = {
                "preferredName": preferred_name,
                "aliases": list(accepted_names),
            }

        return {"options": options}

    # -- hooks -------------------------------------------------------------

    @abstractmethod
    async def ensure_agent(self, init_param: Any = None) -> BaseAgent:
        """Create or return the platform agent."""

    @abstractmethod
    def create_temporary_device(self) -> BaseDevice:
        """Create a temporary device to read the action space."""

    def prepare_platform_tools(self) -> List[ToolDefinition]:
        return []

    def get_cli_report_session_name(self) -> Optional[str]:
        return None

    def create_new_cli_report_session(
        self, target_identity: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        session_name = self.get_cli_report_session_name()
        if not session_name:
            return None
        return generate_cli_report_session(session_name, target_identity)

    def commit_cli_report_session(
        self, session: Optional[Dict[str, Any]]
    ) -> None:
        if session:
            write_cli_report_session(session)

    def read_cli_report_file_name(self) -> Optional[str]:
        session_name = self.get_cli_report_session_name()
        if not session_name:
            return None
        session = read_cli_report_session(session_name)
        return session.get("reportFileName") if session else None

    def read_cli_report_agent_options(
        self,
    ) -> Optional[Dict[str, Any]]:
        report_file_name = self.read_cli_report_file_name()
        if not report_file_name:
            return None
        return {
            "reportFileName": report_file_name,
            "reportAttributes": {"data-group-id": report_file_name},
        }

    # -- lifecycle ---------------------------------------------------------

    async def init_tools(self) -> None:
        """Initialize all tools by querying the action space."""
        self.tool_definitions = []

        # 1. Platform-specific tools do not require an agent.
        self.tool_definitions.extend(self.prepare_platform_tools())

        # 2. Agent action space, or a temporary device for deferred startup.
        if self.agent is not None:
            get_action_space = getattr(self.agent, "get_action_space", None)
            action_space = (
                await _maybe_await(get_action_space())
                if get_action_space is not None
                else list(getattr(self.agent, "action_space", []) or [])
            )
            debug.info(
                "Action space from agent: %s",
                ", ".join(
                    getattr(action, "name", str(action)) for action in action_space
                ),
            )
        else:
            temp_device = self.create_temporary_device()
            action_space = await resolve_device_action_space(temp_device)
            destroy = getattr(temp_device, "destroy", None)
            if destroy is not None:
                await _maybe_await(destroy())
            debug.info(
                "Action space from temporary device: %s",
                ", ".join(
                    getattr(action, "name", str(action)) for action in action_space
                ),
            )

        async def get_agent(args: Optional[Dict[str, Any]] = None) -> BaseAgent:
            return await self.ensure_agent(
                self.extract_agent_init_param(args or {})
            )

        action_tools = generate_tools_from_action_space(
            action_space,
            get_agent,
            self.sanitize_tool_args,
            self.get_agent_init_arg_schema(),
            self.get_agent_init_arg_cli_metadata(),
            self.tool_defaults,
        )
        common_tools = generate_common_tools(
            get_agent,
            self.get_agent_init_arg_schema(),
            self.get_agent_init_arg_cli_metadata(),
            self.tool_defaults,
        )
        self.tool_definitions.extend(action_tools + common_tools)

        debug.info("Total tools prepared: %s", len(self.tool_definitions))

    async def destroy(self) -> None:
        if self.agent is not None:
            destroy = getattr(self.agent, "destroy", None)
            if destroy is not None:
                await _maybe_await(destroy())

    def get_tool_definitions(self) -> List[ToolDefinition]:
        return self.tool_definitions

    def get_cli_tool_definitions(self) -> List[ToolDefinition]:
        """Commands that exist only on the foreground CLI surface."""
        from midscene.shared.cli.record_command import create_record_cli_command

        async def get_agent(args: Optional[Dict[str, Any]] = None) -> BaseAgent:
            return await self.ensure_agent(
                self.extract_agent_init_param(args or {})
            )

        return [
            create_record_cli_command(
                get_agent,
                self.get_agent_init_arg_schema(),
                self.get_agent_init_arg_cli_metadata(),
            )
        ]

    def set_agent(self, agent: BaseAgent) -> None:
        self.agent = agent

    def set_tool_defaults(self, tool_defaults: ToolDefaults) -> None:
        self.tool_defaults = merge_tool_defaults(
            self.tool_defaults, tool_defaults
        )

    # -- helpers -----------------------------------------------------------

    def build_screenshot_content(self, screenshot: str) -> List[Dict[str, Any]]:
        parsed = parse_base64(screenshot)
        return [
            {
                "type": "image",
                "data": parsed["body"],
                "mimeType": parsed["mimeType"],
            }
        ]

    def build_text_result(self, text: str) -> ToolResult:
        return ToolResult([{"type": "text", "text": text}])

    def create_disconnect_handler(self, platform_name: str) -> Any:
        async def handler(_args: Optional[Dict[str, Any]] = None) -> ToolResult:
            if self.agent is None:
                return self.build_text_result(
                    "No active connection to disconnect"
                )
            try:
                destroy = getattr(self.agent, "destroy", None)
                if destroy is not None:
                    await _maybe_await(destroy())
            except Exception as error:  # noqa: BLE001
                debug.warning("Failed to destroy agent during disconnect: %s", error)
            self.agent = None
            return self.build_text_result(f"Disconnected from {platform_name}")

        return handler


__all__ = ["BaseMidsceneTools", "InitArgSpec", "resolve_device_action_space"]
