"""Synced from upstream packages/core/tests/unit-test/conversation-history.test.ts."""

from midscene.core.ai_model.workflows.planning.conversation_history import (
    ConversationHistory,
)

IGNORED_IMAGE_PLACEHOLDER = {
    "type": "text",
    "text": "(image ignored due to size optimization)",
}


def _history_messages(entries):
    return [
        entry["message"]
        if entry["type"] == "input-message"
        else entry["output"]["rawValue"]
        for entry in entries
    ]


def _user(content):
    return {"role": "user", "content": content}


def _assistant(content):
    return {"role": "assistant", "content": content}


def _user_with_image(text, image_url):
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image", "url": image_url},
        ],
    }


def test_stores_explicit_entries_and_exports_chat_output_without_losing_provider_fields():
    """stores explicit entries and exports Chat output without losing provider fields"""
    message = _user("question")
    raw_value = {
        "role": "assistant",
        "content": "answer",
        "refusal": None,
        "reasoning_content": "provider reasoning",
    }
    output = {
        "type": "model-output",
        "output": {"type": "chat-completion", "rawValue": raw_value},
    }
    history = ConversationHistory(
        initial_messages=[{"type": "input-message", "message": message}]
    )
    history.append_model_output(output["output"])
    entries = [{"type": "input-message", "message": message}, output]

    assert history.snapshot() == entries
    assert list(history) == entries
    assert history.to_json() == entries
    assert _history_messages(history.snapshot()) == [message, raw_value]


def test_resets_state_and_seeds_new_messages():
    """resets state and seeds new messages"""
    history = ConversationHistory()
    history.append_message(_assistant("greet"))
    history.append_message(_user("question"))

    history.seed(
        [
            {"type": "input-message", "message": _assistant("seeded")},
            {"type": "input-message", "message": _user("follow-up")},
        ]
    )

    assert _history_messages(history.snapshot()) == [
        _assistant("seeded"),
        _user("follow-up"),
    ]
    assert len(history) == 2


def test_reset_clears_messages_memories_and_sub_goals():
    """reset clears messages, memories, and subGoals"""
    history = ConversationHistory()
    history.append_message(_user("msg1"))
    history.append_message(_assistant("msg2"))
    history.append_memory("Memory from task 1")
    history.append_memory("Another memory")
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "Sub-goal 1"},
            {"index": 2, "status": "pending", "description": "Sub-goal 2"},
        ]
    )

    history.append_historical_log("Step 1")
    history.append_historical_log("Step 2")

    history.pending_feedback_message = "Current time: 2026-03-02T16:04:00"

    history.reset()

    assert len(history) == 0
    assert _history_messages(history.snapshot()) == []
    assert history.get_memories() == []
    assert history.memories_to_text() == ""
    assert history.sub_goals_to_text() == ""
    assert history.historical_logs_to_text() == ""
    assert history.pending_feedback_message == ""


def test_clears_pending_feedback_message_only_when_set():
    """clears pending feedback message only when set"""
    history = ConversationHistory()

    assert history.pending_feedback_message == ""

    history.reset_pending_feedback_message_if_exists()
    assert history.pending_feedback_message == ""

    history.pending_feedback_message = "Need a screenshot"
    history.reset_pending_feedback_message_if_exists()
    assert history.pending_feedback_message == ""

    history.pending_feedback_message = ""
    history.reset_pending_feedback_message_if_exists()
    assert history.pending_feedback_message == ""


def test_returns_independent_snapshot_copies():
    """returns independent snapshot copies"""
    history = ConversationHistory()
    history.append_message(_assistant("hello"))
    snapshot = _history_messages(history.snapshot())
    snapshot.append(_user("mutated"))

    assert len(history) == 1
    assert _history_messages(history.snapshot()) == [_assistant("hello")]


