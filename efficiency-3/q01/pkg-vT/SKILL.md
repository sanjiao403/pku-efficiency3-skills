---
name: graphical-abstract-svg
description: >
  Turn source material into a submission-grade single-page graphical abstract
  (研究问题 → 方法 → 核心结果 → 结论) as a *layered, text-editable SVG* plus real
  PNG and vector PDF, with element-level provenance (every entity, arrow, value
  and legend entry traced to a source locator + verbatim quote), a
  colour-blind-safe and greyscale-safe encoding, and machine-checked export
  assertions. Use when asked to draw / generate / edit / re-layout a graphical
  abstract, 图形摘要, 科研示意图, 机制图, 通路图, 流程图, 技术路线图, 装置图,
  figure for a paper or grant, or to turn study notes / experimental records /
  a CSV of results into a publication figure. Triggers: graphical abstract,
  graphical abstract 生成, 科研绘图, 画图, 示意图, 机制图, 通路图, schematic,
  mechanism figure, pathway diagram, workflow figure, figure SVG, editable
  figure, 可编辑源文件, export figure as PNG/PDF.
  Do NOT use for data analysis, statistics, manuscript prose, slide decks, or
  for editing a raster screenshot (this skill needs editable vector sources).
---

# graphical-abstract-svg · 证据绑定 + 确定性版式的图形摘要

一句话：**材料 → 结构化图稿中间表示（figure IR）→ 确定性排版 → SVG + PNG + PDF + result.json**，
每个图面元素都能回到材料里的 locator 与逐字引文，且同一 IR 重跑得到同一张图。

## 0 · 先看这四条（决定分数）

1. **判分读 `/app/output/result.json`**，但它引用的 `figure.svg / .png / .pdf` 必须真实存在且能打开。
2. **先有文件**：`python3 /skills/weekly-skill/scripts/ga_build.py init` 会立刻写出合法 `result.json`
   （`status=partial`）。之后无论哪一步崩了，磁盘上都有可判的交付。
3. **内容由你写，排版由脚本算**：实体、关系、数值、claim 措辞是你的判断；坐标、字号、溢出、
   导出、断言是脚本的活。不要手写坐标。
4. **四要素缺一就是 partial**：problem / method / results / conclusion 四个面板 + 图例 + 单位 +
   来源带 + 图注。

## 1 · 路径事实（运行期）

| 路径 | 是什么 |
|-|-|
| `/input/case.json` | 输入。`output_contract` 在这里面（脚本会自动识别并按原键回填）|
| `/input/task.md` | 题面/工单（workorder）：图型、尺寸、必须上图的实体或数值、导出格式 |
| `/input/**` | 材料：md/txt/csv/json/pdf/docx/图片。**读实际内容**，不按文件名猜 |
| `/app/work` | 可写中间区：`figure-ir.json`（你写）、`quote-index.json`、`render.log` |
| `/app/output` | **唯一交付区**：`figure.svg`、`figure.png`、`figure.pdf`、`result.json`、`figure-ir.json`、`run.log` |
| `/skills/weekly-skill/` | 本包安装位置（`scripts/ templates/ references/ examples/` 都在下面）|

所有脚本只依赖 Python 标准库；可选依赖（cairosvg / PyMuPDF / Pillow / matplotlib /
rsvg-convert / LibreOffice / Chromium）有就用、没有就降级，并**把实际用的引擎写进 result.json**。

## 2 · 五条命令（照抄即可）

```bash
SK=/skills/weekly-skill
python3 $SK/scripts/ga_build.py init        # ① 扫 /input：quote 索引 + 草稿 IR + 最小 result.json
python3 $SK/scripts/ga_build.py show        # ② 打印带 locator 的材料原文（引文从这里逐字复制）
#   ③ 你写 /app/work/figure-ir.json（结构见第 3 节；草稿已给骨架，改它比从零写快）
python3 $SK/scripts/ga_build.py check       # ④ 机械校验：引文命中/覆盖/图例一致/溢出预算
python3 $SK/scripts/ga_build.py build       # ⑤ 渲染 SVG+PNG+PDF 并 finalize result.json
python3 $SK/scripts/ga_build.py selfcheck   # ⑥ 只复检已产出的文件，不重渲染
```

