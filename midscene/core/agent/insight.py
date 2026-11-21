"""
Insight - AI-powered UI understanding and reasoning engine.

Rewired onto the upstream-synced workflows (grounding / insight / planning)
with the locate and insight model slots. The public API is kept compatible
with the previous Python SDK release.
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from loguru import logger

from midscene.core.ai_model.models.registry import ModelRuntime, get_model_runtime
from midscene.shared.env import ModelConfigManager, get_global_model_config_manager
from midscene.core.ai_model.workflows import ai_extract_element_info
from midscene.core.service.describe import ai_describe_element
from midscene.core.service import locate_service
from midscene.core.types import (
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
        options = options or LocateOption()
        try:
            context = options.ui_context or await self._get_context(
                InsightAction.LOCATE
            )
            response = await locate_service(
                query_prompt=prompt,
                context=context,
                model_runtime=self.model_runtime("locate"),
                deep_locate=bool(options.deep_think),
            )
            element = response.get("element")
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

    async def describe(
        self,
        point: tuple,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Describe the element at the given coordinates.

        The screenshot is annotated with the upstream ring + crosshair marker
        before it is sent. options: {deepDescribe: bool, context: UIContext}.
        """
        options = options or {}
        try:
            context = options.get("context") or await self._get_context(
                InsightAction.EXTRACT
            )
            result = await ai_describe_element(
                context,
                [float(point[0]), float(point[1])],
                self.model_runtime("insight"),
                deep_describe=bool(options.get("deepDescribe", False)),
            )
            return {
                "description": result["description"],
                "usage": result.get("usage"),
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
