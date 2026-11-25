---
name: apparatus-roadmap-figures-min
description: >
  极简版科研绘图 Skill：一条命令把实验材料变成可核验的科研图稿——装置结构/物料流向
  （apparatus schematic）与技术路线（roadmap），交付分层可编辑 SVG（真实文本 + data-* 溯源）
  与 result.json，并用独立脚本复核写出的文件。
  Use when asked to 画实验装置图 / 装置结构图 / 物料流向图 / 技术路线图 / roadmap /
  apparatus schematic / experimental setup figure，或需要在无网络、依赖最小的情况下
  一次跑出矢量源文件 + 结构化结果。
  Do NOT use for 数据分析与拟合、论文排版、实验方案科学合理性判断（题面明确排除）。
---

# apparatus-roadmap-figures-min · runbook

> 先把材料读成数据，再画；画完**重新打开写出的文件**复核。缺什么写缺，不补造。

## 一条主命令

```bash
python3 scripts/apparatus.py --case /input/case.json --out /app/output
```

`apparatus.py` 会在 `/app/output` 写：`figures/figure.svg`（可编辑源）、
`figures/figure.pdf` + `figures/figure.png`（有 pymupdf 或 cairosvg 时；没有则如实记录缺失）、
`result.json`（契约字段 + `case_id` + `elements/relations/data_mapping/provenance/checks/uncertainty`）。
材料从 `case.json` 所在目录递归读取（`.md/.txt/.tex/.csv/.tsv/.json`，PDF 需 pymupdf）。

## 独立复核（必跑）

```bash
python3 scripts/verify.py --svg /app/output/figures/figure.svg \
        --result /app/output/result.json --materials /input
```

复核项：SVG 良构 / 无位图嵌入 / 文本仍是真 `<text>` / 图层存在 / mm 与 viewBox 一致 /
**每条连线恰好一个箭头且箭头落在末端点上** / **比例尺实测 40 mm** / 图元带 `data-quote` 与
`data-src` / `result.json` 键齐全无 null / 状态诚实 / **图上每个数字都能在材料里找到**。
末行 `ok=True` 才算过；退出码 2 = 有硬失败，**不要交**。

## 输出契约

| 文件 | 内容 |
|-|-|
| `figures/figure.svg` | 分层（`layer-units/connectors/labels/legend/rulers/annotations`）可编辑源；文本未转曲；图元带 `data-node/data-kind/data-quote/data-src` |
| `figures/figure.pdf` | 页面尺寸 = 画布 mm 的矢量导出（可选后端） |
| `figures/figure.png` | 300 dpi 预览（可选后端） |
| `result.json` | `case_id`、`status/status_reason`、`elements[]`、`relations[]`、`data_mapping[]`、`deliverable`、`provenance`（含 `ambiguities`/`unreadable`/溯源计数）、`checks`、`uncertainty[]`、`gaps[]`、`contract_echo`（`case.json` 的 `output_contract` 全键透传，缺值给 `""`/`[]`，不给 null） |

## 降级（缺什么报什么）

| 情形 | 处置 |
|-|-|
| 材料里没有装置清单/编号步骤/阶段标记 | 不生成示意内容；`status=partial`，`gaps[]` 写明 |
| 有实体但没有显式流向句 | 连线留空（不按常识补管路），`gaps[]` 记录 |
| 一个称呼对应多个单元（如 `反应釜 A-1`/`A-2`） | 指代不明的句子**不画连线**，写入 `uncertainty[]` 与 `provenance.ambiguities` |
| 有单位但没有数值 | 图中不标数值，`uncertainty[]` 记录；`verify.py` 会拦下任何材料外数字 |
| 无 PDF/PNG 后端 | 仍交 SVG 源文件；`status=partial` 并在 `checks.render.notes` 说明 |
| 读不了的文件（扫描 PDF 等） | 记入 `provenance.unreadable`，不猜内容 |

## 预算与限制

零网络、零必需第三方依赖（PDF/PNG 为可选加速）；单案例 < 2 秒。
不做数据分析、不做期刊排版、不评价实验方案科学合理性。
可编辑但与材料无关的内容（配色、图例、画布）由 `apparatus.py` 中的语义调色板与自动图例决定；
图例颜色与图形颜色同源，改一处即可整套改色。
