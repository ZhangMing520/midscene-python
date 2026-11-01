"""YAML batch runner.

Synced from upstream packages/cli (batch-runner.ts + yaml-batch-executor.ts)
and the MidsceneYamlConfig schema in packages/core/src/yaml.ts.

Config keys: files (required), concurrent, continueOnError, retry, summary,
setup, shareBrowserContext / reusePage (web-only, sequential only).
Result types: success | failed | partialFailed | notExecuted.
"""

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml
from loguru import logger

RESULT_TYPES = ("success", "failed", "partialFailed", "notExecuted")


def parse_batch_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a MidsceneYamlConfig mapping (upstream schema subset)."""
    files = config.get("files")
    if not files:
        raise ValueError('property "files" is required in the batch config')
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        raise ValueError('"files" must be a list of file paths')

    concurrent = int(config.get("concurrent") or 1)
    if concurrent < 1:
        raise ValueError('"concurrent" must be >= 1')

    reuse_page = bool(config.get("reusePage"))
    share_browser_context = bool(config.get("shareBrowserContext"))
    if reuse_page and (not share_browser_context or concurrent != 1):
        raise ValueError(
            '"reusePage" requires shareBrowserContext: true and concurrent: 1'
        )

    retry = int(config.get("retry") or 0)
    if retry < 0:
        raise ValueError('"retry" must be >= 0')

    return {
        "files": files,
        "concurrent": concurrent,
        "continueOnError": bool(config.get("continueOnError", True)),
        "retry": retry,
        "summary": config.get("summary"),
        "setup": config.get("setup"),
        "share_browser_context": share_browser_context,
        "reuse_page": reuse_page,
        "web_overrides": _web_overrides(config),
    }


def _web_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Partial web-env overrides deep-merged into each script
    (web/page/browser/target keys, upstream MidsceneYamlTargetConfig)."""
    for key in ("web", "page", "browser", "target"):
        if isinstance(config.get(key), dict):
            return dict(config[key])
    return {}


def load_batch_config(path: str) -> Dict[str, Any]:
    """Load a batch config from a YAML file."""
    content = Path(path).read_text(encoding="utf-8")
    try:
        obj = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse batch config {path}: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError(f"batch config {path} must be a mapping")
    return parse_batch_config(obj)


def merge_web_overrides(
    script: Dict[str, Any], overrides: Dict[str, Any]
) -> Dict[str, Any]:
    """Deep-merge the batch-level web env into a script's own web env; the
    script's own keys win. A script aimed at a native target keeps its section
    untouched and never gains a web block."""
    if not overrides:
        return script
    merged = dict(script)
    if any(merged.get(key) is not None for key in ("android", "computer")):
        return merged
    web_key = next(
        (
            key
            for key in ("web", "page", "browser", "target")
            if isinstance(merged.get(key), dict)
        ),
        None,
    )
    if web_key:
        merged[web_key] = {**overrides, **merged[web_key]}
    else:
        merged["web"] = dict(overrides)
    return merged


