# Midscene Python

**像人一样理解界面。用自然语言驱动 Web、Android 与桌面的 UI 自动化与端到端测试。**

Midscene Python 是 [Midscene](https://github.com/web-infra-dev/midscene) 的 Python SDK。它截取当前屏幕，交给视觉语言模型判断下一步该做什么，再通过 Playwright、Selenium、Chrome Bridge、ADB 或 pyautogui 执行动作。AI 模型层（提示词、规划/定位/理解协议、多模型插槽、坐标解析）与上游 Midscene v1.17.4 保持同步。

[English](README.md) | [简体中文](README.zh.md)

## 用自然语言编写自动化

只需描述目标，Midscene 会自行规划步骤、在屏幕上定位元素并执行。

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

同样的步骤写成 YAML 脚本，用 `midscene run script.yaml` 运行：

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

安装方式、模型配置、完整的 flow 指令与 CLI 参数见 [docs/quickstart.md](docs/quickstart.md)。

## 像人一样看、操作与验证

端到端测试是从用户视角验证完整流程，因此 Midscene 也按用户的方式测试：**观察屏幕、对可见内容执行操作、验证可见结果**。

### 基于截图定位并操作

Midscene 依据元素的外观与位置进行定位，然后点击、输入、滚动或拖拽来完成你的指令。对于只有图标的按钮、自定义控件、`<canvas>` 以及 iframe 内的元素，都无需维护选择器或添加语义标注。

### 验证用户真正看到的内容

用自然语言描述期望的外观，即可检查颜色、选中高亮、布局与视觉反馈：

```python
await agent.ai_assert("The selected plan has a blue border and a checkmark")
await agent.ai_assert("The error message is visible below the email field")
```

## 跨平台统一 API

视觉定位不依赖具体的 UI 渲染栈，因此同一套 `Agent` API 可用于所有受支持的平台：

| 平台 | 集成方式 |
| --- | --- |
| Web | [Playwright](https://midscenejs.com/integrate-with-playwright) 或 Selenium |
| 桌面 Chrome | [Bridge 模式](https://midscenejs.com/bridge-mode)（Chrome 扩展通过 WebSocket 与本 SDK 通信） |
| Android | 通过 ADB 连接真机与模拟器 |
| iOS | 通过 WebDriverAgent（WDA / Appium XCUITest）连接真机与模拟器 |
| HarmonyOS | 通过 `hdc` + `uitest` 连接真机与模拟器 |
| 桌面系统 | Windows / macOS / Linux 整屏截图与系统指针控制（pyautogui，仅主显示器），需 `pip install "midscene-python[desktop]"` |
| 自定义接口 | 继承 `AbstractInterface`，提供截图与动作能力 |

上游 Midscene 中的 Puppeteer **未移植**到本 SDK。iOS 与 HarmonyOS 层已移植，但尚未在真实设备上验收，目前由假 WDA / `hdc` 传输层的单元测试覆盖。

## 模型与配置

基于截图的规划与定位无需把庞大的 DOM 树发送给模型。Midscene Python 支持与上游相同的模型家族与请求协议：

`qwen2.5-vl` / `qwen3-vl`、`doubao-seed` / `doubao-vision`、`gemini`、`gpt-5`、`gpt-6`、`glm-v`、`kimi` / `kimi3`、`deepseek`（专用的 `<｜point｜>` 定位协议）、`xiaomi-mimo`、`ant-ling`、`vlm-ui-tars`（Thought/Action 自定义规划器）、`auto-glm`（AutoGLM 伪代码规划器）以及 `jev`（System One 协议）。

```bash
# 默认模型（所有职责的兜底）
export MIDSCENE_MODEL_NAME="doubao-seed-1-6-250515"
export MIDSCENE_MODEL_API_KEY="sk-..."
export MIDSCENE_MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export MIDSCENE_MODEL_FAMILY="doubao-seed"   # 定位坐标解析依赖该声明

# 可选：按职责拆分模型插槽（规划 / 定位 / 理解）
# export MIDSCENE_LOCATE_MODEL_NAME="qwen3-vl-max"
# export MIDSCENE_LOCATE_MODEL_FAMILY="qwen3-vl"
# export MIDSCENE_LOCATE_MODEL_BASE_URL="..."
# export MIDSCENE_LOCATE_MODEL_API_KEY="..."
```

旧的 `MIDSCENE_USE_QWEN_VL` / `MIDSCENE_USE_DOUBAO_VISION` 等开关仍然兼容，会自动映射到对应家族。也可以在代码里按 Agent 传入（优先级高于环境变量）：

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

`openai-chat` 与 `openai-responses` 两种协议均支持流式与非流式模式。SIWC（ChatGPT 订阅登录）可通过 `midscene model siwc login` 配合 `MIDSCENE_MODEL_AUTH_MODE=siwc` 使用。

## 与上游 v1.17.4 对齐

与官方 TypeScript SDK 保持一致的能力：

- **规划循环**：`ai_act`（`ai_action` 为别名）支持 `effort` 三档（`fast` / `balance` / 带子目标跟踪与双图历史的 `deepThink`）；`<error>` 与 `<complete success="false">` 立即失败；动作执行错误会反馈给规划模型（单轮最多 5 次）；Jev 委派（delegation）自动切换默认模型并以 `<planning_advice>` 注入建议。
- **便捷操作 API**：`ai_tap / ai_right_click / ai_middle_click / ai_double_click / ai_hover / ai_input / ai_keyboard_press / ai_scroll / ai_long_press / ai_clear_input / ai_drag_and_drop`（单次定位 + 执行，不走规划模型）、`sleep(ms)`，以及 `ai_query / ai_boolean / ai_number / ai_string / ai_ask / ai_assert / ai_wait_for / ai_locate`。`ai_extract` 作为 `ai_query` 的已弃用别名保留。
- **DeepLocate 二段定位**：`deepLocate=True` 时先定位区域，裁剪并放大 2 倍，在放大图上精确定位元素，再映射回原图坐标。
- **模型回退**：无法执行某类任务的模型（例如 jev 之于数据提取）自动回退到默认模型。
- **YAML 自动化**：`midscene run script.yaml` 支持上游同款 flow 指令（`aiAct / aiAssert / aiWaitFor / aiQuery / aiTap / aiInput / aiKeyboardPress / aiScroll / aiDragAndDrop / sleep / javascript` 等）、`${VAR}` 环境变量插值、任务级 `continueOnError`，结果输出到 `midscene_run/output/`。
- **连通性测试**：`midscene model connect` 并行执行规划文本、理解视觉、aiLocate、默认文本四项检查。
- **执行报告**：每次进入规划阶段的 `ai_act` 运行都会写入上游格式的 JSON 报告 `midscene_run/report/<tag>-<YYYY-MM-DD_HH-MM-SS>-<8 位随机串>.json`，并生成同名单文件 HTML 查看器（tag 默认取接口类型，可用 `MIDSCENE_REPORT_TAG_NAME` 覆盖；`generateReport: false` 可关闭）。报告记录规划输出、每个动作的墙钟耗时/状态/错误；缓存回放时写入上游同款 `LoadYaml` 任务（含 `cache.hit` / `hitBy`）。`AgentOptions` 的 `generate_report`、`report_file_name`、`group_name` 与 `group_description` 均会生效。`midscene.core.dump` 对齐上游 `IReportActionDump` 字段结构。

未从上游移植：官方 React 报告可视化器（本 SDK 写入上游格式的 JSON dump，并自带单文件 HTML 查看器）、Midscene Test 框架的 YAML 生命周期钩子与 TypeScript Nodes、Puppeteer。

## 规划循环与缓存

- `ai_action` 采用上游同款「规划 → 执行 → 反馈」循环：每轮输出一个动作（Tap/Input/Scroll/KeyboardPress 等），执行后带新截图反馈重新规划，直到 `<complete>` 或达到循环上限（`MIDSCENE_REPLANNING_CYCLE_LIMIT`，默认 20）。
- 设置 `AgentOptions(cache_id=...)`（YAML 脚本中为 `agent.cache`）即启用缓存，规划结果写入 `midscene_run/cache/<cache_id>.cache.yaml`，同一指令重跑时直接回放缓存动作，命中失败自动回退 AI 重新规划。未设置 `cache_id` 时，`MIDSCENE_CACHE=1` 会用默认缓存 id 启用缓存。
- 元素级定位缓存（Playwright / Selenium）：定位成功后把目标点上的元素以 XPath 特征写入同一个 YAML 缓存（对齐上游 `interface.cacheFeatureForPoint`），后续运行直接由缓存还原坐标、不再调用模型。iframe 内元素通过复合 XPath（`...|>>|...`）缓存，并按上游方式累加 frame 偏移；某段 XPath 命中多个元素时不写入缓存（避免误点第一个），交给 AI 重新定位；位置相关描述（如「第二个按钮」）会由 AI 判断顺序敏感性并生成带索引的 XPath。未实现该钩子的接口（Android、Bridge）、Shadow DOM 内元素，以及无法访问文档的跨域 iframe 仍走 AI 定位。

## 语义重试

模型输出解析失败（坐标非法 / XML 残缺 / JSON 断裂）时，会把解析错误回传给模型自动重试。重试次数与间隔由 `MIDSCENE_MODEL_RETRY_COUNT`（默认 1）和 `MIDSCENE_MODEL_RETRY_INTERVAL`（默认 2000ms）控制。

## 安装与 CLI

```bash
pip install midscene-python

# 桌面自动化需要 GUI 扩展依赖
pip install "midscene-python[desktop]"
```

| 命令 | 用途 |
| --- | --- |
| `midscene run script.yaml [--headed] [--device ID] [--verbose]` | 运行 YAML 自动化脚本 |
| `midscene model connect` | 测试已配置的模型 |
| `midscene model siwc login` | 使用 ChatGPT 订阅登录（SIWC） |
| `midscene version` | 显示已安装版本 |

## 项目结构

```
midscene-python/
├── midscene/
│   ├── core/
│   │   ├── agent.py          # Agent：规划、理解、报告、缓存
│   │   ├── actions.py        # 动作空间与执行器
│   │   ├── insight.py        # Insight（查询 / 断言）引擎
│   │   ├── task_cache.py     # 规划缓存与定位缓存
│   │   ├── yaml_runner.py    # YAML 脚本解析与回放
│   │   ├── dump.py           # 报告 dump 结构
│   │   ├── types.py          # 接口、选项与数据模型
│   │   └── ai_model/         # 模型适配器、提示词、协议、工作流
│   ├── web/                  # Playwright、Selenium、Bridge 接口
│   ├── android/              # ADB 设备与 Android Agent
│   ├── desktop/              # pyautogui 整屏截图与系统输入
│   ├── cli/                  # `midscene` 命令行
│   └── shared/               # 日志与共享工具
├── examples/
├── tests/
└── docs/
```

## 资源

- 上游项目：[web-infra-dev/midscene](https://github.com/web-infra-dev/midscene)
- 文档：[https://midscenejs.com](https://midscenejs.com/)
- 模型选择与配置：[model-selection](https://midscenejs.com/model-selection)、[model-api-setup](https://midscenejs.com/model-api-setup)
- API 参考：[https://midscenejs.com/reference/#common](https://midscenejs.com/reference/#common)

## 致谢

感谢 [Midscene](https://github.com/web-infra-dev/midscene) 项目提供的提示词、协议与整体架构，本 SDK 移植自该项目。本项目与上游维护方无隶属关系。

## 许可证

MIT License
