# 上游对齐实施方案（文件级契约 + 验收闭环）

本文档定义如何把 `midscene-python` 与上游 `midscene`（TypeScript）从“文件存在”推进到“文件、符号、方法、行为、测试”逐层对齐，并提供可复跑、可追踪、可防止回退的执行方案。

---

## 1. 现状与口径

当前有两套检查，结论不同，必须分开看：

| 口径 | 工具 | 结果 | 含义 |
|---|---|---|---|
| 文件级 | `scripts/check_upstream_alignment.py` | 429 aligned / 0 merged / 0 pending / 101 exempt | 每个上游 `.ts` 有对应 Python 文件（或已登记豁免） |
| 导出级 | `scripts/check_upstream_api_alignment.py` | 0 个模块有差异 / 0 个运行时导出缺失 / 0 个已迁移 | 映射文件里没有这些顶层运行时导出 |
| 方法级 | `scripts/check_upstream_method_alignment.py` | 0 个模块 / 0 个函数 / 0 个类 / 0 个方法缺失（另 30 项已登记为等价签名） | 类与函数的方法、参数骨架缺口 |
| 测试级 | `tests/`（220 个 Python 文件，其中 217 个 `test_*.py`） | 2411 passed / 149 skipped | 上游同名测试已同步；skip 原因分类见 `docs/upstream-deviations.md` §2.2 / §2.3 |

**关键结论**：文件级对齐 ≠ 功能完整。`core/report.ts` → `core/report.py` 文件存在，但 `report.py` 只有 `write_report_html`，所以文件级通过、导出级仍有 7 个缺口、测试级有 17 个 skip。

后续所有进度以**导出级 + 测试级**为准，文件级只作为守门条件。

其中 0 个模块存在真正缺失，另外 0 个模块只有迁移差异。
剩余 30 项函数签名差异已登记为等价适配（`scripts/method_alignment_allowlist.json`，见 §7.6）。

### 计数口径

- “有缺口模块”是**模块数**；“真正缺失/已迁移”是**符号数**，两者不能相减。
- 每个模块：`不在映射文件里的导出 = 缺失 + 已迁移`。
- 计数单位是“模块-符号对”，同一名字被多个上游模块导出会重复计数（329 个缺失对应 319 个唯一名字）。
- `已迁移` 表示符号在 Python 其他模块里存在，不是功能缺失，但上游对应导入路径可能仍不可用。

---

## 2. 目标与非目标

### 目标

1. 每个已对齐模块的**顶层运行时导出**在 Python 映射模块中可用。
2. 每个导出类的**公共方法**、每个导出函数的**参数骨架**与上游一致。
3. 上游同名测试文件中的用例，除平台/Node 专属外全部真实执行。
4. 建立可复跑的 ledger 和 CI ratchet，缺口数只能下降。

### 非目标

- 不追求 TypeScript 类型系统在 Python 的等价表达（interface/type 用 TypedDict/dataclass 近似即可）。
- 不移植仅适用于 Node/浏览器/特定 OS 且 Python 无对应运行时能力的实现（登记 `exempt` 并写原因）。
- 不为了对齐而引入新的重型运行时依赖。

明确不移植清单、已知功能偏差和已核实的上游行为事实见
`docs/upstream-deviations.md`；这些内容不重复列入本方案的缺口统计。

---

## 3. 符号定义

本方案中的“符号”指上游模块的**顶层运行时导出**：

| 计入 | 不计入（单独处理） |
|---|---|
| `export function` / `async function` | `export interface` / `type`（类型层） |
| `export class`（类名） | 类的方法/属性（方法级审计单独做） |
| `export const` / `let` / `var`（变量、常量） | zod `*Schema`（schema 层） |
| `export enum` | `export { X } from './other'`（在定义模块审计） |
| 本地 `export { X }`（同文件定义） | 匿名 default export |

方法级审计在导出级基础上再补：

- 类：公共方法名、是否 async、参数个数与默认值。
- 函数：参数名/顺序/默认值/是否可选、返回结构（能静态推断时）。
- 常量：值或形状（数组/对象键）可比较时比较。

---

## 4. 完成定义（DoD）

一个上游文件只有在以下 6 项全部满足时才标记 `done`：

