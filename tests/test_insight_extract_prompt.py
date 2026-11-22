"""Synced from upstream packages/core/tests/unit-test/insight-extract-prompt.test.ts."""


class TestInsightExtractPrompt:
    def test_data_demand_keeps_cjk(self):
        from midscene.core.ai_model.prompt.insight import extract_data_query_prompt

        prompt = extract_data_query_prompt("页面", {"标题": "string"})
        assert "标题" in prompt
        assert "\\u" not in prompt

    def test_typed_demand_values(self):
        from midscene.core.ai_model.prompt.insight import (
            build_type_query_demand_value,
        )

        assert build_type_query_demand_value("Assert", "登录成功").startswith(
            "Boolean, based on the current screenshot"
        )
        assert "wait for" in build_type_query_demand_value("WaitFor", "加载完成")
        assert build_type_query_demand_value("Number", "count").startswith("Number, ")

