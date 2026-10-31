# Midscene Python     [![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/Python51888/Midscene-Python)                  
[English](README.md) | [简体中文](README.zh.md)

Midscene Python is an AI-based automation framework that supports UI automation operations on Web and Android platforms.    

## Overview

Midscene Python provides comprehensive UI automation capabilities with the following core features:

- **Natural Language Driven**: Describe automation tasks using natural language
- **Multi-platform Support**: Supports Web (Selenium/Playwright) and Android (ADB)
- **AI Model Integration**: Supports multiple vision-language models such as GPT-4V, Qwen2.5-VL, and Gemini  
- **Visual Debugging**: Provides detailed execution reports and debugging information
- **Caching Mechanism**: Intelligent caching to improve execution efficiency

## Project Architecture

```
midscene-python/
├── midscene/                    # Core framework
│   ├── core/                    # Core framework
│   │   ├── agent/              # Agent system
│   │   ├── insight/            # AI inference engine
│   │   ├── ai_model/           # AI model integration
│   │   ├── yaml/               # YAML script executor
│   │   └── types.py            # Core type definitions
│   ├── web/                     # Web integration
│   │   ├── selenium/           # Selenium integration
│   │   ├── playwright/         # Playwright integration
│   │   └── bridge/             # Bridge mode
│   ├── android/                 # Android integration
│   │   ├── device.py           # Device management
│   │   └── agent.py            # Android Agent
│   ├── cli/                     # Command line tools
│   ├── mcp/                     # MCP protocol support
│   ├── shared/                 # Shared utilities
│   └── visualizer/             # Visual reports
├── examples/                   # Example code
├── tests/                      # Test cases
└── docs/                       # Documentation
```

## Tech Stack

- **Python 3.9+**: Core runtime environment
- **Pydantic**: Data validation and serialization
- **Selenium/Playwright**: Web automation
- **OpenCV/Pillow**: Image processing
- **HTTPX/AIOHTTP**: HTTP client
- **Typer**: CLI framework
- **Loguru**: Logging

## Quick Start

### Installation

```bash
pip install midscene-python
```

### Basic Usage

```python
from midscene import Agent
from midscene.web import SeleniumWebPage

# Create a Web Agent
with SeleniumWebPage.create() as page:
    agent = Agent(page)
    
    # Perform automation operations using natural language
    await agent.ai_action("Click the login button")
    await agent.ai_action("Enter username 'test@example.com'")
    await agent.ai_action("Enter password 'password123'")
    await agent.ai_action("Click the submit button")
    
    # Data extraction
    user_info = await agent.ai_extract("Extract user personal information")
    
    # Assertion verification
    await agent.ai_assert("Page displays welcome message")
```

## Key Features

### 🤖 AI-Driven Automation

Describe operations using natural language, and AI automatically understands and executes:

```python
await agent.ai_action("Enter 'Python tutorial' in the search box and search")
```

### 🔍 Intelligent Element Location

Supports multiple location strategies and automatically selects the optimal solution:

```python
element = await agent.ai_locate("Login button")
```

### 📊 Data Extraction

Extract structured data from the page:

```python
products = await agent.ai_extract({
    "products": [
        {"name": "Product Name", "price": "Price", "rating": "Rating"}
    ]
})
```

### ✅ Intelligent Assertions

AI understands page state and performs intelligent assertions:

```python
await agent.ai_assert("User has successfully logged in")
```

## Model Configuration (aligned with upstream Midscene)

Since v0.2.0 the model configuration layer is aligned with the official TypeScript SDK (v1.17.4): models can be split into planning / locate / insight slots, and every unconfigured slot falls back to the default model.

```bash
# Default model (fallback for all responsibilities)
export MIDSCENE_MODEL_NAME="doubao-seed-1-6-250515"
export MIDSCENE_MODEL_API_KEY="sk-..."
export MIDSCENE_MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export MIDSCENE_MODEL_FAMILY="doubao-seed"   # required for locate coordinate parsing

# Optional: dedicated (cheaper) locate model
# export MIDSCENE_LOCATE_MODEL_NAME="qwen3-vl-max"
# export MIDSCENE_LOCATE_MODEL_FAMILY="qwen3-vl"
# export MIDSCENE_LOCATE_MODEL_BASE_URL="..."
# export MIDSCENE_LOCATE_MODEL_API_KEY="..."
```

