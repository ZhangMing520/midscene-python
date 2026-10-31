# Midscene Python     [![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/Python51888/Midscene-Python)

[English](README.md) | [中文](README.zh.md)  

Midscene Python 是一个基于 AI 的自动化框架，支持 Web 和 Android 平台的 UI 自动化操作。

## 概述

Midscene Python 提供全面的 UI 自动化能力，具有以下核心特性：

- **自然语言驱动**：使用自然语言描述自动化任务
- **多平台支持**：支持 Web（Selenium/Playwright）和 Android（ADB）
- **AI 模型集成**：支持 GPT-4V、Qwen2.5-VL、Gemini 等多种视觉语言模型
- **可视化调试**：提供详细的执行报告和调试信息
- **缓存机制**：智能缓存提升执行效率

## 项目架构

```
midscene-python/
├── midscene/                    # 核心框架
│   ├── core/                    # 核心框架
│   │   ├── agent/              # Agent系统
│   │   ├── insight/            # AI推理引擎
│   │   ├── ai_model/           # AI模型集成
│   │   ├── yaml/               # YAML脚本执行器
│   │   └── types.py            # 核心类型定义
│   ├── web/                     # Web集成
│   │   ├── selenium/           # Selenium集成
│   │   ├── playwright/         # Playwright集成
│   │   └── bridge/             # Bridge模式
│   ├── android/                 # Android集成
│   │   ├── device.py           # 设备管理
│   │   └── agent.py            # Android Agent
│   ├── cli/                     # 命令行工具
│   ├── mcp/                     # MCP协议支持
│   ├── shared/                 # 共享工具
│   └── visualizer/             # 可视化报告
├── examples/                   # 示例代码
├── tests/                      # 测试用例
└── docs/                       # 文档
```

## 技术栈

- **Python 3.9+**：核心运行环境
- **Pydantic**：数据验证和序列化
- **Selenium/Playwright**：Web 自动化
- **OpenCV/Pillow**：图像处理
- **HTTPX/AIOHTTP**：HTTP 客户端
- **Typer**：CLI 框架
- **Loguru**：日志记录

## 快速开始

### 安装

```bash
pip install midscene-python
```

### 基础用法

```python
from midscene import Agent
from midscene.web import SeleniumWebPage

# 创建 Web Agent
with SeleniumWebPage.create() as page:
    agent = Agent(page)
    
    # 使用自然语言进行自动化操作
    await agent.ai_action("点击登录按钮")
    await agent.ai_action("输入用户名 'test@example.com'")
    await agent.ai_action("输入密码 'password123'")
    await agent.ai_action("点击提交按钮")
    
    # 数据提取
    user_info = await agent.ai_extract("提取用户个人信息")
    
    # 断言验证
    await agent.ai_assert("页面显示欢迎信息")
```

## 主要特性

### 🤖 AI 驱动的自动化

使用自然语言描述操作，AI 自动理解并执行：

```python
await agent.ai_action("在搜索框中输入'Python教程'并搜索")
```

### 🔍 智能元素定位

支持多种定位策略，自动选择最优方案：

```python
element = await agent.ai_locate("登录按钮")
```

### 📊 数据提取

从页面提取结构化数据：

```python
products = await agent.ai_extract({
    "products": [
        {"name": "产品名称", "price": "价格", "rating": "评分"}
    ]
})
```

### ✅ 智能断言

AI 理解页面状态，进行智能断言：

```python
await agent.ai_assert("用户已成功登录")
```

## 模型配置（与上游 Midscene 对齐）

从 v0.2.0 起，模型配置层与官方 TypeScript 版（v1.17.4）对齐：支持按「规划 / 定位 / 理解」三种职责拆分模型插槽，未配置的插槽自动回退到默认模型。

```bash
# 默认模型（所有职责的兜底）
export MIDSCENE_MODEL_NAME="doubao-seed-1-6-250515"
export MIDSCENE_MODEL_API_KEY="sk-..."
export MIDSCENE_MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export MIDSCENE_MODEL_FAMILY="doubao-seed"   # 声明模型家族（定位坐标解析依赖它）

# 可选：为定位单独配置更便宜的专用模型
# export MIDSCENE_LOCATE_MODEL_NAME="qwen3-vl-max"
# export MIDSCENE_LOCATE_MODEL_FAMILY="qwen3-vl"
# export MIDSCENE_LOCATE_MODEL_BASE_URL="..."
# export MIDSCENE_LOCATE_MODEL_API_KEY="..."
```

支持的模型家族包括：`qwen2.5-vl` / `qwen3-vl`、`doubao-seed` / `doubao-vision`、`gemini`、`gpt-5`、`glm-v`、`vlm-ui-tars` 系列、`deepseek`、`kimi`、`auto-glm` 等（与上游 `MIDSCENE_MODEL_FAMILY` 取值一致）。旧的 `MIDSCENE_USE_QWEN_VL` / `MIDSCENE_USE_DOUBAO_VISION` 等开关仍然兼容，会自动映射到对应家族。