| # | 检查项 | 验收方式 |
|---|---|---|
| 1 | 导出级 `missing = 0` | `check_upstream_api_alignment.py` 对应模块无 missing |
| 2 | 方法级无缺口 | 方法级清单中该模块 `method_missing = 0` |
| 3 | 模块路径兼容 | 能从上游对应的 Python 路径导入；`moved` 符号已 re-export |
| 4 | 上游测试真实执行 | 映射测试文件 `skip = 0`，或每条 skip 有 `platform/node-only/type-only/exempt` 原因 |
| 5 | 全量回归通过 | `compileall` + `ruff --select F,E9` + 全量 pytest |
| 6 | ledger 更新 | 状态、理由、测试文件、批次号写入 ledger |

> 规则：**不允许用新增 skip 来“通过”对齐**。skip 只能用于无法在 Python 运行时表达的上游行为，且必须写明具体原因。

---

## 5. 工具链

### 5.1 导出级检查（已有）

`scripts/check_upstream_api_alignment.py`

```bash
.venv/bin/python scripts/check_upstream_api_alignment.py \
  --json scripts/upstream_api_gaps.json --limit 30
```

- 输入：`scripts/upstream_alignment_baseline.json`（文件级映射）
- 输出：按模块分组的 `missing` / `moved`，以及按包汇总
- 排除：interface/type、zod schema；纯 `export ... from` 的 barrel 不计缺失

### 5.2 方法级清单（已有）

`scripts/check_upstream_method_alignment.py` 输出：

```json
{
  "core/report.ts": {
    "functions": {
      "exportReportArtifact": {"params": ["options"], "async": true}
    },
    "classes": {
      "ReportMergingTool": {
        "methods": {
          "append": {"params": ["reportFile"], "async": false},
          "mergeReports": {"params": ["outputFile"], "async": true}
        }
      }
    },
    "constants": {"DEFAULT_XXX": {"kind": "string"}},
    "missing_in_python": ["mergeReports"],
    "signature_mismatch": []
  }
}
```

实现要点：

- 上游侧：轻量 TS 扫描器（括号配对 + 正则），不引入 TypeScript 依赖；若精度不足，再在 `scripts/ts-api/` 下本地安装 `typescript`（加入 `.gitignore`）。
- Python 侧：用 `ast` 读取顶层函数/类/方法、参数名、默认值、`async` 标记。
- 名称归一化：`camelCase`/`PascalCase`/`UPPER_SNAKE` → `lower_snake_case`。
- 比较结果分三类：`missing`（不存在）、`signature_mismatch`（存在但参数骨架不同）、`ok`。

### 5.3 Ledger（已有）

`scripts/upstream_alignment_ledger.json`，每个 aligned 模块一条（当前 425 条，
`status` 以 ledger 为准）。示例：

```json
{
  "module": "core/report.ts",
  "python": "core/report.py",
  "package": "core",
  "status": "partial",
  "missing": ["ReportMergingTool", "TestRunReportAssembler", "collectDedupedExecutions"],
  "moved": ["exportReportArtifact"],
  "method_missing": ["ReportMergingTool.mergeReports"],
  "tests": ["tests/test_report.py"],
  "skipped_cases": 17,
  "skip_reasons": {"node-only": 17},
  "batch": "P1",
  "owner": "",
  "notes": "Python 只有 write_report_html；合并逻辑在 core/dump/report_dump_compactor.py"
}
```

`status` 取值：`todo` / `partial` / `done` / `exempt`。

ledger 由脚本生成初稿，人工只维护 `status`、`skip_reasons`、`notes`、`owner`。

### 5.4 CI Ratchet（已有）

`scripts/check_alignment_ratchet.py` 把当前代码与已提交的 ledger 对比：

- 新增 `api_missing` / `method_missing_*` 直接失败；
- `status` 不得从 `done` 回退到 `partial`；
- 有缺口的模块不在 ledger 中直接失败。

每批完成后用 `--update` 缩小 ledger（默认拒绝写入新增缺口）：

```bash
.venv/bin/python scripts/check_alignment_ratchet.py
.venv/bin/python scripts/check_alignment_ratchet.py --update
```

### 5.5 文档一致性检查（已有）

`scripts/check_docs_consistency.py` 把本方案和 `docs/upstream-deviations.md`
当作契约来校验：

```bash
.venv/bin/python scripts/check_docs_consistency.py
.venv/bin/python scripts/check_docs_consistency.py -q   # 只输出失败项
```

检查内容：

- 文件级 / 导出级 / 测试级计数与 baseline、gap JSON 一致；
- 分阶段模块数、符号数与 `合计` 行、§7.5 覆盖等式一致；
- 每个有缺失的模块恰好属于一个阶段；仅迁移模块与文档列表一致；
- 偏差文档中的事实（常量值、端口、错误文案、类名）仍能在代码中找到；
- 已修正的过时结论没有重新出现；
- Markdown 表格列数一致。

