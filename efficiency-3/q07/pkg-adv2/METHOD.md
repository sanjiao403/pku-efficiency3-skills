# METHOD · academic-talk-structurer（方法、判据与边界）

> 本文只写"怎么算、怎么判、判到什么程度算过"，不复述评分维度。规则的可执行实现在
> `scripts/talkplan.py`（生成）与 `scripts/verify.py`（只读重算），两处同名函数/表一一对应。

## 1. 流水线（单入口，纯标准库）

```
读 case.json → 定输入目录（case-dir → cwd → /input → /app，命中记 resolved_from）
→ 解析材料（只认声明/白名单，见 §4）→ 句子 → 带行号锚点的 atom
→ 听众弧（ARCS）→ 时长与页数预算（bud）→ 页级计划（plan：页型顺序/锚点下限/要点上限/秒数）
→ 先落 slide_plan.json 并按包内 schema 实校（validate_slide_plan）
→ 合成 deck.pptx（minipptx）→ 渲染 preview.pdf（render_preview）→ 写 outline/speaker-notes/result
→ verify.py 只读重算
```

顺序是有意的：**页面先可审、可拒，再谈渲染**；`slide_plan.json` 是人与机器之间的契约面。

## 2. 判据（机器怎么判，而不是"应该怎样"）

| 判据 | 实现 | 不满足时 |
|---|---|---|
| 一页一主张 | `plan()`：每页一个 `claim`，要点只作支撑，重复主张合并 | 重复页被删并把原因写进 `dropped_atoms[]` |
| 主张有锚点 | 每页 `evidence` 带 `material+line+quote`；`EVID` 给页型锚点下限 | 先补锚点；材料不足则保留该页并把差额写进 `evidence_floor.below_floor` + `uncertainty`，**不注水** |
| 引文逐字 | `runtime_recheck()` 与 `verify.py` 各自重读材料，比对所标行的前 40 字（NFKC+空白折叠） | 记 `audit.summary.fail` / verify FAIL |
| 数字可定位 | 页面（主张+要点）里的数字必须出现在材料文本中，不换算不新增 | `number_traceability_rate < 100` / verify FAIL |
| 图注一致 | `figures[]` 必须是材料图注出现过的编号 | verify FAIL；材料无图则引用数必须为 0 |
| 强度不越级 | `strong` 需统计量（p/CI/n/±），有 hedge 不升级，再与弧的 `strength_cap` 取更严者 | 降级并在 `evidence_strength` 体现 |
| 时长恒等 | `∑页秒数 = (duration−qa)×60`：标题页 `max(3, 3%)`、其余按页型权重分配、整数残差折回 | `time_budget_alloc.deviation_pct` 记录；verify 复核 ±5% |
| 页数 | 正文+备用对照 `slide_count`；不足则 `deck_shortfall` + `partial` | 不注水、不复制页 |
| 问答有页 | `qa_prep` 优先取可指页的 atom，`backup_slide_no` 指向真实页，`answer_strength` 取被引页强度 | 无页可指时 `null` + `backup_linked=false`；越级 verify FAIL |
| schema | `jschk()`（JSON-Schema 子集）实跑包内 schema；`verify` 用同一份 schema 独立重算并与 `result.json` 的结论比对 | `schema_errors` + `status=partial`；结论不一致 verify FAIL |
| 空产物 | 0 页 / 0 slide / 锚点回查失败 / schema 违规 ⇒ 不得报 success | `empty_artifact_guard` + `partial`/`unsupported` |
| 引用完整 | `verify.py --refcheck` 扫包内 `.md/.json/.py`（含代码里的 `*.py` 字面量） | 任一悬空即 FAIL |

## 3. 渲染（导出件怎么被核对）

`render_preview()` 两级：① 有 LibreOffice → `soffice --convert-to pdf`（`real_office_render=true`）；
② 否则 `scripts/minipdf.py` 几何渲染（16:9，标题/主张/要点/页脚，WinAnsi 与 CJK 分 run 排字，文字层可再抽取）。
`render-record.json` 记引擎、页数、`MediaBox`、字体与是否嵌入、字节数、sha256、保真度与降级 `attempts`。
`verify.py` **打开 PDF 的字节**重测：页数 = 正文+备用、`MediaBox` 比例 16:9（±2%）、第 1 页主张可抽取、
`render-record` 的 bytes/sha256/页数与磁盘一致、字体嵌入声明与字节里的 `/FontFile` 一致。字体未嵌入时
在 `uncertainty` 明确写"由阅读器提供 CID 字体"，不冒充 Office 渲染。

## 4. 来源纪律（哪些文件可以当证据）

只有 `case.json` 的 `materials[]` 声明件（缺声明时按扩展名白名单）能成为证据。**拒绝**：`case.json` 自身、
`task.md`、`template/spec/schema/manifest/example` 形状的声明件、`_example=true` 或带任务定义键的 json、
以及本流水线自己的运行产物（`--out`/`--work` 下的任何文件）。每条拒绝都进
`result.source_policy.inputs_refused_as_non_evidence` 与 `non_material_inputs[]`（附理由）。
**契约/输入标识回显不算污染**：`output_contract` 声明键与 case 的 `task/audience/goal` 会原样出现在
`result.contract_echo`、`result.input_echo`、`audience_model` 与 `slide_plan.constraints.audience`，
位置全部列在 `input_echo.field_paths`；`verify.py` 保证这些字符串不进入页面主张/要点/备注/引文/图注。

## 5. 失败与降级（一律显式记录）

| 情形 | 处置 |
|---|---|
| 材料全不可读 / 无锚点可提 | `status=unsupported`，不建页；`verify` 对"本就没有产物"的项降级为 warn |
| 扫描件 PDF 无文本层 | `skipped_no_text_layer`，进 `sources[].note` |
| 声明模板缺失 | 退到内置 `DEFAULT_SPEC`，`template_spec.degraded=true` + `uncertainty` |
| 页数/材料不足 | `deck_shortfall` + `partial`（宁短不假） |
| 渲染失败 | `render-record.reasons` + guard ⇒ `partial`（绝不在无预览时谎称成功） |
| `output_contract` 键算不出 | 值写 `null` + `contract_unresolved_fields[]` 给 why/如何修 |
| 声明的键名与 result 自有字段同名 | 不覆盖自有字段，映射存 `contract_echo` + `contract_key_collisions[]` |

## 6. 完成标准（本 Skill 自己认的"过"）

`python3 scripts/verify.py --case … --out …` 返回 0（或仅 warn 的 2），且：
`slide_plan.json` 按 schema 通过、每页主张有可回查锚点、引文逐字、数字与图注可定位、
`outline` 与 `slide_plan` 每页锚点一致、`preview.pdf` 字节自洽、无悬空引用、无本机路径。
`--gain-cases builtin` 的四个带标签反例（grounded / 虚构数字 / 造假行号 / 跑题）全部按标签判定。

## 7. 不做什么

不做论文精读、不写论文正文、不做科研绘图、不生成材料里没有的数据或引文；不判断科学结论对错，
只保证"页面上不存在材料里找不到的数字/引文/图表编号"，以及"组织过程可以被别人按同一份材料复算"。