def test_returns_image_messages_without_modification():
    """returns image messages without modification"""
    history = ConversationHistory()

    message_with_two_images = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Look at these"},
            {"type": "image", "url": "data:image1"},
            {"type": "image", "url": "data:image2"},
        ],
    }

    history.append_message(_user_with_image("first", "data:image1"))
    history.append_message(_assistant("ack1"))
    history.append_message(message_with_two_images)

    snapshot = _history_messages(history.snapshot())

    assert snapshot[0] == _user_with_image("first", "data:image1")
    assert snapshot[1] == _assistant("ack1")
    assert snapshot[2] == message_with_two_images


def test_replaces_older_images_with_text_when_exceeding_the_max_images_limit():
    """replaces older images with text when exceeding the maxImages limit"""
    history = ConversationHistory()

    message_with_two_images = {
        "role": "user",
        "content": [
            {"type": "text", "text": "More images"},
            {"type": "image", "url": "data:image2"},
            {"type": "image", "url": "data:image3"},
        ],
    }

    history.append_message(_user_with_image("first", "data:image1"))
    history.append_message(_assistant("ack"))
    history.append_message(message_with_two_images)

    snapshot_with_limit = _history_messages(history.snapshot(1))

    assert snapshot_with_limit[0] == {
        "role": "user",
        "content": [{"type": "text", "text": "first"}, IGNORED_IMAGE_PLACEHOLDER],
    }
    assert snapshot_with_limit[2] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "More images"},
            {"type": "image", "url": "data:image2"},
            IGNORED_IMAGE_PLACEHOLDER,
        ],
    }

    # Original history remains unchanged
    snapshot_without_limit = _history_messages(history.snapshot())
    assert snapshot_without_limit[0] == _user_with_image("first", "data:image1")
    assert snapshot_without_limit[2] == message_with_two_images


def test_initializes_with_empty_sub_goals():
    """initializes with empty sub-goals"""
    history = ConversationHistory()
    assert history.sub_goals_to_text() == ""


def test_sets_all_sub_goals_and_marks_first_pending_as_running():
    """sets all sub-goals and marks first pending as running"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "finished", "description": "Done task"},
            {"index": 2, "status": "pending", "description": "Todo task"},
        ]
    )

    # First pending is automatically marked as running
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Done task (finished)\n"
        "2. Todo task (running)\n"
        "Current sub-goal is: Todo task"
    )


def test_replaces_existing_sub_goals_when_set_sub_goals_is_called():
    """replaces existing sub-goals when setSubGoals is called"""
    history = ConversationHistory()
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "Old goal"}]
    )

    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "New goal 1"},
            {"index": 2, "status": "pending", "description": "New goal 2"},
        ]
    )

    # First pending is automatically marked as running
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. New goal 1 (running)\n"
        "2. New goal 2 (pending)\n"
        "Current sub-goal is: New goal 1"
    )


def test_preserves_descriptions_when_merge_sub_goals_receives_empty_descriptions():
    """preserves descriptions when mergeSubGoals receives empty descriptions"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "Log in to the system"},
            {"index": 2, "status": "pending", "description": "Open reimbursement page"},
            {
                "index": 3,
                "status": "pending",
                "description": "Fill and submit reimbursement form",
            },
        ]
    )

    history.merge_sub_goals(
        [
            {"index": 1, "status": "finished", "description": ""},
            {"index": 2, "status": "pending", "description": ""},
            {"index": 3, "status": "pending", "description": ""},
        ]
    )

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Log in to the system (finished)\n"
        "2. Open reimbursement page (running)\n"
        "3. Fill and submit reimbursement form (pending)\n"
        "Current sub-goal is: Open reimbursement page"
    )


def test_ignores_newly_introduced_goals_with_empty_descriptions_in_merge_sub_goals():
    """ignores newly introduced goals with empty descriptions in mergeSubGoals"""
    history = ConversationHistory()
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "Existing goal"}]
    )

    history.merge_sub_goals(
        [
            {"index": 1, "status": "finished", "description": ""},
            {"index": 2, "status": "pending", "description": ""},
        ]
    )

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n1. Existing goal (finished)"
    )


