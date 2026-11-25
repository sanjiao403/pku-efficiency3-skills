---
name: scientific-figure-min2
description: 科研数据图表生成与编辑（最终极简自足版）。零附加参数从 case.json（内联数据或同目录 csv/tsv）生成期刊规范的可编辑 SVG，附「图元→源单元格（物理行号）」映射、单位/图例闸、色觉-灰度量化检查与按平台契约回填的 result.json；scripts/verify.py 只读产物重算，scripts/benchmark.py 给出朴素路线对照。当任务要求按源数据画图、出可编辑矢量图、或要求每个数值可追溯到原表时使用。
---

# 科研数据图表生成与编辑（min2）

**一句话**：`case.json` + 数据表 → 可编辑 SVG 图 + 图元↔源单元格映射 + 契约化 `result.json`，只用标准库。

## 1. 什么时候用

| 用 | 不用（交给别的工具） |
|-|-|
| 有真实源表，要出**期刊规范**的柱状/分组柱状图 | 需要重算 p 值/方差分析等统计推断 |
| 要求图**可编辑**（文字是 `<text>`，不是位图/转曲） | 交互图表、3D、动画 |
| 要求**每个数值都能指回原表行列**（审计/复现） | 只有"画个示意图"而无任何源材料 |
| 素材是 mean±s.d. 级汇总表 | 只有逐样本原始数据要做箱线/小提琴 |
| 要检查单位、图例、**色觉异常与黑白打印**可读性 | 多面板拼图、line/scatter/heatmap（本版仅柱状族） |

## 2. 主命令（零附加参数）

```bash
python3 scripts/chart.py  --case /input/case.json --out /app/output   # 出图 + 映射 + 契约
python3 scripts/verify.py --case /input/case.json --out /app/output   # 只读产物，逐条重算
python3 scripts/benchmark.py --out benchmark.json                     # 朴素路线 vs 本 Skill（可复跑）
```

- 仅标准库（**不需要** matplotlib/numpy/pandas）；`--case` 省略时按 `/input/case.json` → `./case.json` 找；
- `--out` 省略时默认 `/app/output`；重复执行幂等覆盖；
- **路径解析与 cwd 无关**（R1b）：`case.json` 里的相对路径先按 **case.json 所在目录**解析，再 cwd，再 `/input`，
  每次结果写进 `result.json.resolved_from[]`；把整包拷到别处（如 `.../stage/outputs/`）照样能跑。

## 3. 输入形状（容错读取）

- 表：`case.json` 内联（`data` / `{columns,rows}` / 记录数组），或与 `case.json` 同目录的 `.csv`/`.tsv`；
  CSV 允许 `#` 注释行，**行号用物理 1-based 行号**（注释行与表头都算），映射里就写这个行号。
- 列角色自动判定：非数值列→分类；含 `n/count/rep`→样本量；含 `err/sd/sem/ci`→误差；其余数值列→测量值。
  **整格是数字才算数**（`Il6`、`n.d.`、空 都不算数据，会被计入 `uncertainty` 的 unmapped）。
- x 轴优先取命名键列（`gene/symbol/sample/condition/...`），其余 2–6 值的分类列作系列。
- 单位：优先 `y_unit`，其次列名括号或下划线后缀（`response_rfu`→`RFU`，`time_h`→`(h)`）；
  **单位只写在轴上**；`relative/fold change/ratio/%/a.u./index` 等按**整词**匹配视为无量纲
  （`concentration` 不会被误判成 `ratio`）。

## 4. 输出（写入 `--out`）

