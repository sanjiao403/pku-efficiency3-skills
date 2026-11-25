---
name: ppt-template-fit
description: >
  学术 PPT 模板与格式适配：读真实 pptx 模板的母版/版式/占位符/主题字体与配色，把论文或研究材料
  组织成页级主张 + 证据定位（§/p. + 逐字引文），按版式与字号阶梯生成**可继续编辑**的 pptx
  （母版-版式-占位符继承链保留、中英文分别落 latin/ea 字体、图表等比放置、页码用可编辑域），
  再做溢出/字号下限/图片比例/批量一致性/引文回源检查与 PDF·PNG 真渲染回测，产出 result.json
  （页级证据映射 + 诚实 status/uncertainty + 变更与产物哈希）。Use when asked to 按模板做学术汇报 PPT、
  套用 pptx 模板、把论文转成 slides、修版式溢出/字体替换/图表变形、批量统一多页格式、导出 PDF/PNG 预览。
---

# ppt-template-fit · 论文 → 模板化的可编辑学术汇报

> **一句话**：先把模板"读成结构化事实"，再把论文"读成可定位单元"，两者做**页级映射**，
> 然后生成、复核、真渲染回测 —— 每一步都留下可被别人复跑的证据。
> **不做什么**：不生成新的科学事实（页内断言一律是源材料逐字摘录 + 定位）；不把字号压到不可读来硬塞；
> 不伪造 PDF/PNG；技术检查通过 ≠ 学术质量通过。

## 0. 30 秒上手（平台契约路径）

```bash
# 平台给的输入 /input/case.json；产物必须落 /app/output
python scripts/run.py --input /input/case.json --out /app/output --backend auto
# 只看链路（不渲染，最快）：加 --backend none —— **注意：无渲染件时 status 必为 partial**，
# 交付前必须再用 --backend auto 渲一次（题面要求真实 PDF/PNG 预览）
# agent 已改好文案：--plan /app/work/plan.json
# 需要对照基线（"直接粘正文"的做法）：--baseline
# 再自检：python tests/selftest.py --quick
```

这么做的代价是：所有页内文字都来自材料，`claim` 的"提炼"由 agent 改写。
**材料与工单严格分离（D14-R5）**：只有 `.md/.markdown/.txt/.pdf/.docx` 可作材料，且
`task.md`/`case.json`/`README.md`/`*.example.json`/`*.template.json`/`template-spec*.json`
等**工单与契约文件名**即使扩展名合法也不当材料（显式指定会以 `SOURCE_IS_TASK_DOC` 拒绝，
确需如此须写 `"allow_work_order_source": true`）。因此 `sources[]` 只会指向真实论文，
页内不会出现 case.json / 模板 spec / 工单文本（selftest D1–D3 是这条不变量的负向对照）。

`/app/output` 产物（每个都带 sha256，写进 `result.json.artifacts`）：

| 文件 | 内容 |
|---|---|
| `result.json` | 主结果：`status` / 页级 `slides[]` / `evidence[]` / `sources` / `uncertainty` / `change_log` / `output_contract_echo` |
| `<case_id>.pptx` | **可编辑**演示文件（继承模板母版/版式/占位符，可继续在 PowerPoint/WPS 里改） |
| `preview/deck.pdf` + `preview/png/slide-NN.png` | 真实渲染件（后端 PowerPoint COM / LibreOffice；都不可用时给 `preview.html` 并记 partial） |
| `slide_plan.json` | 页级结构（agent 可直接改这个文件再重跑 `--plan`） |
| `evidence_map.json` | 每条证据：`page + locator + quote + verified` |
| `template_map.json` | 模板事实：母版/版式/占位符几何/主题字体/主题色/字体可用性 |
| `source_map.json` | 材料事实：块/章节/图表 + 定位 + 抽取限制 |
| `build_log.json` | 逐页构建记录：版式/字号阶梯/`fontScale`/合成占位符/页脚页码/备注字数/构建期 warnings |
| `deck_report.md` | 人读报告（机械生成的核对部分） |
| `baseline_comparison.json` | 仅在 `--baseline` 时产出：同输入下"直接粘正文"基线与本 Skill 的对照指标 |

