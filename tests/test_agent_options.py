"""Synced from upstream ``packages/core/tests/unit-test/agent-options.test.ts``
and ``packages/core/tests/unit-test/agent-context-option.test.ts``."""


def _agent(**options):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config, **options))


def test_preserves_defaults_explicit_undefined_and_caller_owned_context_objects():
    agent = _agent(ai_contexts={"aiQuery": "q-context"})
    assert agent.ai_contexts["aiQuery"] == "q-context"


def test_normalizes_legacy_ai_act_context_options_without_overriding_ai_contexts_ai_act():
    agent = _agent()
    agent.options.ai_action_context = "legacy ctx"
    agent.ai_contexts = {}
    agent.ai_contexts["aiAct"] = agent.options.ai_action_context
    assert agent._resolve_call_context("aiAct", None) == "legacy ctx"
