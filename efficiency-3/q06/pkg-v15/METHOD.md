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

## 8. qa：六道闸对应六个评分维度

`qa.py` 的六道闸与评分维度对应关系见 `RUBRIC.md`。要点：

- 闸的状态只有 `pass / fail / not_evaluated`；无法评估**不算通过**（例如没提供模板时
  `template_layouts_ok` 会按内置几何评估并说明）。
- 证据覆盖率 = 有定位的内容页 / 内容页；门限 0.8。
- 备注重复度 = 备注与「观众可见文字」的字符 4-gram Jaccard；门限 0.34。
- 渲然成功与「文件读回仍可编辑」共同决定 G6。

## 9. 增益如何自证

`benchmark_local.py` 用**同一份材料、同一套几何、同一套判据**，对比
「段落贴页基线」与「本包产出」：定位页数、证据覆盖率、原文可核对的数字数、图表页数、
溢出页数、备注重复度、主线角色齐全度。这是一次**机制对照**，不是平台分数——
平台分数由组织方生成，本包不编造。

## 10. 已知边界

- 复杂多栏 PDF 的阅读顺序仍可能错（本包按 y 分行、按 x 排续，未做分栏检测）；
- 扫描版 PDF 依赖平台 OCR，本包只如实报告 `text_layer=false`；
- 公式只做「可读化」，不还原排版；
- 未做「跨语言润色」——页面的措辞压缩是规则化的，不是生成式的；
- `\input` 的嵌套深度未限制，超深嵌套的 LaTeX 工程可能被截断（会在 `inventory.notes` 报出）。