def test_updates_a_single_sub_goal_by_index():
    """updates a single sub-goal by index"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "First"},
            {"index": 2, "status": "pending", "description": "Second"},
        ]
    )

    # After setSubGoals, first is running, second is pending
    result = history.update_sub_goal(1, {"status": "finished"})

    assert result is True
    # updateSubGoal doesn't auto-promote, only markSubGoalFinished does
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. First (finished)\n"
        "2. Second (pending)\n"
        "Current sub-goal is: Second"
    )


def test_updates_description_of_a_sub_goal():
    """updates description of a sub-goal"""
    history = ConversationHistory()
    history.set_sub_goals([{"index": 1, "status": "pending", "description": "Old"}])

    history.update_sub_goal(1, {"description": "Updated description"})

    # First pending was marked as running by setSubGoals
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Updated description (running)\n"
        "Current sub-goal is: Updated description"
    )


def test_returns_false_when_updating_non_existent_sub_goal():
    """returns false when updating non-existent sub-goal"""
    history = ConversationHistory()
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "First"}]
    )

    result = history.update_sub_goal(99, {"status": "finished"})

    assert result is False


def test_marks_a_sub_goal_as_finished_and_promotes_next_pending_to_running():
    """marks a sub-goal as finished and promotes next pending to running"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "Task 1"},
            {"index": 2, "status": "pending", "description": "Task 2"},
        ]
    )

    # After setSubGoals: Task 1 is running, Task 2 is pending
    result = history.mark_sub_goal_finished(1)

    assert result is True
    # After markSubGoalFinished: Task 1 is finished, Task 2 is promoted to running
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (running)\n"
        "Current sub-goal is: Task 2"
    )


def test_returns_false_when_marking_non_existent_sub_goal_as_finished():
    """returns false when marking non-existent sub-goal as finished"""
    history = ConversationHistory()
    result = history.mark_sub_goal_finished(1)
    assert result is False


def test_marks_all_sub_goals_as_finished():
    """marks all sub-goals as finished"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "Task 1"},
            {"index": 2, "status": "pending", "description": "Task 2"},
            {"index": 3, "status": "pending", "description": "Task 3"},
        ]
    )

    history.mark_all_sub_goals_finished()

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (finished)\n"
        "3. Task 3 (finished)"
    )


def test_marks_all_sub_goals_as_finished_when_some_are_already_finished():
    """marks all sub-goals as finished when some are already finished"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "finished", "description": "Task 1"},
            {"index": 2, "status": "pending", "description": "Task 2"},
        ]
    )

    history.mark_all_sub_goals_finished()

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (finished)"
    )


def test_handles_mark_all_sub_goals_finished_with_empty_sub_goals():
    """handles markAllSubGoalsFinished with empty sub-goals"""
    history = ConversationHistory()
    history.mark_all_sub_goals_finished()
    assert history.sub_goals_to_text() == ""


def test_mark_first_pending_as_running_only_affects_first_pending_goal():
    """markFirstPendingAsRunning only affects first pending goal"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "finished", "description": "Task 1"},
            {"index": 2, "status": "pending", "description": "Task 2"},
            {"index": 3, "status": "pending", "description": "Task 3"},
        ]
    )

    # setSubGoals already called markFirstPendingAsRunning, so Task 2 is running
    # Task 3 should still be pending
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (running)\n"
        "3. Task 3 (pending)\n"
        "Current sub-goal is: Task 2"
    )


def test_does_not_change_status_when_no_pending_goals_exist():
    """does not change status when no pending goals exist"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "finished", "description": "Task 1"},
            {"index": 2, "status": "finished", "description": "Task 2"},
        ]
    )

    # No pending goals, so no change
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (finished)"
    )


