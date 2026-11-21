"""YAML batch executor.

Synced from upstream packages/cli/src/yaml-batch-executor.ts and the
MidsceneYamlConfig schema in packages/core/src/yaml.ts.

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

from midscene.cli.config_options import (
    NATIVE_TARGET_KEYS as _NATIVE_TARGET_KEYS,
)
from midscene.cli.config_options import WEB_TARGET_KEYS as _WEB_TARGET_KEYS
from midscene.cli.config_options import YAML_TARGET_KEYS as _TARGET_KEYS
from midscene.cli.execution_summary import (
    create_not_executed_yaml_result,
    is_batch_successful,
    write_execution_summary_file,
)
from midscene.cli.yaml_batch_error import YamlBatchExecutionError

RESULT_TYPES = ("success", "failed", "partialFailed", "notExecuted")


def parse_batch_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a MidsceneYamlConfig mapping (upstream schema subset)."""
    files = config.get("files")
    if not files:
        raise ValueError('property "files" is required in the batch config')
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        raise ValueError('"files" must be a list of file paths')

    concurrent_value = config.get("concurrent")
    if concurrent_value is None:
        concurrent_value = config.get("maxConcurrentFiles")
    concurrent = int(concurrent_value or 1)
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

    def _hook(name: str) -> Optional[str]:
        value = config.get(name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f'"{name}" must be a YAML file path')
        return value

    before_all = _hook("beforeAll") or config.get("setup")
    if before_all is not None and not isinstance(before_all, str):
        raise ValueError('"setup" must be a YAML file path')
    namespace = config.get("namespace") or config.get("name")
    if namespace is not None and not isinstance(namespace, str):
        raise ValueError('"namespace" must be a string')
    artifact_dir = config.get("artifactDir") or config.get("output")
    if artifact_dir is not None and not isinstance(artifact_dir, str):
        raise ValueError('"artifactDir" must be a directory path')

    return {
        "files": files,
        "concurrent": concurrent,
        "continueOnError": bool(config.get("continueOnError", True)),
        "retry": retry,
        "summary": config.get("summary"),
        "setup": before_all,
        "before_all": before_all,
        "after_all": _hook("afterAll"),
        "before_each": _hook("beforeEach"),
        "after_each": _hook("afterEach"),
        "namespace": namespace,
        "artifact_dir": artifact_dir,
        "share_browser_context": share_browser_context,
        "reuse_page": reuse_page,
        "web_overrides": _web_overrides(config),
        "native_overrides": _native_overrides(config),
    }


def _web_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Partial web-env overrides deep-merged into each script
    (web/page/browser/target keys, upstream MidsceneYamlTargetConfig)."""
    for key in _WEB_TARGET_KEYS:
        if isinstance(config.get(key), dict):
            return dict(config[key])
    return {}


def _native_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Batch-level native target section merged into each script of that
    platform (upstream globalConfig merge for android/ios/harmony/computer)."""
    for key in _NATIVE_TARGET_KEYS:
        if isinstance(config.get(key), dict):
            return {key: dict(config[key])}
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
    if any(merged.get(key) is not None for key in _NATIVE_TARGET_KEYS):
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


