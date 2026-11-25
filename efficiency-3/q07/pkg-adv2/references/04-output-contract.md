# 04 · 输出契约（output contract）

## 1. 运行期 `/app/output` 清单

| 文件 | 必需 | 内容 | 由谁写 |
|---|---|---|---|
| **`slide_plan.json`** | 是 | **一等中间产物，最先落盘**：`version / case_id / planner / language / constraints / spine / slides / qa_prep / uncertainty`，形状见 `schemas/slide_plan.schema.json` | `talkplan.py`（**建页之前**） |
| `deck.pptx` | 是 | 可编辑演示文件：标题/正文占位符 + 讲稿备注页 + 备用页（母版按题面模板或内置 spec 合成） | `talkplan.py` + `minipptx.py` |
| `preview.pdf` | 是 | **渲染件**：整份 deck 的 PDF 预览（LibreOffice 可用则真 Office 渲染，否则 `minipdf` 几何渲染；16:9，含可抽取文字层） | `talkplan.py` + `minipdf.py` |
| `render-record.json` | 是 | 渲染记录：引擎 / `real_office_render` / 页数 / `MediaBox` / 字体与嵌入 / 字节数 / sha256 / 保真度 / 降级 `attempts` | `talkplan.py` |
| `outline.json` | 是 | 页级大纲：主张 / 强度 / 要点 / 图表 / 秒数 / 证据引用 / 备用页 / `dropped_atoms[]` | `talkplan.py` |
| `speaker-notes.md` | 是 | 人读讲稿：每页主张 / 指哪里 / 秒数 / 锚点 | `talkplan.py` |
| `result.json` | 是 | 结构化结果：契约动态回显 + `outputs[]` + `sources`/`uncertainty`/`change_log` + `audit` + `audience_model` + `slide_plan` + `evidence_floor` + `time_budget_alloc` + `empty_artifact_guard` | `talkplan.py` |
| `verification.json` | 用 `verify.py` 时 | 只读重算（项数见 `summary.total`，成功路径 41 项，`partial`/`unsupported` 多一项条件检查），每项 **expected vs actual** + `refcheck` + `source_policy_probe` + 渲染件字节重测 | `verify.py` |
| `benchmark.json` | 用 `--benchmark` 时 | baseline vs skill 六项指标 + `copy_probe` + `method` 原文 | `talkplan.py` |
| `gain-cases.json` | 用 `verify.py --gain-cases … --out-dir <dir>` 时 | 带标签案例的判定与证据字段 | `verify.py` |
| `resolved-paths.json` | 总是（写在 `--work`，不在 `--out`） | 输入发现过程：候选目录、命中来源 `resolved_from`、实际 cwd | `talkplan.py` |

二进制（`deck.pptx`）**只在运行期产生**，不进本包。

## 2. `output_contract` 动态透传（字段名不预设）

入口按 `output_contract → contract → output_spec → expected_outputs → outputs → deliverables` 找契约声明
（dict 取键名；list 取每项 `name/key/field/path`），然后**逐键三级解析**：

1. **命中键名提示** → 写真值（提示表：deck/outline/evidence/render/qa/notes/time/audience/uncertainty/status）。
2. **未命中提示但能按产物名匹配** → 写该产物的 `path + exists + bytes + sha256`。
3. **真算不出** → 值写 `null`，并在 `result.json.contract_unresolved_fields[]` 给
   `{key, declared, why, available_artifacts, how_to_fix}`。**不猜值、不静默留 null。**
4. **声明的键名与 result.json 自有字段同名**（例如 `output_contract.uncertainty`）→ **不覆盖**自有字段：
   契约映射原样写进 `result.json.contract_echo.<键>`，并在 `contract_key_collisions[]` 说明原因与位置；
   `verify.py` 会检查"每个声明键要么出现在顶层、要么出现在 `contract_echo`"，不再有静默丢失。

## 3. `result.json` 字段与来源