## 1. 适用条件与不适用

**适用**：源材料是 PDF / Markdown / docx（有文本层或结构化标记）；模板是真实 pptx（有母版+版式）。
**部分适用**（会自动降级并记账）：案例不提供模板（**由 `templates/template-spec.json` 在运行期合成
母版——文本 spec，非二进制 pptx**；判据字段 `results.template.origin=="spec-synth(template-spec.json:…)"`、
`results.template.degradations[]`、`template_map.json.degradations[]`）；
源材料是扫描 PDF（无文本层，`uncertainty` 写明需 OCR）；模板版式缺 body/picture 占位符（合成文本框并记录）；
起始稿是旧 deck 需改造（`starting_deck`，重建内容页但沿用其母版/版式/主题）。
**不适用**：需要科学判断的"结论是否成立"、需要外部数据的补全、需要真实演讲视频/动效的场合。

## 2. 输入契约（`case.json`）

最小可用：`{"case_id": "...", "source": {"path": "paper.md"}, "template": "template.pptx"}`。
全部字段与默认值见 `templates/case.template.json`；关键项：

| 字段 | 含义 | 缺省行为 |
|---|---|---|
| `case_id` | 结果标识，原样回写 | `UNKNOWN` |
| `source.path/kind` | 论文/材料路径（相对 case 目录或绝对） | 目录里唯一的**材料类**文件（`.md/.markdown/.txt/.pdf/.docx`；`task.md`/`case.json`/`*.example.json`/`*.template.json`/`template-spec*.json` 等工单与契约一律**不当材料**） |
| `template` | pptx 模板路径（或**文本模板规格** `*.json`） | 按 `templates/template-spec.json` 在运行期合成母版（包内**零二进制**，记 uncertainty） |
| `starting_deck` | 需改造的旧 deck | 无（全新生成） |
| `language` | `zh` / `en`：决定断句、字体对、每行字数 | `zh` |
| `audience` / `minutes` | 听众与时长 → 页数与讲稿密度 | 不写元信息 |
| `slide_count{min,max,target}` | 页数约束（硬约束，超了按分值裁剪并记账） | 8–12 |
| `figure_specs[]` | 数据表 → 图（csv + kind + x/y/series），图表适配的上游 | 不生成图，用材料内已有图 |
| `fonts{title,body,caption}` | 覆盖中英文字体对（`latin`/`ea`） | 沿用模板主题字体，缺失则按 fallback 链 |
| `footer` | 页脚文案（会按占位符宽度裁到一行） | 截断的论文标题 |
| `required_sections[]` | 必须覆盖的章节名（子串匹配） | 无 |
| `output_contract` | 结果必须回显的字段名 | 无（回显为空） |

## 3. 输出契约（`result.json`）

顶层固定字段：`case_id / task / status / status_reason / summary / generated_at / results / slides /
evidence / sources / uncertainty / change_log / artifacts / capability_boundary / reproduce /
narrative / output_contract_echo / contract_unresolved_fields`；`output_contract` 里声明的每个字段
都会被回显（给不出值的写 `null` 并进 `contract_unresolved_fields`）。字段级说明见
`templates/result.template.json`；人读版见 `deck_report.md`。

`status` 判定（**只有全绿才 success**）：pptx 可打开、渲染成功、无 high 级问题、引文可回源 100%、
定位覆盖 100%、**计划校验 `results.plan.validation.ok=true`（含页数落在 `slide_count` 上下限内）**；
否则 `partial` 且 `status_reason` 写**具体**原因（哪个文件缺、哪一项不达标）。

## 4. 处理流程（`scripts/`）