退出码非 0 即表示文档已与仓库脱节，需要同一批更新文档或代码。

---

## 6. 单文件工作流

以 `core/report.ts` 为例：

1. **读契约**
   - 上游源码：`packages/core/src/report.ts`
   - 上游测试：`packages/core/tests/unit-test/report.test.ts`
   - Python 现状：`midscene/core/report.py`、`midscene/core/dump/report_dump_compactor.py`、`midscene/core/report_cli.py`

2. **生成清单**

   ```bash
   .venv/bin/python scripts/check_upstream_method_alignment.py \
     --module core/report.ts --json /tmp/report-methods.json
   ```

   逐项确认哪些是 `missing`、哪些是 `moved`、哪些是 `type/schema`。

3. **实现**
   - 在映射模块补齐导出；`moved` 的符号在映射模块 re-export。
   - Python 命名使用 snake_case；类名保持 PascalCase。
   - 错误信息、默认值、返回结构按上游实现，不做“看起来差不多”的简化。

4. **解锁测试**
   - 打开 `tests/test_report.py` 中对应 skip，改为真实断言。
   - 若确实无法在 Python 表达，改成带 `reason` 的 skip，并在 ledger 记录类别。

5. **本地验收**

   ```bash
   .venv/bin/python -m compileall -q midscene tests
   .venv/bin/ruff check midscene tests --select F,E9
   .venv/bin/python -m pytest tests/test_report.py -q --no-cov -p no:cacheprovider
   .venv/bin/python -m pytest tests/ -q --no-cov -p no:cacheprovider
   .venv/bin/python scripts/check_upstream_api_alignment.py --quiet
   .venv/bin/python scripts/check_alignment_ratchet.py
   ```

6. **更新 ledger**：`status: done`，填写批次、测试文件、skip 原因统计。

7. **提交**：一个批次一个 commit，消息格式：

   ```
   Align <module list> with upstream (batch P1)
   ```

---

## 7. 分阶段路线图

### Phase 0：工具与基座（不改功能）

- [x] `check_upstream_method_alignment.py`
- [x] `upstream_alignment_ledger.json` 初稿（由现有 gap JSON 生成）
- [x] `check_alignment_ratchet.py`
- [x] 在 `docs/upstream-alignment-plan.md` 固定 DoD 与批次
- [x] 选 `core/report.ts` 做样板，只验证工具链，不要求一次补完

验收：工具能对 1 个模块输出函数/类/方法缺口，ledger 可生成，ratchet 可运行。

### Phase 1：报表链路（已完成）

7 个报表模块、24 个符号已全部对齐，`tests/test_report.py`（17）和
`tests/test_report_markdown.py`（10）的 27 个 skip 已全部转为真实断言。

已补齐：`ReportMergingTool`、`TestRunReportAssembler`、`collectDedupedExecutions`、
`dedupeExecutionsKeepLatest`、`isDirectoryModeReport`、`removeReportArtifact`、
`splitReportHtmlByExecution`、`exportReportArtifact`、`executionToMarkdown`、
`readReportArtifactManifestAsync`、`ExecutionDump` / `GroupedActionDump` /
`ReportActionDump`、`ReportImageStore` / `ScreenshotStore` /
`resolveScreenshotSource`、`createInlineImageResolver` /
`restoreImageReferences` / `restoreReportImageReferences`、
`createReportCliCommands`。

### Phase 2：共享基础设施（已完成）

`html-utils`、`img/transform`、`img/box-select`、`report-artifact`、
`env/constants`、`env/parse-model-config`、`env/types`、`logger`、
`extractor/util`、`shared/utils` 已全部对齐，剩余 0 个模块 / 0 个符号。
`env/types.py` 已重导出原 `moved` 的共享类型符号。

### Phase 3：core 主体（已完成）

`core` 包的 57 个剩余模块、90 个符号已全部对齐，API 级缺失为 0：device action
space、agent utils/options/tasks/UI observer、service-caller、模型适配器与注册表、
planning/grounding、recorder-generation、report-session、Service/errors 等均已补齐。

### Phase 4：CLI / Web / 平台（已完成）

28 个模块 / 68 个符号已全部对齐，导出级缺失清零：