async def run_yaml_batch(
    config: Dict[str, Any],
    player_factory: Callable[[str, str], Any],
    state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Execute every file of a batch config and return the result list.

    `player_factory(yaml_content, file_path)` returns a ScriptPlayer-like
    object with run()/status/failed_tasks/output_path/result. Unexpected
    failures are raised as YamlBatchExecutionError; per-file player errors are
    recorded as failed results instead. When `state` is provided it receives
    the lifecycle hook error (if any) under the "hook_error" key.
    """
    if state is None:
        state = {}
    cfg = parse_batch_config(config)
    results: List[Dict[str, Any]] = []
    hook_error: Optional[str] = None

    try:
        # beforeAll (alias: setup): failure aborts the whole batch.
        if cfg["before_all"]:
            setup_result = await _run_one(
                cfg, player_factory, cfg["before_all"], retries=0
            )
            results.append(setup_result)
            if not setup_result["success"]:
                hook_error = f"beforeAll failed: {setup_result.get('error')}"
                for file_path in cfg["files"]:
                    results.append(_not_executed(file_path))
                state["hook_error"] = hook_error
                _write_summary(cfg, results)
                _write_artifact(cfg, results, hook_error)
                return results

        if cfg["concurrent"] > 1:
            semaphore = asyncio.Semaphore(cfg["concurrent"])

            async def bounded(file_path: str) -> Dict[str, Any]:
                async with semaphore:
                    return await _run_file(
                        cfg,
                        player_factory,
                        file_path,
                        retries=cfg["retry"],
                        overrides=cfg["web_overrides"],
                        native_overrides=cfg["native_overrides"],
                    )

            outcomes = await asyncio.gather(
                *(bounded(f) for f in cfg["files"])
            )
            results.extend(outcomes)
        else:
            shared_page = None
            for index, file_path in enumerate(cfg["files"]):
                result = await _run_file(
                    cfg,
                    player_factory,
                    file_path,
                    retries=cfg["retry"],
                    overrides=cfg["web_overrides"],
                    native_overrides=cfg["native_overrides"],
                    shared_page=shared_page if cfg["share_browser_context"] else None,
                )
                results.append(result)
                if cfg["share_browser_context"]:
                    shared_page = result.get("_shared_page") or shared_page
                if not result["success"] and not cfg["continueOnError"]:
                    for remaining_path in cfg["files"][index + 1:]:
                        results.append(_not_executed(remaining_path))
                    break

        if cfg["after_all"]:
            after_all = await _run_one(
                cfg,
                player_factory,
                cfg["after_all"],
                retries=0,
                overrides=cfg["web_overrides"],
                native_overrides=cfg["native_overrides"],
            )
            if not after_all["success"]:
                hook_error = f"afterAll failed: {after_all.get('error')}"
                logger.warning(hook_error)

        state["hook_error"] = hook_error
        _write_summary(cfg, results)
        _write_artifact(cfg, results, hook_error)
        return results
    except YamlBatchExecutionError:
        raise
    except Exception as error:
        occurrences = [
            {"caseId": result.get("file"), "result": result} for result in results
        ]
        raise YamlBatchExecutionError(error, occurrences) from error


async def _run_file(
    cfg: Dict[str, Any],
    player_factory: Callable[[str, str], Any],
    file_path: str,
    retries: int = 0,
    overrides: Optional[Dict[str, Any]] = None,
    native_overrides: Optional[Dict[str, Any]] = None,
    shared_page: Any = None,
) -> Dict[str, Any]:
    """Run one file with the beforeEach / afterEach lifecycle hooks."""
    kwargs = {
        "retries": retries,
        "overrides": overrides,
        "native_overrides": native_overrides,
    }
    if shared_page is not None:
        kwargs["shared_page"] = shared_page

    if cfg["before_each"]:
        pre = await _run_one(
            cfg,
            player_factory,
            cfg["before_each"],
            retries=0,
            overrides=overrides,
            native_overrides=native_overrides,
        )
        if not pre["success"]:
            return _hook_failure(file_path, "beforeEach", pre)

    result = await _run_one(cfg, player_factory, file_path, **kwargs)

    if cfg["after_each"]:
        post = await _run_one(
            cfg,
            player_factory,
            cfg["after_each"],
            retries=0,
            overrides=overrides,
            native_overrides=native_overrides,
        )
        if not post["success"]:
            result = _hook_failure(file_path, "afterEach", post, result)
    return result


def _hook_failure(
    file_path: str,
    hook: str,
    hook_result: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    failed = {
        "file": file_path,
        "success": False,
        "executed": True,
        "error": f"{hook} failed: {hook_result.get('error')}",
        "resultType": "failed",
        "duration": (result or {}).get("duration", 0),
    }
    if result is not None:
        failed["attempts"] = result.get("attempts", [])
        if "_shared_page" in result:
            failed["_shared_page"] = result["_shared_page"]
    return failed


async def _run_one(
    cfg: Dict[str, Any],
    player_factory: Callable[[str, str], Any],
    file_path: str,
    retries: int = 0,
    overrides: Optional[Dict[str, Any]] = None,
    native_overrides: Optional[Dict[str, Any]] = None,
    shared_page: Any = None,
) -> Dict[str, Any]:
    start = time.time()
    attempts: List[Dict[str, Any]] = []
    max_attempts = retries + 1
    last_error: Optional[str] = None

    content = Path(file_path).read_text(encoding="utf-8")
    if overrides:
        content = _apply_web_overrides(content, overrides)
    if native_overrides:
        content = _apply_native_overrides(content, native_overrides)

    for attempt in range(1, max_attempts + 1):
        player = player_factory(content, file_path)
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


def _apply_web_overrides(content: str, overrides: Dict[str, Any]) -> str:
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
    has_own = any(
        isinstance(doc.get(k), dict) for k in _WEB_TARGET_KEYS
    )
    has_native_target = any(
        doc.get(k) is not None for k in _NATIVE_TARGET_KEYS
    )
    if has_own or has_native_target:
        return content
    web_block = yaml.safe_dump({"web": overrides}, allow_unicode=True)
    return web_block + content


def _apply_native_overrides(
    content: str, overrides: Dict[str, Any]
) -> str:
    """Deep-merge the batch-level native target section into a script of
    the same platform; the script's own keys win. A script targeting
    another platform (or another target) is left untouched."""
    if not overrides:
        return content
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if not isinstance(doc, dict):
        return content
    key, values = next(iter(overrides.items()))
    declared = [k for k in _TARGET_KEYS if doc.get(k) is not None]
    if declared and declared[0] != key:
        return content
    own = doc.get(key)
    if isinstance(own, dict):
        doc[key] = {**values, **own}
    else:
        doc[key] = dict(values)
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _not_executed(file_path: str) -> Dict[str, Any]:
    return create_not_executed_yaml_result(file_path)


def _write_summary(cfg: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
    write_execution_summary_file(cfg.get("summary"), results)


def _write_artifact(
    cfg: Dict[str, Any],
    results: List[Dict[str, Any]],
    hook_error: Optional[str],
) -> None:
    """Publish a directory report artifact when artifactDir is configured."""
    artifact_dir = cfg.get("artifact_dir")
    if not artifact_dir:
        return
    import re

    from midscene.shared.report_artifact import ReportArtifactStore

    namespace = cfg.get("namespace") or "batch-report"
    report_id = re.sub(r"[^A-Za-z0-9_-]+", "-", namespace).strip("-") or "batch-report"
    try:
        store = ReportArtifactStore(
            artifact_dir,
            report_id,
            kind="test",
            reuse_existing_report=True,
        )
        for index, result in enumerate(results, start=1):
            file_path = result.get("file") or f"file-{index}"
            store.write_execution(str(file_path), result, {"file": file_path})
        store.write_runner(
            {
                "namespace": cfg.get("namespace"),
                "results": results,
                "hookError": hook_error,
                "passed": is_batch_successful(results, hook_error),
            }
        )
        store.finalize()
    except Exception as error:
        # The run itself already finished; do not turn a failed artifact
        # write (permissions, lock timeout) into a crash after the results.
        logger.warning(
            f"Failed to write report artifact to {artifact_dir}: {error}"
        )
        return
    logger.info(f"Batch report artifact written to {artifact_dir}")