def test_sub_goals_to_text_shows_all_sub_goals_with_their_status():
    """subGoalsToText shows all sub-goals with their status"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "finished", "description": "Log in to the system"},
            {"index": 2, "status": "finished", "description": "Complete to-do items"},
            {"index": 3, "status": "pending", "description": "Submit the form"},
        ]
    )

    # First pending is automatically marked as running
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Log in to the system (finished)\n"
        "2. Complete to-do items (finished)\n"
        "3. Submit the form (running)\n"
        "Current sub-goal is: Submit the form"
    )


def test_appends_log_to_the_currently_running_sub_goal():
    """appends log to the currently running sub-goal"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "Task 1"},
            {"index": 2, "status": "pending", "description": "Task 2"},
        ]
    )

    # Task 1 is automatically running
    history.append_sub_goal_log("Clicked login button")
    history.append_sub_goal_log("Typed username")

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (running)\n"
        "2. Task 2 (pending)\n"
        "Current sub-goal is: Task 1\n"
        "Actions performed for current sub-goal:\n"
        "- Clicked login button\n"
        "- Typed username"
    )


def test_ignores_empty_log_strings():
    """ignores empty log strings"""
    history = ConversationHistory()
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "Task 1"}]
    )

    history.append_sub_goal_log("")
    history.append_sub_goal_log("Valid log")

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (running)\n"
        "Current sub-goal is: Task 1\n"
        "Actions performed for current sub-goal:\n"
        "- Valid log"
    )


def test_does_nothing_when_appending_log_with_no_running_sub_goal():
    """does nothing when appending log with no running sub-goal"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "finished", "description": "Task 1"},
            {"index": 2, "status": "finished", "description": "Task 2"},
        ]
    )

    history.append_sub_goal_log("Some log")

    # No running goal, so no logs appear
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (finished)"
    )


def test_clears_logs_when_sub_goal_status_changes_via_mark_sub_goal_finished():
    """clears logs when sub-goal status changes via markSubGoalFinished"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "Task 1"},
            {"index": 2, "status": "pending", "description": "Task 2"},
        ]
    )

    # Append logs to Task 1 (running)
    history.append_sub_goal_log("Step A")
    history.append_sub_goal_log("Step B")

    # Mark Task 1 finished -> Task 2 becomes running (logs cleared for both)
    history.mark_sub_goal_finished(1)

    # Task 2 is now running with no logs
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (running)\n"
        "Current sub-goal is: Task 2"
    )


def test_clears_logs_when_sub_goal_description_changes_via_update_sub_goal():
    """clears logs when sub-goal description changes via updateSubGoal"""
    history = ConversationHistory()
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "Task 1"}]
    )

    history.append_sub_goal_log("Did something")

    # Update description -> logs should be cleared
    history.update_sub_goal(1, {"description": "Updated Task 1"})

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Updated Task 1 (running)\n"
        "Current sub-goal is: Updated Task 1"
    )


def test_preserves_logs_when_update_sub_goal_sets_same_values():
    """preserves logs when updateSubGoal sets same values"""
    history = ConversationHistory()
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "Task 1"}]
    )

    history.append_sub_goal_log("Did something")

    # Update with same status and description -> no change, logs preserved
    history.update_sub_goal(1, {"status": "running", "description": "Task 1"})

    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (running)\n"
        "Current sub-goal is: Task 1\n"
        "Actions performed for current sub-goal:\n"
        "- Did something"
    )


def test_clears_logs_when_set_sub_goals_replaces_all_sub_goals():
    """clears logs when setSubGoals replaces all sub-goals"""
    history = ConversationHistory()
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "Old task"}]
    )

    history.append_sub_goal_log("Old log")

    # Replace all sub-goals
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "New task"}]
    )

    # New sub-goals start with no logs
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. New task (running)\n"
        "Current sub-goal is: New task"
    )


def test_clears_logs_for_non_finished_goals_when_mark_all_sub_goals_finished_is_called():
    """clears logs for non-finished goals when markAllSubGoalsFinished is called"""
    history = ConversationHistory()
    history.set_sub_goals(
        [
            {"index": 1, "status": "pending", "description": "Task 1"},
            {"index": 2, "status": "pending", "description": "Task 2"},
        ]
    )

    history.append_sub_goal_log("Some work")
    history.mark_all_sub_goals_finished()

    # All finished, no current goal, no logs shown
    assert history.sub_goals_to_text() == (
        "Sub-goals:\n"
        "1. Task 1 (finished)\n"
        "2. Task 2 (finished)"
    )