也可以在代码里按 Agent 传入（优先级高于环境变量）：

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

### 与官方 TypeScript 版全量对齐（v1.17.4）

除模型配置外，以下能力也与上游保持一致：

- **规划循环**：`aiAct`（`aiAction` 为别名）支持 `effort` 三档（`fast` 跳过思考输出 / `balance` 默认 / `deepThink` 子目标分解 + 双图历史）；`<error>` 与 `<complete success="false">` 立即失败；动作执行错误反馈给模型重规划（单轮最多 5 次）；Jev 委派（delegation）自动切换默认模型并以 `<planning_advice>` 注入建议。
- **便捷操作 API**：`ai_tap / ai_right_click / ai_middle_click / ai_double_click / ai_hover / ai_input / ai_keyboard_press / ai_scroll / ai_long_press / ai_clear_input`（单次定位 + 执行，不走规划模型）、`sleep(ms)`、`ai_query / ai_boolean / ai_number / ai_string / ai_ask / ai_assert(keepRawResponse) / ai_wait_for / ai_locate`。
- **DeepLocate 二段定位**：`deepLocate=True` 时先定位区域（section locate）→ 裁剪放大 2 倍 → 在放大图上精确定位 → 映射回原图坐标。
- **模型家族全覆盖**：qwen2.5-vl / qwen3-vl / doubao-seed / doubao-vision / gemini / gpt-5 / gpt-6 / glm-v / kimi / kimi3 / deepseek（含 `<｜point｜>` 专属定位协议）/ xiaomi-mimo / ant-ling / vlm-ui-tars（Thought/Action 自定义规划器）/ auto-glm（AutoGLM 伪代码规划器）/ jev（System One 协议）。
- **协议**：`openai-chat`（流式/非流式）与 `openai-responses`（流式/非流式）均支持；SIWC（ChatGPT 订阅登录）可通过 `midscene model siwc login` 完成登录并保存凭据（`MIDSCENE_MODEL_AUTH_MODE=siwc`）。
- **模型回退**：jev 等不支持数据提取的模型在 extract 任务上自动回退默认模型。
- **YAML 自动化脚本**：`midscene run script.yaml` 支持 `aiAct/aiAssert/aiWaitFor/aiQuery/aiTap/aiInput/aiKeyboardPress/aiScroll/aiDragAndDrop/sleep/javascript` 等上游同款 flow 指令、`${VAR}` 环境变量插值、任务 `continueOnError`、结果输出到 `midscene_run/output/`。
- **连通性测试**：`midscene model connect` 并行执行文本 / 视觉 / 定位 / 默认四项检查。
- **报告 dump 结构**：`midscene.core.dump` 对齐上游 `IReportActionDump` 字段结构（`ExecutionDumpBuilder`、`build_execution_task`、`build_service_dump`），`ExecutionDumpBuilder.write_to_disk()` 可写入 `midscene_run/report/*.json`；Agent 运行时的自动报告生成 / HTML 可视化尚未接入。

### 规划循环与缓存

- `ai_action` 采用上游同款「规划 → 执行 → 反馈」循环：每轮输出一个动作（Tap/Input/Scroll/KeyboardPress 等），执行后带截图反馈重新规划，直到 `<complete>` 或达到循环上限（`MIDSCENE_REPLANNING_CYCLE_LIMIT`，默认 20）。
- 开启 `MIDSCENE_CACHE=1` 并提供 `cache_id` 后，规划结果会缓存到 `midscene_run/cache/<cache_id>.cache.yaml`，同一指令重跑时直接回放缓存动作（命中元素级定位缓存时直接复用坐标），命中失败自动回退 AI 重新规划。
- 元素级定位缓存（Playwright / Selenium）：定位成功后把目标点上的元素以 XPath 特征写入同一个 YAML 缓存（对齐 `interface.cacheFeatureForPoint`），下次运行直接由缓存还原坐标、不再调用模型；Android / Bridge 等未实现该钩子的接口以及 iframe / Shadow DOM 内元素仍走 AI 定位。

### 语义重试

模型输出解析失败（坐标非法 / XML 残缺 / JSON 断裂）时，会把解析错误回传给模型自动重试，重试次数与间隔由 `MIDSCENE_MODEL_RETRY_COUNT`（默认 1）和 `MIDSCENE_MODEL_RETRY_INTERVAL`（默认 2000ms）控制。

### 📝 致谢

感谢Midscene项目：https://github.com/web-infra-dev/midscene 提供的灵感和技术参考。本项目的 AI 模型层（提示词、规划/定位/理解协议、多模型插槽、坐标解析）与上游 v1.17.4 保持同步。

## 许可证

MIT License
