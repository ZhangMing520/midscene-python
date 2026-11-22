"""Error formatting (upstream packages/shared/tests/unit-test/error-formatter.test.ts)."""

import json

import pytest

from midscene.shared.agent_tools.error_formatter import (
    get_error_message,
    get_error_stack,
    serialize_error,
    truncate_serialized_error_string,
)


class Error(Exception):
    """Python stand-in for the upstream ``Error`` class name."""


class TestGetErrorMessage:
    def test_returns_the_error_message_for_error_instances(self):
        assert get_error_message(Error("boom")) == "boom"
        assert get_error_message(TypeError("bad type")) == "bad type"
        assert (
            get_error_message(Error("Error without a message"))
            == "Error without a message"
        )

    @pytest.mark.skip(reason="Python str(None) is 'None'; upstream null/undefined map to 'null'/'undefined'")
    def test_stringifies_null_and_undefined(self):
        pass

    def test_stringifies_primitives(self):
        assert get_error_message("oops") == "oops"
        assert get_error_message(42) == "42"
        assert get_error_message(True) == "True"

    def test_extracts_message_from_message_shape(self):
        assert get_error_message({"message": "connect ECONNREFUSED"}) == (
            "connect ECONNREFUSED"
        )

    def test_extracts_message_from_nested_error_message_shape(self):
        assert (
            get_error_message({"error": {"message": "upstream failed", "code": 502}})
            == "upstream failed"
        )

    def test_extracts_message_from_cause_message_shape(self):
        assert get_error_message({"cause": {"message": "root cause"}}) == "root cause"

    def test_prefers_top_level_message_over_nested_error_cause(self):
        assert (
            get_error_message(
                {
                    "message": "outer",
                    "error": {"message": "inner"},
                    "cause": {"message": "root"},
                }
            )
            == "outer"
        )

    def test_summarizes_message_less_objects_from_bounded_diagnostic_fields(self):
        assert json.loads(get_error_message({"message": "", "code": "EIO"})) == {
            "name": "Error",
            "message": "Error without a message",
            "code": "EIO",
        }
        assert json.loads(get_error_message({"status": 500, "details": "x"})) == {
            "name": "Error",
            "message": "Error without a message",
            "status": 500,
        }

    def test_does_not_traverse_circular_objects_while_formatting_a_message(self):
        circular = {"foo": "bar"}
        circular["self"] = circular
        assert json.loads(get_error_message(circular)) == {
            "name": "Error",
            "message": "Error without a message",
        }

    def test_keeps_whitelisted_diagnostics_without_arbitrary_object_data(self):
        result = get_error_message({"code": "E_TEST", "detail": "something"})
        assert result != "[object Object]"
        assert "E_TEST" in result
        assert "something" not in result

    def test_does_not_serialize_arbitrary_array_entries(self):
        assert json.loads(get_error_message([1, 2, 3])) == {
            "name": "Error",
            "message": "Error without a message",
        }

    def test_ignores_message_getters_that_throw(self):
        class BrokenMessage:
            code = "E_BROKEN_GETTER"

            @property
            def message(self):
                raise Error("getter failed")

        assert json.loads(get_error_message(BrokenMessage())) == {
            "name": "Error",
            "message": "Error without a message",
            "code": "E_BROKEN_GETTER",
        }

    def test_bounds_long_messages_without_serializing_arbitrary_payloads(self):
        assert len(get_error_message(Error("x" * 10_000))) == 4_096

        result = get_error_message(
            {"code": "E_LARGE_PAYLOAD", "payload": "x" * 10_000_000}
        )
        assert json.loads(result) == {
            "name": "Error",
            "message": "Error without a message",
            "code": "E_LARGE_PAYLOAD",
        }
        assert len(result) < 1_000
        assert "payload" not in result


class TestSerializeError:
    def test_exposes_the_shared_string_bound_for_task_summaries(self):
        serialized = truncate_serialized_error_string("x" * 10_000)

        assert len(serialized) == 4_096
        assert serialized.endswith("… [truncated]")

    def test_preserves_only_the_small_normalized_diagnostic_whitelist(self):
        root_cause = TypeError("socket closed")
        root_cause.code = "ECONNRESET"

        error = Error("request failed")
        error.__cause__ = root_cause
        error.stack = "Error: request failed\n    at test"
        error.code = "UPSTREAM_UNAVAILABLE"
        error.statusCode = "503"
        error.requestID = 42
        error.type = "network"
        error.errno = -1
        error.syscall = "connect"
        error.hostname = "private.example"
        error.payload = "ignored"

        assert serialize_error(error) == {
            "name": "Error",
            "message": "request failed",
            "stack": "Error: request failed\n    at test",
            "code": "UPSTREAM_UNAVAILABLE",
            "status": "503",
            "requestId": 42,
        }

    def test_extracts_messages_from_structured_sdk_errors(self):
        assert serialize_error(
            {
                "error": {"message": "upstream failed", "response": {"secret": True}},
                "status": 502,
            }
        ) == {
            "name": "Error",
            "message": "upstream failed",
            "status": 502,
        }

        assert serialize_error({"cause": {"message": "root cause"}}) == {
            "name": "Error",
            "message": "root cause",
        }

    def test_does_not_traverse_cause_chains_or_circular_payloads(self):
        circular = Error("circular")
        circular.__cause__ = circular
        circular.stack = "Error: circular\n    at test"
        assert serialize_error(circular) == {
            "name": "Error",
            "message": "circular",
            "stack": "Error: circular\n    at test",
        }

        payload = {"data": "ignored"}
        payload["self"] = payload
        assert serialize_error(payload) == {
            "name": "Error",
            "message": "Error without a message",
        }

    def test_does_not_fail_when_diagnostic_getters_throw(self):
        def _throwing_code(_self):
            raise Error("code getter failed")

        broken_error = type(
            "Error", (Exception,), {"code": property(_throwing_code)}
        )
        error = broken_error("safe message")

        serialize_error(error)
        serialized = serialize_error(error)
        assert serialized["name"] == "Error"
        assert serialized["message"] == "safe message"
        assert "code" not in serialized

    def test_omits_arbitrary_payloads_from_message_less_thrown_objects(self):
        serialized = serialize_error({"payload": "x" * 10_000_000})

        assert serialized == {
            "name": "Error",
            "message": "Error without a message",
        }
        assert len(json.dumps(serialized)) < 1_000

    def test_provides_a_readable_fallback_for_empty_primitive_strings(self):
        assert serialize_error("") == {
            "name": "NonError",
            "message": "Empty string thrown",
        }
        assert get_error_message("") == "Empty string thrown"

    def test_provides_a_readable_fallback_for_non_error_primitive_strings(self):
        assert serialize_error("boom") == {"name": "NonError", "message": "boom"}

    def test_caps_every_serialized_string_field(self):
        long_text = "x" * 10_000
        error = Error(long_text)
        error.stack = long_text
        error.code = long_text

        serialized = serialize_error(error)
        assert len(serialized["message"]) == 4_096
        assert len(serialized["stack"]) == 4_096
        assert len(serialized["code"]) == 4_096
        assert serialized["message"].endswith("… [truncated]")
        assert len(json.dumps(serialized)) < 15_000


class TestGetErrorStack:
    def test_reads_string_stacks_and_ignores_throwing_stack_getters(self):
        error = Error("boom")
        error.stack = "Error: boom\n    at test"
        assert "Error: boom" in get_error_stack(error)

        class BrokenStack:
            @property
            def stack(self):
                raise Error("stack getter failed")

        assert get_error_stack(BrokenStack()) is None