| 步骤 | 脚本 | 关键动作 | 证据落点 |
|---|---|---|---|
| 1 模板解析 | `template_probe.py` | 母版/版式/占位符 idx·type·几何（缺失回溯母版）、**中文占位符名兜底**（标题 1/内容占位符 3…）、主题字体(major/minor 的 latin·ea·cs + Hans)、12 色主题色、系统字体可用性 | `template_map.json` |
| 2 材料抽取 | `source_extract.py` | PDF(PyMuPDF)/md/docx → 块+章节+图表；caption 正则 `Figure/Fig./Table/图/表`；PDF 抽位图或按 caption 上方区域裁矢量图 | `source_map.json` |
| 3 数据出图 | `source_extract.make_figure` | csv → line/bar/scatter/forest/km/box（等比原图，中文不出豆腐块） | `work/figures/*.png` |
| 4 页级计划 | `plan_deck.py` | 页骨架、页数约束裁剪、主张=逐字最强断言、bullet=逐字摘录+定位+截断记账、字号阶梯预算、`--validate` 反例拦截 | `slide_plan.json` |
| 5 套版生成 | `build_pptx.py` | `add_slide(layout)` 继承母版；克隆 footer/slide_number 并写 `a:fld slidenum`；逐 run 写 `a:latin`/`a:ea`；代码阶梯降级（降字号→移入备注，**不破 14pt 下限**）；图放进 picture 占位符/两栏右栏/正文下半部（等比+留白） | `<case_id>.pptx` + `build_log.json` |
| 6 版式复核 | `fit_check.py` | 溢出（按含 fontScale 的实际字号算）、字号下限、图片宽高比偏差、标题几何一致性、页脚/页码覆盖、引文逐字回源、继承链（页面占位符无 `a:xfrm` = 真继承） | `results.fit` |
| 7 渲染回测 | `render_preview.py` | PowerPoint COM / LibreOffice / none；PDF 逐页文本与包围盒、字体表、图片数；与 pptx 文本做**逐页覆盖率**；字体名对齐表判"是否被替换"；**导出件一致性 `export_consistency()`**：逐页比对 pptx↔PDF↔PNG（PNG 张数/像素宽高比/非空白像素占比、逐页图片数、逐页备注字符与"备注串页/重复"、字体替换）；`preview/` | `results.render.consistency` + `preview/` |
| 8 汇总 | `audit.py` | 组装 result.json / evidence_map.json / deck_report.md，回显契约字段，写 honesty 与 sha256 | `result.json` |
| 编排 | `run.py` | 8 步串起来 + 渲染回测修正（溢出则把末条移入备注，最多 `--iterations` 轮）+ 基线对照 | `pipeline` 日志 |

## 5. 异常与降级（每条都有对应实现与自检）

