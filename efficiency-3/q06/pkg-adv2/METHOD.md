# METHOD · paper2deck 的方法与取舍

本文说明「论文 → 学术 PPT」这条链路上，本包**为什么这样拆、每步拦什么错**。
结论先行：这套方法的核心不是「生成幻灯片」，而是**在生成之前先建立可回查的证据底账，
在生成之后用同一套判据复查产物**。

## 0. 与「段落切块」的分界线

| 维度 | 常见做法（基线） | 本包做法 |
|---|---|---|
| 页序 | 按论文章节/段落顺序 | 按叙事骨架 `title→question→gap→approach→evidence→result→limits→takeaway` |
| 每页内容 | 段落 → 要点（原文句子） | 一页一主张；要点经 `_compress()` 变成可讲述短语 |
| 图表 | 提到图号但不对账 | 图号/表号**先查存在**，图注逐字保留，并绑定来源定位 |
| 数字 | 直接搬运 | 数值 + 单位一起回查原文（含 `R² = 0.86` 这类指标名单位） |
| 讲稿 | 复制页面文字 | 过渡 / 讲解动作 / 证据位置 / 预设问答 / 时间，且**重复度受门限约束** |
| 版面 | 塞不下就缩字号 | 字宽模型算容量；到 11pt 下限仍溢出就**要求拆页或下移备注** |
| 交付 | 「应该能打开」 | 真渲染 PDF/PNG + 读回校验（形状边界、最小字号、备注存在） |
| 失败 | 静默降级或编造 | 显式 `status=partial` + `uncertainty[]`，缺什么写什么 |

## 1. ingest：先把「材料」变成「带定位的文本」

`papertext.py` 对每种输入给出**同一形状**的段（segment）：`kind / text / source / page /
section / line / para`。定位粒度决定后面所有断言的可核验性。

### 1.1 什么算「材料」（类型白名单 + 角色排除）

素材目录里同时躺着**论文**和**题目本身**：`task.md`（题面与评分表）、`case.json`（输出契约）、
`*.example.json` / `*.template.json`（本包示例与模板）。把它们读进证据底账会得到一种
最坏的结果——幻灯片里出现的是**工单的句子**，对照原文回查却「逐字命中」，
因为命中的是工单本身。所以 ingest 有两道门：

1. **可读类型白名单** `SUPPORTED`：`.pdf .tex .md .txt .docx .bib .json .csv .html`。
2. **角色排除** `non_material_reason()`：按**文件名精确匹配**（`task.md`、`case.json`、
   `readme.md` …）、按**双扩展名**（`*.example.json` / `*.template.json` / `*.sample.*`）、
   以及按**内容形状**（JSON 顶层出现 `case_id` / `output_contract` / `slide_limit` 等键）
   判定「这不是科研来源」。判定是**精确**的，不做前缀匹配，所以论文自带的
   `tables.tex`、`data.json` 不会被误杀。
   被排除的文件**逐条写进** `inventory.json.non_material_excluded` 与 `result.json.uncertainty`，
   不静默丢弃。
3. **运行期目录排除**：`--out` / `--work` 一律不进材料集（否则我们自己的
   `result.json` / `deck.pdf` 会被当成论文来源）。目录名**不按惯例过滤**——
   早期版本把任何叫 `output/` 的目录整棵跳过，结果把真实补充材料删了。

### 1.2 文本层的两个真实陷阱

- **控制字符**：字体没有可用 `ToUnicode` 时，PDF 会给回控制字节（连字 `ﬁ` 变成 `U+0002`，
  `figure` 读成 `\x02gure`）。python-pptx 会把它序列化成字面的 `_x0002_` 印在页面上。
  因此 `Source.add()` 与 `deck.xml_safe()` 各有一道清洗，并且**计数上报**
  （丢一个字节可能意味着缺一个连字，这属于不确定性，不是「干净」）。
- **分节标签**：PDF 没有字体度量，只能按行形状猜标题。于是「图 3 的横轴刻度行」
  「参考文献条目」「以数字开头的句子」都会被误判成小节名——而小节名会印在**每一条定位**里
  （`§478 12 | 17 | 22 …`）。`clean_section()` 因此要求标签**像标题**：长度 ≤ 60 字符、
  ≤ 12 词、不以 4 位年份开头、不以句末标点结尾、非标题词占比受控；
  题干右上角的页码与表格行一律拒绝。

