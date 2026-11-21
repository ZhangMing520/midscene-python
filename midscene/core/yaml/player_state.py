"""Legacy YAML player state (upstream yaml/player-state.ts).

The upstream implementation keeps per-player state in a module-level WeakMap so
CJS and ESM copies share it. Python uses a WeakKeyDictionary keyed by the player.
"""

from typing import Any, Dict
from weakref import WeakKeyDictionary


class LegacyYamlPlayerState(Dict[str, Any]):
    """Includes executionResult / executionRecord / fallbackReportFileName."""


_states: "WeakKeyDictionary[Any, LegacyYamlPlayerState]" = WeakKeyDictionary()


def initialize_legacy_yaml_player_state(player: Any) -> None:
    _states[player] = LegacyYamlPlayerState()


def get_legacy_yaml_player_state(player: Any) -> LegacyYamlPlayerState:
    state = _states.get(player)
    if state is None:
        raise RuntimeError("Expected an initialized YAML ScriptPlayer.")
    return state