def test_initializes_with_empty_historical_logs():
    """initializes with empty historical logs"""
    history = ConversationHistory()
    assert history.historical_logs_to_text() == ""


def test_appends_historical_logs():
    """appends historical logs"""
    history = ConversationHistory()
    history.append_historical_log("Clicked the login button")
    history.append_historical_log("Typed username into the input")

    assert history.historical_logs_to_text() == (
        "Here are the steps that have been executed:\n"
        "- Clicked the login button\n"
        "- Typed username into the input"
    )


def test_ignores_empty_historical_log_strings():
    """ignores empty historical log strings"""
    history = ConversationHistory()
    history.append_historical_log("")
    history.append_historical_log("Valid step")
    history.append_historical_log("")

    assert history.historical_logs_to_text() == (
        "Here are the steps that have been executed:\n- Valid step"
    )


def test_accumulates_historical_logs_across_multiple_rounds():
    """accumulates historical logs across multiple rounds"""
    history = ConversationHistory()
    history.append_historical_log("Step 1: Navigated to page")
    history.append_historical_log("Step 2: Clicked search button")
    history.append_historical_log("Step 3: Entered search query")

    assert history.historical_logs_to_text() == (
        "Here are the steps that have been executed:\n"
        "- Step 1: Navigated to page\n"
        "- Step 2: Clicked search button\n"
        "- Step 3: Entered search query"
    )


def test_historical_logs_are_independent_from_sub_goal_logs():
    """historical logs are independent from sub-goal logs"""
    history = ConversationHistory()

    # Set up sub-goals (deepThink mode scenario)
    history.set_sub_goals(
        [{"index": 1, "status": "pending", "description": "Task 1"}]
    )
    history.append_sub_goal_log("Sub-goal log entry")

    # Also add historical logs (non-deepThink mode scenario)
    history.append_historical_log("Historical log entry")

    # Both should be independently tracked
    assert "Sub-goal log entry" in history.sub_goals_to_text()
    assert "Historical log entry" in history.historical_logs_to_text()
    assert "Sub-goal log entry" not in history.historical_logs_to_text()
    assert "Historical log entry" not in history.sub_goals_to_text()


def test_initializes_with_empty_memories():
    """initializes with empty memories"""
    history = ConversationHistory()
    assert history.get_memories() == []
    assert history.memories_to_text() == ""


def test_appends_memories_to_the_list():
    """appends memories to the list"""
    history = ConversationHistory()
    history.append_memory("First memory")
    history.append_memory("Second memory")

    assert history.get_memories() == ["First memory", "Second memory"]


def test_ignores_empty_memories_when_appending():
    """ignores empty memories when appending"""
    history = ConversationHistory()
    history.append_memory("Valid memory")
    history.append_memory("")
    history.append_memory("Another valid memory")

    assert history.get_memories() == ["Valid memory", "Another valid memory"]


def test_converts_memories_to_text_representation():
    """converts memories to text representation"""
    history = ConversationHistory()
    history.append_memory("User logged in successfully")
    history.append_memory("Found 3 items in the cart")

    assert history.memories_to_text() == (
        "Memories from previous steps:\n---\n"
        "User logged in successfully\n---\n"
        "Found 3 items in the cart\n"
    )


def test_clears_all_memories():
    """clears all memories"""
    history = ConversationHistory()
    history.append_memory("Memory 1")
    history.append_memory("Memory 2")

    history.clear_memories()

    assert history.get_memories() == []
    assert history.memories_to_text() == ""


def test_returns_independent_copy_of_memories_array():
    """returns independent copy of memories array"""
    history = ConversationHistory()
    history.append_memory("Original memory")

    memories = history.get_memories()
    memories.append("Mutated memory")

    assert history.get_memories() == ["Original memory"]


