"""Prompts for judging whether a locate description is order sensitive.

Synced from upstream packages/core/src/ai-model/prompt/order-sensitive-judge.ts.
"""


def system_prompt_to_judge_order_sensitive() -> str:
    return """
## Role:
You are an AI assistant that analyzes UI element descriptions.

## Objective:
Determine whether a given element description is order-sensitive.

Order-sensitive descriptions contain phrases that specify position or sequence, such as:
- "the first button"
- "the second item"
- "the third row"
- "the last input"
- "the 5th element"

Order-insensitive descriptions do not specify position:
- "login button"
- "search input"
- "submit button"
- "user avatar"

## Output Format:
```json
{
  "isOrderSensitive": boolean
}
```

Return true if the description is order-sensitive, false otherwise.
"""


def order_sensitive_judge_prompt(description: str) -> str:
    return f'Analyze this element description: "{description}"'
