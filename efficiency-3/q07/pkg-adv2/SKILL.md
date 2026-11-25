---
name: academic-talk-structurer
description: 学术汇报内容组织（Slides q07，极简可跑版 v1.4-adv1）：一条命令把论文/研究材料组织成可上台、证据可追溯的学术汇报——读 /input/case.json 与材料，按听众与目标选叙事弧，给每页一句可辩护主张并绑定材料行号锚点，按页数与时长预算分配每页秒数（总和=讲述时长），产出 slide_plan.json（按包内 schema 实校）+ 可编辑 deck.pptx（母版按文本 spec 合成）+ outline.json + 讲稿 + result.json（动态回显 case 契约 + 问答页指针）。适用于"学术汇报/组会/答辩/评审内容组织""把论文做成 PPT 大纲与讲稿"类任务。
---

# 学术汇报内容组织（极简版）

**主命令（端到端，纯标准库）：**

```bash
python3 scripts/talkplan.py --case /input/case.json --out /app/output
python3 scripts/verify.py   --case /input/case.json --out /app/output   # 自校验（只读重算）
```

可选：`--input /input`（材料目录，默认 case.json 所在目录）、`--work /app/work`；
`--benchmark` 追加 A/B 基准；`--strict-exit` 让 partial/unsupported 变成退出码 2/1（默认只要有产物就是 0）；
`python3 scripts/verify.py --refcheck` 不需要跑案例即可核对"包内每个引用都指向真实文件"。

## 包内指南（先读这些）

`README.md`（用法与产物次序）· `METHOD.md`（方法与判据）· `references/01-audience-profiles.md`（听众画像）· `references/02-narrative-patterns.md`（页型与叙事）·
`references/03-evidence-rules.md`（证据三纪律与强度阶梯）· `references/04-output-contract.md`（产物清单 / 动态契约透传 / 退出码）·
`references/05-qa-and-timing.md`（时长预算与问答准备）· `schemas/slide_plan.schema.json`（一等中间产物 schema）。
**次序**：读材料 → 计划 → **先落 `slide_plan.json` 并自检** → 再合成 `deck.pptx`。

## 何时触发

用户给了一份研究材料（论文/摘要/实验记录/报告）要做**汇报/组会/答辩/评审幻灯片**，或指定了听众、时长、
页数、模板中任意几项，需要判断"哪些内容上页、按什么顺序、每页讲多久"。
**不适用**：论文精读/文献综述、科研绘图、学术写作成稿（本 Skill 不生产新的科学内容）。

## 输入（`/input/case.json`）

`case_id · task · audience · goal · presentation_type · language · duration_min · qa_min · slide_count ·
template_spec · materials[] · output_contract{}`。
材料支持 `.md .txt .json .csv .docx .pdf`（文本层）。**读实际文件，不按文件名猜内容。**
`output_contract`（或 `contract` / `expected_outputs`）声明的键**逐个赋值**：能映射的写真值，能按产物名
匹配的写成文件条目（`path/bytes/sha256`），都算不出的写 `null` 并在 `contract_unresolved_fields[]` 说明——绝不猜值。

## 输出（`/app/output`）

| 文件 | 内容 |
|---|---|
| `slide_plan.json` | **一等中间产物，最先落盘**：`version/case_id/planner/language/constraints/spine/slides/qa_prep/uncertainty`；按包内 `schemas/slide_plan.schema.json` **实际校验**（JSON-Schema 子集），违规写进 `result.json.slide_plan.schema_errors` 并转 `status=partial` |
| `outline.json` | 页级计划：主张 / 强度 / 要点 / 图表 / 秒数 / 证据锚点（`material`+`line`）/ 备用页 / 取舍留痕 `dropped_atoms[]` |
| `deck.pptx` | 可编辑演示文件：标题+正文占位符、讲稿备注页、备用页（纯标准库 OOXML 写入器，无需 python-pptx） |
| `preview.pdf` | **真实渲染件**：整份 deck 的 PDF 预览（有 LibreOffice 时用其转换＝真 Office 渲染；否则由 `scripts/minipdf.py` 按同一份页计划几何渲染），页面尺寸 16:9、文字层可再抽取 |
| `render-record.json` | 渲染记录：引擎（libreoffice / minipdf-geometric）、`real_office_render`、页数、`MediaBox`、字体与是否嵌入、字节数与 sha256、保真度说明与降级尝试 |
| `speaker-notes.md` | 人读讲稿：每页主张 / 指哪里 / 秒数 / 锚点 / 过渡 |
| `result.json` | 契约动态回显 + `outputs[]`（path/bytes/sha256）+ status/uncertainty/change_log + `audience_model` + `slide_plan` + `evidence_floor` |

