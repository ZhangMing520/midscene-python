"""Port of upstream packages/ios/tests/unit-test/input-focus.test.ts.

The upstream fixture injects a ``request`` function; Python's
``clear_input_with_focus`` takes the same injected transport, so the fixture
is ported almost verbatim.
"""

from typing import Any

import pytest

from midscene.ios.input_focus import clear_input_with_focus
from midscene.webdriver import WebDriverRequestError


def protocol_error(code: str) -> WebDriverRequestError:
    return WebDriverRequestError(code, 404, code)


class Fixture:
    def __init__(
        self,
        *,
        blur: bool = False,
        stale: bool = False,
        clear_error: BaseException | None = None,
        click_error: BaseException | None = None,
        remaining_text: Any = ...,
        input_type: str = "XCUIElementTypeTextView",
        placeholder: str | None = None,
        clear_fails_once: bool = False,
        initial_matches: list[str] | None = None,
        final_matches: list[str] | None = None,
        recover_focus: bool = True,
    ):
        self.blur = blur
        self.stale = stale
        self.clear_error = clear_error
        self.click_error = click_error
        self.remaining_text = remaining_text
        self.input_type = input_type
        self.placeholder = placeholder
        self.clear_fails_once = clear_fails_once
        self.initial_matches = initial_matches
        self.final_matches = final_matches
        self.recover_focus = recover_focus
        self.cleared = False
        self.clear_count = 0
        self.active: str | None = "original"
        self.calls: list[tuple] = []

    async def __call__(self, method: str, path: str, body=None) -> dict[str, Any]:
        self.calls.append((method, path, body))
        if path == "/element/active":
            if not self.active:
                raise protocol_error("no such element")
            return {"value": {"ELEMENT": self.active}}
        if path.endswith("/attribute/name"):
            return {"value": "message-input"}
        if path.endswith("/attribute/type"):
            return {"value": self.input_type}
        if path.endswith("/attribute/placeholderValue"):
            return {"value": self.placeholder}
        if path.endswith("/attribute/value"):
            return {"value": "" if self.remaining_text is ... else self.remaining_text}
        if path == "/elements":
            if self.cleared:
                matches = (
                    self.final_matches
                    if self.final_matches is not None
                    else ["replacement"]
                )
            else:
                matches = self.initial_matches or ["original"]
            return {"value": [{"ELEMENT": element} for element in matches]}
        if path.endswith("/clear"):
            self.cleared = True
            if self.blur:
                self.active = None
            self.clear_count += 1
            if self.clear_error is not None and (
                not self.clear_fails_once or self.clear_count == 1
            ):
                raise self.clear_error
            return {"value": None}
        if path.endswith("/click"):
            if self.click_error is not None:
                raise self.click_error
            if self.stale and "/original/" in path:
                raise protocol_error("stale element reference")
            if self.recover_focus:
                self.active = "original" if "/original/" in path else "replacement"
            return {"value": None}
        raise RuntimeError(f"Unexpected request: {method} {path}")

    def called(self, method: str, path: str) -> bool:
        return any(call[0] == method and call[1] == path for call in self.calls)

    def calls_ending(self, suffix: str) -> list[tuple]:
        return [call for call in self.calls if call[1].endswith(suffix)]


@pytest.mark.asyncio
async def test_does_not_click_when_clearing_preserves_focus():
    """does not click when clearing preserves focus."""

    request = Fixture()
    assert await clear_input_with_focus(request) is True
    assert not request.calls_ending("/click")


@pytest.mark.asyncio
async def test_rejects_an_unverified_clear_instead_of_appending_to_old_text():
    """rejects an unverified clear instead of appending to old text."""

    request = Fixture(
        blur=True,
        clear_error=protocol_error("stale element reference"),
        remaining_text="old text",
    )
    with pytest.raises(RuntimeError, match="refusing to append text"):
        await clear_input_with_focus(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["no such element", "unknown command", "unsupported operation"]
)
async def test_preserves_unavailable_initial_discovery(code):
    """preserves unavailable initial discovery: %s."""

    class Unavailable:
        def __init__(self):
            self.calls = 0

        async def __call__(self, method, path, body=None):
            self.calls += 1
            raise protocol_error(code)

    request = Unavailable()
    assert await clear_input_with_focus(request) is False
    assert request.calls == 1


@pytest.mark.asyncio
async def test_reacquires_a_stale_input_and_verifies_a_clear_that_failed_after_mutation():
    """reacquires a stale input and verifies a clear that failed after mutation."""

    request = Fixture(
        blur=True,
        stale=True,
        clear_error=protocol_error("stale element reference"),
    )
    assert await clear_input_with_focus(request) is True
    assert request.called("POST", "/element/replacement/click")
    assert request.called("GET", "/element/replacement/attribute/value")


@pytest.mark.asyncio
async def test_uses_an_identifier_and_input_type_predicate_instead_of_label_matching():
    """uses an identifier and input type predicate instead of label matching."""

    request = Fixture(blur=True, stale=True)
    await clear_input_with_focus(request)
    assert (
        "POST",
        "/elements",
        {
            "using": "predicate string",
            "value": (
                'name == "message-input" AND name != label '
                'AND type == "XCUIElementTypeTextView"'
            ),
        },
    ) in request.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("final_matches", [[], ["replacement", "other"]])
async def test_rejects_a_missing_or_ambiguous_replacement(final_matches):
    """rejects a missing or ambiguous replacement: %j."""

    request = Fixture(blur=True, stale=True, final_matches=final_matches)
    with pytest.raises(RuntimeError, match="Cannot uniquely identify"):
        await clear_input_with_focus(request)


@pytest.mark.asyncio
async def test_retries_clear_once_rather_than_trusting_text_equal_to_the_placeholder():
    """retries clear once rather than trusting text equal to the placeholder."""

    request = Fixture(
        blur=True,
        stale=True,
        clear_error=protocol_error("stale element reference"),
        clear_fails_once=True,
        remaining_text="Message",
        placeholder="Message",
    )
    assert await clear_input_with_focus(request) is True
    assert len(request.calls_ending("/clear")) == 2


@pytest.mark.asyncio
async def test_bounds_retries_when_placeholder_content_remains_ambiguous():
    """bounds retries when placeholder content remains ambiguous."""

    request = Fixture(
        blur=True,
        clear_error=protocol_error("stale element reference"),
        remaining_text="Message",
        placeholder="Message",
    )
    with pytest.raises(RuntimeError, match="refusing to append text"):
        await clear_input_with_focus(request)
    assert len(request.calls_ending("/clear")) == 2