class BatchRunner:
    """Run a batch of YAML scripts with concurrency / retry / setup."""

    def __init__(
        self,
        config: Dict[str, Any],
        player_factory: Callable[[str, str], Any],
    ):
        """player_factory(yaml_content, file_path) -> ScriptPlayer-like object
        with run()/status/failed_tasks/output_path/result."""
        self.config = parse_batch_config(config)
        self._player_factory = player_factory
        self.results: List[Dict[str, Any]] = []

    async def run(self) -> List[Dict[str, Any]]:
        cfg = self.config
        self.results = []

        # Setup script: failure aborts the whole batch.
        if cfg["setup"]:
            setup_path = cfg["setup"]
            setup_result = await self._run_one(setup_path, retries=0)
            self.results.append(setup_result)
            if not setup_result["success"]:
                for file_path in cfg["files"]:
                    self.results.append(self._not_executed(file_path))
                return self.results

        if cfg["concurrent"] > 1:
            semaphore = asyncio.Semaphore(cfg["concurrent"])

            async def bounded(file_path: str) -> Dict[str, Any]:
                async with semaphore:
                    return await self._run_one(
                        file_path,
                        retries=cfg["retry"],
                        overrides=cfg["web_overrides"],
                    )

            outcomes = await asyncio.gather(
                *(bounded(f) for f in cfg["files"])
            )
            self.results.extend(outcomes)
        else:
            shared_page = None
            for index, file_path in enumerate(cfg["files"]):
                result = await self._run_one(
                    file_path,
                    retries=cfg["retry"],
                    overrides=cfg["web_overrides"],
                    shared_page=shared_page if cfg["share_browser_context"] else None,
                )
                self.results.append(result)
                if cfg["share_browser_context"]:
                    shared_page = result.get("_shared_page") or shared_page
                if not result["success"] and not cfg["continueOnError"]:
                    for remaining_path in cfg["files"][index + 1:]:
                        self.results.append(self._not_executed(remaining_path))
                    break

        self._write_summary()
        return self.results

    async def _run_one(
        self,
        file_path: str,
        retries: int = 0,
        overrides: Optional[Dict[str, Any]] = None,
        shared_page: Any = None,
    ) -> Dict[str, Any]:
        start = time.time()
        attempts: List[Dict[str, Any]] = []
        max_attempts = retries + 1
        last_error: Optional[str] = None

        content = Path(file_path).read_text(encoding="utf-8")
        if overrides:
            content = self._apply_web_overrides(content, overrides)

        for attempt in range(1, max_attempts + 1):
            player = self._player_factory(content, file_path)
            last_error = None
            try:
                await player.run()
            except Exception as e:
                last_error = str(e)
            if last_error is None:
                last_error = (
                    "; ".join(
                        f"task - {t.get('name')}: {t.get('error')}"
                        for t in getattr(player, "failed_tasks", [])
                    )
                    or None
                )
            success = getattr(player, "status", "done") != "error" and last_error is None
            attempts.append({"attempt": attempt, "success": success})
            if success:
                return {
                    "file": file_path,
                    "success": True,
                    "executed": True,
                    "output": getattr(player, "output_path", None),
                    "attempts": attempts,
                    "duration": int((time.time() - start) * 1000),
                    "resultType": "success",
                    **(
                        {"_shared_page": getattr(player, "shared_page", None)}
                        if shared_page is not None or getattr(player, "shared_page", None)
                        else {}
                    ),
                }

        return {
            "file": file_path,
            "success": False,
            "executed": True,
            "error": last_error,
            "attempts": attempts,
            "duration": int((time.time() - start) * 1000),
            "resultType": "failed",
        }


    def _apply_web_overrides(self, content: str, overrides: Dict[str, Any]) -> str:
        """Apply batch-level web env overrides to a script without a web
        section: prepend a web block (script-level keys always win because we
        only inject when the script declares none)."""
        if not overrides:
            return content
        try:
            doc = yaml.safe_load(content)
        except yaml.YAMLError:
            return content
        if not isinstance(doc, dict):
            return content
        has_own = any(isinstance(doc.get(k), dict) for k in ("web", "page", "browser", "target"))
        has_native_target = any(
            doc.get(k) is not None for k in ("android", "computer")
        )
        if has_own or has_native_target:
            return content
        web_block = yaml.safe_dump({"web": overrides}, allow_unicode=True)
        return web_block + content

    @staticmethod
    def _not_executed(file_path: str) -> Dict[str, Any]:
        return {
            "file": file_path,
            "success": False,
            "executed": False,
            "resultType": "notExecuted",
        }

    def _write_summary(self) -> None:
        summary_path = self.config.get("summary")
        if not summary_path:
            return
        import json as _json

        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        Path(summary_path).write_text(
            _json.dumps(
                [{k: v for k, v in r.items() if not k.startswith("_")} for r in self.results],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info(f"Batch summary written to {summary_path}")

    # -- summary helpers (upstream execution-summary) -----------------------

    def get_failed_files(self) -> List[str]:
        return [r["file"] for r in self.results if r.get("resultType") == "failed"]

    def get_successful_files(self) -> List[str]:
        return [r["file"] for r in self.results if r.get("resultType") == "success"]

    def get_not_executed_files(self) -> List[str]:
        return [r["file"] for r in self.results if r.get("resultType") == "notExecuted"]

    @property
    def passed(self) -> bool:
        return all(r["success"] for r in self.results)