| 上游文件 | 原缺失 | 现状 |
|---|---|---|
| `cli/printer.ts` | 9 | 已补齐 |
| `cli/execution-summary.ts` | 8 | 已补齐 |
| `computer/device.ts` | 7 | 已补齐 |
| `computer/utils.ts` | 4 | 已补齐 |
| `computer/agent.ts` | 3 | 已补齐 |
| `web-integration/bridge-mode/common.ts` | 6 | 已补齐 |
| `web-integration/common/viewport.ts` | 4 | 已补齐 |
| `web-integration/web-page.ts` | 3 | 已补齐 |
| `android/adb-shell.ts` | 3 | 已补齐 |
| `android/adb.ts` / `agent.ts` / `ui-tree.ts` / `utils.ts` | 各 1 | 已补齐 |
| `cli/args.ts` | 2 | 已补齐 |
| `cli/cli-utils.ts` / `openai/login.ts` / `yaml-batch-executor.ts` | 各 1 | 已补齐 |
| `computer/rdp/backend-client.ts` | 1 | 已补齐 |
| `harmony/agent.ts` | 1 | 已补齐 |
| `ios/agent.ts` / `device.ts` / `utils.ts` | 各 1 | 已补齐 |
| `web-integration/bridge-mode/browser.ts` / `page-browser-side.ts` / `playwright/page.ts` | 各 1 | 已补齐 |
| `web-integration/web-element.ts` | 2 | 已补齐 |
| `webdriver/utils/base-url.ts` / `utils/request.ts` | 各 1 | 已补齐 |
| **合计** | **28 个模块 / 68 个符号** | **剩余 0** |

平台相关文件允许保留 `exempt`，但必须在 ledger 写明“Python 运行时无对应机制”的具体原因（例如 macOS Accessibility 权限、WDA helper 子进程）。

---

### 7.5 全覆盖分派

四个阶段的模块数与符号数必须满足：

```
模块：0 (P1) + 0 (P2) + 0 (P3) + 0 (P4) = 0
符号：0 (P1) + 0 (P2) + 0 (P3) + 0 (P4) = 0
```

分派规则（无重叠、无遗漏）：

| 阶段 | 范围 |
|---|---|
| P1 | 已完成的 7 个报表模块，当前剩余 0 |
| P2 | 已完成的共享基础设施，当前剩余 0 |
| P3 | 已完成的 `core` 包，当前剩余 0 |
| P4 | 已完成的其余包（android / cli / computer / harmony / ios / web-integration / webdriver），当前剩余 0 |

ledger 必须做到**一行一个上游模块**，且每行有且只有一个 `batch`；ratchet 校验
两个总数不变。新增上游模块时，先补 ledger 再动代码。

另有 0 个模块只有迁移差异、没有 missing（原有 16 个迁移符号已全部在映射模块 re-export，DoD #3 完成）。
re-export 覆盖 `AgentReportManager`、`TestReportImages`、`mapJevBox`、
`multimodalPromptToMessages`、`REPORT_ARTIFACT_SCRIPT_TYPE` 等；`debug`、`TaskExecutionError`、
`AIResponseParseError`、`parseLegacyYamlScript`、`reportFileToMarkdown` 等也已就位。

### 7.6 方法级对齐（已完成）

方法级审计结果：`0` 个模块 / `0` 个函数 / `0` 个类 / `0` 个方法缺失。
剩余 `30` 项函数“签名差异”是 Python 侧的等价适配，已登记在
`scripts/method_alignment_allowlist.json`，分两类：

| 类别 | 含义 | 典型例子 |
|---|---|---|
| `options-object` | 上游接收单个 options/input 对象，Python 展开为显式关键字参数 | `prepareModelImage`、`standardPlan`、`defineNode` |
| `context-object` | 上游分开传多个上下文参数，Python 聚合为 adapter/context 对象 | `resolveLocate`、`resolvePlanning`、`verifyLocator` |

检查脚本会把这类条目计入 `allowlisted_signature_mismatch` 并输出原因，
不计入 `signature_mismatch`；`--strict` 只对未登记的缺口失败。新增条目必须写明
具体技术原因，禁止用它掩盖真实的参数缺失。

---

## 8. 并行执行约定

- 每批 3–5 个文件，按模块依赖关系分组。
- 并行 agent 只能操作各自分配的文件；禁止修改共享 `tests/conftest.py`、`tests/core_helpers.py`。
- 生产代码有改动时，必须在批次汇报里逐条列出文件、原因、对应上游行号。
- 每批固定产出：方法级清单、代码改动、测试结果、ledger 更新。
- 全量测试与 ratchet 由主流程串行执行，避免并发结果互相干扰。

