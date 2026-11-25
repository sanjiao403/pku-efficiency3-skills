---
name: academic-talk-structurer
description: 学术汇报内容组织（Slides q07，极简可跑版）：一条命令把论文/研究材料组织成可上台、证据可追溯的学术汇报——读 /input/case.json 与材料，按听众与目标选叙事弧，给每页一句可辩护主张并绑定材料行号锚点，按页数与时长预算分配每页秒数，产出 outline.json + 可编辑 deck.pptx（母版按文本 spec 合成）+ result.json（动态回显 case 契约）。适用于"学术汇报/组会/答辩/评审内容组织""把论文做成 PPT 大纲与讲稿"类任务。
---

# 学术汇报内容组织（极简版）

**主命令（端到端，纯标准库）：**

```bash
python3 scripts/talkplan.py --case /input/case.json --out /app/output
python3 scripts/verify.py   --case /input/case.json --out /app/output   # 自校验
```

可选：`--input /input`（材料目录，默认 case.json 所在目录）、`--work /app/work`。

## 包内指南（先读这些）

`README.md`（用法与产物次序）· `references/01-audience-profiles.md`（听众画像）· `references/02-narrative-patterns.md`（页型与叙事）·
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
| `outline.json` | 页级计划：主张 / 强度 / 要点 / 图表 / 秒数 / 证据锚点（`material`+`line`）/ 备用页 / 取舍留痕 `dropped_atoms[]` |
| `deck.pptx` | 可编辑演示文件：标题+正文占位符、讲稿备注页、备用页（纯标准库 OOXML 写入器，无需 python-pptx） |
| `speaker-notes.md` | 人读讲稿：每页主张 / 指哪里 / 秒数 / 锚点 |
| `result.json` | 契约动态回显 + `outputs[]`（path/bytes/sha256）+ status/uncertainty/change_log |

## 组织规则（内建，可改；完整口径见本节）

1. **听众先行**：由 `audience/goal/presentation_type/task` 命中 5 类弧（答辩/组会/评审/教学/立项），
   弧决定结论**强度上限**（答辩·评审=strong，组会·教学·立项=moderate）与问答焦点。
2. **一页一个主张**：标题即断言；要点 ≤4 条，单条中文 ≤42 / 西文 ≤96 字。
3. **主张必有锚点**：每页 `evidence_refs` 带 `material + line + numbers`；`verify.py` **重读材料**核对行号。
4. **数字可定位**：页面数字必须能在材料中找到，否则 verify 判 FAIL（不换算、不新增）。
5. **强度 ≤ 证据**：`strong` 需统计量（p/CI/n/±）；原文有 hedge 措辞不得升为 strong。
6. **时长预算**：`∑页秒数 = (duration−qa)×60`（±5%）；正文+备用页尽量等于 `slide_count`。
7. **材料不够就认**：可定位内容不足时**不注水**——差额写进 `deck_shortfall` 与 `uncertainty`，`status=partial`。
8. **图表引用**：只用材料图注里的编号；材料没图就不画图。
9. **讲稿与页面互补**：备注写"讲什么/指哪里/强度"，不与要点重复。

## 降级（如实记录）

材料全部不可读 → `status=unsupported`，不编页；扫描件 PDF 无文本层 → 记 `skipped_no_text_layer`；
缺模板 → 用包内内置 `DEFAULT_SPEC` 合成母版，字体/色值取自 spec；
页数不足 → `deck_shortfall` + `partial`；任何异常都不写假数据。

## 运行期逐字回查 + 空产物守卫

每次运行**重读材料**回查，结论写进 `result.json.audit`：`locators_verified`（行号可解析且原文片段逐字命中）、
`number_traceability_rate`、`caption_consistency_rate`。**空产物守卫**：0 页 / 0 pptx 页 / 锚点回查失败 ⇒
`status=partial` + 原因（`result.json.empty_artifact_guard`），绝不把空产物报成 success。

## 路径解析（与 cwd 无关）

材料/模板 spec/生成资产的相对路径按 **case.json 所在目录 → cwd → `/input` → `/app`** 解析，命中即记
`resolved_from` 并写 `<work>/resolved-paths.json`；内部一律使用绝对路径；`scripts/` 与内置 `DEFAULT_SPEC` 以 `__file__` 定位，不依赖 cwd 与模板文件。
输入发现**只用相对判据**，绝不按绝对路径里的 `outputs`/`stage` 目录名过滤。

## 包内文件（引用即存在，逐条由 `_build/refcheck.py` 复核）

`README.md` · `references/01-audience-profiles.md` · `references/02-narrative-patterns.md` ·
`references/03-evidence-rules.md` · `references/04-output-contract.md` · `references/05-qa-and-timing.md` ·
`schemas/slide_plan.schema.json` · `scripts/talkplan.py` · `scripts/minipptx.py` · `scripts/verify.py` ·
`examples/README.md` · `examples/case.example.json` · `examples/paper.example.md`

运行期才产生的文件（不随包发布，写到 `--out`）：`slide_plan.json` · `deck.pptx` · `outline.json` ·
`speaker-notes.md` · `result.json`；`verify.py` 另写 `verification.json`；`--benchmark` 另写 `benchmark.json`。

## 同题 A/B 基准

`--benchmark` 会用同一份材料跑一遍**写死在代码里的 baseline 配方**（一页一句、备注复述页面、无锚点/无预算），
把 备注复述率 / 图注一致率 / 已核实 locator 数 / 数字可定位率 / 页数是否等于 `slide_count` / 耗时 落进
`<out>/benchmark.json`（最近一次：备注复述 100%→0%，locator 0→14，页数 5≠8→8=8）；方法与口径见本文件上一节。

## 自校验（`verify.py`，退出码 0/2/1）

契约键非静默 null · `outputs[]` 文件真实存在且 sha256 一致 · 页数 · 时长预算 ±5% · 每页有主张/强度/锚点 ·
**锚点行号在真实材料中可解析** · **页面数字都能在材料中找到** · 图表编号来自材料图注 · 讲稿不与页面重复 ·
status 与缺口自洽 · 产物无本机绝对路径。

## 最小示例（**示例（非正式答案）**）

`examples/case.example.json`（6 分钟组会、8 页、动态契约字段）+ `examples/case.example.json`
（示意 `result.json` 形状）。字段形态与真实运行一致，数值仅作示例。

# 叙事与时长预算规则（精简版）

规则的人读口径；脚本内建同一条逻辑（`talkplan.py` 的 ARCS / W / bud / strength）。

## 边界与预算

预算 **64 模型请求 / 900 秒 / 单次 16384 tokens**；本 Skill 不需要额外模型请求，端到端 1–3 秒。
不读文献找空白、不做科研绘图、不写论文正文、不生成新数据；材料没写的就留空并登记。
