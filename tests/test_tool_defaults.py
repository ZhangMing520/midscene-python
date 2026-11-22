"""Tool defaults (upstream packages/shared/tests/unit-test/tool-defaults.test.ts)."""

from midscene.shared.agent_tools.tool_defaults import (
    TOOL_BEHAVIOR_FLAGS,
    merge_tool_defaults,
    resolve_tool_defaults,
    strip_behavior_flags,
)


class TestMergeToolDefaults:
    def test_merges_locate_and_act_bags_with_b_winning(self):
        assert merge_tool_defaults(
            {"locate": {"deepLocate": True}, "act": {"deepThink": True}},
            {"locate": {"deepLocate": False}, "act": {"deepLocate": True}},
        ) == {
            "locate": {"deepLocate": False},
            "act": {"deepThink": True, "deepLocate": True},
        }

    def test_omits_empty_bags(self):
        assert merge_tool_defaults({}, {}) == {}
        assert merge_tool_defaults({"act": {"deepThink": True}}, {}) == {
            "act": {"deepThink": True},
        }


class TestResolveToolDefaults:
    def test_returns_empty_defaults_when_nothing_is_enabled(self):
        assert resolve_tool_defaults(lambda _cli: False) == {}

    def test_resolves_a_single_flag_from_the_registry(self):
        assert resolve_tool_defaults(lambda cli: cli == "deep-locate") == {
            "locate": {"deepLocate": True},
            "act": {"deepLocate": True},
        }

    def test_merges_every_enabled_flag(self):
        assert resolve_tool_defaults(lambda _cli: True) == {
            "locate": {"deepLocate": True},
            "act": {"deepLocate": True, "deepThink": True},
        }


class TestStripBehaviorFlags:
    def test_returns_empty_defaults_and_untouched_args_when_no_flag_is_present(self):
        assert strip_behavior_flags(["tap", "--locate", "btn"]) == (
            ["tap", "--locate", "btn"],
            {},
        )

    def test_strips_a_leading_behavior_flag_and_resolves_its_defaults(self):
        assert strip_behavior_flags(["--deep-locate", "tap", "--locate", "btn"]) == (
            ["tap", "--locate", "btn"],
            {"locate": {"deepLocate": True}, "act": {"deepLocate": True}},
        )

    def test_strips_a_behavior_flag_that_follows_the_command_preserving_order(self):
        assert strip_behavior_flags(["tap", "--deep-locate", "--locate", "btn"]) == (
            ["tap", "--locate", "btn"],
            {"locate": {"deepLocate": True}, "act": {"deepLocate": True}},
        )

    def test_merges_defaults_when_several_behavior_flags_are_present(self):
        assert strip_behavior_flags(
            ["act", "--deep-locate", "--deep-think", "--prompt", "go"]
        ) == (
            ["act", "--prompt", "go"],
            {
                "locate": {"deepLocate": True},
                "act": {"deepLocate": True, "deepThink": True},
            },
        )

    def test_only_recognizes_exact_kebab_case_flags_not_camel_case_or_value_forms(self):
        camel_raw, camel_defaults = strip_behavior_flags(["--deepLocate", "tap"])
        assert camel_defaults == {}
        assert camel_raw == ["--deepLocate", "tap"]

        valued_raw, valued_defaults = strip_behavior_flags(
            ["--deep-locate=true", "tap"]
        )
        assert valued_defaults == {}
        assert valued_raw == ["--deep-locate=true", "tap"]

    def test_covers_every_registered_flag(self):
        for flag in TOOL_BEHAVIOR_FLAGS:
            raw_args, tool_defaults = strip_behavior_flags([f"--{flag['cli']}", "cmd"])
            assert raw_args == ["cmd"]
            assert tool_defaults == flag["defaults"]
