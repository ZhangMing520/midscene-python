"""File chooser handling (upstream agent/file-chooser.ts)."""

import inspect
from pathlib import Path
from typing import Any, Callable, List, Optional

from midscene.core.device import _supports
from midscene.core.types import AbstractInterface, FileChooserHandler

_FILE_CHOOSER_ACCEPT_KEYS = ("fileChooserAccept", "file_chooser_accept")


_FILE_CHOOSER_ALLOWED_DIR_KEYS = ("fileChooserAllowedDir", "file_chooser_allowed_dir")


def _normalize_file_paths(files: Any) -> List[str]:
    """Resolve file chooser paths and fail early when a file is missing
    (upstream normalizeFilePaths)."""
    items = files if isinstance(files, (list, tuple)) else [files]
    normalized: List[str] = []
    for item in items:
        if not isinstance(item, str) or not item:
            raise ValueError("File path must be a non-empty string")
        resolved = Path(item).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(
                f"File not found: {item}. Resolved to: {resolved}. "
                f"Current working directory: {Path.cwd()}"
            )
        normalized.append(str(resolved))
    return normalized


def _normalize_file_chooser_accept_in_allowed_dir(
    files: Any, allowed_dir: str
) -> List[str]:
    """Resolve files relative to `allowed_dir` and reject paths escaping it
    (upstream normalizeFileChooserAcceptInAllowedDir)."""
    allowed = Path(allowed_dir).expanduser().resolve()
    items = files if isinstance(files, (list, tuple)) else [files]
    resolved_files: List[str] = []
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
    return _normalize_file_paths(resolved_files)


async def _read_registration_error(registration: Any) -> Optional[BaseException]:
    error = registration.get_error()
    if inspect.isawaitable(error):
        error = await error
    return error


class _FileChooserAccepter:
    """Holds the file chooser configuration for one aiAct execution
    (upstream FileChooserAccepter)."""

    def __init__(self, interface: AbstractInterface):
        self._interface = interface
        self._registration = None

    async def register(self, files: Any) -> None:
        await self._replace(_normalize_file_paths(files))

    async def register_from_allowed_dir(
        self, files: Any, allowed_dir: str
    ) -> None:
        await self._replace(
            _normalize_file_chooser_accept_in_allowed_dir(files, allowed_dir)
        )

    async def _replace(self, accepted_files: List[str]) -> None:
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

    async def clear(self) -> Optional[BaseException]:
        registration, self._registration = self._registration, None
        if registration is None:
            return None
        try:
            return await _read_registration_error(registration)
        finally:
            registration.dispose()


async def _with_file_chooser(
    interface: AbstractInterface,
    files: Optional[List[str]],
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
