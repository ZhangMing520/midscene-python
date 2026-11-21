"""CLI report session persistence (upstream agent-tools/cli-report-session.ts)."""

import json
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from midscene.shared.env import get_midscene_run_dir

_SESSION_DIR_NAME = "cli-report-session"
_VERSION = 1


def _sanitize_session_name(session_name: str) -> str:
    sanitized = "".join(
        char if (char.isalnum() or char in "._-") else "_"
        for char in session_name
    )
    return sanitized or "default"


def _sanitize_file_segment(segment: str) -> str:
    sanitized = "".join(
        char if (char.isalnum() or char in "._-") else "_" for char in segment
    )
    return (sanitized or "unknown")[:80]


def _ensure_html_file_name(report_file_name: str) -> str:
    return (
        report_file_name
        if report_file_name.endswith(".html")
        else f"{report_file_name}.html"
    )


def _format_date_for_file_name(date: datetime) -> str:
    day = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
    time = f"{date.hour:02d}-{date.minute:02d}-{date.second:02d}"
    return f"{day}_{time}"


def _random_id() -> str:
    alphabet = string.digits + string.ascii_lowercase
    return "".join(random.choice(alphabet) for _ in range(8))


def _get_cli_report_session_dir() -> str:
    return get_midscene_run_dir(_SESSION_DIR_NAME)


def _get_cli_report_session_path(session_name: str) -> str:
    return str(
        Path(_get_cli_report_session_dir()) / f"{_sanitize_session_name(session_name)}.json"
    )


def generate_cli_report_session(
    session_name: str, target_identity: Optional[str] = None
) -> Dict[str, Any]:
    identity_segment = (
        f"-{_sanitize_file_segment(target_identity)}" if target_identity else ""
    )
    report_file_name = (
        f"{_sanitize_session_name(session_name)}"
        f"{identity_segment}-{_format_date_for_file_name(datetime.now())}-{_random_id()}"
    )
    report_path = str(
        Path(get_midscene_run_dir("report"))
        / _ensure_html_file_name(report_file_name)
    )
    session: Dict[str, Any] = {
        "version": _VERSION,
        "sessionName": session_name,
        "reportFileName": report_file_name,
        "reportPath": report_path,
        "createdAt": int(datetime.now().timestamp() * 1000),
    }
    if target_identity:
        session["targetIdentity"] = target_identity
    return session


def write_cli_report_session(session: Dict[str, Any]) -> None:
    path = _get_cli_report_session_path(session["sessionName"])
    Path(path).write_text(
        json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def create_cli_report_session(
    session_name: str, target_identity: Optional[str] = None
) -> Dict[str, Any]:
    session = generate_cli_report_session(session_name, target_identity)
    write_cli_report_session(session)
    return session


def read_cli_report_session(session_name: str) -> Optional[Dict[str, Any]]:
    session_path = _get_cli_report_session_path(session_name)
    if not Path(session_path).exists():
        return None
    try:
        parsed = json.loads(Path(session_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    report_file_name = parsed.get("reportFileName")
    if (
        parsed.get("version") != _VERSION
        or parsed.get("sessionName") != session_name
        or not isinstance(report_file_name, str)
        or not report_file_name.strip()
        or "/" in report_file_name
        or "\\" in report_file_name
    ):
        return None
    return parsed


__all__ = [
    "create_cli_report_session",
    "generate_cli_report_session",
    "read_cli_report_session",
    "write_cli_report_session",
]