- **PDF**：自带解析器（`pdf_lite.py`）解释内容流，按文本矩阵的 y 变化切行，按 x 间距切列
  （间距 > 14pt 记为列分隔符 `|`，这是后面能重建表格的关键）。没有文字层时明确
  `text_layer=false`，交给平台的 OCR 工具，**不猜**。
- **LaTeX**：解析 `\section/\subsection`、`figure/table/equation` 环境、`\label`、`\ref`、
  `\cite` 与 `.bib`。`\ref{fig:x}` 在展平前被替换成人类标签（`Figure 1`），因此「图号」
  在后续校验里是**解析出来的事实**而不是字符串猜测；`\begin{tabular}` 的行被还原为
  带 `|` 的 `table-row` 段，`$^\circ$C` 这类公式被规整成 `°C`。
- **Markdown / DOCX / HTML / TXT**：标题层级、列表、表格行分别成段；DOCX 的表格逐行入段。
- **顺序**：LaTeX 的表格行、`\title{}`、`abstract` 都在**正确位置**发射（早期实现把表格行提前，
  导致 deck 标题抓到了表格内容——这类顺序错误会让「证据」错位，所以按文档位置发射是硬要求）。

### 1.3 分词器必须永远前进（v12 的死锁）

`_run_content()` 是内容流解释器。它的每个分支都必须让 `pos` 前进；v12 的兜底分支
在遇到**单独的** `)`、`]`、`>` 时既不前进也不报错，于是**死循环**——
没有异常、没有超时、没有产物，900 秒预算整个消失。真实 PDF 里这种字节很常见
（内嵌图像区、嵌套字典），实测：v12 读一篇真实 arXiv 论文（`seq2seq_1409.3215.pdf`）
**90 秒仍未返回**；本包 **0.14 秒**读完 9 页 / 30981 字符。
修复是三层的：兜底分支把该字节当作单字符 token 并 `+1`；循环末尾再加一条
`pos > start` 断言；token 总数设硬上限 `_MAX_TOKENS`（超限即截断并写明）。
`tests/selftest.py::pdf_tokeniser_always_advances` 固化这条。

## 2. inventory：证据底账

`inventory.py` 把段变成可比较的条目：

- `numbers`：数值 + **单位**，含 `%`、`°C`、`km`、`stations` 等度量单位，也含
  `R² / MAE / RMSE / AUC / F1 / IoU / NSE` 这类**指标名单位**（`R² = 0.86`）。
  数值做规范化（`0.860 == 0.86`），单位做别名归一（`℃/degC → °c`）。
- `captions`：带编号的图注/表注，并**去重与择优**（正文里「Table 1 reports…」这种伪图注被排除，
  保留真正带「编号 + 标点 + 大写起头」的图注）。
- `tables`：连续 `table-row` 段聚合成表；用「首行无数值、次行有数值」判定表头；
  `< 2 行` 或无数值的聚合被丢弃（避免把示意图里的标签行当成表格）。
- `claims`：带结果动词、带量化结果（`reduce … by 18.4%`）或带年份的句子，打分为结果候选。
- `limits`：含 limitation / only / remains unclear / 局限 等线索的句子。
- `verify_value()` / `verify_locator()`：后面所有硬闸的比较函数。

## 3. plan：先主线，后页面

`outline.py` 只做一件事：**按叙事功能分配页面**，而不是按章节。推不出的环节不编：
`gap` 没有原文依据时留空并写 `evidence_absent_reason`，同时进入 `uncertainty`。

页级字段（见 `templates/slide-plan.template.json`）：`role / title / claim / bullets /
numbers / evidence[] / figure|table / kpis / density`。其中 `evidence[]` 的 `locator` 与
`quote` 是「证据锁」的输入，`quote` 必须能回到原文。

`plan.json` 可人工编辑：把它放在 `case.json` 同目录，`run.py` 会自动采用并标记
`drafter=plan.json`。这是「人机协作」的接口——也是效率增益的来源：改页不用改脚本。

## 4. evidence lock：四道硬闸

`plan_validate.py`：

