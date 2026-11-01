"""Task cache for planning/locate results.

Synced from upstream packages/core/src/agent/task-cache.ts (plan + locate
entries, YAML file format `<cacheId>.cache.yaml` under midscene_run/cache).
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from loguru import logger

from .ai_model.env_config import MIDSCENE_RUN_DIR, get_midscene_run_dir

CACHE_FILE_EXT = ".cache.yaml"


def _replace_illegal_path_chars_and_space(cache_id: str) -> str:
    return re.sub(r'[/\\?%*:|"<> ]', "-", cache_id).strip()


class TaskCache:
    """Store planning YAML flows and locate results per cache id."""

    def __init__(
        self,
        cache_id: str,
        enabled: bool,
        read_only_mode: bool = False,
        write_only_mode: bool = False,
        cache_dir: Optional[str] = None,
    ):
        if not cache_id:
            raise ValueError("cacheId is required")

        self.enabled = enabled
        self.read_only_mode = read_only_mode
        self.write_only_mode = write_only_mode
        self.is_cache_result_used = False
        self.cache_original_length = 0

        safe_cache_id = _replace_illegal_path_chars_and_space(cache_id)
        self.cache_id = safe_cache_id

        cache_dir = cache_dir or os.environ.get(MIDSCENE_RUN_DIR) or get_midscene_run_dir()
        cache_file_dir = Path(cache_dir) / "cache"
        cache_file_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file_path = str(cache_file_dir / f"{safe_cache_id}{CACHE_FILE_EXT}")

        self.cache: Dict[str, Any] = {
            "midscene_version": __import__("midscene").__version__,
            "cache_id": safe_cache_id,
            "caches": [],
        }

        if enabled and Path(self.cache_file_path).exists():
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f) or {}
                if isinstance(content, dict) and content.get("caches"):
                    self.cache = content
            except Exception as e:
                logger.warning(f"Failed to read cache file, will create new one: {e}")

        self.cache_original_length = len(self.cache.get("caches", []))
        # Consumed locate entries for this run only; upstream keeps this in
        # memory so a fresh Agent run can reuse the same cache file.
        self._locate_matched_indices = set()

    # -- matching -----------------------------------------------------------

    def match_plan_cache(self, prompt: Any) -> Optional[Dict[str, Any]]:
        """Match the first unconsumed plan cache entry for the prompt."""
        if not self.enabled or self.write_only_mode:
            return None
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        for index, entry in enumerate(self.cache.get("caches", [])):
            if (
                entry.get("type") == "plan"
                and not entry.get("consumed")
                and entry.get("prompt") == prompt_str
            ):
                cached_version = self.cache.get("midscene_version")
                if cached_version:
                    logger.debug(f"cache file written by version {cached_version}")
                entry["consumed"] = True
                self.is_cache_result_used = True
                logger.info(f"Matched plan cache for prompt: {prompt_str[:50]}")
                return dict(entry)
        return None

    def append_plan_cache(self, prompt: Any, yaml_workflow: str) -> None:
        """Append a plan cache entry (or replace a consumed match of same prompt)."""
        if not self.enabled or self.read_only_mode:
            return
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        for index, entry in enumerate(self.cache.get("caches", [])):
            if entry.get("type") == "plan" and entry.get("prompt") == prompt_str:
                self.cache["caches"][index] = {
                    "type": "plan",
                    "prompt": prompt_str,
                    "yamlWorkflow": yaml_workflow,
                }
                self._flush()
                return
        self.cache.setdefault("caches", []).append(
            {"type": "plan", "prompt": prompt_str, "yamlWorkflow": yaml_workflow}
        )
        self._flush()

    def release_plan_cache(self, prompt: Any) -> None:
        """Make a matched entry replayable again after a failed replay."""
        if not self.enabled or self.read_only_mode:
            return
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        changed = False
        for entry in self.cache.get("caches", []):
            if (
                entry.get("type") == "plan"
                and entry.get("prompt") == prompt_str
                and entry.get("consumed")
            ):
                entry.pop("consumed", None)
                changed = True
        if changed:
            self._flush()

    # -- locate entries ------------------------------------------------------

    def match_locate_cache(self, prompt: Any) -> Optional[Dict[str, Any]]:
        """Match the next unconsumed locate entry for the prompt.

        Returns ``{"cache": feature, "index": index, "prompt": prompt_str}``.
        Each entry is consumed once per run so repeated prompts keep their own
        occurrence, mirroring upstream `matchCache('locate')`.
        """
        if not self.enabled or self.write_only_mode:
            return None
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        for index, entry in enumerate(self.cache.get("caches", [])):
            if entry.get("type") != "locate" or index in self._locate_matched_indices:
                continue
            if entry.get("prompt") != prompt_str:
                continue
            feature = entry.get("cache")
            if not feature and entry.get("xpaths"):
                feature = {"xpaths": entry["xpaths"]}
            if not isinstance(feature, dict) or not feature.get("xpaths"):
                continue
            self._locate_matched_indices.add(index)
            self.is_cache_result_used = True
            logger.info(f"Matched locate cache for prompt: {prompt_str[:50]}")
            return {"cache": feature, "index": index, "prompt": prompt_str}
        return None

    def has_locate_cache(self, prompt: Any) -> bool:
        """True when the prompt already has a non-empty locate entry.

        Non-consuming: used to avoid appending a duplicate entry when the plan
        supplies the coordinates (upstream ``hasNonEmptyCache`` check).
        """
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        for entry in self.cache.get("caches", []):
            if entry.get("type") != "locate" or entry.get("prompt") != prompt_str:
                continue
            feature = entry.get("cache") or {"xpaths": entry.get("xpaths")}
            if isinstance(feature, dict) and feature.get("xpaths"):
                return True
        return False

    def append_locate_cache(
        self,
        prompt: Any,
        feature: Dict[str, Any],
        replace_index: Optional[int] = None,
    ) -> None:
        """Append a locate entry, or replace a stale matched entry in place."""
        if not self.enabled or self.read_only_mode:
            return
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        record = {"type": "locate", "prompt": prompt_str, "cache": feature}
        caches = self.cache.setdefault("caches", [])
        if replace_index is not None and 0 <= replace_index < len(caches):
            caches[replace_index] = record
        else:
            caches.append(record)
        self._flush()

    # -- persistence --------------------------------------------------------

    def flush(self) -> None:
        self._flush()

    def _flush(self) -> None:
        if not self.enabled or self.read_only_mode:
            return
        try:
            path = Path(self.cache_file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.cache, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            logger.warning(f"Failed to write cache file: {e}")