| 文件 | 内容 |
|-|-|
| `figure.svg` | 图：坐标轴、刻度、图例、误差线；文字为真 `<text>` 且声明字体族，无位图、无外链 |
| `figure.map.json` | `elements[]`：`element_id` + `role` + `value` + `source{file,row,col,row_key}`；`by_element` 反查；写明「行=物理行号」约定 |
| `result.json` | 契约键逐字回填（不认识的名字保留为 null，全文留在 `_contract_source` 说明）+ 审计块：`outputs`、`output_files[]`(path/bytes/sha256)、`sources`、`resolved_from[]`、`cwd_independent`、`figure`、`checks`、`changes`、`uncertainty` |
| **`render_report.json`** | **一等产物**：图型/尺寸/字体/系列配色/图元数/映射覆盖率/`null_value_notes`（哪些格子无数值故未画）/导出件 path+bytes+sha256/耗时；纯文本无二进制 |
| **`verification_report.json`** | **一等产物**（`verify.py` 默认写出）：逐条 `expected vs actual`、`passed/total`、`failed[]`、`verdict`，由只读产物的判定器生成 |

`status`：全部检查通过且无缺口 = `success`；出了图但有失败项或缺口 = `partial`；没出图或**画布为空** = `failed`/`partial`（空图**不会**被报成 success）。

## 5. 检查项（`checks`）

`axis_units`（数量轴必须有单位或明确无量纲）、`legend_series`（图例唯一、颜色不重复）、
`value_fidelity`（每个图元都有 file/row/col 且能在 SVG 里找到 id）、`error_bars`（含义与 n 必须声明）、
`cvd_grayscale`（Machado 2009 severity 1.0 + CIE76 ΔE：<12 判 FAIL，12–20 警告；灰度 |ΔL*| <5 且颜色是唯一通道时判 FAIL；
≥3 系列给出虚实线等冗余通道）、`export`（`<text>` 保留、无 `<image>`）。

## 6. 降级行为

1. 找不到/解析不了 `case.json` → 仍写 `result.json`（`status=failed` + `uncertainty` 说明找过哪些路径），退出码 1；
2. 表里没有数值列 / 没有可分派的数据 → **不建空坐标系**，`failed`/`partial` 并说明；
3. 单元格非数字 → 跳过并计入 `uncertainty`，不猜；
4. 数量轴缺单位 → 出图但 `axis_units=FAIL`、`status=partial`，并给出修法；
5. 无 CJK 字体/无第三方库 → 中文可能缺字、只出 SVG，均如实记录。

## 7. 示例、报告与复用（均标「示例（非正式答案）」）

```bash
python3 scripts/benchmark.py --dump-case gain-01 /tmp/case.json        # 把示例工单落成可跑文件
python3 scripts/chart.py  --case /tmp/case.json --out /tmp/out          # 出图 + render_report.json
python3 scripts/verify.py --case /tmp/case.json --out /tmp/out          # 复算 + verification_report.json
python3 scripts/benchmark.py --out benchmark.json                       # 4 条带标签案例判定 + 朴素路线对照
```

随包样例报告（真实运行产物）：`examples/case-01.{render,verification}_report.json`。

- 带标签案例集（grounded / fabricated_number / off_topic / unit_missing）：`tests/gain_cases.json`，
  判定落 `benchmark.json.gain_cases[]`；结论页 `GAIN.md`（含字段路径）；机制与来源 `INNOVATION.md`；
  五维度对照 `RUBRIC.md`；例外与退出码 `references/exceptions.md`；期刊预设 `references/journal-profiles.md`；
  编码规则 `references/encoding-rules.md`。

**复用**：`scripts/` 整目录复制即当库用（`import chart, verify`，仅标准库）；`verify.py` 可对任何符合约定的产物目录单独跑；
新增闸门须在 `chart.run_checks()` 与 `verify.py` **两边都加**，并把期望写进 `tests/gain_cases.json`；
元素 id 约定（`el-<series>-<category>`、`legend-swatch-*`、`xaxis/yaxis/xlabel/ylabel`、`ytick-*`、`xtick-*`）可直接被外部工具消费。

## 8. 边界

不做统计推断；只做柱状/分组柱状图；不 OCR 扫描件、不读 xlsx（先转 CSV）；不输出 PDF/PNG（二进制会被平台预检拒绝）。