## 组织规则（内建，可改；完整口径见本节）

1. **听众先行**：由 `audience/goal/presentation_type/task` 命中 5 类弧（答辩/组会/评审/教学/立项），
   弧决定结论**强度上限**（答辩·评审=strong，组会·教学·立项=moderate）与问答焦点。
2. **一页一个主张**：标题即断言；要点条数按页型上限（`MAXB`：标题 2、方法 4、结果/局限 3…），
   单条中文 ≤42 / 西文 ≤96 字。
3. **主张必有锚点**：每页 `evidence_refs` 带 `material + line + numbers`，且**每页锚点数不少于页型下限**
   （`EVID`：结果页 2，其余 1；达不到就记 `evidence_floor`，不注水）；`verify.py` **重读材料**核对行号与**引文逐字**。
4. **数字可定位**：页面数字必须能在材料中找到，否则 verify 判 FAIL（不换算、不新增）。
5. **强度 ≤ 证据**：`strong` 需统计量（p/CI/n/±）；原文有 hedge 措辞不得升为 strong。
6. **时长预算**：`∑页秒数 = (duration−qa)×60` **精确相等**（标题页占固定 3%，其余按页型权重分配，
   整数残差折回；越界判定 ±5%）。
7. **材料不够就认**：可定位内容不足时**不注水**——差额写进 `deck_shortfall` 与 `uncertainty`，`status=partial`。
8. **图表引用**：只用材料图注里的编号；材料没图就不画图。
9. **讲稿与页面互补**：备注四行式（讲什么/指哪里/强度/过渡），不与要点重复。
10. **问答有页可翻**：`slide_plan.qa_prep` 的每个追问带 `backup_slide_no` 指向真实页与
    `answer_strength`（不超过被引页强度）；没有页可指时留 `null` 并标 `backup_linked=false`。
11. **只有科研材料能当证据**：证据只从 `case.json` 声明的 `materials[]` 里取；未声明时按扩展名白名单
    自动发现，并且**绝不**把工单当数据——`case.json`、`task.md`、`template/spec/example/schema` 声明件、
    以及本流水线自己的运行产物（`resolved-paths.json`/`outline.json`/`speaker-notes.md`/`deck.pptx`…）
    一律拒绝并逐条记进 `result.json.source_policy`（`inputs_refused_as_non_evidence`）。

## 降级（如实记录）

材料全部不可读 → `status=unsupported`，不编页；扫描件 PDF 无文本层 → 记 `skipped_no_text_layer`；
缺模板 → 用包内内置 `DEFAULT_SPEC` 合成母版，字体/色值取自 spec；
页数不足 → `deck_shortfall` + `partial`；任何异常都不写假数据。
**渲染降级链**：LibreOffice 转换（真 Office 渲染）→ 内置 `minipdf` 几何渲染；当前容器无 LibreOffice 时
`render-record.json` 记 `real_office_render=false` 与 `attempts`，并在 `uncertainty` 写明"字体未嵌入、由阅读器
提供 CID 字体"，同时 verify 仍按字节重测页数/尺寸/文字层。`--no-render` 可关闭渲染（此时 `preview` 为 null 且
`status` 会因空产物守卫转 `partial`，不会假装成功）。

## 运行期逐字回查 + 空产物守卫

每次运行**重读材料**回查，结论写进 `result.json.audit`：`locators_verified`（行号可解析且原文片段逐字命中）、
`number_traceability_rate`、`caption_consistency_rate`。**空产物守卫**：0 页 / 0 pptx 页 / 锚点回查失败 ⇒
`status=partial` + 原因（`result.json.empty_artifact_guard`），绝不把空产物报成 success。

## 路径解析（与 cwd 无关）

材料与模板 spec 的相对路径按 **case.json 所在目录 → cwd → `/input` → `/app`** 解析，命中即记
`resolved_from` 并写 `<work>/resolved-paths.json`；内部一律使用绝对路径；`scripts/` 与内置 `DEFAULT_SPEC` 以 `__file__` 定位，不依赖 cwd 与模板文件。
输入发现**只用相对判据**，绝不按绝对路径里的 `outputs`/`stage` 目录名过滤。

