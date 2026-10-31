"""Custom planning framework + UI-TARS / Auto-GLM planners.

Synced from upstream packages/core/src/ai-model:
  workflows/planning/custom-planning.ts
  models/ui-tars/{parser,actions,prompt,planning}.ts
  models/auto-glm/{parser,actions,prompt,planning,locate}.ts
  model-adapter/custom-planning-action.ts

AutoGLM prompts derive from Open-AutoGLM (zai-org, Apache-2.0).
"""

import json
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from ..adapters import ModelRuntime
from ..caller import AIResponseParseError, call_ai_with_string_response
from ..locate_result import create_locate_result_codec, resolve_locate_result_coordinates
from .context_utils import (
    ensure_data_url,
    get_screenshot_base64,
    get_shot_size,
    prepare_model_image,
    user_prompt_to_string,
)

# ---------------------------------------------------------------------------
# Custom planning framework (custom-planning.ts)
# ---------------------------------------------------------------------------

async def run_custom_planning(
    user_instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: List[Any],
    conversation_history: Any,
    config: Dict[str, Any],
    include_locate_in_planning: bool = False,
    action_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one custom-planner turn (system prompt + screenshot + history)."""
    messages_config = config["messages"]
    system_prompt = messages_config["build_system_prompt"]()
    if action_context:
        system_prompt = f"{system_prompt}{action_context}\n"
    user_instruction_text = messages_config.get("build_user_instruction", lambda t: t)(
        user_instruction
    )

    adapter = model_runtime.adapter
    screenshot_base64 = ensure_data_url(get_screenshot_base64(context))
    shot_size = get_shot_size(context)
    prepared_image = prepare_model_image(
        image_base64=screenshot_base64,
        width=shot_size["width"],
        height=shot_size["height"],
        policy=(
            {"padBlockSize": adapter.image_pad_block_size}
            if adapter.image_pad_block_size
            else None
        ),
    )

    history_image_limit = messages_config.get("history_image_limit")
    if conversation_history.pending_feedback_message:
        conversation_history.append_message(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{conversation_history.pending_feedback_message}. The "
                            "previous action has been executed, here is the latest "
                            "screenshot. Please continue according to the instruction."
                        ),
                    }
                ],
            }
        )
        conversation_history.reset_pending_feedback_message_if_exists()

    conversation_history.append_message(
        {"role": "user", "content": [{"type": "image", "url": prepared_image["image_base64"]}]}
    )

    if messages_config["system_prompt_placement"] == "system-message":
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [{"type": "text", "text": user_instruction_text}]},
        ]
        messages.extend(
            conversation_history.snapshot(history_image_limit)
        )
    else:
        messages = [
            {"role": "user", "content": f"{system_prompt}{user_instruction_text}"},
            *conversation_history.snapshot(history_image_limit),
        ]

    response = await call_ai_with_string_response(
        messages, model_runtime, {"requiresOriginalImageDetail": include_locate_in_planning}
    )
    content = response["content"]
    usage = response.get("usage")

    try:
        parsed = config["parse_response"](content, context, model_runtime)
        actions = config["transform_actions"](
            parsed, context, action_space, model_runtime
        )
        _normalize_custom_locate_fields(
            actions,
            config["coordinates"],
            {
                "preparedSize": prepared_image["prepared_size"],
                "contentSize": prepared_image["content_size"],
            },
        )
        should_continue = config["should_continue_planning"](parsed, actions)
    except AIResponseParseError:
        raise
    except Exception as parse_error:
        raise AIResponseParseError(
            f"Parse error: {parse_error}",
            json.dumps(content, ensure_ascii=False, indent=2) if not isinstance(content, str) else content,
            usage,
        ) from parse_error

    assistant_content = messages_config.get("build_assistant_content", lambda p, c: None)(
        parsed, content
    )
    if assistant_content:
        conversation_history.append_message(
            {"role": "assistant", "content": assistant_content}
        )

    return {
        "actions": actions,
        "log": config["build_response_log"](parsed, content),
        "usage": usage,
        "should_continue_planning": should_continue,
        "raw_response": content,
    }


def _normalize_custom_locate_fields(
    actions: List[Dict[str, Any]],
    coordinates: Dict[str, Any],
    locate_result_context: Dict[str, Any],
) -> None:
    """Convert raw `point`/`bbox` coordinates on locate params into
    `locatedPixelResult` (upstream normalizePlanningActionLocateFields)."""
    if not coordinates:
        return
    resolved = resolve_locate_result_coordinates(coordinates)
    codec = create_locate_result_codec({"coordinates": resolved})
    result_key = codec.prompt_spec["resultKey"]

    for action in actions:
        param = action.get("param") or {}
        for field, value in list(param.items()):
            if not isinstance(value, dict) or "prompt" not in value:
                continue
            raw = value.get(result_key)
            if raw is None:
                continue
            pixel_result = codec.to_pixel_result(raw, locate_result_context)
            rest = {k: v for k, v in value.items() if k != result_key}
            param[field] = {**rest, "locatedPixelResult": pixel_result}


def get_tap_located_pixel_result(
    actions: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """First Tap action's locatedPixelResult (custom-planning-action.ts)."""
    for action in actions:
        if action.get("type") != "Tap":
            continue
        locate = (action.get("param") or {}).get("locate") or {}
        return locate.get("locatedPixelResult")
    return None


# ---------------------------------------------------------------------------
# Auto-GLM (models/auto-glm/*)
# ---------------------------------------------------------------------------

BACK_BUTTON_NAMES = ["AndroidBackButton", "HarmonyBackButton"]
HOME_BUTTON_NAMES = ["AndroidHomeButton", "HarmonyHomeButton"]


def _multilingual_formatted_date() -> str:
    today = datetime.now()
    weekdays = [
        "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    ]
    # Python weekday(): Monday=0; upstream getDay(): Sunday=0
    return f"{today.year}-{today.month:02d}-{today.day:02d}, {weekdays[(today.weekday() + 1) % 7]}"


def _chinese_formatted_date() -> str:
    today = datetime.now()
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    # Python Monday=0; upstream getDay() Sunday=0
    return f"{today.year}年{today.month:02d}月{today.day:02d}日 {weekday_names[today.weekday()]}"


def _extract_value_after(src: str, key: str) -> str:
    """Substring-based value extraction; regex breaks on escaped quotes."""
    idx = src.find(key)
    if idx == -1:
        raise ValueError(f"Missing key {key} in action payload {src}")
    rest = src[idx + len(key):].strip()
    if rest.endswith('")'):
        rest = rest[:-2]
    return rest


def parse_auto_glm_response(content: str) -> Dict[str, str]:
    """Split a raw response into {think, content}."""
    if "finish(message=" in content:
        parts = content.split("finish(message=")
        return {"think": parts[0].strip(), "content": f"finish(message={parts[1]}"}
    if "do(action=" in content:
        parts = content.split("do(action=")
        return {"think": parts[0].strip(), "content": f"do(action={parts[1]}"}
    if "<answer>" in content:
        parts = content.split("<answer>")
        think = parts[0].replace("<think>", "").replace("</think>", "").strip()
        return {"think": think, "content": parts[1].replace("</answer>", "").strip()}
    return {"think": "", "content": content}


def parse_auto_glm_planning_action(response: Dict[str, str]) -> Dict[str, Any]:
    """Parse the AutoGLM action payload into a discriminated dict."""
    think = response.get("think", "")
    trimmed = response["content"].strip()
    try:
        if trimmed.startswith('do(action="Type"') or trimmed.startswith('do(action="Type_Name"'):
            text = _extract_value_after(trimmed, 'text="')
            return {"_metadata": "do", "action": "Type", "text": text, "think": think}

        if trimmed.startswith("finish(message="):
            message = _extract_value_after(trimmed, 'finish(message="')
            if not trimmed.endswith('")') and message.endswith(")"):
                message = message[:-1]
            return {"_metadata": "finish", "message": message, "think": think}

        if trimmed.startswith("do("):
            action_match = re.search(r'do\(action="([^"]+)"', trimmed)
            if not action_match:
                raise ValueError(
                    f"Failed to extract action type from do() call; raw=\"{trimmed}\""
                )
            action_type = action_match.group(1)
            base: Dict[str, Any] = {"_metadata": "do", "think": think}

            def _coords(pattern: str, label: str) -> Tuple[int, int]:
                match = re.search(pattern, trimmed)
                if not match:
                    raise ValueError(
                        f"Failed to extract {label} coordinates for {action_type}; "
                        f"raw=\"{trimmed}\""
                    )
                return (int(match.group(1)), int(match.group(2)))

            if action_type == "Tap":
                base["action"] = "Tap"
                base["element"] = _coords(r"element=\[(\d+),(\d+)\]", "element")
                return base
            if action_type == "Double Tap":
                base["action"] = "Double Tap"
                base["element"] = _coords(r"element=\[(\d+),(\d+)\]", "element")
                return base
            if action_type == "Swipe":
                base["action"] = "Swipe"
                base["start"] = _coords(r"start=\[(\d+),(\d+)\]", "start")
                base["end"] = _coords(r"end=\[(\d+),(\d+)\]", "end")
                return base
            if action_type == "Long Press":
                base["action"] = "Long Press"
                base["element"] = _coords(r"element=\[(\d+),(\d+)\]", "element")
                return base
            if action_type == "Launch":
                base["action"] = "Launch"
                base["app"] = _extract_value_after(trimmed, 'app="')
                return base
            if action_type == "Back":
                base["action"] = "Back"
                return base
            if action_type == "Home":
                base["action"] = "Home"
                return base
            if action_type == "Wait":
                base["action"] = "Wait"
                match = re.search(r'duration=(?:["\[])?(\d+)', trimmed)
                if not match:
                    raise ValueError(
                        f"Failed to extract duration for Wait; raw=\"{trimmed}\""
                    )
                base["durationMs"] = int(match.group(1)) * 1000
                return base
            if action_type == "Interact":
                base["action"] = "Interact"
                return base
            if action_type == "Call_API":
                base["action"] = "Call_API"
                base["instruction"] = _extract_value_after(trimmed, 'instruction="')
                return base
            if action_type == "Take_over":
                base["action"] = "Take_over"
                base["message"] = _extract_value_after(trimmed, 'message="')
                return base
            if action_type == "Note":
                base["action"] = "Note"
                base["message"] = _extract_value_after(trimmed, 'message="')
                return base
            raise ValueError(f"Unknown action type: {action_type}; raw=\"{trimmed}\"")

        raise ValueError(f"Failed to parse action: {trimmed}")
    except ValueError as e:
        raise ValueError(f"Failed to parse action: {e}; raw=\"{trimmed}\"") from e


def parse_auto_glm_planning_response(content: str) -> Dict[str, Any]:
    response = parse_auto_glm_response(content)
    return {
        "response": response,
        "action": parse_auto_glm_planning_action(response),
    }


def _find_action_name(
    action_space: List[Any], known_names: List[str], default_name: str
) -> str:
    if not action_space:
        return default_name
    for action in action_space:
        name = action["name"] if isinstance(action, dict) else action.name
        if name in known_names:
            return name
    return default_name


def transform_auto_glm_action(
    action: Dict[str, Any],
    action_space: List[Any],
    coordinate_distance_to_pixels: Callable[[float, str], float],
) -> List[Dict[str, Any]]:
    """Map a parsed AutoGLM action to Midscene planning actions."""
    try:
        if action["_metadata"] == "finish":
            return [{"type": "Finished", "param": {}, "thought": action["message"]}]

        if action["_metadata"] != "do":
            raise ValueError(f"Unknown action metadata: {action['_metadata']}")

        think = action.get("think") or ""
        action_type = action["action"]

        if action_type == "Tap":
            return [
                {
                    "type": "Tap",
                    "param": {"locate": {"point": action["element"], "prompt": ""}},
                }
            ]
        if action_type == "Double Tap":
            return [
                {
                    "type": "DoubleClick",
                    "param": {"locate": {"point": action["element"], "prompt": ""}},
                }
            ]
        if action_type == "Type":
            return [{"type": "Input", "param": {"value": action["text"]}}]
        if action_type == "Swipe":
            start = action["start"]
            end = action["end"]
            delta_x = end[0] - start[0]
            delta_y = end[1] - start[1]
            abs_delta_x = abs(delta_x)
            abs_delta_y = abs(delta_y)
            if abs_delta_y > abs_delta_x:
                # Vertical scroll; direction inverted relative to finger movement.
                distance = coordinate_distance_to_pixels(delta_y, "y")
                direction = "up" if delta_y > 0 else "down"
            else:
                distance = coordinate_distance_to_pixels(delta_x, "x")
                direction = "left" if delta_x > 0 else "right"
            return [
                {
                    "type": "Scroll",
                    "param": {
                        "locate": {"point": start, "prompt": ""},
                        "distance": distance,
                        "direction": direction,
                    },
                    "thought": think,
                }
            ]
        if action_type == "Long Press":
            return [
                {
                    "type": "LongPress",
                    "param": {"locate": {"point": action["element"], "prompt": ""}},
                    "thought": think,
                }
            ]
        if action_type == "Back":
            return [
                {
                    "type": _find_action_name(
                        action_space, BACK_BUTTON_NAMES, "AndroidBackButton"
                    ),
                    "param": {},
                    "thought": think,
                }
            ]
        if action_type == "Home":
            return [
                {
                    "type": _find_action_name(
                        action_space, HOME_BUTTON_NAMES, "AndroidHomeButton"
                    ),
                    "param": {},
                    "thought": think,
                }
            ]
        if action_type == "Wait":
            return [
                {"type": "Sleep", "param": {"timeMs": action["durationMs"]}, "thought": think}
            ]
        if action_type == "Launch":
            return [{"type": "Launch", "param": {"uri": action["app"]}, "thought": think}]
        if action_type == "Interact":
            raise ValueError(
                'Action "Interact" from auto-glm is not supported in the current implementation.'
            )
        if action_type == "Call_API":
            raise ValueError(
                'Action "Call_API" from auto-glm is not supported in the current implementation.'
            )
        if action_type == "Take_over":
            raise ValueError(
                'Action "Take_over" from auto-glm is not supported in the current implementation.'
            )
        if action_type == "Note":
            raise ValueError(
                'Action "Note" from auto-glm is not supported in the current implementation.'
            )
        raise ValueError(f"Unknown do() action type: {action_type}")
    except ValueError as e:
        raise ValueError(f"Failed to transform action: {e}") from e


# AutoGLM prompts (auto-glm/prompt.ts, byte-for-byte)
_MULTILINGUAL_PLAN_PROMPT = """
The current date: {date}

# Setup
You are a professional Android operation agent assistant that can fulfill the user's high-level instructions. Given a screenshot of the Android interface at each step, you first analyze the situation, then plan the best course of action using Python-style pseudo-code.

# More details about the code
Your response format must be structured as follows:

Think first: Use <think>...</think> to analyze the current screen, identify key elements, and determine the most efficient action.
Provide the action: Use <answer>...</answer> to return a single line of pseudo-code representing the operation.

Your output should STRICTLY follow the format:
<think>
[Your thought]
</think>
<answer>
[Your operation code]
</answer>

- **Tap**
  Perform a tap action on a specified screen area. The element is a list of 2 integers, representing the coordinates of the tap point.
  **Example**:
  <answer>
  do(action="Tap", element=[x,y])
  </answer>
- **Type**
  Enter text into the currently focused input field.
  **Example**:
  <answer>
  do(action="Type", text="Hello World")
  </answer>
- **Swipe**
  Perform a swipe action with start point and end point.
  **Examples**:
  <answer>
  do(action="Swipe", start=[x1,y1], end=[x2,y2])
  </answer>
- **Long Press**
  Perform a long press action on a specified screen area.
  You can add the element to the action to specify the long press area. The element is a list of 2 integers, representing the coordinates of the long press point.
  **Example**:
  <answer>
  do(action="Long Press", element=[x,y])
  </answer>
- **Launch**
  Launch an app. Try to use launch action when you need to launch an app. Check the instruction to choose the right app before you use this action.
  **Example**:
  <answer>
  do(action="Launch", app="Settings")
  </answer>
- **Back**
  Press the Back button to navigate to the previous screen.
  **Example**:
  <answer>
  do(action="Back")
  </answer>
- **Finish**
  Terminate the program and optionally print a message.
  **Example**:
  <answer>
  finish(message="Task completed.")
  </answer>


REMEMBER:
- Think before you act: Always analyze the current UI and the best course of action before executing any step, and output in <think> part.
- Only ONE LINE of action in <answer> part per response: Each step must contain exactly one line of executable code.
- Generate execution code strictly according to format requirements.
"""

_CHINESE_PLAN_PROMPT = """
今天的日期是: {date}

你是一个智能体分析专家，可以根据操作历史和当前状态图执行一系列操作来完成任务。
你必须严格按照要求输出以下格式：
<think>{{think}}</think>
<answer>{{action}}</answer>

其中：
- {{think}} 是对你为什么选择这个操作的简短推理说明。
- {{action}} 是本次执行的具体操作指令，必须严格遵循下方定义的指令格式。

操作指令及其作用如下：
- do(action="Launch", app="xxx")  
    Launch是启动目标app的操作，这比通过主屏幕导航更快。此操作完成后，您将自动收到结果状态的截图。
- do(action="Tap", element=[x,y])  
    Tap是点击操作，点击屏幕上的特定点。可用此操作点击按钮、选择项目、从主屏幕打开应用程序，或与任何可点击的用户界面元素进行交互。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。此操作完成后，您将自动收到结果状态的截图。
- do(action="Tap", element=[x,y], message="重要操作")  
    基本功能同Tap，点击涉及财产、支付、隐私等敏感按钮时触发。
- do(action="Type", text="xxx")  
    Type是输入操作，在当前聚焦的输入框中输入文本。使用此操作前，请确保输入框已被聚焦（先点击它）。输入的文本将像使用键盘输入一样输入。重要提示：手机可能正在使用 ADB 键盘，该键盘不会像普通键盘那样占用屏幕空间。要确认键盘已激活，请查看屏幕底部是否显示 'ADB Keyboard {{ON}}' 类似的文本，或者检查输入框是否处于激活/高亮状态。不要仅仅依赖视觉上的键盘显示。自动清除文本：当你使用输入操作时，输入框中现有的任何文本（包括占位符文本和实际输入）都会在输入新文本前自动清除。你无需在输入前手动清除文本——直接使用输入操作输入所需文本即可。操作完成后，你将自动收到结果状态的截图。
- do(action="Type_Name", text="xxx")  
    Type_Name是输入人名的操作，基本功能同Type。
- do(action="Swipe", start=[x1,y1], end=[x2,y2])  
    Swipe是滑动操作，通过从起始坐标拖动到结束坐标来执行滑动手势。可用于滚动内容、在屏幕之间导航、下拉通知栏以及项目栏或进行基于手势的导航。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。滑动持续时间会自动调整以实现自然的移动。此操作完成后，您将自动收到结果状态的截图。
- do(action="Long Press", element=[x,y])  
    Long Pres是长按操作，在屏幕上的特定点长按指定时间。可用于触发上下文菜单、选择文本或激活长按交互。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。此操作完成后，您将自动收到结果状态的屏幕截图。
- do(action="Double Tap", element=[x,y])  
    Double Tap在屏幕上的特定点快速连续点按两次。使用此操作可以激活双击交互，如缩放、选择文本或打开项目。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。此操作完成后，您将自动收到结果状态的截图。
- do(action="Back")  
    导航返回到上一个屏幕或关闭当前对话框。相当于按下 Android 的返回按钮。使用此操作可以从更深的屏幕返回、关闭弹出窗口或退出当前上下文。此操作完成后，您将自动收到结果状态的截图。
- do(action="Home") 
    Home是回到系统桌面的操作，相当于按下 Android 主屏幕按钮。使用此操作可退出当前应用并返回启动器，或从已知状态启动新任务。此操作完成后，您将自动收到结果状态的截图。
- do(action="Wait", duration="x seconds")  
    等待页面加载，x为需要等待多少秒。
- finish(message="xxx")  
    finish是结束任务的操作，表示准确完整完成任务，message是终止信息。 

必须遵循的规则：
0. 严禁调用 Interact、Take_over、Note、Call_API 这四个操作，这些操作暂不支持。
1. 在执行任何操作前，先检查当前app是否是目标app，如果不是，先执行 Launch。
2. 如果进入到了无关页面，先执行 Back。如果执行Back后页面没有变化，请点击页面左上角的返回键进行返回，或者右上角的X号关闭。
3. 如果页面未加载出内容，最多连续 Wait 三次，否则执行 Back重新进入。
4. 如果页面显示网络问题，需要重新加载，请点击重新加载。
5. 如果当前页面找不到目标联系人、商品、店铺等信息，可以尝试 Swipe 滑动查找。
6. 遇到价格区间、时间区间等筛选条件，如果没有完全符合的，可以放宽要求。
7. 在做小红书总结类任务时一定要筛选图文笔记。
8. 购物车全选后再点击全选可以把状态设为全不选，在做购物车任务时，如果购物车里已经有商品被选中时，你需要点击全选后再点击取消全选，再去找需要购买或者删除的商品。
9. 在做外卖任务时，如果相应店铺购物车里已经有其他商品你需要先把购物车清空再去购买用户指定的外卖。
10. 在做点外卖任务时，如果用户需要点多个外卖，请尽量在同一店铺进行购买，如果无法找到可以下单，并说明某个商品未找到。
11. 请严格遵循用户意图执行任务，用户的特殊要求可以执行多次搜索，滑动查找。比如（i）用户要求点一杯咖啡，要咸的，你可以直接搜索咸咖啡，或者搜索咖啡后滑动查找咸的咖啡，比如海盐咖啡。（ii）用户要找到XX群，发一条消息，你可以先搜索XX群，找不到结果后，将"群"字去掉，搜索XX重试。（iii）用户要找到宠物友好的餐厅，你可以搜索餐厅，找到筛选，找到设施，选择可带宠物，或者直接搜索可带宠物，必要时可以使用AI搜索。
12. 在选择日期时，如果原滑动方向与预期日期越来越远，请向反方向滑动查找。
13. 执行任务过程中如果有多个可选择的项目栏，请逐个查找每个项目栏，直到完成任务，一定不要在同一项目栏多次查找，从而陷入死循环。
14. 在执行下一步操作前请一定要检查上一步的操作是否生效，如果点击没生效，可能因为app反应较慢，请先稍微等待一下，如果还是不生效请调整一下点击位置重试，如果仍然不生效请跳过这一步继续任务，并在finish message说明点击不生效。
15. 在执行任务中如果遇到滑动不生效的情况，请调整一下起始点位置，增大滑动距离重试，如果还是不生效，有可能是已经滑到底了，请继续向反方向滑动，直到顶部或底部，如果仍然没有符合要求的结果，请跳过这一步继续任务，并在finish message说明但没找到要求的项目。
16. 在做游戏任务时如果在战斗页面如果有自动战斗一定要开启自动战斗，如果多轮历史状态相似要检查自动战斗是否开启。
17. 如果没有合适的搜索结果，可能是因为搜索页面不对，请返回到搜索页面的上一级尝试重新搜索，如果尝试三次返回上一级搜索后仍然没有符合要求的结果，执行 finish(message="原因")。
18. 在结束任务前请一定要仔细检查任务是否完整准确的完成，如果出现错选、漏选、多选的情况，请返回之前的步骤进行纠正。
"""

_MULTILINGUAL_LOCATE_PROMPT = """
The current date: {date}

# Setup
You are a professional Android operation agent assistant that can fulfill the user's high-level instructions. Given a screenshot of the Android interface at each step, you first analyze the situation, then plan the best course of action using Python-style pseudo-code.

# More details about the code
Your response format must be structured as follows:

Think first: Use <think>...</think> to analyze the current screen, identify key elements, and determine the most efficient action.
Provide the action: Use <answer>...</answer> to return a single line of pseudo-code representing the operation.

Your output should STRICTLY follow the format:
<think>
[Your thought]
</think>
<answer>
[Your operation code]
</answer>

- **Tap**
  Perform a tap action on a specified screen area. The element is a list of 2 integers, representing the coordinates of the tap point.
  **Example**:
  <answer>
  do(action="Tap", element=[x,y])
  </answer>

REMEMBER:
- Your goal is to locate and tap the UI element specified by the user (e.g., button, icon, link, etc.). Do not attempt any other actions.
"""

_CHINESE_LOCATE_PROMPT = """
今天的日期是: {date}

你是一个智能体分析专家，可以根据操作历史和当前状态图执行一系列操作来完成任务。
你必须严格按照要求输出以下格式：
<think>{{think}}</think>
<answer>{{action}}</answer>

其中：
- {{think}} 是对你为什么选择这个操作的简短推理说明。
- {{action}} 是本次执行的具体操作指令，必须严格遵循下方定义的指令格式。

操作指令及其作用如下：
- do(action="Tap", element=[x,y])  
    Tap是点击操作，点击屏幕上的特定点。可用此操作点击按钮、选择项目、从主屏幕打开应用程序，或与任何可点击的用户界面元素进行交互。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。此操作完成后，您将自动收到结果状态的截图。

必须遵循的规则：
- 你的目标是定位并点击用户指定的UI元素（例如按钮、图标、链接等），请不要尝试任何其他的操作。
"""


def get_auto_glm_multilingual_plan_prompt() -> str:
    return _MULTILINGUAL_PLAN_PROMPT.format(date=_multilingual_formatted_date())


def get_auto_glm_chinese_plan_prompt() -> str:
    return _CHINESE_PLAN_PROMPT.format(date=_chinese_formatted_date())


def get_auto_glm_multilingual_locate_prompt() -> str:
    return _MULTILINGUAL_LOCATE_PROMPT.format(date=_multilingual_formatted_date())


def get_auto_glm_chinese_locate_prompt() -> str:
    return _CHINESE_LOCATE_PROMPT.format(date=_chinese_formatted_date())


AUTO_GLM_COORDINATES = {"shape": "point", "order": "xy", "normalizedBy": 1000}


def create_auto_glm_planner(is_multilingual: bool) -> Dict[str, Any]:
    return {
        "messages": {
            "system_prompt_placement": "system-message",
            "build_system_prompt": (
                get_auto_glm_multilingual_plan_prompt
                if is_multilingual
                else get_auto_glm_chinese_plan_prompt
            ),
            "history_image_limit": 1,
            "build_assistant_content": lambda parsed, raw: (
                f"<think>{parsed['response']['think']}</think>"
                f"<answer>{parsed['response']['content']}</answer>"
            ),
        },
        "coordinates": AUTO_GLM_COORDINATES,
        "parse_response": lambda raw, context, runtime: parse_auto_glm_planning_response(raw),
        "transform_actions": lambda parsed, context, action_space, runtime: (
            transform_auto_glm_action(
                parsed["action"],
                action_space,
                _coordinate_distance_to_pixels_for(
                    context, runtime, AUTO_GLM_COORDINATES
                ),
            )
        ),
        "should_continue_planning": lambda parsed, actions: (
            parsed["action"]["_metadata"] != "finish"
        ),
        "build_response_log": lambda parsed, raw: raw,
    }


def create_auto_glm_planning_tap_locator(is_multilingual: bool) -> Dict[str, Any]:
    return {
        "build_system_prompt": (
            get_auto_glm_multilingual_locate_prompt
            if is_multilingual
            else get_auto_glm_chinese_locate_prompt
        ),
        "get_located_pixel_result": get_tap_located_pixel_result,
    }


async def auto_glm_locate(
    target_element_description: Any,
    context: Any,
    model_runtime: ModelRuntime,
) -> Dict[str, Any]:
    """Auto-GLM planning-tap-locator (models/auto-glm/locate.ts)."""
    is_multilingual = model_runtime.adapter.family == "auto-glm-multilingual"
    locator = create_auto_glm_planning_tap_locator(is_multilingual)

    from .context_utils import get_shot_size, prepare_model_image, ensure_data_url

    shot_size = get_shot_size(context)
    prepared = prepare_model_image(
        ensure_data_url(get_screenshot_base64(context)),
        shot_size["width"],
        shot_size["height"],
        None,
    )
    messages = [
        {
            "role": "user",
            "content": f"{locator['build_system_prompt']()}Tap: {user_prompt_to_string(target_element_description)}",
        },
        {
            "role": "user",
            "content": [{"type": "image", "url": prepared["image_base64"]}],
        },
    ]
    try:
        response = await call_ai_with_string_response(messages, model_runtime)
        parsed = parse_auto_glm_planning_response(response["content"])
        actions = transform_auto_glm_action(
            parsed["action"],
            [],
            _coordinate_distance_to_pixels_for(context, model_runtime, AUTO_GLM_COORDINATES),
        )
        _normalize_custom_locate_fields(
            actions,
            AUTO_GLM_COORDINATES,
            {
                "preparedSize": prepared["prepared_size"],
                "contentSize": prepared["content_size"],
            },
        )
        located = locator["get_located_pixel_result"](actions)
        if not located:
            raise ValueError("No locatedPixelResult found in planner response")
        return {
            "locatedPixelResult": located,
            "raw_response": response["content"],
            "usage": response.get("usage"),
            "reasoningContent": parsed["response"]["think"],
        }
    except AIResponseParseError as error:
        return {
            "raw_response": error.raw_response,
            "usage": error.usage,
            "errors": [error.message or "Failed to parse planning tap locator response"],
        }
    except Exception as error:
        return {
            "raw_response": str(error),
            "errors": [str(error) or "Failed to parse planning tap locator response"],
        }


def _coordinate_distance_to_pixels_for(
    context: Any, model_runtime: ModelRuntime, coordinates: Dict[str, Any]
) -> Callable[[float, str], float]:
    from .locate_result import create_coordinate_distance_to_pixels, resolve_locate_result_coordinates

    size = get_shot_size(context)
    return create_coordinate_distance_to_pixels(
        size, resolve_locate_result_coordinates(coordinates)
    )


# ---------------------------------------------------------------------------
# UI-TARS (models/ui-tars/*)
# ---------------------------------------------------------------------------

_UI_TARS_KEY_MAP = {
    "return": "Enter",
    "enter": "Enter",
    "command": "Meta",
    "cmd": "Meta",
    "ctrl": "Control",  # non-mac
    "shift": "Shift",
    "alt": "Alt",
    "space": " ",
    "page down": "PageDown",
    "pagedown": "PageDown",
    "page up": "PageUp",
    "pageup": "PageUp",
}


def _transform_hotkey_input(key_input: str) -> List[str]:
    lower = key_input.lower()
    if lower in _UI_TARS_KEY_MAP:
        return [_UI_TARS_KEY_MAP[lower]]
    return [
        _UI_TARS_KEY_MAP.get(token.lower(), token) for token in key_input.split(" ")
    ]


def _convert_bbox_to_coordinates(text: str) -> str:
    pattern = re.compile(r"<bbox>(\d+)\s+(\d+)\s+(\d+)\s+(\d+)</bbox>")

    def replace_match(match: re.Match) -> str:
        x1, y1, x2, y2 = (int(g) for g in match.groups())
        x = (x1 + x2) // 2
        y = (y1 + y2) // 2
        return f"({x},{y})"

    cleaned = text.replace("[EOS]", "")
    cleaned = re.sub(r"```(?:[a-zA-Z0-9_-]+)?", "", cleaned)
    return pattern.sub(replace_match, cleaned).strip()


_THOUGHT_PATTERN = re.compile(r"Thought:\s*([\s\S]*?)(?=Action:|$)", re.IGNORECASE)
_ACTION_LINE_PATTERN = re.compile(r"Action[^\n:]*:\s*([\s\S]+)", re.IGNORECASE)


def parse_ui_tars_action_calls(raw_response: str) -> List[Dict[str, Any]]:
    """Minimal port of @ui-tars/action-parser: parse 'Action: name(k=v, ...)'
    calls with factor 1000 (coordinates become [0,1] floats)."""
    converted = _convert_bbox_to_coordinates(raw_response)
    thought_match = _THOUGHT_PATTERN.search(converted)
    thought = thought_match.group(1).strip() if thought_match else None

    action_match = _ACTION_LINE_PATTERN.search(converted)
    if not action_match:
        return []
    action_text = action_match.group(1).strip()

    parsed: List[Dict[str, Any]] = []
    for action_type, inputs_text in _iter_action_calls(action_text):
        action_inputs: Dict[str, Any] = {}
        for key, value in _parse_action_kwargs(inputs_text):
            if key in ("start_box", "end_box"):
                action_inputs[key] = _normalize_box(value)
            else:
                action_inputs[key] = value
        parsed.append(
            {
                "action_type": action_type,
                "action_inputs": action_inputs,
                "reflection": None,
                "thought": thought,
            }
        )
    return parsed


def _iter_action_calls(action_text: str) -> List[Tuple[str, str]]:
    """Find `name(...)` calls with a balanced-paren scan so quoted values
    containing parentheses or nested tuples are handled."""
    calls: List[Tuple[str, str]] = []
    index = 0
    while index < len(action_text):
        open_paren = action_text.find("(", index)
        if open_paren == -1:
            break
        name_match = re.search(r"(\w+)\($", action_text[: open_paren + 1])
        if not name_match:
            index = open_paren + 1
            continue
        depth = 1
        cursor = open_paren + 1
        in_string: Optional[str] = None
        while cursor < len(action_text) and depth > 0:
            char = action_text[cursor]
            if in_string:
                if char == in_string:
                    in_string = None
            elif char in ("'", '"'):
                in_string = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            cursor += 1
        if depth != 0:
            break
        calls.append((name_match.group(1), action_text[open_paren + 1 : cursor - 1]))
        index = cursor
    return calls


def _parse_action_kwargs(inputs_text: str) -> List[Tuple[str, Any]]:
    kwargs: List[Tuple[str, Any]] = []
    for part in re.findall(r"(\w+)\s*=\s*('[^']*'|\"[^\"]*\"|\[[^\]]*\]|[^,]+)", inputs_text):
        key, raw_value = part[0], part[1].strip()
        if (raw_value.startswith("'") and raw_value.endswith("'")) or (
            raw_value.startswith('"') and raw_value.endswith('"')
        ):
            kwargs.append((key, raw_value[1:-1]))
        elif raw_value.startswith("[") and raw_value.endswith("]"):
            kwargs.append((key, raw_value))
        else:
            kwargs.append((key, raw_value))
    return kwargs


def _normalize_box(box_text: str) -> str:
    """Replicate action-parser's factor-1000 handling: parse up to 4 numbers,
    divide by 1000, duplicate to 4, and store as a JSON string."""
    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", str(box_text))]
    if not numbers:
        raise ValueError(f"invalid box data for ui-tars planning: {box_text}")
    float_numbers = [n / 1000 for n in numbers]
    if len(float_numbers) == 2:
        float_numbers = [float_numbers[0], float_numbers[1], float_numbers[0], float_numbers[1]]
    return json.dumps(float_numbers)


def parse_ui_tars_planning_response(
    raw_response: str, shot_size: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "rawResponse": raw_response,
        "actions": parse_ui_tars_action_calls(raw_response),
    }


def _get_ui_tars_point(start_box: str) -> Tuple[float, float]:
    values = json.loads(start_box)
    x, y = values[0], values[1]
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise ValueError(f"invalid point data for ui-tars planning: {start_box}")
    return (x, y)


def transform_ui_tars_actions(
    parsed_response: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map parsed UI-TARS actions to Midscene planning actions.
    Returns (transformed_actions, unhandled_actions)."""
    transformed: List[Dict[str, Any]] = []
    unhandled: List[Dict[str, Any]] = []

    for action in parsed_response["actions"]:
        action_type = (action.get("action_type") or "").lower()
        action_inputs = action.get("action_inputs") or {}
        thought = action.get("thought") or ""
        prompt = thought

        if action_type == "click":
            if not action_inputs.get("start_box"):
                raise ValueError("start_box is required")
            point = _get_ui_tars_point(action_inputs["start_box"])
            transformed.append(
                {
                    "type": "Tap",
                    "param": {"locate": {"point": point, "prompt": prompt}},
                }
            )
        elif action_type == "left_double":
            if not action_inputs.get("start_box"):
                raise ValueError("start_box is required")
            point = _get_ui_tars_point(action_inputs["start_box"])
            transformed.append(
                {
                    "type": "DoubleClick",
                    "param": {"locate": {"point": point, "prompt": prompt}},
                    "thought": thought,
                }
            )
        elif action_type == "right_single":
            if not action_inputs.get("start_box"):
                raise ValueError("start_box is required")
            point = _get_ui_tars_point(action_inputs["start_box"])
            transformed.append(
                {
                    "type": "RightClick",
                    "param": {"locate": {"point": point, "prompt": prompt}},
                    "thought": thought,
                }
            )
        elif action_type == "drag":
            if not action_inputs.get("start_box") or not action_inputs.get("end_box"):
                raise ValueError("start_box and end_box are required")
            start_point = _get_ui_tars_point(action_inputs["start_box"])
            end_point = _get_ui_tars_point(action_inputs["end_box"])
            transformed.append(
                {
                    "type": "DragAndDrop",
                    "param": {
                        "from": {"point": start_point, "prompt": prompt},
                        "to": {"point": end_point, "prompt": prompt},
                    },
                    "thought": thought,
                }
            )
        elif action_type == "type":
            transformed.append(
                {"type": "Input", "param": {"value": action_inputs.get("content")}, "thought": thought}
            )
        elif action_type == "scroll":
            transformed.append(
                {
                    "type": "Scroll",
                    "param": {"direction": action_inputs.get("direction")},
                    "thought": thought,
                }
            )
        elif action_type == "finished":
            transformed.append(
                {
                    "type": "Finished",
                    "param": {},
                    "thought": action_inputs.get("content") or thought,
                }
            )
        elif action_type == "hotkey":
            if not action_inputs.get("key"):
                logger.warning("No key found in action: hotkey. Will not perform action.")
                continue
            keys = _transform_hotkey_input(action_inputs["key"])
            transformed.append(
                {
                    "type": "KeyboardPress",
                    "param": {"keyName": "+".join(keys)},
                    "thought": thought,
                }
            )
        elif action_type == "wait":
            transformed.append(
                {"type": "Sleep", "param": {"timeMs": 1000}, "thought": thought}
            )
        elif action_type:
            unhandled.append({"type": action_type, "thought": thought})

    return transformed, unhandled


def _build_no_ui_tars_actions_error(
    raw_response: str,
    actions: List[Dict[str, Any]],
    unhandled_actions: List[Dict[str, Any]],
) -> str:
    message = "No actions found in UI-TARS response."
    if len(actions) == 0:
        message += "Action parser returned no actions"
        if "Thought:" in raw_response and "Action:" not in raw_response:
            message += 'Response contains "Thought:" but missing "Action:" line'
        else:
            message += "Response may be malformed or empty"
    if unhandled_actions:
        types = ", ".join(a["type"] for a in unhandled_actions)
        message += f"Unhandled action types: {types}"
    return message


def get_ui_tars_planning_prompt() -> str:
    from ..env_config import get_preferred_language

    preferred_language = get_preferred_language()
    return f"""
You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task. 

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(start_box='[x1, y1, x2, y2]')
left_double(start_box='[x1, y1, x2, y2]')
right_single(start_box='[x1, y1, x2, y2]')
drag(start_box='[x1, y1, x2, y2]', end_box='[x3, y3, x4, y4]')
hotkey(key='')
type(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format. If you want to submit your input, use \\n at the end of content. 
scroll(start_box='[x1, y1, x2, y2]', direction='down or up or right or left')
wait() #Sleep for 5s and take a screenshot to check for any changes.
finished(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format.


## Note
- Use {preferred_language} in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
"""


def _ui_tars_summary(prediction: str) -> str:
    return re.sub(r"Reflection:[\s\S]*?(?=Action_Summary:|Action:|$)", "", prediction).strip()


UI_TARS_COORDINATES = {"shape": "point", "order": "xy", "normalizedBy": 1}


def create_ui_tars_planner() -> Dict[str, Any]:
    return {
        "messages": {
            "system_prompt_placement": "user-message",
            "build_system_prompt": get_ui_tars_planning_prompt,
            "build_user_instruction": (
                lambda instruction: f"<user_instruction>{instruction}</user_instruction>"
            ),
            "build_assistant_content": lambda parsed, raw: _ui_tars_summary(raw),
        },
        "coordinates": UI_TARS_COORDINATES,
        "parse_response": lambda raw, context, runtime: parse_ui_tars_planning_response(
            raw, get_shot_size(context)
        ),
        "transform_actions": lambda parsed, context, action_space, runtime: (
            _transform_ui_tars_with_error(parsed)
        ),
        "should_continue_planning": lambda parsed, actions: all(
            action["type"] != "Finished" for action in actions
        ),
        "build_response_log": lambda parsed, raw: _ui_tars_summary(raw),
    }


def _transform_ui_tars_with_error(
    parsed_response: Dict[str, Any],
) -> List[Dict[str, Any]]:
    transformed, unhandled = transform_ui_tars_actions(parsed_response)
    if len(transformed) == 0:
        raise ValueError(
            _build_no_ui_tars_actions_error(
                parsed_response.get("rawResponse", ""),
                parsed_response.get("actions", []),
                unhandled,
            )
        )
    return transformed


# ---------------------------------------------------------------------------
# Adapter wiring: bind custom plan/locate functions to their adapters
# ---------------------------------------------------------------------------

def register_custom_planners() -> None:
    """Attach the custom planning/locate callables to their model adapters."""
    from ..adapters import get_model_adapter

    auto_glm = get_model_adapter("auto-glm")
    auto_glm.planning_plan_fn = _make_auto_glm_plan_fn(False)
    auto_glm.locate_fn = auto_glm_locate

    auto_glm_multilingual = get_model_adapter("auto-glm-multilingual")
    auto_glm_multilingual.planning_plan_fn = _make_auto_glm_plan_fn(True)
    auto_glm_multilingual.locate_fn = auto_glm_locate

    for family in ("vlm-ui-tars", "vlm-ui-tars-doubao", "vlm-ui-tars-doubao-1.5"):
        adapter = get_model_adapter(family)
        adapter.planning_plan_fn = _make_ui_tars_plan_fn()


def _make_auto_glm_plan_fn(is_multilingual: bool) -> Callable:
    async def plan(
        instruction: str,
        context: Any,
        model_runtime: ModelRuntime,
        action_space: List[Any],
        conversation_history: Any,
        include_locate_in_planning: bool = False,
        action_context: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        result = await run_custom_planning(
            instruction,
            context,
            model_runtime,
            action_space,
            conversation_history,
            create_auto_glm_planner(is_multilingual),
            include_locate_in_planning,
            action_context,
        )
        result["yaml_flow"] = _yaml_flow_of(result["actions"])
        return result

    return plan


def _make_ui_tars_plan_fn() -> Callable:
    async def plan(
        instruction: str,
        context: Any,
        model_runtime: ModelRuntime,
        action_space: List[Any],
        conversation_history: Any,
        include_locate_in_planning: bool = False,
        action_context: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        result = await run_custom_planning(
            instruction,
            context,
            model_runtime,
            action_space,
            conversation_history,
            create_ui_tars_planner(),
            include_locate_in_planning,
            action_context,
        )
        result["yaml_flow"] = _yaml_flow_of(result["actions"])
        return result

    return plan


def _yaml_flow_of(actions: List[Dict[str, Any]]) -> str:
    import yaml

    flow = [
        {"type": action["type"], **(action.get("param") or {})} for action in actions
    ]
    return yaml.dump(
        {"tasks": [{"name": "flow", "flow": flow}]},
        allow_unicode=True,
        sort_keys=False,
        width=10**6,
    ).strip()
