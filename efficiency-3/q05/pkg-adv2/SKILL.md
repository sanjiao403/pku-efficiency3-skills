---
name: apparatus-roadmap-figures-min
description: >
  极简版科研绘图 Skill：一条命令把实验材料变成可核验的科研图稿——装置结构/物料流向
  （apparatus schematic）、编号步骤与回流（flow）与技术路线（roadmap），交付分层可编辑
  SVG（真实文本 + data-* 溯源）与 result.json，并用独立脚本复核写出的文件。
  Use when asked to 画实验装置图 / 装置结构图 / 物料流向图 / 步骤流程图 / 技术路线图 /
  roadmap / apparatus schematic / experimental setup figure，或需要在无网络、依赖最小
  的情况下一次跑出矢量源文件 + 结构化结果 + 独立复核报告。
  Do NOT use for 数据分析与拟合、论文排版、实验方案科学合理性判断（题面明确排除）。
---

# apparatus-roadmap-figures-min · runbook（adv1）

> 先把材料读成数据，再画；画完**重新打开写出的文件**复核。缺什么写缺，不补造。

## 一条主命令

```bash
python3 scripts/apparatus.py --case /input/case.json --out /app/output
```

零附加参数。`apparatus.py` 在 `/app/output` 写：`figures/figure.svg`（可编辑源）、
`figures/figure.pdf` + `figures/figure.png`（有 pymupdf 或 cairosvg 时；没有则如实记录缺失并给
`partial`）、`result.json`（契约字段 + `case_id` + `elements/relations/data_mapping/provenance/
checks/change_log/review/uncertainty/output_contract`）。

材料从 `case.json` 所在目录递归读取，**按字典序**；`.md/.txt/.tex/.csv/.tsv/.json/.yaml/.yml/.log`
按文本读，`.pdf` 需文本层（有 pymupdf 用 pymupdf，没有走包内纯标准库 `scripts/pdftext.py`）。

## 三件交付物（题面 L97 `Real editable SVG/PNG/PDF`）

| 产物 | 说明 | 由谁**量** |
|-|-|-|
| `figures/figure.svg` | 可编辑分层源（真实 `<text>`、CJK 回退链、`data-*` 溯源） | `verify.py` 重算尺寸/图层/图元/文本 |
| `figures/figure.pdf` | 矢量页：页盒 = 画布 mm、文字仍是活文本、**0 个位图 XObject** | `verify.py` 读 `/MediaBox`、`/Subtype /Image`、`Tj/TJ`、`/FontFile*` |
| `figures/figure.png` | 300 dpi 位图，`pHYs` 按真实 dpi 重写 | `verify.py` 读 IHDR 宽高 + `pHYs`，与 `画布 mm × dpi` 比对 |
| `figures/figure.edited.svg` | **源文件保留式编辑**证据：改 1 个标注、其余逐字节不变 | `edit.py` 计数 + `verify.py --edited` 独立比对 |

导出件不被"调用成功"糊弄：`scripts/measure.py` 会**回读写出的字节**（页盒/位图数/字体程序数/
文本算子/PNG 宽高与 pHYs/像素采样），任何一项不符就降 `status=partial` 并写明差多少。
没有 PDF/PNG 后端时只交 SVG 并如实标 `partial`（不伪造）。

## 源文件保留式编辑（题面 `source-preserving edit`）

```bash
python3 scripts/edit.py --svg /app/output/figures/figure.svg --dry-run          # 清点可编辑单元
python3 scripts/edit.py --svg /app/output/figures/figure.svg \
        --out /app/output/figures/figure.edited.svg --set-text U1 "改后的标注"
```

判定：`elements_changed=1`、`unchanged=总数-1`、输出仍良构、图层不变；复核再独立比一次
（`edit.one_text_touched` / `edit.structure_preserved`），改后的图仍能通过同一份 result.json 的复核。默认是**行级外科编辑**（`lines_changed=1`、`byte_identical_outside_target=true`）；`--engine xml` 会整份重排并如实报行数变化。`data-quote` 这类溯源字段默认拒改（改引文＝改证据来源）。

## 独立复核（必跑）

```bash
python3 scripts/verify.py --svg /app/output/figures/figure.svg \
        --result /app/output/result.json --materials /input --case /input/case.json \
```

复核**只读写出的 SVG 与 result.json**（不信作者内存里的数据结构），并且自己重算内容包围盒、
箭头端点、比例尺长度。38 项检查（只给 `--svg/--result` 时 31 项；只给 `--case` 时 36 项）里硬失败项包括：SVG 良构 / 无位图 / 真实 `<text>` /
图层存在 / mm 与 viewBox 一致 / **每段文字都有 font-family 回退链** / 每条连线恰好一个箭头
且箭头落在末端点上 / **内容不越出画布** / 比例尺实测 40 mm / 图元带 `data-quote` 与 `data-src` /
连线带 `data-quote` / **result.json 声称的每个实体都真的画在图上** / 键齐全无 null /
状态诚实 / **图上每个数字都能在材料里找到**（数字白名单只收 material 角色文件）/
**case.json 声明的 `output_contract` 字段都在 result.json 顶层** / **PDF 页盒 = 画布 mm、矢量无位图、文字仍是活文本** / **PNG 像素数 = 画布 mm × dpi 且 `pHYs` 标的就是该 dpi** / **PDF 字形着墨率（未嵌字体会掉下来）**。
末行 `ok=True` 且退出码 0 才算过；退出码 2 = 有硬失败，**不要交**。