## 包内文件（引用即存在，**每次运行由 `scripts/verify.py` 的 refcheck 复核**）

`README.md` · `METHOD.md` · `references/01-audience-profiles.md` · `references/02-narrative-patterns.md` ·
`references/03-evidence-rules.md` · `references/04-output-contract.md` · `references/05-qa-and-timing.md` ·
`schemas/slide_plan.schema.json` · `scripts/talkplan.py` · `scripts/minipptx.py` · `scripts/minipdf.py` ·
`scripts/verify.py` ·
`examples/README.md` · `examples/case.example.json` · `examples/paper.example.md` · `examples/result.example.json`

`refcheck` 扫描包内 `.md/.json/.py` 里所有 `scripts|references|schemas|examples/…` 路径与 `*.py` 名字字面量
（含**代码里的**引用），任何一个不指向包内真实文件即判 FAIL；只想核引用不跑案例时用
`python3 scripts/verify.py --refcheck`。

运行期才产生的文件（不随包发布，写到 `--out`）：`slide_plan.json` · `deck.pptx` · `preview.pdf` ·
`render-record.json` · `outline.json` · `speaker-notes.md` · `result.json`；`verify.py` 另写 `verification.json`；
`--benchmark` 另写 `benchmark.json`（`--gain-cases --out-dir <dir>` 另写 `gain-cases.json`）；
`resolved-paths.json` 只写在 `--work` 里。**包内零二进制**——`.pptx` 与 `.pdf` 都只在运行期生成。

## 同题 A/B 基准

`--benchmark` 会用同一份材料跑一遍**写死在代码里的 baseline 配方**（一页一句、备注复述页面、无锚点/无预算），
把 备注复述率 / 图注一致率 / 已核实 locator 数 / 数字可定位率 / 页数是否等于 `slide_count` / 耗时 落进
`<out>/benchmark.json`，并附 `copy_probe`（把整包拷到含 `stage/outputs` 的路径、在包外 cwd 用零附加参数重跑）。
最近一次（`Get-Date` 实测见 `questions/q07/NOTES.md`）：备注复述 100%→0%，locator 0→14，页数 5≠8→8=8，
`copy_probe ok`。

## 自校验（`verify.py`，退出码 0/2/1）

只读重算，**准确项数见 `verification.json.summary.total`**（成功路径 41 项，`partial`/`unsupported` 时多一项条件检查）。
覆盖：
契约键非静默 null · `outputs[]` 文件真实存在且 sha256 一致 · 页数 · 时长预算 ±5% · 每页有主张/强度/锚点 ·
**锚点行号在真实材料中可解析** · **页型锚点下限达标或已诚实登记** · **`slide_plan.json` 按包内 schema 独立重算** ·
**result.json 的 schema 结论与重算一致** · **校验器不是橡皮图章（故意改坏的计划必须被拒）** ·
**`slide_plan` 引文在真实材料上逐字命中** · 问答页指针指向真实页且回答强度不越级 · **页面数字都能在材料中找到** ·
图表编号来自材料图注 · 讲稿不与页面重复 · status 与缺口自洽 · **`outline` 与 `slide_plan` 的每页锚点一致** ·
**引用的每个来源都在证据语料里、且没有任何页面把工单/模板/示例/自身产物当证据**（附负向对照）·
**没有任何页面页内文字是 case 描述字段的逐字复制**（工单不是页面内容）·
**`preview.pdf` 是真 PDF 且页数/页面尺寸/文字层/字体事实由字节重测**（`render-record.json` 的字节数与 sha256
必须与磁盘一致，字体嵌入声明必须与字节里的 `/FontFile` 一致）· 包内引用全部存在 · 产物无本机绝对路径。

## 最小示例（**示例（非正式答案）**）

输入：`examples/case.example.json`（6 分钟组会、8 页、动态契约字段）+ `examples/paper.example.md`（合成材料）；
示意输出：`examples/result.example.json`（`result.json` 的形状摘录，**示意输出，非正式案例结果**）。
字段形态与真实运行一致，数值仅作示例。

# 叙事与时长预算规则（精简版）

规则的人读口径；脚本内建同一条逻辑（`talkplan.py` 的 ARCS / W / bud / strength）。

## 边界与预算

预算 **64 模型请求 / 900 秒 / 单次 16384 tokens**；本 Skill 不需要额外模型请求，端到端 1–3 秒。
不读文献找空白、不做科研绘图、不写论文正文、不生成新数据；材料没写的就留空并登记。
