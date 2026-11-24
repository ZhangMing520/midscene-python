"""Synced from upstream packages/core/tests/unit-test/task-cache-empty-flow.test.ts,
task-cache-poisoning.test.ts and ai-act-plan-cache-fallback.test.ts."""


def test_should_return_cache_when_yaml_workflow_has_non_empty_flow(
    tmp_path, monkeypatch
):
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    cache = TaskCache(cache_id="unit-test", enabled=True)
    cache.append_plan_cache("do something", "- type: Tap")

    cache2 = TaskCache(cache_id="unit-test", enabled=True)
    entry = cache2.match_plan_cache("do something")

    assert entry is not None
    assert entry["yamlWorkflow"] == "- type: Tap"

    # consumed entries do not match again
    assert cache2.match_plan_cache("do something") is None


def test_should_return_none_when_no_plan_cache_matches(tmp_path, monkeypatch):
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    cache = TaskCache(cache_id="empty", enabled=True)

    assert cache.match_plan_cache("nothing") is None


def test_should_release_a_consumed_plan_cache_after_a_failed_replay(
    tmp_path, monkeypatch
):
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    cache = TaskCache(cache_id="release-test", enabled=True)
    cache.append_plan_cache("do something", "- type: Tap")

    assert cache.match_plan_cache("do something") is not None
    assert cache.match_plan_cache("do something") is None

    cache.release_plan_cache("do something")
    assert cache.match_plan_cache("do something") is not None


def test_appends_a_new_locate_entry_when_nothing_was_consumed(tmp_path, monkeypatch):
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    cache = TaskCache(cache_id="locate-unit", enabled=True)
    cache.append_locate_cache("the button", {"xpaths": ["/html/body/button[1]"]})

    cache2 = TaskCache(cache_id="locate-unit", enabled=True)
    matched = cache2.match_locate_cache("the button")

    assert matched is not None
    assert matched["cache"] == {"xpaths": ["/html/body/button[1]"]}
    assert matched["index"] == 0
    # each entry is consumed once per run
    assert cache2.match_locate_cache("the button") is None


def test_replaces_a_stale_locate_entry_in_place_when_the_consumed_hit_was_rejected(
    tmp_path, monkeypatch
):
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    cache = TaskCache(cache_id="locate-replace", enabled=True)
    cache.append_locate_cache("the button", {"xpaths": ["/old"]})
    matched = cache.match_locate_cache("the button")
    cache.append_locate_cache(
        "the button", {"xpaths": ["/new"]}, replace_index=matched["index"]
    )

    cache2 = TaskCache(cache_id="locate-replace", enabled=True)
    assert len(cache2.cache["caches"]) == 1
    assert cache2.match_locate_cache("the button")["cache"] == {"xpaths": ["/new"]}


def test_replaces_in_memory_but_does_not_flush_to_file_in_read_only_mode(
    tmp_path, monkeypatch
):
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    cache = TaskCache(cache_id="locate-readonly", enabled=True, read_only_mode=True)
    cache.append_locate_cache("the button", {"xpaths": ["/x"]})

    cache2 = TaskCache(cache_id="locate-readonly", enabled=True)
    assert cache2.match_locate_cache("the button") is None
