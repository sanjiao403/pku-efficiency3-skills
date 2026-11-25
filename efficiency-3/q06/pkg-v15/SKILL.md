---
name: paper2deck
description: >
  Turn a research paper or research material into an academic talk deck that
  keeps the evidence: extract the paper's own storyline (problem, gap, approach,
  evidence, limits), plan one claim per slide, attach a page-level locator to
  every page, verify every number/unit/figure number against the source, build
  an editable template-conformant .pptx with computed text fit and speaker notes
  that do not echo the slide, then render a real PDF/PNG preview and report an
  honest audit. Use for 论文转学术 PPT, 学术汇报幻灯片, 组会/答辩 PPT, paper to
  slides, academic deck, conference talk, slide plan, speaker notes, figure
  captions and locators. Not for generating the paper's scientific conclusions,
  for designing new figures, or for prose polishing.
---

# paper2deck · 论文 → 可讲、可核验、可编辑的学术 PPT

> **本 Skill 的主张**：一份学术 PPT 的价值不在于页数，而在于 **每页一句主张 + 一句能回到原文的定位**。
> 所以本包把「证据锁」放在生成之前：页面上的每个数字、每个「Fig. 3」、每句引文，都先回查原文；
> 查不到就**报错或显式降级**，绝不悄悄改写。渲染走真渲染器，拿不到就明写「模型预览」。

## 预算换算（先看这一行，再看步骤）

平台预算 **64 次模型请求 / 900 s / 单次响应 16384 tokens**。本包脚本是**确定性代码，不调用模型**，
模型请求只花在「读输入 + 判读产物 + 决定是否改 `plan.json` + 汇总」四件事上：

| 项 | 用量 | 余量 |
|---|---|---|
| 模型请求 | **约 8–12 次**（Step 1 读输入 1 次；Step 3 判读 1–3 次；Step 6 汇总 1–2 次；其余步骤 0 次） | >5× |
| 墙钟 | **< 3 分钟**（单案例 `run.py` 3–8 s 含真渲染；`audit_deck.py`/`rigor.py` 各 < 1 s） | >5× |
| tokens/响应 | `result.json` 很大（含 `inventory`/`validation`/`rigor_report`）——**按字段读**，别整份贴回上下文 | — |

## 七步执行卡（走一步勾一步）

```
- [ ] Step 1 读 /input/case.json 与 task.md（按真实文件，不按领域标签假设材料）
- [ ] Step 2 立刻跑 run.py：第一秒先落 partial 保底 result.json，随后原地增强、只增不删
- [ ] Step 3 读 result.json 的 status / uncertainty / checks.errors / evidence_map[].locator_verified
- [ ] Step 4 需要改页就改 plan.json（与 case.json 同目录，run.py 自动采用）并重跑 run.py
- [ ] Step 5 audit_deck.py --out <run> --case <case.json> --report-out reports/audit-report.json
- [ ] Step 6 rigor.py --case <case.json> --all --report reports/rigor-report.json
- [ ] Step 7 契约自检：契约键全在、outputs[] 哈希对、status 与闸一致、uncertainty 如实
```

```bash
python3 scripts/run.py                                    # Step 2 的零参数端到端入口
python3 scripts/run.py --plan-only                        # 只出 plan.json，便于 Step 4 人工改页
python3 tests/selftest.py && python3 scripts/gain_check.py  # Step 5–7 前的回归（9/9、4/4）
```

**保底优先于完美**：`run.py` 的骨架 `{"status":"partial","uncertainty":["run started; nothing produced yet"]}`
先落盘，再逐阶段覆盖；即使渲染器缺失、材料是扫描件、进程被杀，`/app/output` 里永远有一份**可复核的诚实产物**。
失败清单与处置见 `references/04-failure-manual-and-budget.md`。

## 什么时候用 / 不用

| 用 | 不用 |
|---|---|
| 已有论文 PDF / LaTeX / Markdown / DOCX，要做组会、答辩、会议 slides | 需要先产出论文结论、精读结论 |
| 有单位/会议模板 `.pptx`，要在模板里排得下、不崩版 | 需要科研绘图本身的美化 |
| 需要每页能回溯到图表章节，被追问时能翻到 | 需要润色论文正文 |

