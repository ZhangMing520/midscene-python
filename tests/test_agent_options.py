"""Synced from upstream ``packages/core/tests/unit-test/agent-options.test.ts``."""

import pytest

from midscene.core.agent.agent_options import (
    AgentOptions,
    normalize_agent_options,
    with_agent_defaults,
)


def test_preserves_defaults_explicit_undefined_and_caller_owned_context_objects():
    contexts = {"aiAct": "", "default": "shared"}
    original = {
        "generateReport": None,
        "aiContexts": contexts,
        "aiActContext": "legacy",
    }
    options = with_agent_defaults(original)
    warnings = []
    normalize_agent_options(options, warnings.append)

    assert options["persistExecutionDump"] is False
    assert options["autoPrintReportMsg"] is True
    assert options["groupName"] == "Midscene Report"
    assert options["groupDescription"] == ""
    assert options["aiContexts"] == {"aiAct": "", "default": "shared"}
    assert options["aiActContext"] == ""
    assert options["aiActionContext"] == ""
    assert options is not original
    assert options["aiContexts"] is not contexts
    assert original == {
        "generateReport": None,
        "aiContexts": contexts,
        "aiActContext": "legacy",
    }
    assert len(warnings) == 1


@pytest.mark.parametrize(
    "options, expected",
    [
        ({"aiActContext": "act", "aiActionContext": "action"}, "act"),
        ({"aiActionContext": "action"}, "action"),
        ({"aiActContext": "act", "aiContexts": {"aiAct": "new"}}, "new"),
    ],
)
def test_retains_deprecated_context_precedence(options, expected):
    normalized = with_agent_defaults(options)
    normalize_agent_options(normalized, lambda _message: None)
    assert normalized["aiContexts"]["aiAct"] == expected
    assert normalized["aiActContext"] == expected
    assert normalized["aiActionContext"] == expected


@pytest.mark.parametrize("ai_contexts", [None, [], "context"])
def test_rejects_an_invalid_context_map(ai_contexts):
    options = with_agent_defaults({"aiContexts": ai_contexts})
    with pytest.raises(TypeError, match="opts.aiContexts must be a plain object"):
        normalize_agent_options(options, lambda _message: None)


@pytest.mark.parametrize(
    "ai_contexts, message",
    [
        ({"unsupported": "value"}, "Unknown Agent context key: unsupported"),
        ({"aiAct": 123}, 'Agent context "aiAct" must be a string'),
    ],
)
def test_preserves_context_validation_errors(ai_contexts, message):
    with pytest.raises(TypeError, match=message):
        normalize_agent_options(
            with_agent_defaults({"aiContexts": ai_contexts}),
            lambda _message: None,
        )


def test_emits_the_deprecation_warning_before_rejecting_an_invalid_model_config():
    warnings = []
    with pytest.raises(TypeError, match="opts.modelConfig must be a plain object map"):
        normalize_agent_options(
            with_agent_defaults({"aiActContext": "legacy", "modelConfig": []}),
            warnings.append,
        )
    assert len(warnings) == 1


def test_accepts_agent_options_dataclass_and_normalizes_context_fields():
    options = AgentOptions(ai_contexts={"aiAct": "new"}, ai_act_context="old")
    normalize_agent_options(options, lambda _message: None)
    assert options.ai_contexts["aiAct"] == "new"
    assert options.ai_act_context == "new"
    assert options.ai_action_context == "new"