## 输出契约

| 文件 | 内容 |
|-|-|
| `figures/figure.svg` | 分层（`layer-units/connectors/labels/legend/rulers/annotations`）可编辑源；文本未转曲；每图元带 `data-node/data-kind/data-quote/data-src`，连线带 `data-fid/data-flow/data-from/data-to/data-quote` |
| `figures/figure.pdf` | 页面尺寸 = 画布 mm 的矢量导出（可选后端） |
| `figures/figure.png` | 300 dpi 预览（可选后端） |
| `result.json` | `case_id`、`status/status_reason`、`elements[]`、`relations[]`、`data_mapping[]`、`deliverable`、`output_contract`（**四段式交付契约**：editable_sources / exports / data_mapping / element_traceability）、`contract_echo`（case.json 声明的每个契约字段 -> 怎么填的）、`provenance`（材料/抽取器/歧义/不可读/证据范围）、`checks`、`change_log`（来源与修改记录）、`review`（人工确认状态）、`source_files`（含版本 sha256）、`uncertainty[]`、`gaps[]` |

契约字段透传规则：`case.json` 的 `output_contract` 里**每个键**都会出现在 `result.json` 顶层；
能从计算结果直接得到就填真值，名字不同则按 `ALIAS` 映射（如 `editable_source -> deliverable`），
实在没有来源就给该类型的空值（`[]`/`{}`/`""`）并在 `contract_echo` 写明原因 —— 不给 `null`。

## 确定性（同包重复运行必须一致）

* 材料发现按**字典序**（`os.walk` 的目录顺序随文件系统而变，实现里显式排序）；
* **产物目录永不作为材料**：本次 `--out` 目录跳过，另按签名识别历史产物目录
  （含 `result.json` 且带 `case_id`+契约段）整棵跳过 —— 否则第二次运行会把自己上一次的
  图/结果读成材料，同一包跑出不同结果；
* 不写时间戳、无随机数、无随机布局；`tests/selftest.py` 的 `A1/A2` 用两次真跑的 SVG
  sha256 相等来证明（`tests/selftest-report.json`）。

## 证据范围（工单不算科学材料）

证据索引（实体/数值/连线/步骤/阶段）**只收 material 角色文件**：

| 角色 | 判据 | 处置 |
|-|-|-|
| `case` | `--case` 指向的文件 | 只用于读数（`case_id`/标题/`figure_kind`/契约）与**内联材料字段** |
| `workorder` | `case.json`、`task.md`、`*.example.json`、`*.template.json`、`*.schema.json`；或 JSON 里带 `output_contract/output_schema/expected_outputs/deliverables`（或同时有 `case_id`+`task`） | 登记进 `provenance.excluded_workorder_files` 与 `source_files`，**不进证据索引** |
| `material` | 其余（含真正的数据 JSON/CSV） | 进证据索引 |

内联材料（平台另一种投喂方式）只认显式字段 `materials_text / material_text / material /
materials / source_text / sources_text`，不认裸 `text`/`task`；用了就写进
`provenance.inline_materials` 与 `source_files.role=inline-material`。

## 降级（缺什么报什么）

| 情形 | 处置 |
|-|-|
| 材料里没有装置清单/编号步骤/阶段标记 | 不生成示意内容；`status=partial`，`gaps[]` 写明；复核把与内容相关的检查标 `not_applicable` |
| 有实体但没有显式流向句 | 连线留空（不按常识补管路），`uncertainty[]` 记录 |
| 一个称呼对应多个单元（如 `反应釜 A-1`/`A-2`） | 指代不明的句子**不画连线**，写入 `uncertainty[]` 与 `provenance.ambiguities` |
| 有单位但没有数值 / 材料外数字 | 图中不标数值；`verify.py` 会拦下任何材料外数字（负向对照见 `tests/selftest.py` C2） |
| 无 PDF/PNG 后端 | 仍交 SVG 源文件；`status=partial` 并在 `checks.render.notes` 说明 |
| PDF 无文本层 / 读不了 | 记入 `provenance.unreadable`，不猜内容；纯标准库兜底恢复不到有效文本时同样按不可读处理 |
| 内容越出画布 | 自动按实测包围盒加高重画（宽度固定 180 mm）；仍越界则 `status=partial` + 原因 |
| 顶层未预期异常 | 仍写 `status=partial` 的 `result.json`（含 `error` 原文，路径已脱敏），不留空目录 |

## 预算与限制

零网络、**零必需第三方依赖**（PDF/PNG 出图为可选加速；PDF 文本层有纯标准库兜底）；
单案例 < 2 秒（本机实测 0.4–0.9 s，报告见 `tests/selftest-report.json`）。
不做数据分析、不做期刊排版、不评价实验方案科学合理性。
可编辑但与材料无关的内容（配色、图例、画布）由 `apparatus.py` 的语义调色板与自动图例决定；
图例颜色与图形颜色同源，改一处即可整套改色。

## 自查（3 条，30 秒）

1. `python3 tests/selftest.py` → 末行 `failed=0`（14 组断言：确定性 / 工单负向对照 /
   复核真会咬人 3 连 / 降级 2 条 / 契约 / 顶层异常 / PDF 兜底 / 无本机路径）；
2. `python3 scripts/verify.py --svg figures/figure.svg --result result.json --materials /input
   --case /input/case.json` → 末行 `ok=True`；
3. 用浏览器或 Inkscape 打开 `figure.svg`，能直接改一个标注吗？箭头方向都能说出材料里哪句话支持吗？



