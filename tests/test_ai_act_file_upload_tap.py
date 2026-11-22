"""Synced from upstream
``packages/core/tests/unit-test/ai-act-file-upload-tap.test.ts``."""

from typing import Any, List
from unittest.mock import patch

import pytest

from tests.core_helpers import MockInterface


class FileChooserInterface(MockInterface):
    def __init__(self):
        super().__init__()
        self.handlers: List[Any] = []

    async def register_file_chooser_listener(self, handler):
        from midscene.core.types import FileChooserRegistration

        def dispose():
            if handler in self.handlers:
                self.handlers.remove(handler)

        self.accepted_files: List[str] = []
        self.handlers.append(handler)
        return FileChooserRegistration(dispose=dispose, get_error=lambda: None)


def _file_chooser_agent():
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(FileChooserInterface(), AgentOptions(model_config=config))


def _agent():
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config))


class TestAiActFileUploadTap:
    def test_should_serialize_file_chooser_registration_separately_from_tap(self):
        assert "RegisterFileChooserAccept" not in [
            a.name for a in _agent().action_space
        ]
        assert "RegisterFileChooserAccept" in [
            a.name for a in _file_chooser_agent().action_space
        ]

    @pytest.mark.asyncio
    async def test_should_replace_registered_files_and_clear_the_active_registration(
        self, tmp_path
    ):
        from midscene.core.types import FileChooserHandler

        upload = tmp_path / "upload.txt"
        upload.write_text("payload")
        agent = _file_chooser_agent()
        calls: List[tuple] = []

        async def fake_call(action_type, param):
            calls.append((action_type, param))

            async def accept(files):
                agent.interface.accepted_files = list(files)

            await agent.interface.handlers[0](FileChooserHandler(accept=accept))

        with patch.object(agent, "_call_action_in_action_space", new=fake_call):
            await agent.ai_tap(
                "the upload button", {"fileChooserAccept": str(upload)}
            )

        assert calls == [("Tap", {"locate": {"prompt": "the upload button"}})]
        assert agent.interface.accepted_files == [str(upload.resolve())]
        assert agent.interface.handlers == []

    @pytest.mark.asyncio
    async def test_should_return_a_file_chooser_handling_error_while_disposing_the_registration(
        self, tmp_path
    ):
        upload = tmp_path / "upload.txt"
        upload.write_text("payload")
        agent = _file_chooser_agent()

        async def failing_impl(*args, **kwargs):
            raise RuntimeError("boom")

        with patch.object(agent, "_ai_act_impl", new=failing_impl):
            with pytest.raises(RuntimeError, match="boom"):
                await agent.ai_act("upload", {"fileChooserAccept": str(upload)})

        assert agent.interface.handlers == []
        assert agent._active_file_chooser_accepter is None

    @pytest.mark.asyncio
    async def test_requires_file_chooser_allowed_dir_for_model_driven_uploads(self):
        from midscene.core.agent.file_chooser import _FileChooserAccepter

        agent = _file_chooser_agent()
        action = next(
            a
            for a in agent.action_space
            if a.name == "RegisterFileChooserAccept"
        )

        agent._active_file_chooser_accepter = _FileChooserAccepter(agent.interface)
        with pytest.raises(RuntimeError, match="fileChooserAllowedDir"):
            await action.execute({"files": "a.txt"}, agent.interface, None)
        agent._active_file_chooser_accepter = None
        with pytest.raises(RuntimeError, match="only be used while aiAct"):
            await action.execute({"files": "a.txt"}, agent.interface, None)

    @pytest.mark.asyncio
    async def test_registers_model_generated_paths_within_the_configured_directory(
        self, tmp_path
    ):
        from midscene.core.agent.file_chooser import _FileChooserAccepter
        from midscene.core.types import FileChooserHandler

        (tmp_path / "doc.pdf").write_text("pdf")
        agent = _file_chooser_agent()
        action = next(
            a
            for a in agent.action_space
            if a.name == "RegisterFileChooserAccept"
        )
        agent._active_file_chooser_accepter = _FileChooserAccepter(agent.interface)
        agent._active_file_chooser_allowed_dir = str(tmp_path)
        await action.execute({"files": "doc.pdf"}, agent.interface, None)
        assert len(agent.interface.handlers) == 1

        recorded: List[str] = []

        async def accept(files):
            recorded.extend(files)

        await agent.interface.handlers[0](FileChooserHandler(accept=accept))
        assert recorded == [str((tmp_path / "doc.pdf").resolve())]
        agent._active_file_chooser_accepter = None

    def test_only_accepts_model_generated_paths_within_the_configured_directory(
        self, tmp_path
    ):
        from midscene.core.agent.file_chooser import (
            _normalize_file_chooser_accept_in_allowed_dir,
        )

        (tmp_path.parent / "outside.txt").write_text("x")
        with pytest.raises(ValueError, match="fileChooserAllowedDir"):
            _normalize_file_chooser_accept_in_allowed_dir(
                "../outside.txt", str(tmp_path)
            )
