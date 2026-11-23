"""YAML batch executor.

Synced from upstream packages/cli/src/yaml-batch-executor.ts and the
MidsceneYamlConfig schema in packages/core/src/yaml.ts.

Config keys: files (required), concurrent, continueOnError, retry, summary,
setup, shareBrowserContext / reusePage (web-only, sequential only).
Batch-level target sections are the upstream globalConfig: they deep-merge
into each script with the global values winning on conflict.
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
    """Batch-level native target sections merged into each script
    (upstream globalConfig merge for android/ios/harmony/computer)."""
    return {
        key: dict(config[key])
        for key in _NATIVE_TARGET_KEYS
        if isinstance(config.get(key), dict)
    }


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


def _deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge `override` into `base` (upstream lodash.merge).

    Nested maps are merged key by key, so overriding one option (for example
    one HTTP header or waitForNetworkIdle.timeout) keeps the script's other
    nested options. Non-map values, including lists, are replaced wholesale.
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key in merged:
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_web_overrides(
    script: Dict[str, Any], overrides: Dict[str, Any]
) -> Dict[str, Any]:
    """Deep-merge the batch-level web env into a script's own web env; the
    global config wins (upstream lodash merge order)."""
    if not overrides:
        return script
    merged = dict(script)
    web_key = next(
        (
            key
            for key in ("web", "page", "browser", "target")
            if isinstance(merged.get(key), dict)
        ),
        None,
    )
    if web_key:
        merged[web_key] = _deep_merge(merged[web_key], overrides)
    else:
        merged["web"] = dict(overrides)
    return merged


async def run_yaml_batch(
    config: Dict[str, Any],
    options: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Execute every file of a batch config and return the result list.

    ``options`` is either the upstream-style options mapping (which may carry
    a ``player_factory`` and ``state``) or a player factory callable directly.
    `player_factory(yaml_content, file_path)` returns a ScriptPlayer-like
    object with run()/status/failed_tasks/output_path/result. Unexpected
    failures are raised as YamlBatchExecutionError; per-file player errors are
    recorded as failed results instead. A provided ``state`` mapping receives
    the lifecycle hook error (if any) under the "hook_error" key.
    """
    if callable(options):
        player_factory = options
        options = {}
    else:
        options = options or {}
        player_factory = options.get("player_factory")
    if player_factory is None:
        raise ValueError(
            "run_yaml_batch requires a player_factory in options or as the "
            "second argument"
        )
    state = options.get("state") or {}
    cfg = parse_batch_config(config)
    results: List[Dict[str, Any]] = []
    hook_error: Optional[str] = None

    try:
        # beforeAll (alias: setup): failure aborts the whole batch. Retries use
        # a fresh player per attempt, so a failed prerequisite never leaks its
        # runtime into the main files.
        if cfg["before_all"]:
            setup_result = await _run_one(
                cfg, player_factory, cfg["before_all"], retries=cfg["retry"]
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


async def run_yaml_batch_with_case_ids(
    config: Dict[str, Any],
    case_ids: List[str],
    options: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Run a batch and return results paired with caller-provided case IDs.

    The occurrence count covers the setup file (when configured) plus every
    main file; IDs must be unique and in execution order.
    """
    setup_file = config.get("setup") or config.get("beforeAll")
    occurrence_count = len(config.get("files") or []) + (
        1 if setup_file else 0
    )
    if len(case_ids) != occurrence_count:
        raise ValueError(
            "Batch occurrence identity mismatch: expected "
            f"{occurrence_count} case ID(s), received {len(case_ids)}"
        )
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Batch occurrence case IDs must be unique")
    reuse_page = bool(config.get("reusePage"))
    if reuse_page and not config.get("shareBrowserContext"):
        raise ValueError("reusePage requires shareBrowserContext: true")
    if reuse_page and int(config.get("concurrent") or 1) != 1:
        raise ValueError("reusePage requires concurrent: 1")

    results = await run_yaml_batch(config, options or {})
    return [
        {"caseId": case_id, "result": result}
        for case_id, result in zip(case_ids, results)
    ]


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

    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except OSError as e:
        return {
            "file": file_path,
            "success": False,
            "executed": True,
            "error": str(e),
            "attempts": [],
            "duration": int((time.time() - start) * 1000),
            "resultType": "failed",
        }
    if overrides:
        content = _apply_web_overrides(content, overrides)
    if native_overrides:
        content = _apply_native_overrides(content, native_overrides)

    for attempt in range(1, max_attempts + 1):
        try:
            player = player_factory(content, file_path)
        except Exception as e:
            # Player creation (YAML parse, target setup) is not retried:
            # record this file as failed and let the batch continue.
            attempts.append({"attempt": attempt, "success": False})
            return {
                "file": file_path,
                "success": False,
                "executed": True,
                "error": str(e),
                "attempts": attempts,
                "duration": int((time.time() - start) * 1000),
                "resultType": "failed",
            }
        last_error = None
        run_error = None
        try:
            await player.run()
        except Exception as e:
            run_error = str(e)
            last_error = run_error
        if last_error is None:
            last_error = (
                "; ".join(
                    f"task - {t.get('name')}: {t.get('error')}"
                    for t in getattr(player, "failed_tasks", [])
                )
                or None
            )
        status = getattr(player, "status", "done")
        success = status != "error" and last_error is None
        attempts.append({"attempt": attempt, "success": success})
        if success:
            output_path = getattr(player, "output_path", None)
            if output_path and not Path(output_path).exists():
                output_path = None
            return {
                "file": file_path,
                "success": True,
                "executed": True,
                "output": output_path,
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
        # A task failure without a player-level error is a partial failure.
        "resultType": (
            "partialFailed"
            if status != "error" and run_error is None
            else "failed"
        ),
    }


def _apply_web_overrides(content: str, overrides: Dict[str, Any]) -> str:
    """Merge the batch-level web env into a script; the global config wins on
    conflicting keys (upstream merge order) while script-only keys survive."""
    if not overrides:
        return content
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if not isinstance(doc, dict):
        return content
    web_key = next(
        (k for k in _WEB_TARGET_KEYS if isinstance(doc.get(k), dict)), None
    )
    if web_key:
        doc[web_key] = _deep_merge(doc[web_key], overrides)
    else:
        doc["web"] = dict(overrides)
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _apply_native_overrides(
    content: str, overrides: Dict[str, Any]
) -> str:
    """Deep-merge every batch-level native target section into a script; the
    global config wins on conflict (upstream merge order) while script-only
    keys survive."""
    if not overrides:
        return content
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if not isinstance(doc, dict):
        return content
    for key, values in overrides.items():
        own = doc.get(key)
        doc[key] = _deep_merge(own, values) if isinstance(own, dict) else dict(values)
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