---

## 9. 验收命令（每批必跑）

```bash
cd /home/zhangming/gitspace/midscene-python

.venv/bin/python -m compileall -q midscene tests
.venv/bin/ruff check midscene tests --select F,E9
.venv/bin/python -m pytest tests/ -q --no-cov -p no:cacheprovider

.venv/bin/python scripts/check_upstream_alignment.py
.venv/bin/python scripts/check_upstream_api_alignment.py --json scripts/upstream_api_gaps.json
.venv/bin/python scripts/check_upstream_method_alignment.py --json scripts/upstream_method_gaps.json
.venv/bin/python scripts/check_alignment_ratchet.py
.venv/bin/python scripts/check_docs_consistency.py
```

通过标准：

- `compileall` 无输出；
- `ruff` 全过；
- pytest 0 failed；
- 文件级 0 merged / 0 pending；
- API 级 `missing` 与 `method_missing` 不高于上一批；
- 目标测试文件 skip 不增加。

---

## 10. 风险与处理

| 风险 | 处理 |
|---|---|
| 名称级审计误报（同名不同实现） | 以方法级清单 + 上游测试为准；ledger 允许人工标注 `ok-by-equivalent` |
| TS 解析精度不足 | 先轻量解析；不足时在 `scripts/ts-api/` 本地安装 typescript，不进入发布依赖 |
| `moved` 符号路径不兼容 | 在映射模块 re-export；ledger 记录 `moved` 去向 |
| 类型/schema 无法运行时等价 | 用 TypedDict/dataclass/dict 近似，不列入 missing |
| 平台专属能力缺失 | 标记 `exempt`，写明缺少的运行时机制；对应测试 skip 带同一原因 |
| 补一个模块导致其他测试回归 | 每批串行全量测试；ratchet 阻断 skip 增加 |
| 一次性批次过大 | 每批 3–5 个文件；优先高扇入模块 |

---

## 11. 进度模板

每批完成后在 ledger 中维护：

```json
{
  "batch": "P1",
  "started_at": "2026-11-22",
  "modules": 7,
  "missing_before": 24,
  "missing_after": 0,
  "method_missing_before": 63,
  "method_missing_after": 0,
  "skipped_before": 27,
  "skipped_after": 0,
  "notes": "ReportMergingTool / TestRunReportAssembler / executionToMarkdown 已补齐"
}
```

批次状态：`planned` → `in-progress` → `verified` → `done`。

---

## 12. 建议的启动顺序

1. 完成 Phase 0 工具链。
2. 用 `core/report.ts` 跑通单文件闭环（样板）。
3. 按 Phase 1 → 2 → 3 → 4 推进；每批结束更新 ledger 并跑 ratchet。
4. 全部 `done` 后，再把 `check_upstream_api_alignment.py` 升级为默认 CI 门禁，文件级检查退化为辅助。

---

## 13. 当前剩余事项

文件级、导出级与方法级缺口均已清零，`ledger` 全量 `done`。以下事项不改变
四层对齐结论，但属于后续收尾：

| 优先级 | 事项 | 说明 |
|---|---|---|
| 高 | 重新审计 skip | 已从 208 降至 149；报告合并、目录模式、`BatchRunner` 汇总、解析取消、导出转换、`beforeAll` 重试、配置优先级、`client_id` 校验、`rectMatchesCacheFeature` 抛错、`TaskBuilder` 快路径/`promptDisplay`/planning feedback/registry、zod 描述符能力（含 defaults/transforms/refinements）与 web/CDP agent tools 等 59 个用例已改为真实断言。剩余可行动项：测试夹具与平台/Node 专属项 |
| 高 | 实现可移植能力缺口 | 已完成 `ReportGenerator` 目录模式、`BatchRunner` 汇总接口、解析/重试取消、`beforeAll` 重试、全局配置覆盖、动作快路径延迟、`TaskBuilder` planning feedback/registry、zod 描述符能力与 web/CDP agent tools |
| 中 | 统一 `ReportSession` | 已用 `ReportArtifactStore` 支撑目录模式；单一会话宿主仍待收口 |
| 中 | iOS / HarmonyOS 真机验收 | 需 WDA 与 DevEco 真机环境 |
| 低 | CI 门禁 | 串行运行文件级、API 级、方法级、ratchet、文档一致性五个检查器 |

平台/Node 专属且已登记为不移植的项不再列为待办，见
`docs/upstream-deviations.md` §1 与 §2.3。
