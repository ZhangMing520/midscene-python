# 快速开始 - Midscene Python

Midscene Python 是 [Midscene](https://github.com/web-infra-dev/midscene) 的 Python SDK：截取当前屏幕，交给视觉语言模型判断下一步，再通过 Playwright、Selenium、Chrome Bridge 或 ADB 执行动作。

本指南中的 API、环境变量与 YAML 格式均与当前仓库代码一致；上游 TypeScript 版的使用说明见 [midscenejs.com](https://midscenejs.com/)。

## 安装

```bash
pip install midscene-python

# 使用 Playwright 时还需要下载浏览器
playwright install chromium
```

Selenium 模式需要本机安装 Chrome，Selenium Manager 会自动解析 chromedriver；Android 模式需要 `adb` 在 `PATH` 中，且设备已开启 USB 调试。

## 配置模型

Midscene 通过环境变量读取模型配置。最低要求是模型名；定位（locate）还要求声明模型家族，否则无法解析坐标：

```bash
export MIDSCENE_MODEL_NAME="doubao-seed-1-6-250515"
export MIDSCENE_MODEL_API_KEY="sk-..."
export MIDSCENE_MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export MIDSCENE_MODEL_FAMILY="doubao-seed"
```

也可以使用任意 OpenAI 兼容服务，例如：

```bash
export MIDSCENE_MODEL_NAME="qwen3-vl-max"
export MIDSCENE_MODEL_API_KEY="sk-..."
export MIDSCENE_MODEL_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export MIDSCENE_MODEL_FAMILY="qwen3-vl"
```

支持的模型家族包括 `qwen2.5-vl` / `qwen3-vl`、`doubao-seed` / `doubao-vision`、`gemini`、`gpt-5`、`gpt-6`、`glm-v`、`kimi` / `kimi3`、`deepseek`、`xiaomi-mimo`、`ant-ling`、`vlm-ui-tars`、`auto-glm` 与 `jev`。旧开关 `MIDSCENE_USE_QWEN_VL` / `MIDSCENE_USE_DOUBAO_VISION` 等仍然兼容。

### 按职责拆分模型

默认模型是所有职责的兜底；可以单独为规划（planning）、定位（locate）、理解（insight）配置更合适或更便宜的模型。未配置的插槽自动回退到默认模型：

```bash
# 定位专用模型
export MIDSCENE_LOCATE_MODEL_NAME="qwen3-vl-max"
export MIDSCENE_LOCATE_MODEL_FAMILY="qwen3-vl"
export MIDSCENE_LOCATE_MODEL_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export MIDSCENE_LOCATE_MODEL_API_KEY="sk-..."

# 规划 / 理解同理：MIDSCENE_PLANNING_MODEL_* / MIDSCENE_INSIGHT_MODEL_*
```

每个插槽都支持 `_NAME`、`_API_KEY`、`_BASE_URL`、`_FAMILY`、`_PROTOCOL`、`_STREAM_MODE`、`_TIMEOUT`、`_TEMPERATURE`、`_RETRY_COUNT`、`_RETRY_INTERVAL` 等变量，与上游一致。

### 在代码中配置

`AgentOptions.model_config` 接收与环境变量同名的字典，优先级高于全局环境变量：

```python
from midscene import Agent, AgentOptions

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

### 连通性测试

配置完成后先验证模型是否可用：

```bash
midscene model connect
```

该命令并行执行规划文本、理解视觉、aiLocate 与默认文本四项检查，任一失败都会以非零状态退出。使用 ChatGPT 订阅（SIWC）时，先执行 `midscene model siwc login`，并设置 `MIDSCENE_MODEL_AUTH_MODE=siwc`。

## Web 自动化

### Selenium（同步创建，异步调用）

```python
import asyncio

from midscene import Agent, AgentOptions
from midscene.web import SeleniumWebPage


async def main():
    with SeleniumWebPage.create(headless=False) as page:
        await page.navigate_to("https://example.com")

        agent = Agent(page, AgentOptions(cache_id="login-flow"))
        await agent.ai_act("Log in with demo@example.com and password123")
        await agent.ai_assert("The dashboard is visible")

        username = await agent.ai_query({"username": "the displayed username"})
        print(username)


asyncio.run(main())
```

`SeleniumWebPage.create()` 的参数为 `headless`、`window_size=(1920, 1080)`、`user_data_dir`，其余关键字参数会作为 Chrome 启动参数传入。

### Playwright（异步创建）

```python
import asyncio

from midscene import Agent, AgentOptions
from midscene.web import PlaywrightWebPage


async def main():
    async with await PlaywrightWebPage.create(headless=False) as page:
        await page.navigate_to("https://playwright.dev")

        agent = Agent(page, AgentOptions(cache_id="docs-check"))
        await agent.ai_act("Open the documentation page")

        info = await agent.ai_query({
            "title": "the page title",
            "sections": ["the main section names"],
        })
        print(info)


asyncio.run(main())
```

`PlaywrightWebPage.create()` 的参数为 `headless`、`viewport_size=(1920, 1080)`、`user_data_dir`，其余关键字参数传给 Chromium 启动参数。

### Chrome Bridge

Bridge 模式让浏览器里的 Midscene Chrome 扩展通过 WebSocket 驱动当前标签页，本 SDK 作为服务端等待扩展连接：

```python
import asyncio

from midscene import Agent
from midscene.web import BridgeWebPage


async def main():
    page = await BridgeWebPage.create("ws://localhost:8765")
    agent = Agent(page)
    await agent.ai_act("Click the login button")


asyncio.run(main())
```

默认地址为 `ws://localhost:8765`，`wait_for_connection=True` 时会等待扩展接入（默认 30 秒）。

## Android 自动化

```python
import asyncio

from midscene.android import AndroidAgent


async def main():
    agent = await AndroidAgent.create()          # 不传则使用第一台设备
    # agent = await AndroidAgent.create("emulator-5554")

    await agent.launch_app("com.android.settings")
    await agent.ai_act("Open WLAN settings and scroll to the bottom")

    networks = await agent.ai_query({
        "networks": [{"name": "network name", "security": "security type"}],
    })
    print(networks)

    await agent.back()


asyncio.run(main())
```

`AndroidAgent` 还提供 `stop_app(package_name)`、`install_app(apk_path)`、`home()` 与 `recent()`。

## 常用操作 API

### AI 规划：ai_act

`ai_act`（别名 `ai_action`）运行「规划 → 执行 → 反馈」循环，直到任务完成：

```python
await agent.ai_act("Search for headphones and filter the results to prices under $100")

# effort: fast / balance（默认）/ deepThink
await agent.ai_act("Book the cheapest direct flight", {"effort": "deepThink"})
```

可用的选项包括 `effort`、`deepThink`、`deepLocate`、`cacheable`、`replanningCycleLimit` 与 `context`。循环上限也可用 `MIDSCENE_REPLANNING_CYCLE_LIMIT`（默认 20）设置。

### 单次定位 + 操作

这些 API 只调用一次定位模型，不走规划循环，适合步骤明确的场景：

```python
await agent.ai_tap("the login button")
await agent.ai_right_click("the file item")        # 也有 middle / double click
await agent.ai_hover("the help icon")
await agent.ai_input("the email field", {"value": "demo@example.com"})
await agent.ai_clear_input("the search box")
await agent.ai_keyboard_press("Enter")              # 或 ai_keyboard_press("the input", {"keyName": "Enter"})
await agent.ai_scroll("the results list", {"direction": "down", "scrollType": "singleAction"})
await agent.ai_long_press("the message", {"duration": 800})
await agent.ai_drag_and_drop("the card", "the target column")
await agent.sleep(1000)                             # 毫秒，不调用模型
```

滚动方向为 `up / down / left / right`；滚动类型为 `singleAction / scrollToBottom / scrollToTop / scrollToLeft / scrollToRight`。

### 定位与理解

```python
# 只定位，返回坐标与矩形
result = await agent.ai_locate("the submit button")
print(result.center, result.rect)
await agent.ai_tap("the submit button")

# 结构化数据提取
data = await agent.ai_query({
    "username": "the displayed username",
    "email": "the displayed email",
})

# 类型化查询
ok = await agent.ai_boolean("Is the user logged in?")
count = await agent.ai_number("How many items are in the cart?")
title = await agent.ai_string("What is the page title?")
answer = await agent.ai_ask("What does the error message say?")

# 断言与等待
await agent.ai_assert("The selected plan has a blue border and a checkmark")
await agent.ai_wait_for("The loading spinner is gone", {"timeoutMs": 15000, "checkIntervalMs": 3000})
```

`ai_assert` 失败时抛出 `AssertionError`；传入 `{"keepRawResponse": True}` 可得到 `{"pass", "thought", "message"}` 而不抛异常。`ai_wait_for` 的默认超时为 15000ms，检查间隔为 3000ms。

`ai_extract` 是 `ai_query` 的已弃用别名，新代码请使用 `ai_query`。

## YAML 自动化脚本

YAML 脚本由 `midscene run` 执行，用 Playwright 打开页面（或在 Android 设备上运行），按 `tasks` 顺序播放 `flow`。

```yaml
# flow.yaml
web:
  url: https://your-shop.example
  headless: true
  viewportWidth: 1440
  viewportHeight: 900
  agent:
    cache: shop-search
    generateReport: true

tasks:
  - name: Find headphones under $100
    flow:
      - aiAct: Search for headphones and filter the results to prices under $100
      - aiWaitFor: The filtered search results are visible
      - aiAssert: There are products in the search results, and each costs less than $100
      - aiQuery:
          prompt:
            firstProduct: the name of the first product
            price: the price of the first product

  - name: Check the account page
    continueOnError: true
    flow:
      - aiTap: the account menu
      - aiWaitFor:
          prompt: The account summary is visible
          timeoutMs: 10000
      - sleep: 500
```

```bash
midscene run flow.yaml
midscene run flow.yaml --headed      # 强制有头模式
midscene run flow.yaml --verbose
```

### 顶部目标

顶层只能出现 `web`（或别名 `browser` / `page` / `target`）与 `android` 之一。

Web 支持：

| 字段 | 说明 |
| --- | --- |
| `url` | 必填，启动后导航到的地址 |
| `headless` | 默认 `true`；`--headed` 会覆盖为有头 |
| `viewportWidth` / `viewportHeight` | 视口尺寸，需同时设置 |
| `userAgent` | 浏览器 User-Agent |
| `chromeArgs` | 额外 Chromium 启动参数列表 |
| `agent` | Agent 选项（见下） |

Android 支持：

| 字段 | 说明 |
| --- | --- |
| `deviceId` | 设备序列号；也可用 `--device` 覆盖 |
| `launch` | 启动后要打开的包名 |
| `agent` | Agent 选项 |

`agent` 下可配置 `groupName`、`groupDescription`、`generateReport`、`autoPrintReportMsg`、`reportFileName`、`cache`（字符串 id 或 `{id: ...}`）以及 `replanningCycleLimit`。

### tasks 与 flow

每个任务包含：

- `name`：任务名，写入输出文件；
- `flow`：按顺序执行的指令列表；
- `continueOnError`：为 `true` 时该任务失败后继续执行后续任务（默认 `false`）；但只要存在失败任务，`midscene run` 最终仍以退出码 1 结束。

flow 指令支持字符串简写或映射形式：

| 指令 | 说明 |
| --- | --- |
| `aiAct` / `aiAction` / `ai` / `instruction` | AI 规划执行任务 |
| `aiAssert` | 断言，可用 `errorMessage` 自定义失败信息 |
| `aiWaitFor` | 等待条件成立，支持 `timeoutMs` / `checkIntervalMs` |
| `aiQuery` / `aiNumber` / `aiString` / `aiBoolean` / `aiAsk` | 数据查询与类型化查询 |
| `aiLocate` | 只定位，返回 `center` 与 `rect` |
| `aiTap` / `aiRightClick` / `aiMiddleClick` / `aiDoubleClick` / `aiHover` | 点击与悬停 |
| `aiInput` | 输入文本，需提供 `value` |
| `aiKeyboardPress` | 按键，需提供 `keyName`；可配合 `locate` |
| `aiScroll` | 滚动，支持 `direction`、`scrollType`、`distance` |
| `aiLongPress` / `aiClearInput` | 长按 / 清空输入 |
| `aiDragAndDrop` | 拖拽，参数为 `from` 与 `to` |
| `aiSwipe` | 滑动 |
| `aiAndroidBack` / `aiAndroidHome` / `aiAndroidRecentApps` | Android 导航键 |
| `sleep` | 等待毫秒数 |
| `javascript` | 执行页面脚本（Playwright / Selenium） |
| `recordToReport` / `logScreenshot` | 记录日志 |

脚本支持对 `web` / `android` 等非 `tasks` 区域做 `${VAR}` 环境变量插值；变量未定义时会直接报错。

### 输出

任务结果默认写入 `midscene_run/output/<8 位随机串>.json`，包含每个任务的名称、状态、flow 结果与错误信息。可在脚本顶层用 `config.output` 指定路径：

```yaml
config:
  output: ./artifacts/run.json
```

## 缓存与报告

### 规划缓存

设置 `cache_id`（或 YAML 中的 `agent.cache`）即启用缓存，`ai_act` 的规划结果会写入：

```
midscene_run/cache/<cache_id>.cache.yaml
```

同一指令重跑时直接回放缓存动作；回放失败会自动回退到 AI 重新规划。元素级定位缓存（Playwright / Selenium）也写在同一个文件中，命中后无需再调用模型。

### 执行报告

每次实际执行或缓存回放的 `ai_act` 都会写入 JSON 报告：

```
midscene_run/report/<tag>-YYYY-MM-DD_HH-MM-SS-<8 位随机串>.json
```

`tag` 默认取接口类型（`web` / `android`），可用 `MIDSCENE_REPORT_TAG_NAME` 覆盖。`AgentOptions` 的 `generate_report=False` 可关闭报告，`report_file_name` 可指定文件名，`group_name` / `group_description` 写入报告元数据。当前仅输出 JSON，HTML 可视化尚未移植。

缓存、报告与输出目录都位于 `MIDSCENE_RUN_DIR`（默认当前工作目录下的 `midscene_run/`），可用该变量整体迁移：

```bash
export MIDSCENE_RUN_DIR=/tmp/midscene-artifacts
```

## CLI

| 命令 | 用途 |
| --- | --- |
| `midscene run <script.yaml>` | 运行 YAML 脚本 |
| `midscene run <script.yaml> --headed` | 有头模式运行浏览器 |
| `midscene run <script.yaml> --device <id>` | 指定 Android 设备（`-d` 亦可） |
| `midscene run <script.yaml> --verbose` | 输出调试日志（`-v` 亦可） |
| `midscene model connect` | 并行测试模型连通性 |
| `midscene model siwc login` | 使用 ChatGPT 订阅登录（SIWC） |
| `midscene version` | 显示版本 |

## 故障排除

### 模型配置不完整

```
ValueError: Model configuration is incomplete: model name (MIDSCENE_MODEL_NAME) is required.
```

设置 `MIDSCENE_MODEL_NAME`，并确保 `MIDSCENE_MODEL_API_KEY` / `MIDSCENE_MODEL_BASE_URL` 与服务商匹配。

### 定位缺少模型家族

```
Locate model family is required for locate. Configure MIDSCENE_MODEL_FAMILY ...
```

补上 `MIDSCENE_MODEL_FAMILY`（单独配置定位插槽时则是 `MIDSCENE_LOCATE_MODEL_FAMILY`），否则无法解析模型返回的坐标。

### Chrome 或驱动未找到

确认本机已安装 Chrome；Selenium 模式可让 Selenium Manager 自动下载驱动，或手动安装匹配版本的 chromedriver。Playwright 模式需先执行 `playwright install chromium`。

### Android 设备连接失败

确认 `adb devices` 能看到设备、USB 调试已开启；模拟器需先启动。多设备时用 `--device` 或 `AndroidAgent.create(device_id)` 指定。

### 查看执行过程

- 使用 `--headed` 或 `headless=False` 观察浏览器操作；
- 使用 `--verbose` / `midscene.shared.setup_logger("DEBUG")` 打开调试日志；
- 执行完成后查看 `midscene_run/report/` 中的 JSON 报告与 `midscene_run/output/` 中的脚本结果。

## 下一步

- 上游文档与 API 参考：[https://midscenejs.com/](https://midscenejs.com/)
- 模型选择与配置：[model-selection](https://midscenejs.com/model-selection)、[model-api-setup](https://midscenejs.com/model-api-setup)
- 示例代码：[`examples/`](../examples/)
- 上游项目：[web-infra-dev/midscene](https://github.com/web-infra-dev/midscene)