def test_does_not_compress_when_message_count_is_below_threshold():
    """does not compress when message count is below threshold"""
    history = ConversationHistory()
    history.append_message(_user("msg1"))
    history.append_message(_user("msg2"))
    history.append_message(_user("msg3"))

    result = history.compress_history(5, 2)

    assert result is False
    assert len(history) == 3
    assert _history_messages(history.snapshot()) == [
        _user("msg1"),
        _user("msg2"),
        _user("msg3"),
    ]


def test_does_not_compress_when_message_count_equals_threshold():
    """does not compress when message count equals threshold"""
    history = ConversationHistory()
    history.append_message(_user("msg1"))
    history.append_message(_user("msg2"))
    history.append_message(_user("msg3"))

    result = history.compress_history(3, 2)

    assert result is False
    assert len(history) == 3


def test_compresses_history_when_message_count_exceeds_threshold():
    """compresses history when message count exceeds threshold"""
    history = ConversationHistory()
    for index in range(1, 26):
        history.append_message(_user(f"msg{index}"))

    result = history.compress_history(20, 10)

    assert result is True
    # 10 kept messages + 1 placeholder
    assert len(history) == 11


def test_keeps_the_most_recent_messages_after_compression():
    """keeps the most recent messages after compression"""
    history = ConversationHistory()
    for index in range(1, 26):
        history.append_message(_user(f"msg{index}"))

    history.compress_history(20, 10)

    snapshot = _history_messages(history.snapshot())
    # First message should be the placeholder
    assert snapshot[0] == {
        "role": "user",
        "content": "(15 previous conversation messages have been omitted)",
    }
    # Remaining messages should be the last 10 (msg16 to msg25)
    for index in range(1, 11):
        assert snapshot[index] == _user(f"msg{15 + index}")


def test_preserves_message_order_after_compression():
    """preserves message order after compression"""
    history = ConversationHistory()
    history.append_message(_user("old1"))
    history.append_message(_assistant("old2"))
    history.append_message(_user("old3"))
    history.append_message(_assistant("keep1"))
    history.append_message(_user("keep2"))

    history.compress_history(4, 2)

    snapshot = _history_messages(history.snapshot())
    assert snapshot == [
        {
            "role": "user",
            "content": "(3 previous conversation messages have been omitted)",
        },
        _assistant("keep1"),
        _user("keep2"),
    ]


def test_handles_compression_with_image_messages():
    """handles compression with image messages"""
    history = ConversationHistory()
    history.append_message(_user_with_image("old", "data:old-image"))
    history.append_message(_assistant("old response"))
    history.append_message(_user_with_image("new", "data:new-image"))

    history.compress_history(2, 1)

    snapshot = _history_messages(history.snapshot())
    assert len(snapshot) == 2
    assert snapshot[0] == {
        "role": "user",
        "content": "(2 previous conversation messages have been omitted)",
    }
    assert snapshot[1] == _user_with_image("new", "data:new-image")


def test_keeps_output_items_together_while_trimming_old_input_images_in_a_snapshot():
    """keeps output items together while trimming old input images in a snapshot"""
    history = ConversationHistory()
    history.append_message(
        _user_with_image("before", "data:image/png;base64,OLD")
    )
    output = {
        "type": "model-output",
        "output": {
            "type": "responses",
            "rawValue": [
                {
                    "type": "reasoning",
                    "id": "rs-test",
                    "summary": [],
                    "encrypted_content": "opaque-state",
                }
            ],
        },
    }
    history.append_model_output(output["output"])
    history.append_message(
        _user_with_image("after", "data:image/png;base64,NEW")
    )
    snapshot = history.snapshot(1)
    assert snapshot[1] == output
    assert snapshot[0] == {
        "type": "input-message",
        "message": {
            "role": "user",
            "content": [
                {"type": "text", "text": "before"},
                {
                    "type": "text",
                    "text": "(image ignored due to size optimization)",
                },
            ],
        },
    }
    assert snapshot[2] == {
        "type": "input-message",
        "message": _user_with_image("after", "data:image/png;base64,NEW"),
    }
    assert history.snapshot()[0] == {
        "type": "input-message",
        "message": _user_with_image("before", "data:image/png;base64,OLD"),
    }
