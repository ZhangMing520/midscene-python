"""
Insight - AI-powered UI understanding and reasoning engine.

Rewired onto the upstream-synced workflows (grounding / insight / planning)
with the locate and insight model slots. The public API is kept compatible
with the previous Python SDK release.
"""

from collections.abc import Callable, Coroutine
from typing import Any, cast

from loguru import logger

from midscene.core.agent.utils import _extract_typed_query_result
from midscene.core.ai_model.models.registry import ModelRuntime, get_model_runtime
from midscene.core.ai_model.prompt.insight import build_type_query_demand_value
from midscene.core.ai_model.workflows import ai_extract_element_info
from midscene.core.common import user_prompt_to_string
from midscene.core.service import locate_service
from midscene.core.service.describe import ai_describe_element
from midscene.core.types import (
    AssertResult,
    ExtractOption,
    InsightAction,
    LocateOption,
    LocateResult,
    TUserPrompt,
    UIContext,
)
from midscene.shared.env import ModelConfigManager, get_global_model_config_manager


class Insight:
    """AI-powered UI understanding and reasoning engine"""

    def __init__(
        self,
        context_provider: UIContext
        | Callable[[InsightAction], UIContext | Coroutine[Any, Any, UIContext]],
        ai_service: Any | None = None,
        model_config: dict[str, str] | Any | None = None,
    ):
        """Initialize Insight engine

        Args:
            context_provider: UI context or function to get context
            ai_service: (deprecated, ignored) kept for API compatibility
            model_config: env-style model configuration dict
                (MIDSCENE_MODEL_NAME / MIDSCENE_MODEL_API_KEY / ... )
        """
        self.context_provider: Callable[
            [InsightAction], UIContext | Coroutine[Any, Any, UIContext]
        ]
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
            ModelConfigManager(cast(dict[str, str | int | float], model_config))
            if model_config
            else get_global_model_config_manager()
        )
        self._runtime_cache: dict[str, ModelRuntime] = {}
        self._dump_subscribers: list[Callable] = []

    def model_runtime(self, intent: str) -> ModelRuntime:
        if intent not in self._runtime_cache:
            config = self._model_config_manager.get_model_config(intent)
            self._runtime_cache[intent] = get_model_runtime(config)
        return self._runtime_cache[intent]

    async def locate(
        self,
        prompt: TUserPrompt,
        options: LocateOption | None = None,
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
        options: ExtractOption | None = None,
    ) -> dict[str, Any]:
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
            result: dict[str, Any] = {
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
        options: ExtractOption | None = None,
    ) -> AssertResult:
        """Assert a condition about the UI (aiAssert)."""
        options = options or ExtractOption()
        try:
            context = await self._get_context(InsightAction.ASSERT)
            assertion_text = assertion if isinstance(assertion, str) else str(assertion)
            response = await ai_extract_element_info(
                task_type="boolean",
                data_query={"assertion": assertion_text},
                context=context,
                model_runtime=self.model_runtime("insight"),
            )
            parse_result = response.get("parse_result", {})
            data = parse_result.get("data")
            passed = (
                bool(data.get("assertion")) if isinstance(data, dict) else bool(data)
            )
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

    @staticmethod
    def _option(options: Any, key: str, default: Any = None) -> Any:
        if isinstance(options, dict):
            return options.get(key, default)
        return getattr(options, key, default)

    async def ai_query(
        self,
        demand: Any,
        options: Any | None = None,
    ) -> Any:
        """Extract structured data from the UI (upstream aiQuery)."""
        extract_option = ExtractOption(
            dom_included=self._option(options, "domIncluded", False),
            screenshot_included=self._option(options, "screenshotIncluded", True),
        )
        result = await self.extract(demand, extract_option)
        return result.get("data")

    async def _query_primitive(
        self,
        demand_type: str,
        api_name: str,
        prompt: TUserPrompt,
        options: Any | None = None,
    ) -> Any:
        context = await self._get_context(InsightAction.EXTRACT)
        demand_value = build_type_query_demand_value(
            demand_type, user_prompt_to_string(prompt)
        )
        response = await ai_extract_element_info(
            task_type="extract",
            data_query={demand_type: demand_value},
            context=context,
            model_runtime=self.model_runtime("insight"),
            page_description="",
            screenshot_included=self._option(options, "screenshotIncluded", True),
            context_text=self._option(options, "context", None),
        )
        await self._notify_dump_subscribers(
            {
                "type": "extract",
                "prompt": prompt,
                "data": response.get("parse_result", {}).get("data"),
                "usage": response.get("usage"),
            }
        )
        data = response.get("parse_result", {}).get("data")
        return _extract_typed_query_result(data, demand_type)

    async def ai_boolean(
        self,
        prompt: TUserPrompt,
        options: Any | None = None,
    ) -> bool:
        return bool(
            await self._query_primitive("Boolean", "aiBoolean", prompt, options)
        )

    async def ai_number(
        self,
        prompt: TUserPrompt,
        options: Any | None = None,
    ) -> float:
        result = await self._query_primitive("Number", "aiNumber", prompt, options)
        return cast(float, result)

    async def ai_string(
        self,
        prompt: TUserPrompt,
        options: Any | None = None,
    ) -> str:
        result = await self._query_primitive("String", "aiString", prompt, options)
        return cast(str, result)

    async def ai_ask(
        self,
        prompt: TUserPrompt,
        options: Any | None = None,
    ) -> str:
        result = await self._query_primitive("String", "aiAsk", prompt, options)
        return cast(str, result)

    async def ai_assert(
        self,
        assertion: TUserPrompt,
        message: str | None = None,
        options: Any | None = None,
    ) -> dict[str, Any] | None:
        """Assert a condition about the UI (upstream aiAssert)."""
        assertion_text = user_prompt_to_string(assertion)
        result = await self.assert_condition(
            assertion,
            ExtractOption(
                screenshot_included=self._option(options, "screenshotIncluded", True)
            ),
        )
        failure_message = (
            None
            if result.passed
            else (
                f"Assertion failed: {message or assertion_text}\n"
                f"Reason: {result.thought or '(no_reason)'}"
            )
        )
        if self._option(options, "keepRawResponse", False):
            return {
                "pass": result.passed,
                "thought": result.thought,
                "message": failure_message,
            }
        if not result.passed:
            raise AssertionError(failure_message)
        return None

    async def describe(
        self,
        point: tuple,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            return cast(UIContext, await self.context_provider(action))
        result = self.context_provider(action)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _notify_dump_subscribers(self, dump_data: dict[str, Any]) -> None:
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