Supported model families match upstream `MIDSCENE_MODEL_FAMILY`: `qwen2.5-vl` / `qwen3-vl`, `doubao-seed` / `doubao-vision`, `gemini`, `gpt-5`, `glm-v`, `vlm-ui-tars` variants, `deepseek`, `kimi`, `auto-glm`, etc. The legacy `MIDSCENE_USE_QWEN_VL` / `MIDSCENE_USE_DOUBAO_VISION` switches keep working and map to the corresponding family.

You can also pass the configuration per agent (takes precedence over environment variables):

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

### Full parity with the official TypeScript SDK (v1.17.4)

Beyond model configuration, the following are aligned with upstream:

- **Planning loop**: `ai_act` (alias `ai_action`) supports the three `effort` modes (`fast` / `balance` / `deepThink` with sub-goal tracking and dual-image history); `<error>` and `<complete success="false">` fail immediately; action-execution errors are fed back to the planner (up to 5 per loop); Jev delegation switches to the default model with advisory `<planning_advice>`.
- **Convenience APIs**: `ai_tap / ai_right_click / ai_middle_click / ai_double_click / ai_hover / ai_input / ai_keyboard_press / ai_scroll / ai_long_press / ai_clear_input` (one locate call + action, no planning model), `sleep(ms)`, `ai_query / ai_boolean / ai_number / ai_string / ai_ask / ai_assert(keepRawResponse) / ai_wait_for / ai_locate`.
- **DeepLocate two-stage locate**: with `deepLocate=True` the section is located first, cropped and upscaled 2x, the element is located on the zoomed image, then mapped back to original coordinates.
- **All model families**: qwen2.5-vl / qwen3-vl / doubao-seed / doubao-vision / gemini / gpt-5 / gpt-6 / glm-v / kimi / kimi3 / deepseek (dedicated `<｜point｜>` locate protocol) / xiaomi-mimo / ant-ling / vlm-ui-tars (Thought/Action custom planner) / auto-glm (AutoGLM pseudo-code planner) / jev (System One protocol).
- **Protocols**: both `openai-chat` (stream / non-stream) and `openai-responses` (stream / non-stream); SIWC (ChatGPT plan sign-in) via `midscene model siwc login` (credentials in `~/.midscene/siwc.json`, `MIDSCENE_MODEL_AUTH_MODE=siwc`).
- **Model fallback**: models that cannot perform a task (e.g. jev for extraction) automatically fall back to the default model.
- **YAML automation**: `midscene run script.yaml` supports upstream flow commands (`aiAct/aiAssert/aiWaitFor/aiQuery/aiTap/aiInput/aiKeyboardPress/aiScroll/aiDragAndDrop/sleep/javascript`), `${VAR}` interpolation, per-task `continueOnError`, results under `midscene_run/output/`.
- **Connectivity test**: `midscene model connect` runs the text / vision / aiLocate / default checks in parallel.
- **Report dump structures**: `midscene.core.dump` mirrors the upstream `IReportActionDump` field layout (`ExecutionDumpBuilder`, `build_execution_task`, `build_service_dump`); `ExecutionDumpBuilder.write_to_disk()` persists `midscene_run/report/*.json`. Automatic report generation/HTML visualization from agent runs is not wired yet.

### Planning loop and caching

- `ai_action` runs the upstream-style "plan -> execute -> feedback" loop: each turn emits one action (Tap/Input/Scroll/KeyboardPress, ...), which is executed and then fed back with a fresh screenshot until `<complete>` or the cycle limit (`MIDSCENE_REPLANNING_CYCLE_LIMIT`, default 20) is reached.
- With `MIDSCENE_CACHE=1` and a `cache_id`, plans are cached to `midscene_run/cache/<cache_id>.cache.yaml`; rerunning the same instruction replays the cached actions (element locate still re-runs) and falls back to AI planning on any mismatch.
- Element-level locate caching is not implemented: upstream persists element coordinates through `interface.cacheFeatureForPoint`, which the Python interfaces do not provide. The `cacheable` option is accepted for API parity but does not write a locate cache.

### Semantic retry

When the model output fails structural parsing (invalid coordinates / broken XML / truncated JSON), the parse error is fed back to the model automatically. Control it with `MIDSCENE_MODEL_RETRY_COUNT` (default 1) and `MIDSCENE_MODEL_RETRY_INTERVAL` (default 2000ms).

### 📝 Credits

Thanks to Midscene Project: https://github.com/web-infra-dev/midscene for inspiration and technical references. The AI model layer of this SDK (prompts, planning/locate/insight protocols, multi-slot model config, coordinate parsing) is kept in sync with upstream v1.17.4.

## License

MIT License
