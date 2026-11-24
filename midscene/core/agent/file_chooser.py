"""File chooser handling (upstream agent/file-chooser.ts)."""

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from midscene.core.agent.utils import normalize_file_paths
from midscene.core.device import _supports
from midscene.core.types import AbstractInterface, FileChooserHandler

_FILE_CHOOSER_ACCEPT_KEYS = ("fileChooserAccept", "file_chooser_accept")


_FILE_CHOOSER_ALLOWED_DIR_KEYS = ("fileChooserAllowedDir", "file_chooser_allowed_dir")


def normalize_file_chooser_accept(files: Any) -> list[str]:
    """Resolve one or more files for a file chooser accept callback."""
    return normalize_file_paths(files)


# Backward-compatible private alias.
_normalize_file_paths = normalize_file_chooser_accept


def normalize_file_chooser_accept_in_allowed_dir(
    files: Any, allowed_dir: str
) -> list[str]:
    """Resolve files relative to `allowed_dir` and reject paths escaping it
    (upstream normalizeFileChooserAcceptInAllowedDir)."""
    allowed = Path(allowed_dir).expanduser().resolve()
    items = files if isinstance(files, (list, tuple)) else [files]
    resolved_files: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item:
            raise ValueError("File path must be a non-empty string")
        raw = Path(item).expanduser()
        resolved = (raw if raw.is_absolute() else allowed / raw).resolve()
        try:
            resolved.relative_to(allowed)
        except ValueError:
            raise ValueError(
                "File chooser path must be inside the configured "
                f"fileChooserAllowedDir: {item}"
            ) from None
        resolved_files.append(str(resolved))
    return normalize_file_chooser_accept(resolved_files)


# Backward-compatible private alias.
_normalize_file_chooser_accept_in_allowed_dir = (
    normalize_file_chooser_accept_in_allowed_dir
)


async def _read_registration_error(registration: Any) -> BaseException | None:
    error = registration.get_error()
    if inspect.isawaitable(error):
        error = await error
    return error


class FileChooserAccepter:
    """Holds the file chooser configuration for one aiAct execution
    (upstream FileChooserAccepter)."""

    def __init__(self, interface: AbstractInterface):
        self._interface = interface
        self._registration = None

    async def register(self, files: Any) -> None:
        await self._replace(normalize_file_chooser_accept(files))

    async def register_from_allowed_dir(self, files: Any, allowed_dir: str) -> None:
        await self._replace(
            normalize_file_chooser_accept_in_allowed_dir(files, allowed_dir)
        )

    async def _replace(self, accepted_files: list[str]) -> None:
        previous_error = await self.clear()
        if previous_error:
            raise previous_error
        if not accepted_files:
            return
        if not _supports(self._interface, "register_file_chooser_listener"):
            raise RuntimeError(
                f"File upload is not supported on {self._interface.interface_type}"
            )

        async def handler(chooser: FileChooserHandler) -> None:
            await chooser.accept(accepted_files)

        self._registration = await self._interface.register_file_chooser_listener(
            handler
        )

    async def clear(self) -> BaseException | None:
        registration, self._registration = self._registration, None
        if registration is None:
            return None
        try:
            return await _read_registration_error(registration)
        finally:
            registration.dispose()


async def with_file_chooser(
    interface: AbstractInterface,
    files: list[str] | None,
    action: Callable[[], Any],
) -> Any:
    """Run `action` while accepting `files` on any file chooser dialog
    (upstream withFileChooser)."""
    if not files:
        return await action()
    if not _supports(interface, "register_file_chooser_listener"):
        raise RuntimeError(
            f"File upload is not supported on {interface.interface_type}"
        )

    async def handler(chooser: FileChooserHandler) -> None:
        await chooser.accept(files)

    registration = await interface.register_file_chooser_listener(handler)
    try:
        result = await action()
        error = await _read_registration_error(registration)
        if error:
            raise error
        return result
    finally:
        registration.dispose()


# Backward-compatible private aliases.
_FileChooserAccepter = FileChooserAccepter
_with_file_chooser = with_file_chooser


__all__ = [
    "FileChooserAccepter",
    "normalize_file_chooser_accept",
    "normalize_file_chooser_accept_in_allowed_dir",
    "with_file_chooser",
]