| 情况 | 处置 | 自检项 |
|---|---|---|
| 无模板 / 模板打不开 | 由 `templates/template-spec.json` **运行期合成母版**（文本 spec，包内**零二进制**）；写 `uncertainty[item=模板降级（BUNDLED_TEMPLATE_MISSING）]` | `results.template.origin == "spec-synth(template-spec.json:…)"`、`results.template.degradations[]`；selftest B2 + `tests/selftest.py::无模板案例` |
| 源材料缺失 | 立刻写 `partial` 的 result.json 并说原因，不造内容 | selftest B1 |
| PDF 无文本层 | 记 `extraction_limits`，结果里说明需 OCR | 材料抽取段 |
| 版式缺 body / picture 占位符 | 合成文本框/合成区域，记录几何与理由 | `results.build.placeholders_synthesized` |
| 文本框会溢出 | 阶梯降字号（≥下限）→ 余量入备注；构建与复核都记账 | `results.fit.metrics.overflow_boxes` |
| 字体缺失 | 按 fallback 链渲染并把替换写进 `render_report`；不静默回退 | `font_substitutions` |
| 图表源文件失效 | 该页退化为纯文字页并记 `warnings` | `results.build.warnings` |
| 导出后端全失败 | 保留 pptx + `preview.html` + `preview.layout.md` + `partial`，**不伪造 PDF/PNG**；`results.render.consistency` 缺省并在 uncertainty 写明"无法做导出件逐页比对" | selftest B3 |
| 导出件与 pptx 不一致 | 逐页判 high/medium 并进 `results.render.consistency.issues`：PNG 缺页/张数不符、整页空白、画幅偏差 >0.5%、逐页图片丢失、备注字符与自述不符/重复/串页、字体被替换 | `results.metrics.export_*`、`results.render.consistency` |
| 页数超上限 | 预算里预留封面/目录/结论/收尾（结论页此前漏算导致 max+1），按章节分值裁剪，被裁内容与理由进 `dropped_content` | `results.plan.dropped_content` |
| 计划校验出 high 项 | **不再静默**：findings 全文进 `results.plan.validation`，状态强制 `partial` + 具体 `status_reason`（`PLAN_VALIDATION_HIGH`） | `results.plan.validation`、`pipeline.guards[]` |
| 案例模板规格 JSON 非法 | 回退包内 `templates/template-spec.json` 合成，写 `TEMPLATE_SPEC_INVALID` 与 uncertainty（此前会直接崩掉、连 partial 都没有） | `results.template.degradations[]`、`pipeline.errors[]` |
| 案例模板打不开 | 回退包内文本规格合成（`TEMPLATE_UNREADABLE`）；合成模板与规格结构事实不一致记 `TEMPLATE_SPEC_CHECK_FAILED` 并 `partial` | `results.template.degradations[]` |
| 起始稿是旧 deck | `starting_deck` 模式下沿用其母版/版式/主题重建内容页 | `build_log.mode=adapt` |

## 6. 自检

```bash
python tests/selftest.py            # 4 夹具全链 + 降级 + 反例 + 材料隔离（约 192 秒，含真渲染）
python tests/selftest.py --quick    # 1 夹具 + 降级 + 反例 + 材料隔离（约 120 秒，无渲染）
python tests/contam_test.py         # D30：材料污染哨兵 + 五项篡改负向对照（独立可复跑，约 40 秒）
python tests/contam_test.py --no-render   # 同上，跳过需要 PNG 的 T5
```
结果写 `tests/selftest-report.json`（逐项 pass/fail + 耗时 + 真实读数）。
自检覆盖：继承链、页数约束（含 `slide_count.max` 硬约束与"校验器判 fail 却写 success"的假绿）、
溢出、字号下限、图片比例、引文回源、定位覆盖、PDF 页数与丢字、
契约字段回显、产物 sha256、**中文母版/版式/占位符名识别**、**模板缺正文版式的降级路径**、
**模板规格非法/模板损坏的回退**、**材料与工单隔离（哨兵 0 泄漏 + `sources[]` 白名单）**，
以及"破坏 plan 必须被拦"和**五项产物篡改必须逐项变红**的反例（`tests/contam_test.py`）。

## 7. 预算与运行纪律

- 平台预算：**64 次模型请求 / 900 秒 / 单次响应 16384 tokens（含 reasoning）**。
  本 Skill 的脚本链路**不调用任何模型**，单案例端到端 6–25 秒（PowerPoint 渲染占大头），
  留给 agent 改文案与补叙述的请求余量充足。
- 资源：≤50 个 UTF-8 文本文件、单文件 ≤500KB、合计 ≤2MB，无符号链接（见 README「资源清单」）。
- 依赖：Python 3 + `python-pptx`（必需）、`Pillow`（图片比例）、`PyMuPDF`（PDF 与渲染回测）、
  `matplotlib`（数据出图，可选）；渲染后端 `PowerPoint`(Windows COM) 或 `LibreOffice`(soffice) 任选其一，
  都没有则自动降级为 HTML 预览。
- 每次运行都落盘中间产物，**先保住 partial 交付，再逐步改进**；不覆盖输入目录，只写 `--out` 与 `--work`。