规则：**必须先 `show` 读材料再写 IR**；`build` 不会替你判断科学内容。缺 IR 时 `build` 会用
`init` 的草稿出图并写 `status=partial` + `degradations`（草稿未经判断，不冒充 `ok`）。
退出码恒 0；所有路径可用 `--input/--work/--output` 覆盖（本地自测用）。

## 3 · figure IR（你唯一要写的文件）

`/app/work/figure-ir.json`，最小可用骨架（`templates/figure-ir.template.json` 有全字段版）：

```json
{
  "case_id": "<照抄 /input/case.json>",
  "title": "一句话结论式标题",
  "subtitle": "一句补充（方法+量级）",
  "mode": "create",
  "panels": [
    {"order":1,"role":"problem","title":"Gap","claim":"一句话问题",
     "kind":"bullets","items":[{"id":"p1i1","text":"要点","source":{"id":"S1","locator":"p.1#para2","quote":"逐字原文"}}]},
    {"order":2,"role":"method","title":"Route","kind":"chain",
     "items":[{"id":"p2i1","text":"步骤1","source":{"id":"S1","locator":"p.2#para1","quote":"…"}},
              {"id":"p2i2","text":"步骤2","source":{"id":"S1","locator":"p.2#para1","quote":"…"}}]},
    {"order":3,"role":"results","title":"Gain","kind":"relations","relations":["R1","R2"]},
    {"order":4,"role":"conclusion","title":"Impact","claim":"一句话结论",
     "kind":"bullets","items":[{"id":"p4i1","text":"意义","source":{...}}]}
  ],
  "entities":[{"id":"E1","label":"逐字实体名","type":"protein","compartment":"membrane","italic":false,
               "source":{"id":"S1","locator":"p.1#para3","quote":"…"}}],
  "relations":[{"id":"R1","from":"E1","to":"E2","type":"activation","label":"seeding","source":{...}}],
  "charts":[{"id":"CH1","kind":"bar","title":"…","x_label":"组","y_label":"信号","unit":"a.u.",
             "series":[{"name":"WT","points":[{"x":"WT","y":1.0,"raw":"1.00","err":0.1,"source":{...}}]}]}],
  "claims":[{"id":"K1","label":"检测时间","value":20,"unit":"min",
             "compare":{"label":"常规","value":60},"source":{"id":"S1","locator":"p.4#para1","quote":"…"}}],
  "legend":[{"key":"c1","label":"补充图例项","channel":"fill","color":"#0072B2","pattern":"none"}],
  "notes":{"units":"nM","conditions":"37 °C, pH 7.4","scale_bar":"10 µm",
           "caption":"图注","figure_no":"Figure 1"},
  "sources":[{"id":"S1","path":"materials/paper.md","locator":"p.1#para2","quote":"…"}],
  "mode_edit_ops": [],
  "must_include": []
}
```

| 字段 | 作用 | 硬规则 |
|-|-|-|
| `panels[].role` | 四要素顺序 | 必须覆盖 problem/method/results/conclusion；多于 4 段按 order 取前 4 |
| `panels[].kind` | `bullets` / `chain` / `relations` / `chart` | `relations` 需 `relations[]` 非空；`chart` 需 `chart` 指向 `charts[].id` |
| `entities[].type` | protein/gene/cell/tissue/material/device/sample/readout… | 基因用 `italic:true`，蛋白正体 |
| `relations[].type` | activation/inhibition/binding/modification/transport/flow/block | **决定箭头形状**，图例由脚本按图面自动派生 |
| `claims[]` | 需要上图的关键数值 | 图上的每个数字都要有一条 claim 或 chart point，并带 locator |
| `sources[]` | 材料清单 | `quote` 必须在材料中**逐字命中**（`check` 会验） |

`content_map`、`legend`、`compliance_checks`、`exceptions` 由脚本生成；你写的 `legend` 只用于
补充脚本派生不到的分类。

## 4 · 一旦要编辑现有图（source-preserving edit）

输入里给了 `*.svg` 或工单说“修改/在原图上改”时：

```bash
python3 $SK/scripts/ga_build.py edit --ops /app/work/edit-ops.json
```

