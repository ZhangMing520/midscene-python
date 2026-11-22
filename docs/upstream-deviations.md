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
| zod 命名空间 `z` | `export { z }`（如 `core/device/index.ts`） | Python 的 action schema 用普通 dict 表示，不伪造 zod 构建器 |

## 2. 已知功能偏差

### 2.1 已实现但行为不同

| 项 | 现状 | 说明 |
|---|---|---|
| 统一 `ReportSession` 宿主生命周期 | 未实现 | Python 保留 `ReportArtifactStore` + `export_report_artifact` 组合 |
| Recorder → Playwright 代码生成 | 有意超出上游 | 剥离代码围栏并补尾换行；把 fixture 骨架写进提示词（上游嵌入整份代码） |
| 报告查看器 | UI 不同 | 单文件 HTML，数据与 `IReportActionDump` 一致 |
| iOS / HarmonyOS 真机验收 | 待环境 | 代码已移植；WDA / DevEco 真机端到端需用户环境验证 |
| 旧计划缓存的距离语义 | 无缓存版本号 | 历史缓存若存的是“模型输入图像像素”距离，回放会按逻辑距离解释（上游同样存在）；升级后建议清空一次 `midscene_run/cache` |
| GPT 系列 bbox 边界 | 半开区间 | 允许 `right == width` / `bottom == height`；闭区间家族不变 |
| verbose `aiAct` 进度载荷 | 契约不同 | Python 渲染器消费的 progress payload 与上游时间线不完全一致，相关 5 个用例按行为差异 skip |
| 报告导出截图格式 | inline 用 data URI，directory 用外置资产 | directory 导出会内容寻址去重并写 `midscene_screenshot_ref`；inline 保持 data URI |
| 批处理输出路径 | 总是暴露 | Python 结果始终包含 `output_path`；上游用 `node:fs` 可选校验文件是否存在 |
| 终端中断 | `termios` | Python 从进程 stdin 捕获 Ctrl+C，不是可注入的输入流 |

### 2.2 尚未实现的能力（对应 skip）

| 能力 | 影响 | 说明 |
|---|---|---|
| web agent tools 层 | 5 个 skip | Python SDK 未实现该层 |
| CDP agent tools | 2 个 skip | Chrome DevTools Protocol 工具未实现 |
| zod 原生描述符 | 约 6 个 skip | `nativeEnum` / `intersection` / `tuple-rest` / 构造器身份、refinement、default/transform 在 Python dict schema 中没有等价物 |

> 这些 skip 的理由已写明具体能力缺口；实现对应能力后应改为真实断言。
> `ReportGenerator` 目录模式、`BatchRunner` 汇总接口、解析/重试取消、报告合并与
> 源报告删除、`beforeAll` 重试、全局配置覆盖、回调 `client_id` 校验与
> `rectMatchesCacheFeature` 抛错已在后续批次补齐，对应 skip 已改为真实断言。

### 2.3 Node / 测试环境专属（不移植）

| 项 | 影响 | 原因 |
|---|---|---|
| rstest 包装器与逐目标结果文件 | 5 个 skip | Node 测试运行器专属；等价能力由 `run_yaml_batch_with_case_ids` 覆盖 |
| 多进程发布器 | 2 个 skip | 上游 fork 八个 TypeScript publisher 子进程，Python 无等价子进程发布器 |
| TypeScript 编译器静态解析 | 2 个 skip | 上游用 TS Compiler API 解析 `device.ts` 的 `*Raw`/`visualActions` 结构；Python 源码没有该结构 |
| 快照夹具 | 3 个 skip | help 文本 / prompt 快照在 Python 侧没有对应存储 |
| 目录报告夹具 | 2 个 skip | 真实目录报告 fixture 不在仓库中 |
| 原始脚本闭合 token 风险 | 1 个 skip | 上游针对打包产物检查，Python 源码未打包，不存在该风险 |

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

---

## 4. 方法级签名等价登记

`scripts/method_alignment_allowlist.json` 登记了 30 项上游函数与 Python 移植之间的签名等价关系。
它们不是缺失：Python 侧只是把上游的 options/context 对象展开或聚合，行为保持一致。

- `options-object`：上游接收单个 `{...}` options/input 对象，Python 暴露同名关键字参数。
  例如 `prepareModelImage(options)` → `prepare_model_image(image_base64, width, height, policy)`。
- `context-object`：上游分开传多个上下文参数，Python 聚合成 adapter/context 对象。
  例如 `resolveLocate(locate, resolvedCustomPlanner, protocolContext)` → `resolve_locate(adapter)`。

`check_upstream_method_alignment.py` 将这些条目单独计数为
`allowlisted_signature_mismatch` 并输出原因，不混入 `signature_mismatch`。
新增条目必须写明具体技术原因；不得用来掩盖真实的参数缺失。
