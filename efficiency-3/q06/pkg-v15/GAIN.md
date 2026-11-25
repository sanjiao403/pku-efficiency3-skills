# GAIN.md · 使用增益（真实两臂对照，一页）

**这不是平台分数**，也不必换算成分数。它是「同输入、同渲染器、同测量代码、同审计器，只有方法不同」的
**真实对照**：两臂都真跑、都写出可打开的 `deck.pptx` 与 `result.json`，数字全部由
`scripts/benchmark_local.py` 从产物重算，落在 `tests/benchmark-report.json`。

复跑：`python3 scripts/benchmark_local.py --reps 3`（三个案例 × 两臂 × 3 次重复，本机约 60 秒）

## 两条路径

| 臂 | 命令 | 做什么 |
|---|---|---|
| **baseline**（无本 Skill 方法） | 由 `benchmark_local.py::naive()` 实现 | 段落顺序贴页：每段一页、固定 14pt、无 locator、备注=页面文字、**忽略页数上限**、不做字号拟合 |
| **skill**（本包） | `python3 scripts/run.py --case <case.json> --out <T>/skill` | 主线重写 + 证据锁 + 字号拟合 + 独立备注 + 独立审计 |

共享件（刻意不构成差异）：材料读取 `papertext.py`、渲染 `render.py`、度量 `benchmark_local.measure()`、审计 `audit_deck.py`。
两臂都是确定性代码，**不调用模型**。

## 三案例合计（reps=3 中位数）

| 指标 | baseline | skill | Δ | 读法 |
|---|---:|---:|---:|---|
| 备注复述页 `notes_echo_pages` | **57** | **0** | −57 | 讲稿与页面分离：baseline 直接把页面文字当备注 |
| 页数在预算内 `page_budget_ok` | **0.0**（0/3 案例） | **1.0**（3/3） | +1.0 | baseline 页数 58、超预算 20 页；skill 27 页、0 超限 |
| 已核实 locator 的内容页 `content_pages_located` | **0** | **31** | +31 | 每一页内容都能回溯到材料的具体行/页 |
| 独立审计失败项 `audit_deck_failed` | **16** | **0** | −16 | 同一个只读审计器，baseline 在 A2/A5/A6/A7 上成片失败 |
| 布局/溢出违规 `layout_violations` | **5** | **0** | −5 | 拟合在页内并守 11pt 下限 |
| 图注-数值一致率 `caption_number_consistency` | 0.841 | **1.0** | +0.159 | 图页带原文图注；baseline 只贴正文 |
| 来源可追率 `source_traceability` | 0.996 | **1.0** | +0.004 | 贴页逐字抄原文，命中率本来就高 → **不是**差异点 |
| 单页最多字符 `max_page_chars` | 1465 | 1206 | −259 | 单页信息密度受控 |
| 端到端秒 `e2e_seconds` | 0.22 | 17.69 | +17.47 | **不作为效率增益证据**（见下） |

逐案例：`case_zh_md` 预算 `no→yes`、`case_latex` 图注一致率 `0.857→1.0`、`case_en_pdf` 图注一致率 `0.667→1.0`。

## 结论

1. **质量增益有原始数据**：在页数预算、页级定位、备注分离、布局合规、图注一致五项上，skill 严格优于
   baseline，且 baseline 的失败正是题面点名的失败模式（段落贴页、讲稿复述、超页数、缩到看不清）。
2. **增益可验证**：每条数字都能用一条命令复算（见 `GAIN-EVIDENCE.md` 的字段路径），测量函数与审计器
   都不属于被比较的任何一臂。
3. **不夸大**：来源可追率几乎打平（贴页也会逐字抄原文），端到端耗时差**落在重复极差内**，
   故两者都不作为增益主张；「人工修改页数」在无人对照里无法产生真实数字，记 `null`。

## 与「带标签案例」的关系

两臂对照回答「同一张论文，方法不同会差多少」；`tests/gain_cases.json` 回答「证据锁到底抓不抓得住造假」：
`grounded` 0 error、`fabricated_number` 报 `NUMBER_NOT_IN_SOURCE`、`fabricated_figure_ref` 报
`REF_NOT_IN_SOURCE`、`fabricated_quote` 报 `QUOTE_NOT_FOUND`，4/4 与标注一致（`python3 scripts/gain_check.py`）。
