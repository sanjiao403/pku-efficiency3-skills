# INNOVATION.md · 创新点与相对已有方案的边界（一页）

## 1. 新增能力：页级证据锁 + 单条可重证（不是「生成得像 PPT」，而是「每条主张都能被推翻」）

| 能力 | 实现 | 同题通用方案为何难以稳定做到 |
|---|---|---|
| 页级证据锁（4 道硬闸） | `plan_validate.py`：G1 数值+单位、G2 Figure/Table 编号、G3 引文逐字、G4 内容页 locator | 通用 PPT 生成器只保证「文本像幻灯片」，不校验页面上每个数字/图号是否真的在论文里 |
| 逐条可重证 | `rigor.py --item number:3.7:degC`（`--all` 走整本台账） | 判决留在模型上下文里，换个 shell 就复现不了；本包把每条结论变成一个可独立运行的命令 |
| 定位可核对 | `evidence_map[].locator` + `locator_verified`（`文件 · §章节 · p页码 · L行号`） | 通常只有页号，无法逐条回溯到源句 |
| 产出物独立审计 | `audit_deck.py`：只读 `deck.pptx`+`result.json`+材料，重算 A1–A8，**不读**计划中间件 | 自检与生成同源时，生成器的错会被自检继承；这里是两套代码 |

## 2. 方法改进：把「判定」从字符串拼接里救出来

对照 `pkg-v12`（75 分）本版修了一个**会产生假阳性**的判定缺陷：G1/G2 原先在「整页拼接文本」上扫描，
于是相邻两个字段会**跨字段融合**出材料里不存在的数值-单位对——例如页面同时有 `12` 与 `R2 = 0.86`
（分属不同 bullet/title）时，拼接后出现 `12 R2`，被当成「材料里没有 12 R2」而误报
`NUMBER_NOT_IN_SOURCE`，把本来正确的页降级为 `partial`。

修法：`plan_validate.py::_page_fields()` 把页面拆成**独立字段**逐个判 G1/G2，`rigor_report` 与
`audit_deck.deck_facts()['blocks']`/`benchmark_local.measure()` 同口径（逐 block 扫数字与图号，
图注包含率仍按整页判）。**不放松任何真阳性**：

| 带标签案例 | 期望 | 实测 |
|---|---|---|
| `grounded`（数字/图号/引文都真） | 0 error | **0 code、rigor 全命中**（修复前误报 1 个） |
| `fabricated_number`（3.7→4.2 degC） | `NUMBER_NOT_IN_SOURCE` | 命中，rigor `number:4.2:degC` 查不到 |
| `fabricated_figure_ref`（引用 Figure 7） | `REF_NOT_IN_SOURCE` | 命中，rigor `figure:7` 查不到 |
| `fabricated_quote`（改写句冒充原文） | `QUOTE_NOT_FOUND` | 命中，rigor 引文查不到 |

判定器 `scripts/gain_check.py` 只调用 `plan_validate` + `rigor`，**不读**生成器自评；4/4 与标注一致，
原始记录在 `tests/gain-report.json`，标签集在 `tests/gain_cases.json`。

## 3. 创新证据：真实两臂对照（含失败模式的可测量化）

`benchmark_local.py` 真跑两臂并把「段落贴页」的失败量化：页数预算 `0/3 → 3/3`、备注复述 `57 → 0`、
已核实 locator `0 → 31`、独立审计失败 `16 → 0`、布局违规 `5 → 0`（`tests/benchmark-report.json`）。
这不是自述式对照：两臂共用材料读取器与渲染器，测量函数与审计器都不属于任何一臂。

## 4. 边界（不宣称的部分）

- 相对**通用 PPT 工具**：本包不追求模板美观与图形设计，只保证「可讲、可核验、可编辑」；绘图美化不是本包职责。
- 相对**其它课题产出**（论文精读结论、科研绘图、写作润色）：本包只吃材料、不生成新结论；材料里没有的句子会被
  标成 `evidence_absent_reason` 而不是编一句话。
- 相对**人工排版**：本包的收益是「页级证据 + 一致性」，不是「比人类做得好看」。
- 已知不做：LaTeX 源/.docx 直接解析、PDF 内嵌图抽取、扫描件 OCR、office 之外的渲染保真承诺。