| 字段 | 来源 |
|---|---|
| `case_id` / `<契约键>` | 原样取自输入 `/input/case.json`（键名若未知，走上面三级解析） |
| `status` / `status_reason` | `success` / `partial`（材料缺口、页数不足、锚点回查失败）/ `unsupported`（无可定位内容） |
| `sources[]` | 实际读取的材料（文件名、字节、可读性、降级原因）——**只有科研材料会出现在这里** |
| `source_policy` | 来源纪律的执行记录：`used` / `declared_materials` / `declared_but_missing` / `inputs_refused_as_non_evidence`（逐条 `file/path/declared/reason`）/ `rule` |
| `non_material_inputs[]` | 被拒绝当证据的输入（`case.json`、`task.md`、模板/示例声明件、本流水线自己的运行产物），逐条给理由 |
| `outputs[]` | 磁盘实测：`path` + `bytes` + `sha256`，`verify` 逐条重算（含 `preview.pdf` 与 `render-record.json`） |
| `audit` | **重读材料**后的逐字回查统计（locator / 数字 / 图注） |
| `audience_model` | 与 `outline.json` 同一份：`archetype` / `archetype_reason` / **`strength_cap`** / `qa_minutes` |
| `slide_plan` | `{file, schema, schema_sha256, validator, written_before_deck, slides, schema_ok, schema_errors[], qa_prep, qa_backup_linked}` |
| `evidence_floor` | 每页锚点数 vs 页型下限（`references/02-narrative-patterns.md`），`below_floor[]` 记未达标页 |
| `time_budget_alloc` | 秒数分配实算：`talk_seconds / floor_seconds / title_rule / title_seconds / sum / residual / deviation_pct` |
| `empty_artifact_guard` | 0 页 / 0 slide / 回查失败 / schema 违规 的判定与原因 |
| `uncertainty[]` | 材料缺口、缺图、页数不足、锚点下限未达、自检 warn（每条含 why 与 handling） |
| `change_log[]` | 每步做了什么、为什么 |

## 4. `slide_plan.json` 与它自己的 schema

`slide_plan.json` 是**一等中间产物**，先于 `deck.pptx` 落盘；`talkplan.validate_slide_plan()` 每次运行都用
`schemas/slide_plan.schema.json` 实跑一遍（JSON-Schema 子集：type/required/enum/items/min-max/minimum/minLength；
**不是**完整 JSON-Schema 引擎，`result.json.slide_plan.validator` 里如实写明）。两件事保证它不会变成"名义校验"：

1. `verify.py` 用**同一份 schema 文件**独立重算 `slide_plan.json`，再与 `result.json.slide_plan.schema_ok` 比对；
2. **橡皮图章守卫**：`verify.py` 把计划故意改坏 3 处（非法 `role`、`notes` 清空、删掉必需的 `spine`），
   校验器必须报 ≥3 个错，否则该项 FAIL。

`schema_sha256` 写进 `result.json`，`slides[].role` 的枚举与代码可产出的页型 `ROLE_VOCAB` 做包含校验，
schema 与代码不可能悄悄漂移。

## 5. 退出码

`talkplan.py`：**默认只要写成了产物就返回 0**（含诚实的 `partial`/`unsupported`，因为平台按产物与
`result.json` 判分，非零码会被误读成运行失败）；加 `--strict-exit` 时 `partial→2`、`unsupported→1`；
连 `result.json` 都没写成才会抛异常返回 1。
`verify.py`：0 全部通过 ｜ 2 仅 warn ｜ 1 有 FAIL。
`talkplan.py --benchmark` 额外写 `benchmark.json`（含 `copy_probe`：把整包拷到含 `stage/outputs` 的路径、
在包外 cwd 用零参数入口重跑，并记录 `returncode` 与子进程 `stdout_tail`）。

## 6. 渲染件怎么被复核（不许只写"已导出"）

`preview.pdf` 由 `render_preview()` 生成并**当场按字节测量**，`verify.py` 再独立测一遍：

| 测什么 | 怎么测 | 不一致时 |
|---|---|---|
| 是不是真 PDF | 文件头 `%PDF-` | FAIL |
| 页数 | 解析 `/Type/Page` 对象数，必须等于 plan 的正文+备用页 | FAIL |
| 页面尺寸 | 每个 `/MediaBox` 宽高比必须是 16:9（±2%） | FAIL |
| 文字层可抽取 | 解压内容流，取回 `(...)Tj` 与 `<hex>Tj`，第 1 页主张前 16 字必须能抽到 | FAIL |
| 字体事实 | 从字节里取 `/BaseFont` 与 `/FontFile2/3` | `render-record.json.font_embedded` 与字节不一致即 FAIL |
| 记录自洽 | `render-record.json` 的 `bytes`/`sha256`/页数 与磁盘一致 | FAIL |

字体未嵌入（几何渲染 + 阅读器提供 CID 字体）会在 `result.json.uncertainty` 与 `render-record.json.attempts`
里写明，并说明"有 LibreOffice 时自动改走真 Office 渲染"，不冒充 Office 渲染。
