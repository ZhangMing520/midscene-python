# Midscene Python

**See interfaces like a human. UI automation and E2E testing in natural language for Web, Android, and Desktop.**

Midscene Python is the Python SDK for [Midscene](https://github.com/web-infra-dev/midscene). It captures a screenshot, asks a vision-language model what to do next, and executes the action through Playwright, Selenium, the Chrome Bridge, ADB, or pyautogui. The AI model layer (prompts, planning/locate/insight protocols, multi-slot configuration and coordinate parsing) is synced with upstream Midscene v1.17.4.

[English](README.md) | [简体中文](README.zh.md)

## Write automation in natural language

Describe the goal; Midscene plans the steps, locates the elements on screen, and acts.

```python
import asyncio

from midscene import Agent, AgentOptions
from midscene.web import PlaywrightWebPage


async def main():
    async with await PlaywrightWebPage.create(headless=False) as page:
        await page.navigate_to("https://your-shop.example")
        agent = Agent(page, AgentOptions(cache_id="shop-search"))

        await agent.ai_act("Search for headphones and filter the results to prices under $100")
        await agent.ai_wait_for("The filtered search results are visible")
        await agent.ai_assert(
            "There are products in the search results, and each costs less than $100"
        )


asyncio.run(main())
```

The same steps as a YAML script, run with `midscene run script.yaml`:

```yaml
web:
  url: https://your-shop.example
  headless: true

tasks:
  - name: Find headphones under $100
    flow:
      - aiAct: Search for headphones and filter the results to prices under $100
      - aiWaitFor: The filtered search results are visible
      - aiAssert: There are products in the search results, and each costs less than $100
```

See [docs/quickstart.md](docs/quickstart.md) for installation, model setup, the full flow vocabulary and CLI options.

## See, act, and verify like a human

E2E testing verifies complete workflows from the user's perspective, so Midscene tests the way a user does: **observe the screen, act on what is visible, and verify the visible result**.

### Locate and act from screenshots

Midscene locates elements by their appearance and position, then clicks, types, scrolls, or drags to carry out your instruction. You can target icon-only buttons, custom controls, `<canvas>`, and elements inside iframes without maintaining selectors or adding semantic annotations.

### Verify what users see

Describe the expected appearance in natural language to check colors, selection highlights, layout, and visual feedback:

```python
await agent.ai_assert("The selected plan has a blue border and a checkmark")
await agent.ai_assert("The error message is visible below the email field")
```

## One API across platforms

Visual localization does not depend on the UI rendering stack, so the same `Agent` APIs work on every supported platform:

| Platform | Integration |
| --- | --- |
| Web | [Playwright](https://midscenejs.com/integrate-with-playwright) or Selenium |
| Desktop Chrome | [Bridge mode](https://midscenejs.com/bridge-mode) (Chrome extension talks to this SDK over WebSocket) |
| Android | Devices and emulators through ADB |
| iOS | Real devices and simulators through WebDriverAgent (WDA / Appium XCUITest) |
| HarmonyOS | Devices and emulators through `hdc` + `uitest` |
| Desktop | Windows / macOS / Linux screen and pointer control through pyautogui, primary display only (`pip install "midscene-python[desktop]"`) |
| Custom interfaces | Subclass `AbstractInterface` and provide screenshots plus actions |

Puppeteer from upstream Midscene is **not ported** in this SDK. The iOS and HarmonyOS layers are ported but have not been verified against real hardware yet; they are exercised by unit tests over a fake WDA / `hdc` transport.

## Models and configuration

Screenshot-based planning and locate avoid sending large DOM trees to the model. Midscene Python supports the same model families and request protocols as upstream:

`qwen2.5-vl` / `qwen3-vl`, `doubao-seed` / `doubao-vision`, `gemini`, `gpt-5`, `gpt-6`, `glm-v`, `kimi` / `kimi3`, `deepseek` (dedicated `<｜point｜>` locate protocol), `xiaomi-mimo`, `ant-ling`, `vlm-ui-tars` (Thought/Action custom planner), `auto-glm` (AutoGLM pseudo-code planner), and `jev` (System One protocol).

```bash
# Default model (fallback for every responsibility)
export MIDSCENE_MODEL_NAME="doubao-seed-1-6-250515"
export MIDSCENE_MODEL_API_KEY="sk-..."
export MIDSCENE_MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export MIDSCENE_MODEL_FAMILY="doubao-seed"   # required for locate coordinate parsing

# Optional: dedicated slots (planning / locate / insight)
# export MIDSCENE_LOCATE_MODEL_NAME="qwen3-vl-max"
# export MIDSCENE_LOCATE_MODEL_FAMILY="qwen3-vl"
# export MIDSCENE_LOCATE_MODEL_BASE_URL="..."
# export MIDSCENE_LOCATE_MODEL_API_KEY="..."
```

The legacy `MIDSCENE_USE_QWEN_VL` / `MIDSCENE_USE_DOUBAO_VISION` switches still work and map to the corresponding family. Configuration can also be passed per agent (it takes precedence over environment variables):

```python
agent = Agent(page, AgentOptions(
    cache_id="my-task",
    model_config={
        "MIDSCENE_MODEL_NAME": "qwen3-vl-max",
        "MIDSCENE_MODEL_FAMILY": "qwen3-vl",
        "MIDSCENE_MODEL_API_KEY": "sk-...",
        "MIDSCENE_MODEL_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
))
```

Both `openai-chat` and `openai-responses` protocols support streaming and non-streaming modes. SIWC (ChatGPT plan sign-in) is available through `midscene model siwc login` and `MIDSCENE_MODEL_AUTH_MODE=siwc`.

## Upstream v1.17.4 parity

Aligned with the official TypeScript SDK:

- **Planning loop**: `ai_act` (alias `ai_action`) supports the three `effort` modes (`fast` / `balance` / `deepThink` with sub-goal tracking and dual-image history); `<error>` and `<complete success="false">` fail immediately; action-execution errors are fed back to the planner (up to 5 per loop); Jev delegation switches to the default model with advisory `<planning_advice>`.
- **Convenience APIs**: `ai_tap / ai_right_click / ai_middle_click / ai_double_click / ai_hover / ai_input / ai_keyboard_press / ai_scroll / ai_long_press / ai_clear_input / ai_drag_and_drop` (one locate call plus action, no planning model), `sleep(ms)`, and `ai_query / ai_boolean / ai_number / ai_string / ai_ask / ai_assert / ai_wait_for / ai_locate`. `ai_extract` remains as a deprecated alias of `ai_query`.
- **DeepLocate two-stage locate**: with `deepLocate=True` the section is located first, cropped and upscaled 2x, the element is located on the zoomed image, then mapped back to original coordinates.
- **Model fallback**: models that cannot perform a task (for example jev for extraction) automatically fall back to the default model.
- **YAML automation**: `midscene run script.yaml` supports the upstream flow commands (`aiAct / aiAssert / aiWaitFor / aiQuery / aiTap / aiInput / aiKeyboardPress / aiScroll / aiDragAndDrop / sleep / javascript`, and more), `${VAR}` interpolation, per-task `continueOnError`, and results under `midscene_run/output/`.
- **Connectivity test**: `midscene model connect` runs the planning text, insight vision, aiLocate, and default text checks in parallel.
- **Execution reports**: every `ai_act` run that reaches planning updates the combined single-file HTML viewer under `midscene_run/report/` (tag defaults to the interface type, overridable via `MIDSCENE_REPORT_TAG_NAME`); per-execution JSON dumps in the upstream `IReportActionDump` shape are written only when `persistExecutionDump` is enabled (`AgentOptions.persist_execution_dump`), and all report files are skipped with `generateReport: false`. It records the planning output, per-action wall-clock timing/status/errors and, for cache replays, an upstream `LoadYaml` task with `cache.hit` / `hitBy`. `AgentOptions` honors `generate_report`, `report_file_name`, `group_name` and `group_description`. `midscene.core.dump` mirrors the upstream `IReportActionDump` layout.

Not ported from upstream: the official React report visualizer (this SDK writes upstream-shaped JSON dumps plus its own single-file HTML viewer), the Midscene Test framework's YAML lifecycle hooks and TypeScript nodes, Puppeteer, the Chrome-extension in-page `EventRecorder` (recorded event lists are supported through `generate_yaml_test` / `generate_markdown_replay` / `generate_playwright_test`), and the agent-tools/skill CLIs for AI coding assistants (including the Playwright `AiFixture`).

## Planning loop and caching

- `ai_action` runs the upstream-style "plan -> execute -> feedback" loop: each turn emits one action (Tap/Input/Scroll/KeyboardPress, ...), which is executed and then fed back with a fresh screenshot until `<complete>` or the cycle limit (`MIDSCENE_REPLANNING_CYCLE_LIMIT`, default 20) is reached.
- Caching is enabled by `AgentOptions(cache_id=...)` (or `agent.cache` in a YAML script) and stores plans in `midscene_run/cache/<cache_id>.cache.yaml`; rerunning the same instruction replays the cached actions and falls back to AI planning on any mismatch. `MIDSCENE_CACHE=1` enables caching with the default id when no `cache_id` is set.
- Element-level locate caching (Playwright / Selenium): after a successful locate the element at the target point is persisted as an XPath feature in the same YAML cache (upstream `interface.cacheFeatureForPoint` parity), and later runs resolve it back to a rect without calling the model. Elements inside iframes are cached through compound XPaths (`...|>>|...`, with frame offsets accumulated as upstream does); a segment matching more than one element is rejected so the AI re-locates instead of clicking the wrong one; order-sensitive descriptions ("the second button") produce index-based XPaths via an AI order-sensitivity judge. Interfaces without these hooks (Android, Bridge), elements inside shadow roots, and cross-origin frames whose document is unreachable still go through AI locate.

## Semantic retry

When model output fails structural parsing (invalid coordinates / broken XML / truncated JSON), the parse error is fed back to the model automatically. Control it with `MIDSCENE_MODEL_RETRY_COUNT` (default 1) and `MIDSCENE_MODEL_RETRY_INTERVAL` (default 2000ms).

## Installation and CLI

```bash
pip install midscene-python

# Desktop automation needs the GUI extra
pip install "midscene-python[desktop]"
```

| Command | Purpose |
| --- | --- |
| `midscene run script.yaml [--headed] [--device ID] [--verbose]` | Run a YAML automation script |
| `midscene model connect` | Test the configured models |
| `midscene model siwc login` | Sign in with a ChatGPT plan (SIWC) |
| `midscene version` | Show the installed version |

## Project layout

```
midscene-python/
├── midscene/
│   ├── core/
│   │   ├── agent.py          # Agent: planning, insight, reports, cache
│   │   ├── actions.py        # Action space and executors
│   │   ├── insight.py        # Insight (query / assert) engine
│   │   ├── task_cache.py     # Plan and locate caches
│   │   ├── yaml_runner.py    # YAML script parser and player
│   │   ├── dump.py           # Report dump structures
│   │   ├── types.py          # Interfaces, options and data models
│   │   └── ai_model/         # Model adapters, prompts, protocols, workflows
│   ├── web/                  # Playwright, Selenium and Bridge interfaces
│   ├── android/              # ADB device and Android agent
│   ├── desktop/              # pyautogui screen capture and OS input
│   ├── cli/                  # `midscene` command line
│   └── shared/               # Logger and shared helpers
├── examples/
├── tests/
└── docs/
```

## Resources

- Upstream project: [web-infra-dev/midscene](https://github.com/web-infra-dev/midscene)
- Documentation: [https://midscenejs.com](https://midscenejs.com/)
- Model selection and setup: [model-selection](https://midscenejs.com/model-selection), [model-api-setup](https://midscenejs.com/model-api-setup)
- API reference: [https://midscenejs.com/reference/#common](https://midscenejs.com/reference/#common)

## Credits

Thanks to the [Midscene](https://github.com/web-infra-dev/midscene) project for the prompts, protocols, and architecture this SDK ports. This project is not affiliated with the upstream maintainers.

## License

MIT License
