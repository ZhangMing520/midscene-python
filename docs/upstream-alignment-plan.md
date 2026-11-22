# 上游对齐实施方案（文件级契约 + 验收闭环）

本文档定义如何把 `midscene-python` 与上游 `midscene`（TypeScript）从“文件存在”推进到“文件、符号、方法、行为、测试”逐层对齐，并提供可复跑、可追踪、可防止回退的执行方案。

---

## 1. 现状与口径

当前有两套检查，结论不同，必须分开看：

| 口径 | 工具 | 结果 | 含义 |
|---|---|---|---|
| 文件级 | `scripts/check_upstream_alignment.py` | 425 aligned / 0 merged / 0 pending / 105 exempt | 每个上游 `.ts` 有对应 Python 文件（或已登记豁免） |
| 导出级 | `scripts/check_upstream_api_alignment.py` | 112 个模块有差异 / 240 个运行时导出缺失 / 163 个已迁移 | 映射文件里没有这些顶层运行时导出 |
| 方法级 | `scripts/check_upstream_method_alignment.py` | 132 个模块 / 143 个函数 / 19 个类 / 104 个方法缺失 | 类与函数的方法、参数骨架缺口 |
| 测试级 | `tests/`（205 个 Python 文件，其中 202 个 `test_*.py`） | 1897 passed / 240 skipped | 上游同名测试已同步，skip 表示已知能力缺口 |

**关键结论**：文件级对齐 ≠ 功能完整。`core/report.ts` → `core/report.py` 文件存在，但 `report.py` 只有 `write_report_html`，所以文件级通过、导出级仍有 7 个缺口、测试级有 17 个 skip。

后续所有进度以**导出级 + 测试级**为准，文件级只作为守门条件。

其中 104 个模块存在真正缺失，另外 8 个模块只有迁移差异。分阶段路线图对
**全部 104 个模块 / 240 个缺失符号**做了无遗漏分派（见 §7.5）。

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

### Phase 2：共享基础设施（剩余 3 个模块）

`html-utils`、`img/transform`、`img/box-select`、`report-artifact`、
`env/constants`、`env/parse-model-config`、`logger` 已完成。

| 上游文件 | 缺失 | 备注 |
|---|---|---|
| `shared/extractor/util.ts` | 15 | rect/id/属性/伪元素 |
| `shared/utils.ts` | 9 | assert/isPlainObject/脚本转义 |
| `shared/env/types.ts` | 3 + 121 moved | 决策：是否在 `types.py` re-export |
| **合计** | **3 个模块 / 27 个符号** | |

### Phase 3：core 主体

| 上游文件 | 缺失 |
|---|---|
| `core/device/index.ts` | 21（`defineAction*` 工厂） |
| `core/agent/utils.ts` | 11 |
| `core/agent/ui-utils.ts` | 7 |
| `core/ai-model/service-caller/request-timeout.ts` | 7 |
| `core/ai-model/workflows/recorder-generation/yaml.ts` | 7 |
| `core/ai-model/models/deepseek/locate-protocol.ts` | 4 |
| `core/ai-model/service-caller/utils.ts` | 4 |
| `core/ai-model/workflows/recorder-generation/common.ts` | 4 |
| `core/ai-model/workflows/recorder-generation/playwright.ts` | 4 |
| `core/ai-model/model-adapter/default-planning-protocol.ts` | 3 |
| `core/device/input-strategy.ts` | 3 |
| `core/agent/ui-observer.ts` | 3 |
| `core/ai-model/models/gemini.ts` | 2 |
| `core/ai-model/service-caller/openai/openai-request-context.ts` | 2 |
| `core/ai-model/service-caller/openai/siwc/network.ts` | 2 |
| `core/ai-model/shared/model-locate-result/pixel-mapper.ts` | 2 |
| `core/ai-model/shared/model-locate-result/types.ts` | 2 |
| `core/ai-model/workflows/recorder-generation/markdown.ts` | 2 |
| `core/dump/report-session.ts` | 2 |
| `core/index.ts` | 2 |
| `core/agent/agent-options.ts` / `cache-config` / `screenshot-preparation` / `tasks` | 各 2 |
| 其余 51 个 core 模块 | 各 1（明细见 `scripts/upstream_api_gaps.json`） |
| **合计** | **73 个模块 / 145 个符号** |

### Phase 4：CLI / Web / 平台

| 上游文件 | 缺失 |
|---|---|
| `cli/printer.ts` | 9 |
| `cli/execution-summary.ts` | 8 |
| `computer/device.ts` | 7 |
| `computer/utils.ts` | 4 |
| `computer/agent.ts` | 3 |
| `web-integration/bridge-mode/common.ts` | 6 |
| `web-integration/common/viewport.ts` | 4 |
| `web-integration/web-page.ts` | 3 |
| `android/adb-shell.ts` | 3 |
| `android/adb.ts` / `agent.ts` / `ui-tree.ts` / `utils.ts` | 各 1 |
| `cli/args.ts` | 2 |
| `cli/cli-utils.ts` / `openai/login.ts` / `yaml-batch-executor.ts` | 各 1 |
| `computer/rdp/backend-client.ts` | 1 |
| `harmony/agent.ts` | 1 |
| `ios/agent.ts` / `device.ts` / `utils.ts` | 各 1 |
| `web-integration/bridge-mode/browser.ts` / `page-browser-side.ts` / `playwright/page.ts` | 各 1 |
| `web-integration/web-element.ts` | 2 |
| `webdriver/utils/base-url.ts` / `utils/request.ts` | 各 1 |
| **合计** | **28 个模块 / 68 个符号** |

平台相关文件允许保留 `exempt`，但必须在 ledger 写明“Python 运行时无对应机制”的具体原因（例如 macOS Accessibility 权限、WDA helper 子进程）。

---

### 7.5 全覆盖分派

四个阶段的模块数与符号数必须满足：

```
模块：0 (P1) + 3 (P2) + 73 (P3) + 28 (P4) = 104
符号：0 (P1) + 27 (P2) + 145 (P3) + 68 (P4) = 240
```

分派规则（无重叠、无遗漏）：

| 阶段 | 范围 |
|---|---|
| P1 | 已完成的 7 个报表模块，当前剩余 0 |
| P2 | 所有 `shared` 包缺失模块（`html-utils` 已完成，仅剩 moved） |
| P3 | 其余所有 `core` 包缺失模块 |
| P4 | 其余所有包（android / cli / computer / harmony / ios / web-integration / webdriver） |

ledger 必须做到**一行一个上游模块**，且每行有且只有一个 `batch`；ratchet 校验
`104 / 240` 两个总数不变。新增上游模块时，先补 ledger 再动代码。

另有 8 个模块**只有迁移差异、没有 missing**，不计入 240，但必须按 DoD #3 处理
re-export：

| 模块 | 迁移符号 | 归入 |
|---|---|---|
| `core/agent/agent-report-manager.ts` | `AgentReportManager` | P3 |
| `core/agent/task-cache.ts` | `debug` | P3 |
| `core/dump/html-utils.ts` | `extractImageByIdSync` | P2 |
| `core/dump/image-reference.ts` | `normalizeScreenshotRef` | P3 |
| `core/dump/test-report-images.ts` | `TestReportImages` | P1 |
| `core/report-cli.ts` | `createReportCliCommands` | P1 |
| `shared/env/utils.ts` | `globalConfigManager` / `globalModelConfigManager` / `overrideAIConfig` | P2 |
| `shared/report-artifact.ts` | `REPORT_ARTIFACT_SCRIPT_TYPE` | P2 |

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
