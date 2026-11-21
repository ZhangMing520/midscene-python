"""Multi-turn conversation example (upstream prompt/planning/multi-turn-example.ts)."""

from typing import Any, Dict, Optional

from midscene.core.ai_model.prompt.planning.action_output_example import (
    build_action_output_example,
    create_sample_input_action,
    create_sample_tap_action,
)
from midscene.core.ai_model.prompt.planning.planning_response_example import (
    build_planning_response_example,
)
from midscene.core.ai_model.prompt.planning.sub_goals_text import build_sub_goals_text

_SAMPLE_NAME_SUB_GOAL = {"index": 1, "description": "Fill in the Name field with 'John'"}
_SAMPLE_EMAIL_SUB_GOAL = {
    "index": 2,
    "description": "Fill in the Email field with 'john@example.com'",
}
_SAMPLE_RETURN_EMAIL_SUB_GOAL = {
    "index": 3,
    "description": "Return the filled email address",
}


def build_planning_multi_turn_example(
    action_output_protocol,
    include_sub_goals: bool,
    include_thought: bool,
    include_log: bool,
    locate_prompt_spec: Optional[Dict[str, Any]] = None,
    prefix: Optional[str] = None,
) -> str:
    build_action_output = action_output_protocol["build_action_output"]

    def render_sub_goals_content(content: str, fallback: str = "") -> str:
        return content if include_sub_goals else fallback

    tap_name_example = build_action_output_example(
        create_sample_tap_action("Name input field in the registration form"),
        build_action_output,
        locate_prompt_spec,
        2,
    )
    input_name_example = build_action_output_example(
        create_sample_input_action("John"), build_action_output
    )
    tap_email_example = build_action_output_example(
        create_sample_tap_action("Email input field in the registration form"),
        build_action_output,
        locate_prompt_spec,
        3,
    )
    input_email_example = build_action_output_example(
        create_sample_input_action("john@example.com"), build_action_output
    )

    def ex(**kwargs) -> str:
        update = kwargs.pop("update_sub_goals", None)
        return build_planning_response_example(
            prefix=prefix, update_sub_goals=update, **kwargs
        )

    turn1 = ex(
        planning=(
            (
                "The user wants me to fill out the registration form with specific "
                "values and return the email address. I can see the form has two "
                "fields: Name and Email. Both are currently empty. "
                + render_sub_goals_content(
                    "I'll break this down into sub-goals and start with the Name field.",
                    "I should start by clicking on the Name field.",
                )
                + " Note: The instruction is to fill the form only (not submit), "
                "and return the email at the end."
            )
            if include_thought
            else None
        ),
        update_sub_goals=(
            [
                {**_SAMPLE_NAME_SUB_GOAL, "status": "pending"},
                {**_SAMPLE_EMAIL_SUB_GOAL, "status": "pending"},
                {**_SAMPLE_RETURN_EMAIL_SUB_GOAL, "status": "pending"},
            ]
            if include_sub_goals
            else None
        ),
        log="Click on the Name field to start filling the form" if include_log else None,
        action_output_example=tap_name_example,
    )

    turn2 = ex(
        planning=(
            (
                "The Name field is now focused. I need to type 'John' into this field. "
                + render_sub_goals_content(
                    "Current sub-goal is running, will be completed after input.",
                    "After this, I'll need to fill the Email field as well.",
                )
            )
            if include_thought
            else None
        ),
        log="Typing 'John' into the Name field" if include_log else None,
        action_output_example=input_name_example,
    )

    turn3 = ex(
        planning=(
            (
                "The Name field now shows 'John'. "
                + render_sub_goals_content(
                    "Sub-goal 1 is complete. Next, I need to fill the Email field "
                    "for sub-goal 2.",
                    "Next, I need to fill the Email field with 'john@example.com'. "
                    "I'll click on the Email field first.",
                )
            )
            if include_thought
            else None
        ),
        mark_sub_goals_done=[1] if include_sub_goals else None,
        memory="Name field has been filled with 'John'" if include_sub_goals else None,
        log="Moving to the Email field" if include_log else None,
        action_output_example=tap_email_example,
    )

    turn4 = ex(
        planning=(
            (
                "The Email field is now focused. I'll enter 'john@example.com'. "
                + render_sub_goals_content(
                    "After this, sub-goal 2 will be complete and my task will be done.",
                    "After this, both required fields will be filled and my task "
                    "will be complete.",
                )
            )
            if include_thought
            else None
        ),
        log="Typing email address into the Email field" if include_log else None,
        action_output_example=input_email_example,
    )

    turn5 = ex(
        planning=(
            (
                "Both fields are now filled: Name shows 'John' and Email shows "
                "'john@example.com'. "
                + render_sub_goals_content(
                    "Sub-goal 2 is complete. The user asked me to return the filled "
                    "email address, so I need to include 'john@example.com' in my "
                    "response. All sub-goals are now finished.",
                    "The user asked me to return the filled email address, so I "
                    "should include 'john@example.com' in my response. The "
                    "instruction has been fulfilled.",
                )
            )
            if include_thought
            else None
        ),
        mark_sub_goals_done=[2, 3] if include_sub_goals else None,
        complete={"success": True, "message": "john@example.com"},
    )

    return f"""
## Multi-turn Conversation Example

Below is an example of a multi-turn conversation for "fill out the registration form with name 'John' and email 'john@example.com', then return the filled email address":

### Turn 1 - Initial instruction

**User message:**
<user_instruction>fill out the registration form with name 'John' and email 'john@example.com', then return the filled email address</user_instruction>

**Screenshot:** [Shows a registration form with empty Name and Email fields]

**Your response:**

{turn1}

### Turn 2 - After clicking Name field

**User message:**
The previous action has been executed, here is the latest screenshot. Please continue according to the instruction.

{render_sub_goals_content(build_sub_goals_text([
    {**_SAMPLE_NAME_SUB_GOAL, 'status': 'running', 'logs': ['Click on the Name field to start filling the form']},
    {**_SAMPLE_EMAIL_SUB_GOAL, 'status': 'pending'},
    {**_SAMPLE_RETURN_EMAIL_SUB_GOAL, 'status': 'pending'},
]))}

**Screenshot:** [Shows the form with Name field now focused/active]

**Your response:**

{turn2}

### Turn 3 - After entering name

**User message:**
The previous action has been executed, here is the latest screenshot. Please continue according to the instruction.

{render_sub_goals_content(build_sub_goals_text([
    {**_SAMPLE_NAME_SUB_GOAL, 'status': 'running', 'logs': ['Click on the Name field to start filling the form', "Typing 'John' into the Name field"]},
    {**_SAMPLE_EMAIL_SUB_GOAL, 'status': 'pending'},
    {**_SAMPLE_RETURN_EMAIL_SUB_GOAL, 'status': 'pending'},
]))}

**Screenshot:** [Shows the form with Name field containing 'John']

**Your response:**

{turn3}

### Turn 4 - After clicking Email field

**User message:**
The previous action has been executed, here is the latest screenshot. Please continue according to the instruction.

{render_sub_goals_content(build_sub_goals_text([
    {**_SAMPLE_NAME_SUB_GOAL, 'status': 'finished'},
    {**_SAMPLE_EMAIL_SUB_GOAL, 'status': 'running', 'logs': ['Moving to the Email field']},
    {**_SAMPLE_RETURN_EMAIL_SUB_GOAL, 'status': 'pending'},
]))}

**Screenshot:** [Shows the form with Name='John' and Email field focused]

**Your response:**

{turn4}

### Turn 5 - After entering email ({render_sub_goals_content('Goal accomplished', 'Instruction fulfilled')})

**User message:**
The previous action has been executed, here is the latest screenshot. Please continue according to the instruction.

{render_sub_goals_content(build_sub_goals_text([
    {**_SAMPLE_NAME_SUB_GOAL, 'status': 'finished'},
    {**_SAMPLE_EMAIL_SUB_GOAL, 'status': 'running', 'logs': ['Moving to the Email field', 'Typing email address into the Email field']},
    {**_SAMPLE_RETURN_EMAIL_SUB_GOAL, 'status': 'pending'},
]))}

**Screenshot:** [Shows the form with Name='John' and Email='john@example.com']

**Your response:**

{turn5}
"""


__all__ = ["build_planning_multi_turn_example"]