## 30 秒上手

```bash
# 0)（平台）案例输入在 /input/case.json，产物写 /app/output
python3 scripts/run.py                        # 零参数，端到端
python3 scripts/run.py --dry-run              # 8 秒冒烟：只到「证据锁」
python3 scripts/run.py --plan-only            # 出 plan.json 后就停，便于人工改页
python3 scripts/run.py --no-render            # 无 office 环境
python3 scripts/run.py --case X/case.json --out out --work work
```

产物（`/app/output`）：

| 文件 | 作用 |
|---|---|
| `result.json` | 契约回显 + `deck` / `slides` / `evidence_map` / `render` / `notes` / `status` / `uncertainty` / `changes` |
| `deck.pptx` | 可编辑演示文件（真占位符、真表格、真图片、真备注页） |
| `deck.pdf` + `slides/slide-NN.png` | 真渲染预览（引擎写进 `render.json`） |
| `evidence-map.json` | 页级证据映射：页号 / 主张 / 图注编号 / 定位 / 引文是否逐字命中 |
| `plan.json` | 页级大纲（可手改后重跑；存在 `case.json` 同目录则自动采用） |
| `inventory.json` | 从材料抽到的数字/图表/引文/局限清单（证据底账） |
| `validation.json` `audit.json` `layout.json` `render.json` | 四份可复核的机器结论 |
| `speaker-notes.md` / `deck-outline.md` / `run.log` | 讲稿、主线摘要、运行日志 |

## 五步流水线（也是失败时的降级顺序）

```
ingest → inventory → plan → evidence-lock → layout → build → render → audit
```

1. **ingest** `papertext.py`：PDF 走自带文字层解析并记页码；LaTeX 解析 `\section/\label/\ref/\cite`
   与 `figure/table` 环境；MD/DOCX/txt 各自解析。**无文字层 = 明确 `text_layer=false`**，不猜。
2. **inventory** `inventory.py`：建「证据底账」——带单位的数字、Figures/Tables/Eq 编号与图注、
   引用键、局限句、主张句。这是后面所有校验的比较基准。
3. **plan** `outline.py`：按 **叙事骨架** 而不是论文章节顺序出页：
   `title → question → gap → approach → evidence → result → limits → takeaway`。
   推不出的环节（比如原文没写 gap）留**空页 + `evidence_absent_reason`**，并进 `uncertainty`。
4. **evidence-lock** `plan_validate.py`：四道硬闸——图号存在、数字存在、引文逐字可定位、内容页必须有定位。
   另查「把示意图当实验数据」「要点是不是原文长句搬运」。
5. **layout → build** `layout.py` + `deck.py`：按模板占位符与真实字宽算每页能装多少字，
   **不靠缩小字号解决溢出**（下限 11pt，低于就要求拆页/下移备注）。
6. **render → audit** `render.py` + `qa.py`：LibreOffice → PowerPoint COM → 模型预览（明确标注），
   然后 6 道闸（主线/页结构/证据/备注/版式模板/渲染可编辑）出 `audit.json`。

## 输入

`/input/case.json`。只认事实字段，**不认领域标签**：

```json
{
  "case_id": "case-001",
  "task": "把论文做成 12 分钟组会汇报",
  "materials": ["paper.pdf"],          // 或相对 case.json 的目录
  "template": "group-template.pptx",   // 可选，给了就必须在其占位符内排
  "language": "zh", "audience": "…", "duration_min": 12, "slide_limit": 16,
  "output_contract": { "deliverable": "…", "slides": "…", "evidence_map": "…" }
}
```

契约四种形态都能吃：`{字段: 描述}`、JSON Schema、字符串数组、缺失（用默认集合）。
**契约里每个字段都会出现在 `result.json` 顶层**：没有内容给 `""`/`[]`，绝不给 `null`；
读不懂的字段写进 `contract.unresolved`，不猜。详见 `references/03-output-contract.md` 与 `references/02-evidence-rules.md`。

## 输出与状态

- `status`: `success` / `partial` / `unsupported`。
- `uncertainty[]`：材料缺口、无文字层、图未提取到、预览非真渲染、契约未解析字段。
- `changes[]`：每阶段一条，谁改了什么。
- **诚实原则**：示意图永远标 `schematic-placeholder`；模型预览永远标 `preview_mode="model"`；
  没有的数字永远不写（缺就报 `NUMBER_NOT_IN_SOURCE`）。

