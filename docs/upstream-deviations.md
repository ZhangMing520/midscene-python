# 上游对齐：偏差与已核实事实

本文件只记录三类信息：

1. **明确不移植**的上游能力及原因；
2. **已知功能偏差**（行为不同或尚未实现，但当前接受）；
3. **已核实的上游行为事实**，用于避免重复评审和误判。

已完成的历史清单不再记录（见 git 历史）。当前缺口以
`scripts/upstream_api_gaps.json` 和测试 skip 为准，推进方式见
`docs/upstream-alignment-plan.md`。

---

## 1. 明确不移植

| 能力 | 上游位置 | 原因 |
|---|---|---|
| Puppeteer 驱动 | `packages/web-integration` | Python 侧有 Playwright、WebDriver 与 Chrome 扩展 bridge，没有 Puppeteer 适配器；`browser_agent_utils.py` 仅保留 puppeteer 名称映射 |
| 官方 React 可视化器 | `packages/visualizer` | Python 使用自研单文件 HTML 查看器，数据结构一致、UI 不同 |
| Chrome 扩展内 `EventRecorder` | 浏览器扩展 | 需要扩展注入；Python 只消费事件序列 |
| Playwright `AiFixture` | `web-integration/src/playwright/ai-fixture.ts` | 已登记 `exempt`：面向 Playwright Test runner，Python 用户直接用 pytest |

## 2. 已知功能偏差

| 项 | 现状 | 说明 |
|---|---|---|
| 统一 `ReportSession` 宿主生命周期 | 未实现 | Python 保留 `ReportArtifactStore` + `export_report_artifact` 组合 |
| Recorder → Playwright 代码生成 | 有意超出上游 | 剥离代码围栏并补尾换行；把 fixture 骨架写进提示词（上游嵌入整份代码） |
| 报告查看器 | UI 不同 | 单文件 HTML，数据与 `IReportActionDump` 一致 |
| iOS / HarmonyOS 真机验收 | 待环境 | 代码已移植；WDA / DevEco 真机端到端需用户环境验证 |
| 旧计划缓存的距离语义 | 无缓存版本号 | 历史缓存若存的是“模型输入图像像素”距离，回放会按逻辑距离解释（上游同样存在）；升级后建议清空一次 `midscene_run/cache` |
| GPT 系列 bbox 边界 | 半开区间 | 允许 `right == width` / `bottom == height`；闭区间家族不变 |

## 3. 已核实的上游行为事实

### iOS

- `typeText` **会 trim**（`midscene/ios/wda.py` 的 `text.strip()`），逐字符路径 `typeRawKeys` 不 trim；这与上游一致，不是缺陷。
- `scroll` 的方向语义 = **要揭示的内容方向**，与手指滑动方向相反。
- `Pinch`：`in` = 手指并拢（缩小），`out` = 手指张开（放大）；所有平台实现必须保持该语义。
- `getElementsInfo() → []`、`getElementsNodeTree() → {node: null, children: []}` 是上游的“简化实现”，fork 的零尺寸占位树不是差距。
- `scrollUntilBoundary` 常量：最多 20 次、每次前 500ms、手势后 2000ms、位移 0.6×轴长、时长 300ms；截图逐字符比较，容忍 10%，`scrollToRight` 需连续 3 帧不变。
- 无 locate 的 `scroll` 走 `scrollDefault`：中央 70% 区段（0.85 ↔ 0.15），时长 `max(1000, hypot / 0.4)` 限制释放速度。
- iOS 动作空间包含 `ClearInput` 与 `CursorMove`（来自 `createDefaultMobileActions`）。

### Android / scrcpy

- Android 专属动作在上游 `packages/android/src/device.ts`，不在 `core/device/index.ts`：`AndroidBackButton` / `HomeButton` / `RecentAppsButton`、`RunAdbShell`、`Launch`、`Terminate`。
- scrcpy `frameRate` 已实现（`resolve_scrcpy_frame_rate`），不再是不移植项。

### Recorder 生成

- `MARKDOWN_REPLAY_SCREENSHOT_PAYLOAD_BUDGET = 600_000`，`MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE = 768`；≤768px 的截图**原样返回**，不做无谓 JPEG 重编码。
- 截图标签优先级：`semantic.actionSummary → elementDescription → replayInstruction → "Navigate to url" → value`。
- `createMessageContent`：intro 前插到 prompt 之前，图片追加其后，始终是单条 user 消息的 content 数组。
- Playwright 侧截图取 `maxScreenshots`（默认 3），并与 Markdown 共用 600KB 预算。

### 规划与动作

- `deepLocate` 下，规划坐标仅作为搜索区域提示，不作为最终定位结果。
- 距离字段在缓存/YAML 中存**逻辑值**；执行前按 `shrunk_shot_to_logical_ratio` 从模型图像像素换算。
- `Pinch` 标签语义见 iOS 小节，跨平台统一。
- 动作执行后默认等待 `waitAfterAction` = 300ms。
- action readiness 等待满 5000ms 时打印警告并**继续等待**，不超时失败。
- 单轮规划循环最多允许 5 次执行错误（`MAX_ERROR_COUNT_IN_ONE_PLANNING_LOOP = 5`），超过即返回 `Too many errors in one planning loop`。

### Agent / 测试运行器

- `ui_observer` 不做帧内容去重：上游 `dedupeRefs` 去重的是持久化 frame ref，不是像素；Python 每帧独立截图，与视觉输入一致。
- `run_gherkin_scenario` 的 `Then` 分支断言的是 `build_step_prompt` 构造出的 `Verify that ...` prompt，与上游一致。
- `shared/agent_tools` 与上游 `agent-tools` 目录一一对应（含 `AgentTools`、`base-tools`、`tool-generator`、`web_tabs`）；`core/skill` 也已移植。
- `core/test-runner/**` 全部为 `aligned`，不再有“测试运行器钩子未移植”的偏差。

### Bridge

- 默认端口为 `3766`，与上游一致；不再有 8765 的历史差异。

### 模型调用与部署前提

- Codex app-server 的 JSON-RPC 传输已移植（`service_caller/codex/`），`codex://` 会走该通道。
- 运行时需要本机安装 `codex` 可执行文件；缺失时报 `failed to start codex app-server: codex binary not found`，不会静默回退到 OpenAI 通道。

### 报告写盘

- `generateReport` 开启时始终更新合并 HTML 报告。
- 单次执行的 JSON dump 仅在 `persistExecutionDump`（默认 false）时写入。
- `generateReport: false` 时全部跳过。
- `aiAct` 同时写 JSON + HTML。
