"""
Insight - AI-powered UI understanding and reasoning engine.

Rewired onto the upstream-synced workflows (grounding / insight / planning)
with the locate and insight model slots. The public API is kept compatible
with the previous Python SDK release.
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from loguru import logger

from .ai_model.adapters import ModelRuntime, get_model_runtime
from .ai_model.env_config import ModelConfigManager, get_global_model_config_manager
from .ai_model.workflows import ai_extract_element_info, ai_locate_element
from .ai_model.prompts.describe import element_describer_instruction
from .ai_model.workflows.context_utils import ensure_data_url
from .types import (
    AssertResult,
    ExtractOption,
    InsightAction,
    LocateOption,
    LocateResult,
    TUserPrompt,
    UIContext,
)


class Insight:
    """AI-powered UI understanding and reasoning engine"""

    def __init__(
        self,
        context_provider: Union[
            UIContext,
            Callable[[InsightAction], Union[UIContext, Awaitable[UIContext]]],
        ],
        ai_service: Optional[Any] = None,
        model_config: Optional[Union[Dict[str, str], Any]] = None,
    ):
        """Initialize Insight engine

        Args:
            context_provider: UI context or function to get context
            ai_service: (deprecated, ignored) kept for API compatibility
            model_config: env-style model configuration dict
                (MIDSCENE_MODEL_NAME / MIDSCENE_MODEL_API_KEY / ... )
        """
        if callable(context_provider):
            self.context_provider = context_provider
        else:
            self.context_provider = lambda _: context_provider

        if model_config is not None and not isinstance(model_config, dict):
            # Legacy AIModelConfig object -> convert to env-style dict
            config = model_config
            model_config = {
                "MIDSCENE_MODEL_NAME": getattr(config, "model", None) or "",
                "MIDSCENE_MODEL_API_KEY": getattr(config, "api_key", None) or "",
                "MIDSCENE_MODEL_BASE_URL": getattr(config, "base_url", None) or "",
            }
            model_config = {k: v for k, v in model_config.items() if v}

        self._model_config_manager: ModelConfigManager = (
            ModelConfigManager(model_config)
            if model_config
            else get_global_model_config_manager()
        )
        self._runtime_cache: Dict[str, ModelRuntime] = {}
        self._dump_subscribers: List[Callable] = []

    def model_runtime(self, intent: str) -> ModelRuntime:
        if intent not in self._runtime_cache:
            config = self._model_config_manager.get_model_config(intent)
            self._runtime_cache[intent] = get_model_runtime(config)
        return self._runtime_cache[intent]

    async def locate(
        self,
        prompt: TUserPrompt,
        options: Optional[LocateOption] = None,
    ) -> LocateResult:
        """Locate a UI element by description (vision grounding)."""
        try:
            context = await self._get_context(InsightAction.LOCATE)
            response = await ai_locate_element(
                target_element_description=prompt,
                context=context,
                model_runtime=self.model_runtime("locate"),
            )
            parse_result = response.get("parse_result", {})
            element = parse_result.get("element")
            await self._notify_dump_subscribers(
                {
                    "type": "locate",
                    "prompt": prompt,
                    "element": element,
                    "usage": response.get("usage"),
                }
            )
            if not element:
                return LocateResult()
            return LocateResult(
                center=list(element["center"]),
                rect=element.get("rect"),
                description=element.get("description"),
                raw_response=response.get("raw_response"),
            )
        except Exception as e:
            logger.error(f"Locate failed: {e}")
            raise

    async def extract(
        self,
        prompt: TUserPrompt,
        options: Optional[ExtractOption] = None,
    ) -> Dict[str, Any]:
        """Extract data from the UI (aiQuery)."""
        options = options or ExtractOption()
        try:
            context = await self._get_context(InsightAction.EXTRACT)
            response = await ai_extract_element_info(
                task_type="extract",
                data_query=prompt,
                context=context,
                model_runtime=self.model_runtime("insight"),
                screenshot_included=options.screenshot_included,
            )
            parse_result = response.get("parse_result", {})
            await self._notify_dump_subscribers(
                {
                    "type": "extract",
                    "prompt": prompt,
                    "data": parse_result.get("data"),
                    "usage": response.get("usage"),
                }
            )
            result: Dict[str, Any] = {
                "data": parse_result.get("data"),
                "usage": response.get("usage"),
            }
            if options.return_thought:
                result["thought"] = parse_result.get("thought")
            return result
        except Exception as e:
            logger.error(f"Extract failed: {e}")
            raise

    async def assert_condition(
        self,
        assertion: TUserPrompt,
        options: Optional[ExtractOption] = None,
    ) -> AssertResult:
        """Assert a condition about the UI (aiAssert)."""
        options = options or ExtractOption()
        try:
            context = await self._get_context(InsightAction.ASSERT)
            assertion_text = (
                assertion if isinstance(assertion, str) else str(assertion)
            )
            response = await ai_extract_element_info(
                task_type="boolean",
                data_query={"assertion": assertion_text},
                context=context,
                model_runtime=self.model_runtime("insight"),
            )
            parse_result = response.get("parse_result", {})
            data = parse_result.get("data")
            passed = bool(data.get("assertion")) if isinstance(data, dict) else bool(data)
            thought = parse_result.get("thought") or ""

            await self._notify_dump_subscribers(
                {
                    "type": "assert",
                    "assertion": assertion,
                    "passed": passed,
                    "usage": response.get("usage"),
                }
            )
            return AssertResult(passed=passed, thought=thought)
        except Exception as e:
            logger.error(f"Assert failed: {e}")
            raise

    async def describe(self, point: tuple) -> Dict[str, Any]:
        """Describe the element at the given coordinates.

        Uses the upstream element-describer prompt with the insight model.
        """
        try:
            context = await self._get_context(InsightAction.EXTRACT)
            screenshot = ensure_data_url(
                getattr(context, "screenshot_base64", "")
            )
            system_prompt = element_describer_instruction()
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Describe the element at the marker. The marker is "
                                f"located at pixel ({point[0]}, {point[1]}) in the "
                                "screenshot below (a ring with a crosshair)."
                            ),
                        },
                        {"type": "image", "url": screenshot},
                    ],
                },
            ]
            from .ai_model.caller import call_generative_ai

            response = await call_generative_ai(
                messages, self.model_runtime("insight")
            )
            return {
                "description": response.get("content"),
                "usage": response.get("usage"),
            }
        except Exception as e:
            logger.error(f"Describe failed: {e}")
            raise

    def add_dump_subscriber(self, subscriber: Callable) -> None:
        """Add dump subscriber for debugging"""
        self._dump_subscribers.append(subscriber)

    async def _get_context(self, action: InsightAction) -> UIContext:
        """Get UI context for action"""
        import asyncio

        if asyncio.iscoroutinefunction(self.context_provider):
            return await self.context_provider(action)
        result = self.context_provider(action)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _notify_dump_subscribers(self, dump_data: Dict[str, Any]) -> None:
        """Notify all dump subscribers"""
        import asyncio

        for subscriber in self._dump_subscribers:
            try:
                if asyncio.iscoroutinefunction(subscriber):
                    await subscriber(dump_data)
                else:
                    subscriber(dump_data)
            except Exception as e:
                logger.warning(f"Dump subscriber failed: {e}")
