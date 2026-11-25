---
name: scientific-figure-adv2
description: 科研数据图表生成与编辑。从 case.json（内联数据或同目录/相邻 csv/tsv）按源数据出图：可编辑 SVG（真 <text>）+ 投稿用矢量 PDF + 300 dpi PNG 预览，附「图元→源数据物理行/列」映射、按 output_contract 回填的 result.json 与由产出物重新读出的 export_check.json；verify.py 只读产物独立复算并交叉核对 SVG/PDF/PNG 三种渲染是否一致。当任务要求「按源数据画图 / 出可编辑矢量图 / 修改既有图 / 生成带单位、图例、误差线与来源可追溯的科研图」时使用。
---

# 科研数据图表生成与编辑（adv2）

**一句话**：给定工单（`case.json`）+ 数据表 → 出一张**可编辑 SVG**、一份**投稿矢量 PDF**、一张 **300 dpi PNG**、
一份能指回原单元格（物理行号）的映射，以及一份**由产出物重新测量**得到的导出检查报告。

## 1. 什么时候用

| 用 | 不用（交给别的工具） |
|-|-|
| 有真实源数据表，要出**期刊规范**的柱状/分组柱状图 | 需要重算 p 值/方差分析等统计推断 |
| 要求图**可编辑**（文字保留为 `<text>`，不是转曲/位图） | 需要交互图表、3D、动画 |
| 要求每个图元都能追溯到源文件的**行与列** | 只有"画个示意图"而无任何源材料 |
| 要求同时交**可编辑源 + 导出件**（含尺寸/分辨率/字体/色彩检查） | 只有逐样本原始数据要做箱线/小提琴 |
| 要改一张已生成的图并证明"其余部分没动" | 多面板拼图（a/b/c 版面） |

## 2. 主命令（零附加参数）

```bash
python3 scripts/chart.py  --case /input/case.json --out /app/output   # 出图 + 三种渲染 + 契约 + 导出检查
python3 scripts/verify.py --case /input/case.json --out /app/output   # 只读产物独立复算
```

- 只用标准库即可跑通；`--engine` 默认 `auto`：**优先 matplotlib** 渲染导出件（字体更真、支持 CJK、
  可嵌入 TrueType 子集），**环境里没有 matplotlib 时自动降级到标准库写出器**（矢量 PDF + zlib PNG）。
  两条路径共用同一份几何、产物字段一致，**均已实测 `verify.py` 19/19 通过**；
  `--engine stdlib` 是显式开关（用于在无 GUI/无 matplotlib 的最小容器里强制走降级路径），`--dpi N` 改预览分辨率。
- 未给 `--case` 时按 `/input/case.json` → `<cwd>/case.json` 查找；未给 `--out` 时默认 `/app/output`。
- **逐字节可复现**：钉住环境变量 `SOURCE_DATE_EPOCH`（任意整数）后，同输入两次运行的全部产物
  逐字节相同——`figure.pdf` 的 `/CreationDate`、`result.json`/`render_report.json` 的时间戳与耗时字段
  都取自该变量（不再读墙钟）。不钉时按真实时间记录，产物照常可用。回归项：`tests/selftest.py`
  的 `reproducible_byte_identical`。
- 相对引用（`data_file` / `materials` / 表格名）解析顺序：**case.json 所在目录 → cwd → `/input`**，
  每次尝试都记进 `result.json.resolved_from`，所以包被整份拷走后仍能找到材料。

## 3. 输入形状（容错读取，不改平台给的键名）

- 表：内联（`{columns,rows}` / `data` / 记录数组），或与 `case.json` 同目录/相邻的 `.csv` / `.tsv`。
- 单位的**证据边界**：只有 `.csv` / `.tsv`（或内联表）会被当成测量数据；`.txt` / `.md` 是材料，
  只登记进 `evidence_channels.materials_seen` **绝不解析成数字**；`case.json` / `task.md` /
  `*.example.json` / `*.template.json` 属于工单与文档，永远不是数据来源，同名 JSON 只记进
  `evidence_channels.rejected_as_non_data`。
- 行号 = **源文件的物理 1-based 行号**：注释行、表头、表内空行都算进去（用 csv 自身行计数，不用记录序号）；
  内联表没有物理行，此时 `source.row = record_index + 1` 并给出 `record_index`，真正的键是 `row_key`。
- 列角色自动判定：非数值列→分类；含 `n/count/rep`→样本量；含 `err/sd/sem/ci`→误差；其余数值列→测量值。
  **整格是数字才算数**（`Il6`、`n.d.`、空 都不会被当成数据，记入 `unmapped`）。