| 闸 | 判据 | 违反后果 |
|---|---|---|
| G1 图号存在 | 页面上出现的 `Figure/Table/Eq N` 必须在该材料里存在 | `REF_NOT_IN_SOURCE`（error） |
| G2 数字存在 | 页面上的每个数值 + 单位组合必须能在原文找到 | `NUMBER_NOT_IN_SOURCE`（error） |
| G3 引文可定位 | `quote` 逐字命中；PDF 抽取噪声允许一次归一化匹配 | `QUOTE_NOT_FOUND`（error） |
| G4 有定位 | 内容页至少一条定位，或声明 `evidence_absent_reason` | `EVIDENCE_MISSING`（error） |

另有三类质量闸（warn）：要点过长/像原文、一页多主张、**把示意图放在结果主张里**
（`SCHEMATIC_AS_DATA`，error 级）。所有结论写入 `validation.json`，进入 `result.json`。

## 5. layout：容量是算出来的，不是猜出来的

`layout.py` 用字宽模型（CJK 1.0 em / 数字 0.56 / 小写 0.53 …）把文本框尺寸换算成
「能放几行」，再从字号阶梯里选**最大的能放下的字号**：

- 正文阶梯 22/20/18/16，下限 16；标题 34…24，下限 24；图注 13/12/11。
- **到下限仍溢出**：不改字号，而是给出 `action`（`split` / `trim` / `table-shrink`）与
  差多少 pt。auto-shrink 到看不清是题目明列的失败模式，所以这里选择「报错并要求改结构」。
- 表格：列宽按内容宽度加权，逐格换行算行高；行高在写 pptx 时**被固定**，否则 PowerPoint
  会把每行撑到填满文本框（这是真机上很常见的「表格突然变得巨大」的原因）。
- 计算出的几何（`layout.json`）就是写 pptx 时的几何，读回校验比对的是同一份 spec。

## 6. deck：模板是权威，产物必须还能编辑

`deck.py`：

- 有模板就打开模板，**保留主题**（不写死字体/颜色），按角色名匹配版式
  （`Title Slide` / `Title and Content` / `Section Header` / `Title Only`），
  使用真占位符（标题走占位符继承主题样式），只改它们的**位置尺寸**到 `layout` 算出的几何。
- 没有模板时用内置 16:9 几何，仍是真版式 + 真主题。
- 图：能从 PDF 抽到嵌图就放真图（`assets.py`，按页与图注就近绑定）；
  抽不到就画**虚线示意图框**，框内是原文图注 + 定位 + 「schematic」字样，绝不冒充实验数据。
- 表：真 `GraphicFrame` 表格；表体没能还原时用标注框说明「表体未还原，见原文 §x」。
- 页码用 **OOXML 域**（`a:fld type="slidenum"`）而不是写死的数字，页面重排后仍然正确。
- 备注写入 notes 页（真备注页，可编辑）。

## 7. render：真渲染，且说明是哪个引擎

`render.py` 顺序：`$SOFFICE_BIN`/`soffice`/`libreoffice` → Windows PowerPoint COM →
模型预览（Pillow 按 `layout` spec 画框）。引擎与实际产物写进 `render.json`；
模型预览同时写 `preview_mode="model"` 并把 `status` 降为 `partial`。
本包自证运行使用 PowerPoint COM，得到真 PDF + 每页 PNG。

### 7.1 预览件是二进制，但**证据必须是文本**

题面要求「可编辑产物必须同时给真实渲染的 PDF/PNG 预览」；平台同时只接受
**UTF-8 文本型 Skill 资源**（运行期产物可以且应当是二进制，见 Runtime contract
的 `Runtime artifacts may be binary`）。两者并不冲突——**预览在运行期生成，包内不放二进制**。
但这样一来，判分人读到的包里只剩一个结论「已渲染」，无法复核。所以 `render.verify()`
在渲染后**当场测量**预览件，并把数字写回 `result.json.render.verification`：