## 异常与降级（都能交，都不编）

| 情况 | 处置 |
|---|---|
| PDF 无文字层 / 加密 | `text_layer=false`，`status=partial`，提示先用平台 OCR 再跑 |
| 材料只有摘要 | plan 变薄，gap/limits 标 `not-derivable`，`status=partial` |
| 论文没有 figure | 证据页退化为「表/正文段」页，`inventory` 记 `no figure` |
| 图提取不到 | 画**虚线示意图框**，框内放原文图注 + 定位，`rendered=schematic-placeholder` |
| 模板占位符不足 | 用同版式的手动文本框补齐，`audit` 记 `template_layouts_ok` |
| 无 LibreOffice / 无 PowerPoint | 模型预览 + `preview_mode="model"`，`status=partial` |
| 页数超限 | `SLIDE_LIMIT` 警告，砍备份页优先，主结论页不动 |
| 契约字段读不懂 | 顶层给 `""`/`[]` + `contract.unresolved` |

## 预算与资源

平台预算：**64 次模型请求 / 900 s / 单次响应 16384 tokens（含 reasoning）**。
本包脚本是**确定性代码**，不调用模型：单案例在本机实测 **< 20 s**（含 PowerPoint COM 渲染），
`--dry-run` < 8 s。全部 15 个脚本共约 200KB，资源遵守 ≤50 文件 / 500KB 每文件 / 2MB 合计、无符号链接。
依赖：`python-pptx`（必需）、`Pillow`（可选，图提取与模型预览）、`lxml`（python-pptx 依赖）。
导出 PDF 优先 `soffice`，其次 Windows PowerPoint COM，都没有则模型预览。

## 自查

```bash
python3 tests/selftest.py            # 单元 + 端到端，写 tests/selftest-report.json
python3 scripts/qa.py --out /app/output   # 对已产出目录重跑 6 道闸
python3 scripts/benchmark_local.py     # 与「段落贴页」基线做可比对照
```

判据（任一不满足即 `partial`）：证据覆盖率 ≥ 0.8、证据锁 0 error、备注最大重复度 ≤ 0.34、
溢出页 = 0、最小字号 ≥ 11pt、渲染成功。

## 目录

```
SKILL.md  METHOD.md  README.md  RUBRIC.md GAIN.md GAIN-EVIDENCE.md INNOVATION.md PROVENANCE.md ECOSYSTEM.md
references/  01-deck-blueprint.md 页级骨架 · 02-evidence-rules.md 证据锁四闸/逐条重证 · 03-output-contract.md 字段与产物
             04-failure-manual-and-budget.md 失败手册 + 预算换算与七步卡
scripts/     run.py 纸→PPT 主控 · papertext.py 材料读取 · inventory.py 证据底账 · outline.py 页级大纲
             plan_validate.py 证据锁 · layout.py 版式与字号 · deck.py pptx 生成 · notes.py 讲稿
             render.py 真渲染 · qa.py 六道闸 · assets.py 图提取 · contract.py 契约 · selftest.py 自检
             benchmark_local.py 对照 · make_case_pdf.py / template_build.py 造夹具
templates/   slide-plan.template.json  template-spec.example.json
examples/    3 个示例（EN-PDF / LaTeX / ZH-MD+模板），均标 EXAMPLE ONLY
tests/       selftest.py  selftest-report.json  gain_cases.json  gain-report.json  benchmark-report.json
reports/     rigor-report.json  audit-report.json（一等随包产物：逐条证据台账 / A1–A8 审计结论）
RUBRIC.md GAIN.md GAIN-EVIDENCE.md INNOVATION.md PROVENANCE.md ECOSYSTEM.md（一维度一文件：判据表/增益/原始数字/创新/来路/复用）
```

## 不要做

不要把论文段落直接贴成要点；不要引用原文里不存在的图号；不要把示意图当实验数据；
不要把备注写成页面文字的复述；不要为了塞进去把字号缩到 11pt 以下；不要声称没跑过的渲染或分数。
