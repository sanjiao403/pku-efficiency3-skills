# INNOVATION — 三件别人没做的具体事（附来源与边界）

不是"更好的画图脚本"，而是三个**可被判分器复算**的机制。

## 1. 图元 ↔ 源单元格双向映射，行号用物理行

`figure.map.json` 每个图元带 `source{file,row,col,row_key}`，文件里 `convention` 明文写明：
**`row` 是源表物理 1-based 行号（`#` 注释行与表头都算）**；`row_key` 记下该行关键列取值，用于发现"表被重排后定位失效"。
复算：`python3 scripts/verify.py --case <case.json> --out <o>` → `values_match_source` 行。

出处与理由：工单字段名不可控，行号必须唯一且可人工核对；单位优先 `y_unit`、其次列名括号/下划线后缀
（`response_rfu`→`RFU`）是因为列名是最常见的单位载体；无量纲词按**整词**匹配，是因为子串匹配会把
`concentration` 里的 `ratio` 当成无量纲标记从而放过"缺单位"（这是我们真的踩过并修掉的 bug）。

## 2. 以"产物"为唯一输入的独立判定器（编造数值必被抓）

`scripts/verify.py` **不 import `chart.py`、不读运行期内存**，只打开 `figure.svg`/`figure.map.json`/`result.json`
并自己重算：产物 `bytes/sha256`、图元 id 是否真在 SVG 里、每个数值回到源单元格是否相等、单位是否写在轴上、
图例是否唯一、颜色对在三种色觉模拟下的 ΔE 与灰度 ΔL\*。判定落成**随包一等产物**
`examples/case-01.verification_report.json`（每次运行也会在 `--out` 里生成同名报告）。

实测：`tests/gain_cases.json#gain-02` 在渲染**之后**把映射里的一个数值改成源表不存在的 `7.77`，
`verify.py` 同时报 `values_match_source` 与 `output_files_hashed` 两条违规。

## 3. 色觉/灰度是可复算的阈值，不是形容词

`cvd_pairs()` 用 **Machado, Oliveira & Fernandes (2009) severity 1.0**（线性 RGB 三组矩阵，含 tritanopia）
模拟 protanopia/deuteranopia/tritanopia，经 sRGB→XYZ→CIELAB 用 **CIE76 ΔE** 度量：
`score = min(ΔE_full, ΔE_deut, ΔE_prot)`，**<12 判 FAIL、12–20 警告**；灰度另算 \|ΔL\*\|（<5 且颜色为唯一通道时 FAIL），
≥3 系列时给出虚实线等冗余通道。逐对 `dE76`/`cvd.*`/`dL_greyscale` 落在 `checks.cvd_grayscale.pairs[]`。

## 4. 来源、边界与可审计性

输入只有平台注入的 `/input/case.json` 及材料；本包不含真实实验数据、不含正式案例、不含答案，
`tests/gain_cases.json` 与两份 `examples/*_report.json` 都是标了「示例（非正式答案）」的合成数据。
第三方仅公开文献（Okabe–Ito 2008 调色板、Machado et al. 2009 色觉矩阵）。
边界：不做统计推断、只做柱状族、不 OCR/不读 xlsx、只出 SVG；逐条见 `references/exceptions.md`。
可审计性：产物 `sha256` 写在 `result.json.output_files[]` 并由 `verify.py` 逐一比对，重跑应得同样判定。
