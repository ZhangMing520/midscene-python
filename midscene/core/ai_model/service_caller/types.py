"""Caller errors (upstream service-caller/types.ts)."""

from typing import Any, Dict, Optional

class AIResponseParseError(Exception):
    """Error that preserves usage and raw response when AI parsing fails."""

    def __init__(
        self,
        message: str,
        raw_response: str,
        usage: Optional[Dict[str, Any]] = None,
        raw_assistant_output: Optional[Dict[str, Any]] = None,
        reasoning_content: Optional[str] = None,
    ):
        super().__init__(message)
        self.raw_response = raw_response
        self.usage = usage
        self.raw_assistant_output = raw_assistant_output
        self.reasoning_content = reasoning_content


class CodexAppServerNotSupportedError(NotImplementedError):
    pass

DEFAULT_MODEL_PROTOCOL = "openai-chat"
