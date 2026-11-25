# 04 · 输出契约（output contract）

## 1. 运行期 `/app/output` 清单

| 文件 | 必需 | 内容 | 由谁写 |
|---|---|---|---|
| **`slide_plan.json`** | 是 | **一等中间产物，最先落盘**：`version / case_id / planner / language / constraints / spine / slides / qa_prep / uncertainty`，形状见 `schemas/slide_plan.schema.json` | `talkplan.py`（**建页之前**） |
| `deck.pptx` | 是 | 可编辑演示文件：标题/正文占位符 + 讲稿备注页 + 备用页（母版按题面模板或内置 spec 合成） | `talkplan.py` + `minipptx.py` |
| `outline.json` | 是 | 页级大纲：主张 / 强度 / 要点 / 图表 / 秒数 / 证据引用 / 备用页 / `dropped_atoms[]` | `talkplan.py` |
| `speaker-notes.md` | 是 | 人读讲稿：每页主张 / 指哪里 / 秒数 / 锚点 | `talkplan.py` |
| `result.json` | 是 | 结构化结果：契约动态回显 + `outputs[]` + `sources`/`uncertainty`/`change_log` + `audit` + `slide_plan` + `empty_artifact_guard` | `talkplan.py` |
| `verification.json` | 用 `verify.py` 时 | 只读重算 16 项，每项 **expected vs actual** | `verify.py` |
| `benchmark.json` | 用 `--benchmark` 时 | baseline vs skill 六项指标 + `copy_probe` + `method` 原文 | `talkplan.py` |
| `gain-cases.json` | 用 `verify.py --gain-cases` 时 | 带标签案例的判定与证据字段 | `verify.py` |

二进制（`deck.pptx`）**只在运行期产生**，不进本包。

## 2. `output_contract` 动态透传（字段名不预设）

入口按 `output_contract → contract → output_spec → expected_outputs → outputs → deliverables` 找契约声明
（dict 取键名；list 取每项 `name/key/field/path`），然后**逐键三级解析**：

1. **命中键名提示** → 写真值（提示表：deck/outline/evidence/render/qa/notes/time/audience/uncertainty/status）。
2. **未命中提示但能按产物名匹配** → 写该产物的 `path + exists + bytes + sha256`。
3. **真算不出** → 值写 `null`，并在 `result.json.contract_unresolved_fields[]` 给
   `{key, declared, why, available_artifacts, how_to_fix}`。**不猜值、不静默留 null。**

## 3. `result.json` 字段与来源

| 字段 | 来源 |
|---|---|
| `case_id` / `<契约键>` | 原样取自输入 `/input/case.json`（键名若未知，走上面三级解析） |
| `status` / `status_reason` | `success` / `partial`（材料缺口、页数不足、锚点回查失败）/ `unsupported`（无可定位内容） |
| `sources[]` | 实际读取的材料（文件名、字节、可读性、降级原因） |
| `outputs[]` | 磁盘实测：`path` + `bytes` + `sha256`，`verify` 逐条重算 |
| `audit` | **重读材料**后的逐字回查统计（locator / 数字 / 图注） |
| `slide_plan` | `{file, schema, written_before_deck:true, slides, schema_ok, schema_errors[]}` |
| `empty_artifact_guard` | 0 页 / 0 slide / 回查失败 的判定与原因 |
| `uncertainty[]` | 材料缺口、缺图、页数不足、自检 warn（每条含 why 与 handling） |
| `change_log[]` | 每步做了什么、为什么 |

## 4. 退出码

`talkplan.py`：0 全绿 ｜ 2 诚实 partial ｜ 1 FAIL。
`verify.py`：0 全部通过 ｜ 2 仅 warn ｜ 1 有 FAIL。
`talkplan.py --benchmark` 额外写 `benchmark.json`（含 `copy_probe`）。