| 被测量的东西 | 怎么量 | 为什么这条能替代「打开文件」 |
|---|---|---|
| 页数 | 解析 PDF 里每个 `/MediaBox` | 页数对不上就说明导出件不是这份 deck |
| 页面尺寸 | `/MediaBox` 宽高 ÷ 72 | 13.333×7.5 in 才对得上 16:9 的 deck；被缩放会露出来 |
| 字体是否嵌入 | `/BaseFont` 与 `/FontFile` 对象；`ABCDEF+` 子集前缀 | 题面点名的「导出后字体被替换」在这里变成可判定项 |
| 字体是否被替换 | 与 `.pptx` **真正渲染所用**的字面比对（显式 run 字体 + 主题 `majorFont/minorFont` 解析结果） | 只比「deck 要求 vs PDF 实际」，不比主题里的复杂脚回退表 |
| 每页预览 | PNG `IHDR` 取宽高；像素算墨迹率与边缘墨迹 | 空白页、被裁切、拉伸变形、内容压到页边（疑似溢出）都能判 |
| 有效 dpi | 像素宽 ÷ PDF 页宽（英寸） | 1600px / 13.333in = 120 dpi，可直接复核 |
| 图/表是否掉件 | 读回 `.pptx` 形状：图页必须有 picture 或带标注的示意图框，表页必须有表格对象 | 「图注还在、图没了」是页数检查看不见的失真 |

`checked=false` 不等于通过：**任何**一条不达标都会把 `status` 降为 `partial` 并写进
`uncertainty[]`。第三方复核走 `scripts/audit_deck.py` 的 A9——它**不读** `render.json`，
自己去数 PDF 页数与 PNG 页数、走 PNG 的 chunk 链确认文件完整（尾随垃圾会被抓）、
再用像素判断空白页。自证（`render.verify`）与他证（`audit_deck` A9）刻意分开实现。

## 8. qa：八道闸对应评分维度

`qa.py` 的八道闸与评分维度对应关系见 `RUBRIC-MAP.md`。要点：

- 闸的状态只有 `pass / fail / not_evaluated`；无法评估**不算通过**（例如没提供模板时
  `template_layouts_ok` 会按内置几何评估并说明）。
- 证据覆盖率 = 有定位的内容页 / 内容页；门限 0.8。
- 备注重复度 = 备注与「观众可见文字」的字符 4-gram Jaccard；门限 0.34。
- 渲然成功与「文件读回仍可编辑」共同决定 G6；**预览件被测量且合格**才给 G7。\n- `qa.py --out` 复查时**重新打开交付件**：`deck.pptx` 重新读回、PDF/PNG 重新测量，再由新增的\n  `G0_ledgers_match_artefacts` 比对「`result.json.outputs[]` 的 bytes/sha256」「`deck-readback.json`\n  的页数与最小字号」「有没有台账里没有的文件」三件事。只读台账的复查会在交付件被改写后依旧全绿，\n  那不是复查，是复述。`G1–G4` 仍只判页面计划，README §8 写清了分工。

## 9. 增益与「不是假绿」如何自证

`benchmark_local.py` 用**同一份材料、同一套几何、同一套判据**，对比
「段落贴页基线」与「本包产出」：定位页数、证据覆盖率、原文可核对的数字数、图表页数、
溢出页数、备注重复度、主线角色齐全度。这是一次**机制对照**，不是平台分数——
平台分数由组织方生成，本包不编造。

独立审计（`audit_deck.py`）本身也可能「假绿」：如果它复述运行期写下的结论，
自证与他证就串通成一句话。A5 因此**不读** `locator_verified` 这个由生成本身写下的标志，
而是拿 `evidence_map[].quote` 回到材料里**重新定位**；A9 自己去数 PDF/PNG 的字节；
A10 按同一套角色规则重新判定 `sources[]` 里有没有工单文件。
对健康交付做五种篡改（引文指向未读材料 / 把 `task.md` 塞进 `sources[]` / 删掉一页的引用 /
把伪造数值写进 slide XML / 破坏一页预览文件），对应的 A5 / A10 / A5 / A4 / A9
**逐项变红**；不篡改时 `0` 项失败。复跑脚本：
`questions/q06/runs/adv1-audit/contam_test.py`（运行期验证脚本，不属于提交包）。

## 10. 已知边界

- 复杂多栏 PDF 的阅读顺序仍可能错（本包按 y 分行、按 x 排续，未做分栏检测）；
- 扫描版 PDF 依赖平台 OCR，本包只如实报告 `text_layer=false`；
- 公式只做「可读化」，不还原排版；
- 未做「跨语言润色」——页面的措辞压缩是规则化的，不是生成式的；
- `\input` 的嵌套深度未限制，超深嵌套的 LaTeX 工程可能被截断（会在 `inventory.notes` 报出）。
