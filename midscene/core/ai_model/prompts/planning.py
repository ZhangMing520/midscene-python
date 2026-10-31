"""Planning prompts.

Synced from upstream packages/core/src/ai-model/prompt/planning/*
(system-prompt.ts, action-space-description.ts, action-output-example.ts,
planning-response-example.ts, sub-goals-text.ts, multi-turn-example.ts).
"""

from typing import Any, Dict, List, Optional, Sequence

import yaml

from ..env_config import get_preferred_language
from ..env_config import (
    planning_model_family_required_for_locate_message,
)  # noqa: F401 re-export
from .locate import locate_grounding_rules


# ---------------------------------------------------------------------------
# Action output examples (action-output-example.ts)
# ---------------------------------------------------------------------------

def _inject_locate_result_into_sample(
    sample: Dict[str, Any],
    locate_fields: List[str],
    prompt_spec: Dict[str, Any],
    locate_result_example_index: int,
) -> Dict[str, Any]:
    result = dict(sample)
    example_index = locate_result_example_index
    for field in locate_fields:
        value = result.get(field)
        if isinstance(value, dict) and value.get("prompt"):
            example_values = prompt_spec["exampleValues"]
            result[field] = {
                **value,
                prompt_spec["resultKey"]: example_values[
                    example_index % len(example_values)
                ],
            }
            example_index += 1
    return result


def build_action_output_example(
    action: Dict[str, Any],
    build_action_output,
    locate_prompt_spec: Optional[Dict[str, Any]] = None,
    locate_result_example_index: int = 0,
) -> Optional[str]:
    sample = action.get("sample")
    if not isinstance(sample, dict):
        return None

    locate_fields = list(action.get("locate_fields", []))
    sample_with_locate_result = (
        _inject_locate_result_into_sample(
            sample, locate_fields, locate_prompt_spec, locate_result_example_index
        )
        if locate_prompt_spec
        else sample
    )

    return build_action_output(
        {
            "actionName": action["name"],
            "param": sample_with_locate_result,
            "locateFields": locate_fields,
            "locateResultKey": locate_prompt_spec.get("resultKey")
            if locate_prompt_spec
            else None,
        }
    )


def create_sample_tap_action(prompt: str) -> Dict[str, Any]:
    return {
        "name": "Tap",
        "sample": {"locate": {"prompt": prompt}},
        "locate_fields": ["locate"],
    }


def create_sample_input_action(value: str) -> Dict[str, Any]:
    return {"name": "Input", "sample": {"value": value}, "locate_fields": ["locate"]}


# ---------------------------------------------------------------------------
# Planning response examples (planning-response-example.ts)
# ---------------------------------------------------------------------------

def build_planning_response_example(
    prefix: Optional[str] = None,
    planning: Optional[str] = None,
    update_sub_goals: Optional[List[Dict[str, Any]]] = None,
    mark_sub_goals_done: Optional[List[int]] = None,
    memory: Optional[str] = None,
    complete: Optional[Dict[str, Any]] = None,
    log: Optional[str] = None,
    action_output_example: Optional[str] = None,
) -> str:
    sections: List[str] = []
    if prefix:
        sections.append(prefix)

    if planning:
        sections.append(f"<planning>{planning}</planning>")

    if update_sub_goals:
        lines = "\n".join(
            f'  <sub-goal index="{goal["index"]}" status="{goal["status"]}">'
            f'{goal["description"]}</sub-goal>'
            for goal in update_sub_goals
        )
        sections.append(f"<update-plan-content>\n{lines}\n</update-plan-content>")

    if mark_sub_goals_done:
        lines = "\n".join(
            f'  <sub-goal index="{index}" status="finished" />'
            for index in mark_sub_goals_done
        )
        sections.append(f"<mark-sub-goal-done>\n{lines}\n</mark-sub-goal-done>")

    if memory:
        sections.append(f"<memory>{memory}</memory>")

    if complete:
        sections.append(
            f'<complete success="{str(complete["success"]).lower()}">'
            f'{complete.get("message", "")}</complete>'
        )
    else:
        if not action_output_example:
            raise ValueError(
                "Cannot build planning response example without an action output example"
            )
        if log:
            sections.append(f"<log>{log}</log>")
        sections.append(action_output_example)

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Sub-goals text (sub-goals-text.ts)
# ---------------------------------------------------------------------------