`edit-ops.json`：`[{"id":"<原 SVG 元素 id>","op":"set_text|set_fill|move|set_size","value":…}]`。
脚本**只改被点名的元素**，其余字节原样保留，并输出 `edit_record`（原图 sha256、改了几处、每处前后值）。
原图元素 id 找不到就跳过并记入 `exceptions`，不会重排整张图。

## 5 · 异常与降级（每条都要落到 result.json）

| 情况 | 脚本行为 | 写进哪 |
|-|-|-|
| `/input/case.json` 缺失/坏 JSON | 仍出最小交付，`status=input_error` | `errors`、`status_reason` |
| 材料为空/无可抽取内容 | 用 `title` 占位，四面板留空，`status=insufficient_evidence` | `uncertainty`、`gaps` |
| 没有 IR | 用 `init` 草稿出图，`status=partial` | `degradations`（`ir_origin=draft`）|
| 字体缺失 | 顺序探测 fontconfig→常见路径→PyMuPDF 内置；记录替换与影响 | `compliance_checks`、`exceptions` |
| 画布溢出 | 修复阶梯：删低优先条目→压行距→降字号（不低于 `canvas.min_font_px`）→截断加省略号 | `repairs`（逐步记录）|
| PNG 导出失败 | 引擎链 cairosvg→PyMuPDF→Pillow→matplotlib→CLI→纯标准库，逐级降级；每次重开 PNG 解 IHDR 验真 | `export_artifact.png.attempts`、`exceptions` |
| PDF 导出失败 | 同上，末级纯标准库矢量 PDF（文字仍可选中） | `export_artifact.pdf.engine` |
| 全流程超时（>120 s） | 已落盘的 SVG 有效，PNG/PDF 缺失项写 `exceptions` | `runtime.timed_out` |

## 6 · 一个合格交付长什么样（示例数据，非正式案例结果）

- 四列等宽面板 + 段间箭头；每列顶部 `① PROBLEM … ④ CONCLUSION` 徽标；
- 结果列是**带类型的通路**（激活实线箭头 / 抑制 T 形），图例按图面实际关系类型自动生成；
- 关键数值带（长度编码，刻度线=对照值，行尾 locator）；
- 页脚：图例 → 单位/条件/比例尺 → 来源带 → 图注（`Figure 1. …`）；
- `figure.svg` 里 `<text>` 可选中可改字；`figure.png` 2400×1350@300 dpi；`figure.pdf` 矢量单页。

## 7 · 预算与自查

- 执行预算：**64 次模型请求 / 900 s / 单次 16384 tokens**。脚本单次运行目标 **≤ 20 s**（三案例
  合计 ≤ 60 s），硬超时 120 s 后只 finalize 已落盘产物。
- 提交前自查：`python3 scripts/ga_build.py selfcheck` → 末行 `SELFCHECK_OK`；
  `check` 末行 `CHECK_OK`。非 0 或末行不是 OK，就回去补，别交空壳。
- 三次重复运行应得同一 `figure.svg`（`sha256` 一致），脚本会把该断言写进 `compliance_checks`。

## 8 · 包里还有什么

| 文件 | 用途 |
|-|-|
| `METHOD.md` | 方法、设计取舍、与基础 Agent 的对照协议 |
| `RUBRIC-MAP.md` | 5 个评分维度 → 包内文件/证据 的逐条映射 |
| `references/figure-design-rules.md` | 图形摘要的四要素、关系语法、色彩/灰度、字体与版式规则 |
| `references/result-contract.md` | `result.json` 字段表 + 状态语义 + 断言清单 |
| `references/pitfalls.md` | 六类典型失败（实体混淆/方向反/图例错配/溢出/字体替换/导出失败）的检测点与处置 |
| `templates/figure-ir.template.json` | IR 全字段模板 |
| `templates/result.template.json` | result.json 骨架 |
| `examples/` | 3 个**示例**案例（文本型/数据型/编辑型）+ 示例输出，均标「示例」 |
| `RUBRIC-MAP.md` | 评分维度 → 包内证据 的逐条映射（评审用）|
| `tests/selftest.py` | 真跑自检；`tests/selftest-report.json` 为最近一次报告 |
| `tests/ab_harness.py` | skill 臂 vs 消融臂对照；`tests/ab-report.json` |


