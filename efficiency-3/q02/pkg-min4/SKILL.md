---
name: scientific-schematic-min
description: >
  Minimal, fully self-sufficient scientific schematic skill (standard library only, no
  network, no LLM, no external figure model required). One command reads a case.json plus
  its material and derives the figure itself: entities and relations are mined from the
  material text, a data table found in the material is encoded directly (columns inferred),
  the legend and colour mapping come from the data, and every element keeps the verbatim
  sentence it came from. Polarity is re-derived from that sentence - an inhibition drawn as
  an activation is a blocking error - and a figure that drew nothing can never report
  success. Use when asked to 画/生成/修改 科研示意图, 机制图, 通路图, 关系图, 流程图,
  数据图表, 期刊插图, or when a figure must stay editable (改一个标签不用重画) and
  traceable to its source. Do NOT use for artistic illustration, poster layout, statistics
  selection, or manuscript writing.
---

# scientific-schematic-min2 · 极简自足科研示意图（启发式推导 + 可核验 + 可编辑）

**一条命令，零附加参数**（缺省即这两个路径）：

```bash
python3 scripts/schematic.py --case /input/case.json --out /app/output
```

**完全启发式：不依赖任何外部 spec。** 材料里有什么就画什么：

1. **实体/关系**：从材料文本里挖「实体—动词—实体」句式，关系用固定词表判定
   （`inhibits` → inhibition、`activates` → activation…），每条都带**逐字原句**；
2. **数据编码**：材料目录里的 CSV/TSV 会被自动发现，列的角色由启发式推断
   （数值列 → value/error，其余 → category/series，常见列名优先）；
3. **图例/配色**：由实际画出的关系与数据系列现算，不用手写；
4. 如果 `case.json` 自己声明了 `figure_spec`，就用它（那是案例自带的输入）；
   但**没有它也能跑通**——这正是本臂的设计目标。

相对路径解析顺序（与工作目录无关）：**`case.json` 所在目录 → 材料目录 → cwd → `/input`**，
每一步的来源记在 `result.json.resolved_from`。
退出码：`0` = `success`，`2` = `partial`（**产物照常落盘**，不是崩溃）。

## 1. 什么时候用 / 不用

| 用 | 不用 |
|-|-|
| 机制/通路/关系/层级图；材料是 md/txt/tex/csv；需要**可编辑源文件** | 艺术插画、封面、海报版式 |
| 有数据表的柱状对比图，图例/配色/坐标必须与表一致 | 统计方法选择、显著性检验 |
| 必须**逐元素追溯到材料原句**（审稿人挑不出错） | 论文正文写作、文献综述 |

## 2. 输入

| 位置 | 内容 |
|-|-|
| `case.json`（默认 `/input/case.json`） | 只需 `case_id`；可选 `task`/`title`、`material_dir`、`figure_spec`、`output_contract` |
| 材料目录 | `md / txt / tex / csv / tsv / json / rst / html / xml`；二进制或 Office 件**不猜内容**，记 `not_reported` |

## 3. 输出契约（`--out`，默认 `/app/output`）

| 文件 | 内容 |
|-|-|
| `figure.svg` | **主产物**：分层可编辑 SVG。真实 `<text>`（可选可改）、`<g data-layer>` 命名图层、每个实体/边/数据条带 `id` 与 `data-source`，边带 `data-relation`/`data-glyph`（`tee` = 抑制横杠）。**同时充当矢量导出件** |
| `result.json` | **主结果**（28 个顶层键）：`case_id`/`task`/`status`/`status_reason`/`summary`/`deliverable`/`editable_source`/`exports[]`/`outputs[]`/`element_sources[]`/`data_mapping`/`checks`/`uncertainty[]`/`manual_review[]`/`not_reported[]`/`gaps[]`/`changes[]`/`source_preservation`/`change_log[]`/`sources[]`/`metrics`/`run_log`/`resolved_from`/`contract_echo`/`self_scored`（恒 `false`）等 |

* `element_sources[]`：每个实体/边一条，含 `locator`（`材料#charNNNN`）、`quote`（逐字原句）、
  `verified_in_material`（原句拿回材料**逐字查找**的结果）；
* `data_mapping`：图例/配色/坐标与表的逐项映射（`categories`/`series`/`colors`/`rows`）；
* `checks.blocking = {model_errors, data_errors}`：**status 只由它决定**，不是自述；
* `contract_echo`：`output_contract`（四种形态都支持）逐字段回显，缺值的必填字段进
  `contract_missing_required`，**不编造**。

## 4. 降级与失败处理（全部写进 `result.json`）

| 情况 | 处置 |
|-|-|
| 没有 `case.json` | 材料发现 + 启发式推导继续；`partial` + `gaps` |
| **列名写错 / 缺列** | `data_column_missing`（**阻塞**，绝不换一列） |
| **抑制画成激活** | `polarity_inverted`（**阻塞**），附原句 |
| **空产物**（0 实体 + 0 关系 + 0 数据标记） | `empty_figure`（**阻塞**）：**空图永远不会报 success** |
| 图构建/导出抛异常 | 转成 `figure_not_drawable` 阻塞项，**仍写出 `result.json`** |

## 5. 自查（只读产物重算）

```bash
python3 scripts/verify.py --result /app/output/result.json --case /input/case.json
```

末行 `VERIFY_OK` 才算通过（非 0 退出是故意的，可作闸门）。它只读产物重算：契约字段、
产物是否真在磁盘、SVG 是否真为可编辑分层文本、系列数=颜色数、图例覆盖全部系列、
`element_sources` 有无核验失败原句、`checks.blocking` 是否清零。

## 6. 限制与预算

* 不内嵌字体（矢量文字保持可编辑，查看器替换系统字体）；**不出 PDF/PNG**；
* 启发式抽取面向「一句一个判决关系」的写法；含糊句会落到 `unknown` 或只报 warn；
* 纯 Python、无网络无 LLM，单案例 **< 0.1 s**；平台预算 64 请求 / 900 s / 16384 tokens 内绰绰有余；
* 资源 ≤14 个 UTF-8 文本文件、合计 ≤110 KB、零二进制。