def build_sub_goals_text(sub_goals: List[Dict[str, Any]]) -> str:
    if not sub_goals:
        return ""

    lines = [
        f'{goal["index"]}. {goal["description"]} ({goal["status"]})'
        for goal in sub_goals
    ]

    current_goal = next(
        (goal for goal in sub_goals if goal["status"] == "running"), None
    ) or next((goal for goal in sub_goals if goal["status"] == "pending"), None)

    current_goal_text = ""
    if current_goal:
        current_goal_text = f'\nCurrent sub-goal is: {current_goal["description"]}'
        logs = current_goal.get("logs")
        if logs:
            log_lines = "\n".join(f"- {log}" for log in logs)
            current_goal_text += (
                f"\nActions performed for current sub-goal:\n{log_lines}"
            )

    return "Sub-goals:\n" + "\n".join(lines) + current_goal_text


# ---------------------------------------------------------------------------
# Multi-turn conversation example (multi-turn-example.ts)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Action space description (action-space-description.ts)
# ---------------------------------------------------------------------------

class _LiteralBlockDumper(yaml.SafeDumper):
    """Dump multiline strings as literal blocks, matching js-yaml output."""


def _represent_str_as_literal(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_LiteralBlockDumper.add_representer(str, _represent_str_as_literal)


def serialize_action_descriptions(
    action_descriptions: List[Any], action_space_format: str = "yaml"
) -> str:
    if action_space_format == "jsonl":
        import json as _json

        return "\n".join(_json.dumps(d, ensure_ascii=False) for d in action_descriptions)
    return yaml.dump(
        action_descriptions,
        Dumper=_LiteralBlockDumper,
        indent=2,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=10**6,
    ).strip()


def build_planning_action_space_description(
    action_space: Sequence[Any],
    planning_protocol,
    locate_prompt_spec: Optional[Dict[str, Any]] = None,
) -> str:
    locate_field_description = planning_protocol[
        "action_space_protocol"
    ]["build_locate_field_description"](locate_prompt_spec)

    action_output_protocol = planning_protocol["action_output_protocol"]
    include_example = planning_protocol["action_space_protocol"][
        "include_action_output_example"
    ]

    descriptions = []
    for action in action_space:
        action_output_example = (
            build_action_output_example(
                action if isinstance(action, dict) else action.to_prompt_dict(),
                action_output_protocol["build_action_output"],
                locate_prompt_spec,
            )
            if include_example
            else None
        )
        descriptions.append(
            planning_protocol["action_space_protocol"]["build_action_description"](
                {
                    "action": action,
                    "locate_field_description": locate_field_description,
                    "action_output_example": action_output_example,
                }
            )
        )

    action_space_format = planning_protocol["action_space_protocol"].get(
        "format", "yaml"
    )
    return serialize_action_descriptions(descriptions, action_space_format)


def build_locate_field_description(
    locate_prompt_spec: Optional[Dict[str, Any]] = None,
) -> str:
    if locate_prompt_spec:
        return (
            "{ prompt: string, "
            f"{locate_prompt_spec['resultKey']}: {locate_prompt_spec['resultValueSchema']}"
            f" /* {locate_prompt_spec['resultValueDescription']} */ }}"
        )
    return "{ prompt: string /* description of the target element */ }"


# ---------------------------------------------------------------------------
# Standard planning system prompt (system-prompt.ts)
# ---------------------------------------------------------------------------

def build_standard_planning_system_prompt(
    action_space: Sequence[Any],
    planning_protocol,
    include_locate_in_planning: bool,
    locate_prompt_spec: Optional[Dict[str, Any]] = None,
    include_sub_goals: bool = False,
    include_thought: bool = True,
    include_log: bool = True,
) -> str:
    if include_locate_in_planning and not locate_prompt_spec:
        raise ValueError(planning_model_family_required_for_locate_message())

    action_output_protocol = planning_protocol["action_output_protocol"]
    preferred_language = get_preferred_language()

    action_space_description = build_planning_action_space_description(
        action_space, planning_protocol, locate_prompt_spec if include_locate_in_planning else None
    )

    has_run_adb_shell = any(
        (action if isinstance(action, dict) else action.to_prompt_dict()).get("name")
        == "RunAdbShell"
        for action in action_space
    )
    action_output_tags_text = ", ".join(
        f"<{tag}>" for tag in action_output_protocol["action_output_tag_names"]
    )

    should_include_sub_goals = include_sub_goals

    def render_sub_goals_content(content: str, fallback: str = "") -> str:
        return content if should_include_sub_goals else fallback

    def render_thought_content(content: str, fallback: str = "") -> str:
        return content if include_thought else fallback

    def render_log_content(content: str, fallback: str = "") -> str:
        return content if include_log else fallback

    completion_check_step_number = 3 if should_include_sub_goals else 2
    action_step_number = completion_check_step_number + 1

    adb_shell_line = (
        "- If the user's task can be completed with the RunAdbShell action, prefer using the RunAdbShell action.\n"
        if has_run_adb_shell
        else ""
    )

    sub_goals_memory_section = render_sub_goals_content(
        """## Step 2: Memory Data from Current Screenshot (related tags: <memory>)

Use <memory> to record clear, task-relevant information from the current screenshot that may be needed in later steps. The current screenshot will not be available later, so memory should preserve enough detail for future reasoning, verification, or action.

- Record information completely and exactly as shown. Do not summarize, translate, normalize, or merge values that may matter later.
- When recording an item, include the item itself, its exact task-relevant details, and the visible cue or UI context that identifies where it came from when relevant.
- Keep similar or repeated items as separate memory entries unless their task-relevant details are confirmed to be the same.
- After navigation, scrolling, editing, deletion, saving, or other screen changes, treat remembered positions, order, indexes, and UI bindings as references only. Re-check the current screen before acting on them.

Examples:
- If you need to find an item and later assert its details, record the item name and the exact details needed for the assertion, such as status, price, date, owner, description, or other visible fields.
- If you need to compare multiple similar results, record each candidate separately with its exact distinguishing details and visible context.
- If you need to copy information from one place to another, record the exact source value and the target field or UI cue it should be mapped to.

Don't use this tag if no information needs to be preserved.""",
        "",
    )

    planning_tag_section = render_thought_content(
        f"""### <planning> tag (REQUIRED)

REQUIRED: You MUST always output the <planning> tag. Never skip it.

Write the content of the <planning> tag in {preferred_language}.

Include your planning details in the <planning> tag. It should answer: {render_sub_goals_content(
            "What is the user's requirement? What is the current state based on the screenshot? Are all sub-goals completed? If not, what should be the next action?",
            'What is the current state based on the screenshot? What should be the next action?',
        )} Write it naturally without numbering or section headers.

CRITICAL - Following Explicit Instructions: When the user gives you specific operation steps (not high-level goals), you MUST execute ONLY those exact steps - nothing more, nothing less. Do NOT add extra actions even if they seem logical. For example: "fill out the form" means only fill fields, do NOT submit; "click the button" means only click, do NOT wait for page load or verify results; "type 'hello'" means only type, do NOT press Enter.""",
        render_thought_content(
            "### <planning> tag (REQUIRED)\n\nREQUIRED: You MUST always output the <planning> tag. Never skip it.",
            "",
        ),
    ) if include_thought else ""

    observation_guidelines = render_sub_goals_content(
        """### Observation Guidelines

- Treat visible summaries, thumbnails, cropped content, and partially visible lists as potentially incomplete when the task depends on precise details.
- If the current view does not provide enough information to decide safely, use available UI affordances such as opening details, expanding content, previewing, enlarging, zooming, or scrolling before acting.""",
        "",
    )

    update_plan_section = render_sub_goals_content(
        """### <update-plan-content> tag

Use this structure to give or update your plan:

<update-plan-content>
  <sub-goal index="1" status="finished|pending">sub goal description</sub-goal>
  <sub-goal index="2" status="finished|pending">sub goal description</sub-goal>
  ...
</update-plan-content>

### <mark-sub-goal-done> tag

Use this structure to mark a sub-goal as done:

<mark-sub-goal-done>
  <sub-goal index="1" status="finished" />
</mark-sub-goal-done>

IMPORTANT: You MUST only mark a sub-goal as "finished" AFTER you have confirmed the task is actually completed by observing the result in the screenshot. Do NOT mark a sub-goal as done just because you expect the next action will complete it. Wait until you see visual confirmation in the screenshot that the sub-goal has been achieved.

### Note

During execution, you can call <update-plan-content> at any time to update the plan based on the latest screenshot and completed sub-goals.

### Example

If the user wants to "log in to a system using username and password, complete all to-do items, and submit a registration form", you can break it down into the following sub-goals:

<planning>...</planning>
<update-plan-content>
  <sub-goal index="1" status="pending">Log in to the system</sub-goal>
  <sub-goal index="2" status="pending">Complete all to-do items</sub-goal>
  <sub-goal index="3" status="pending">Submit the registration form</sub-goal>
</update-plan-content>

After logging in and seeing the to-do items, you can mark the sub-goal as done:

<mark-sub-goal-done>
  <sub-goal index="1" status="finished" />
</mark-sub-goal-done>

At this point, the status of all sub-goals is:

<update-plan-content>
  <sub-goal index="1" status="finished" />
  <sub-goal index="2" status="pending" />
  <sub-goal index="3" status="pending" />
</update-plan-content>

After some time, when the last sub-goal is also completed, you can mark it as done as well:

<mark-sub-goal-done>
  <sub-goal index="3" status="finished" />
</mark-sub-goal-done>""",
        "",
    )

    log_section = render_log_content(
        """### Log to give user feedback (preamble message)

The <log> tag is a brief preamble message to the user explaining what you're about to do. It should follow these principles and examples:

- **Use """
        + preferred_language
        + """
- **Keep it concise**: be no more than 1-2 sentences, focused on immediate, tangible next steps. (8–12 words or Chinese characters for quick updates).
- **Build on prior context**: if this is not the first action to be done, use the preamble message to connect the dots with what's been done so far and create a sense of momentum and clarity for the user to understand your next actions.
- **Keep your tone light, friendly and curious**: add small touches of personality in preambles feel collaborative and engaging.

**Examples:**
- <log>Click the login button</log>
- <log>Scroll to find the 'Yes' button in popup</log>
- <log>Previous actions failed to find the 'Yes' button, i will try again</log>
- <log>Go back to find the login button</log>""",
        "",
    )

    action_space_protocol = planning_protocol["action_space_protocol"]

    navigation_restriction_section = render_sub_goals_content(
        '',
        """**Page navigation restriction:**
- Unless the user's instruction explicitly asks you to click a link, jump to another page, or navigate to a URL, you MUST complete the task on the current page only.
- Do NOT navigate away from the current page on your own initiative (e.g., do not click links that lead to other pages, do not use browser back/forward, do not open new URLs).
- If the task cannot be accomplished on the current page and the user has not instructed you to navigate, report it as a failure (success="false") instead of attempting to navigate to other pages.""",
    )

    always_include_section = render_thought_content(
        """**Always include (REQUIRED):**
<!-- Step 1: Observe and Plan -->
<planning>Your planning details here. NEVER skip this tag.</planning>""",
        "",
    )

    return_format_sub_goals_section = render_sub_goals_content(
        """<!-- required when no update-plan-content is provided in the previous response -->
<update-plan-content>...</update-plan-content>

<!-- required when any sub-goal is completed -->
<mark-sub-goal-done>
  <sub-goal index="1" status="finished" />
</mark-sub-goal-done>

<!-- Step 2: Memory data from current screenshot if needed -->
<memory>...</memory>""",
        "",
    )
    response_prefix = planning_protocol.get("response_prefix") or ""

    return f"""
Target: You are an expert to manipulate the UI to accomplish the user's instruction. User will give you an instruction, some screenshots, background knowledge and previous logs indicating what have been done. Your task is to accomplish the instruction by thinking through the path to complete the task and give the next action to execute.

## Step 1: {render_sub_goals_content(
        'Observe and Plan (related tags: <planning>, <update-plan-content>, <mark-sub-goal-done>)',
        render_thought_content('Observe (related tags: <planning>)', 'Observe'),
    )}

First, observe the current screenshot and previous logs{render_sub_goals_content(
        ", then break down the user's instruction into multiple high-level sub-goals. Update the status of sub-goals based on what you see in the current screenshot.",
        ' to understand the current state.',
    )}

{observation_guidelines}

{planning_tag_section}

{update_plan_section}

{sub_goals_memory_section}

## Step {completion_check_step_number}: {render_sub_goals_content(
        'Check if Goal is Accomplished',
        'Check if the Instruction is Fulfilled',
    )} (related tags: <complete>)

Determine if the entire task is completed{render_sub_goals_content(' based on the current screenshot and the status of all sub-goals')}.

### CRITICAL: The User's Instruction is the Supreme Authority

The user's instruction defines the EXACT scope of what you must accomplish. You MUST follow it precisely - nothing more, nothing less. Violating this rule may cause severe consequences such as data loss, unintended operations, or system failures.

**Explicit instructions vs. High-level goals:**
- If the user gives you **explicit operation steps** (e.g., "click X", "type Y", "fill out the form"), treat them as exact commands. Execute ONLY those steps, nothing more.
- If the user gives you a **high-level goal** (e.g., "log in to the system", "complete the purchase"), you may determine the necessary steps to achieve it.

**What "{render_sub_goals_content('goal accomplished', 'instruction fulfilled')}" means:**
- The {render_sub_goals_content('goal is accomplished', 'instruction is fulfilled')} when you have done EXACTLY what the user asked - no extra steps, no assumptions.
- Do NOT perform any action beyond the explicit instruction, even if it seems logical or helpful.

**Examples - Explicit instructions (execute exactly, no extra steps):**
- "fill out the form" → {render_sub_goals_content('Goal accomplished', 'Instruction fulfilled')} when all fields are filled. Do NOT submit the form.
- "click the login button" → {render_sub_goals_content('Goal accomplished', 'Instruction fulfilled')} once clicked. Do NOT wait for page load or verify login success.
- "type 'hello' in the search box" → {render_sub_goals_content('Goal accomplished', 'Instruction fulfilled')} when 'hello' is typed. Do NOT press Enter or trigger search.
- "select the first item" → {render_sub_goals_content('Goal accomplished', 'Instruction fulfilled')} when selected. Do NOT proceed to checkout.

**Change completion:**
- If the requested outcome is a durable change, such as create, edit, update, delete, save, send, submit, apply, or publish, do not stop at an unsaved draft, open editor, temporary input, transient selection, or staged value. Continue through the app/page's normal completion control such as Save, Done, Confirm, OK, Submit, Apply, Send, or Publish before completing, so the result remains after leaving the screen.
- If the user only asks for an intermediate UI state, such as typing text, selecting an option, filling fields, or opening a screen without saving/submitting/applying, stop once that exact state is reached.

**Special case - Scrollable option lists and dropdowns:**
- When choosing an item from a scrollable select, dropdown, listbox, menu, or similar option list, first open the control if it is closed. Once the list is open, interact with the list itself, not the page.
- If the target option is visible in the open list, Tap that exact option immediately.
- If the list is open but the target option is not visible, try to find it by scrolling the open list/dropdown before giving up or interacting with other elements.
- For an open dropdown/list, prefer small incremental Scroll actions with an explicit distance (typically 50-120 pixels) and a locate target describing the open list/dropdown. Do NOT omit distance while searching within a list, because the default scroll distance can skip over relevant options and cause oscillation.
- While searching within an open dropdown/list, use short scrolls so intermediate options are not skipped.
- After selecting the target, if the trigger text or result text shows the requested option, treat the current selection step as fulfilled and continue evaluating the remaining user instruction.

**Special case - Text hidden by a narrow input field:**
- CRITICAL PRIORITY OVERRIDE - Input verification after an input action:
- This rule overrides the general requirement to verify the exact target text from the screenshot.
- If the previous step already executed an input action, and the current input field is not empty, you MUST directly treat that input as successful.
- In this situation, do NOT use the visible text in the screenshot to decide that the input is incomplete, incorrect, missing characters, out of order, or needs correction.
- Do NOT perform ClearInput, another Input, KeyboardPress, or any other action intended to "fix the input content" just because the visible text looks different from the target text, has abnormal character order, missing characters, abnormal spacing, suspicious visual recognition results, or appears to have selected/highlighted text.
- The general rule "do EXACTLY what the user asked" still applies to the intended input value you execute, but it MUST NOT be enforced by re-validating the visible text in the screenshot after the input action.
- Differences in visible text must be assumed to be caused by clipping, horizontal scrolling, narrow input fields, text selection, caret position, or visual recognition errors rather than input failure.
- Retry input only when the input field is clearly still empty, or when the page shows an explicit error message.

**Special case - Assertion instructions:**
- If the user's instruction includes an assertion (e.g., "verify that...", "check that...", "assert..."), and you observe from the screenshot that the assertion condition is NOT satisfied and cannot be satisfied, mark {render_sub_goals_content('the goal', 'it')} as failed (success="false").
- If the page is still loading (e.g., you see a loading spinner, skeleton screen, or progress bar), do NOT assert yet. Wait for the page to finish loading before evaluating the assertion.

### Completion Criteria for Process-required Instructions

If the user's instruction includes explicit operation steps, ordering requirements, or action requirements, it is a process-required instruction.

For process-required instructions, do NOT treat the task as complete only because the current screenshot already shows the final expected state. Do NOT infer that earlier steps were executed from the final UI state.

You may output <complete success="true"> only when the current execution history, previous logs, or the screenshot after the most recent action proves that every explicit step required by the user has been completed, and the final check condition is also satisfied.

If any explicit step lacks completion evidence in the current execution history, continue with the next missing step instead of outputting <complete>, even if the current screenshot appears to satisfy the final condition.

{navigation_restriction_section}

### Output Rules

- If the task is NOT complete, skip this section and continue to Step {action_step_number}.
- Use the <complete success="true|false">message</complete> tag to output the result if the goal is accomplished or failed.
  - the 'success' attribute is required. {render_sub_goals_content('It means whether the expected goal is accomplished based on what you observe in the current screenshot and the current execution history. ')}No matter what errors occurred during execution, set success="true" only when the current execution history shows that all steps required by the user have been completed and the final state satisfies the requirement. If the user asks for explicit operation steps or an ordered workflow, do not treat those steps as completed only because the current screenshot already shows the final expected state. If the {render_sub_goals_content('expected goal is not accomplished and cannot be accomplished', 'instruction is not fulfilled and cannot be fulfilled')}, set success="false".
  - the 'message' is the information that will be provided to the user. If the user asks for a specific format, strictly follow that.
- If you output <complete>, do NOT output {action_output_tags_text}. The task ends here.

## Step {action_step_number}: Determine Next Action (related tags: {render_log_content('<log>, ')}{action_output_tags_text}, <error>)

ONLY if the task is not complete: Think what the next action is according to the current screenshot{render_sub_goals_content(' and the plan')}.

- Don't give extra actions or plans beyond the instruction or the plan. For example, don't try to submit the form if the instruction is only to fill something.
- Consider the current screenshot and give the action that is most likely to accomplish the instruction. For example, if the next step is to click a button but it's not visible in the screenshot, you should try to find it first instead of give a click action.
- Make sure the previous actions are completed successfully. Otherwise, retry or do something else to recover.
- Give just the next ONE action you should do (if any)
- If there are some error messages reported by the previous actions, don't give up, try parse a new action to recover. If the error persists for more than 3 times, you should think this is an error and set the "error" field to the error message.

### Action Guidelines

{adb_shell_line}- If Swipe is available in the current Action Space, for touch continuous controls that set a value along a track, such as a slider, prefer Swipe from the current handle or filled position to the requested track endpoint instead of tapping the endpoint.
- When editing existing text in a UI field, preserve all existing text by moving the cursor and typing/deleting the minimal necessary characters.
- For insert/prepend/append edits, use CursorMove when the caret must be adjusted precisely, then use Input with mode "typeOnly" for inserted characters and KeyboardPress for newlines or deletion. If the caret lands in the wrong position, recover with CursorMove, KeyboardPress, or undo and retry cursor placement; do not switch to replace as a fallback for cursor placement failures.

### Interpreting Scroll and Swipe Directions

Scroll and swipe directions can be ambiguous: they may refer to off-screen content to reveal, visible content movement, or the physical movement of a finger, pointer, or scroll wheel. Infer the intended result from the user's goal, the interaction target, the current UI, and common usage in the user's language, rather than mechanically copying the user's direction word.

In the current Action Space, `direction` has the following meanings:

- Scroll follows the traditional mouse-wheel convention (with natural scrolling disabled). Its direction refers to the off-screen content to reveal; under this convention, it matches the wheel movement direction and is opposite to the content movement direction.
- Swipe follows the finger-movement convention. Its direction refers to finger movement; for controls where content follows the finger, it matches the content movement direction and is opposite to the direction from which off-screen content is revealed.

Use the following priority order:

1. Prioritize the user's goal or expected result, even when it conflicts with a direction word. For example, for "swipe the date picker down to increase the date", if dates increase from top to bottom, use Swipe up to move a larger date from below into the selected position.
2. Otherwise, if the user specifies a moving object or movement path, follow that object's physical movement. For example, "swipe the finger to the left" means Swipe left; "move the page content from top to bottom" means moving content downward, corresponding to Swipe down on a page where content follows the finger.
3. Otherwise, consider the interaction target and common usage in the user's language. For content browsing, such as pages and lists, scroll directions usually refer to the off-screen content the user wants to see. For directly manipulated controls, such as sliders and wheel pickers, swipe directions usually refer to the intended movement of the control's movable part. For example, the Chinese "往下滑一下页面" and English "scroll down the page" usually mean revealing content below, corresponding to Scroll down; the Chinese "向右滑动滑块" and English "slide the slider to the right" usually mean moving the slider right, corresponding to Swipe right if using Swipe.
4. If the intent remains ambiguous, use the Scroll and Swipe direction definitions above.

After interpreting the intent, choose an appropriate Action from the current Action Space and use its supported parameters to achieve the intended result. Some actions support start and end points instead of `direction`. When using `direction`, ensure its value achieves the intended result according to the selected Action's definition.

{locate_grounding_rules() if include_locate_in_planning else ''}

### {action_space_protocol['title']}

{action_space_description}

{log_section}

### If there is some action to do ...

{action_output_protocol['action_output_rules']}

For example:
{build_action_output_example(
        create_sample_tap_action('Add to cart button for Sauce Labs Backpack'),
        action_output_protocol['build_action_output'],
        locate_prompt_spec if include_locate_in_planning else None,
        1,
    ) or ''}

### If you think there is an error ...

- Use the <error> tag to output the error message.

For example:
<error>Unable to find the required element on the page</error>

### If there is no action to do ...

- Don't output {action_output_tags_text} if there is no action to do.

## Return Format

Return in XML format following this decision flow:

{response_prefix}

{always_include_section}
{return_format_sub_goals_section}

**Then choose ONE of the following paths:**

**Path A: If the {render_sub_goals_content('goal is accomplished', 'instruction is fulfilled')} or failed (Step {completion_check_step_number})**
<complete success="true|false">...</complete>

**Path B: If the {render_sub_goals_content('goal is NOT complete', 'instruction is NOT fulfilled')} yet (Step {action_step_number})**
<!-- Determine next action -->
{render_log_content('<log>...</log>')}
{action_output_protocol['action_output_placeholder']}

<!-- OR if there's an error -->
<error>...</error>

{build_planning_multi_turn_example(
        action_output_protocol=action_output_protocol,
        include_sub_goals=should_include_sub_goals,
        include_thought=include_thought,
        include_log=include_log,
        locate_prompt_spec=locate_prompt_spec if include_locate_in_planning else None,
        prefix=response_prefix or None,
    )}"""