- 图：`chart_type`（默认按是否存在分组列推 `grouped_bar`/`bar`）、`journal`、`x_label`/`y_label`/`y_unit`/
  `caption`/`error_bar_meaning`/`title`/`notes` 均为可选别名容错。
- 单位：优先 `y_unit`，其次列名括号或下划线后缀（`vehicle_rfu`→`RFU`）；**整词**判无量纲
  （relative / fold change / ratio / % / a.u. / index），`concentration` 不会被误判成 `ratio`。

## 4. 输出（写入 `--out`）

| 文件 | 内容 |
|-|-|
| `figure.svg` | 可编辑源：真 `<text>`、每个图元带 `id`、无位图、无外链 |
| `figure.pdf` | 投稿导出：单页矢量、真文本算子（`Tj`）、无位图；matplotlib 路径 `pdf.fonttype=42` 子集嵌入 |
| `figure.png` | 预览导出：`--dpi`（默认 300）栅格 + `pHYs` dpi 标记，sRGB |
| `figure.map.json` | `elements[]`（`element_id`/`role`/`value`/`source{file,row,record_index,col,row_key}`）+ `by_element` 反查 |
| `export_check.json` | **从产物字节重新解析**得到的导出证据（MediaBox/页数/Tj 数/字体/嵌入/位图数/色彩；PNG 的 IHDR+pHYs）+ 逐项判定 |
| `result.json` | 按 `output_contract` 键名回填 **并保留 `case_id`/`status`/`sources`/`uncertainty`**；`output_files[]` 含 path/bytes/sha256/role；`checks` 逐项 |
| `render_report.json` | 渲染记录：图型、系列配色、图元数、映射覆盖率、未映射单元格说明 |

三种渲染共用**同一份 `layout()`**，所以柱高不可能在 SVG/PDF/PNG 之间漂移。
`status`：全部检查（含导出闸与零遮挡闸）通过且无缺口 → `success`；出了图但有失败项/缺口 → `partial`；没出图 → `failed`。

## 5. 缺输入 / 异常时的行为（先落盘，再降级）

1. 找不到 `case.json` → 仍写 `result.json`（`status=failed`，说明找过哪些路径），退出码 1；
2. 解析失败 / 表里无数值列 / 表里无数值单元格 → `result.json` 记录原因，**不建空坐标系糊过去**（空画布绝不报 success）；
3. 单元格非数字 / 空 → **不猜**：跳过该点，计入 `unmapped` 与 `uncertainty`；
4. 数量轴没有单位且非无量纲 → 出图但 `checks.axis_units=false` 并给出修法，`status=partial`；
5. 轴标题与刻度标签会重叠 → 左边界按最长刻度文本自适应加宽，`checks.label_occlusion` 给出实测间隙（mm）；
6. 无法写进导出的字符（标准库 PDF 的 WinAnsi 之外）→ 记入 `uncertainty` 并说明以 `figure.svg` 为准；
7. 导出失败 → 逐项写入 `export_check.json.checks`，失败项计入 `result.json.checks` 与 `status`；
8. 所有的失败都保留已产出的文件（部分交付优于零交付）。

## 6. 自检与示例（示例（非正式答案），非平台案例）

```bash
python3 scripts/chart.py  --case examples/case.example.json --out /tmp/out
python3 scripts/verify.py --case examples/case.example.json --out /tmp/out
python3 tests/selftest.py --out /tmp/selftest          # 端到端 + 降级 + 拷贝探针，末行 SELFTEST_OK
```

`examples/case.example.json` 自带内联数据（4 基因 × 2 条件，mean±s.d.，n=3）与 `output_contract` 形状；
`examples/example-spec.json` 是对应图规范；`examples/export_check.example.json` 是一次真实运行得到的导出证据样例。
三者都标「示例（非正式答案）」，不含平台案例答案。

## 7. 边界（不承诺的部分）

- 不做统计推断（只校验图上的声明与材料一致）；不 OCR 扫描件、不读 xlsx（先转 CSV）。
- 图型只有柱状与分组柱状；不做多面板拼图、3D、动画、交互。
- 色彩空间只到 sRGB/DeviceRGB，不输出 CMYK/PDF-X，不嵌 ICC。
- 标准库导出路径的 PNG 只画图元不画字形（无字形光栅器），已在产物里显式说明。
- 详见 `references/encoding-rules.md`（编码→图例/单位/色盲灰度）与 `references/exports.md`（导出预设、引擎链、证据字段）。
