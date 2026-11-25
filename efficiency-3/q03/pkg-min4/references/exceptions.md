# 例外与不可判定情形（exceptions）

每行对应**本包真实存在的一条处理路径**：检测点在代码里，处置写进产物字段。原则：**绝不静默丢数据、绝不猜**。

| # | 情形 | 检测点 | 处置 | 记录在 |
|-|-|-|-|-|
| 1 | 空 / `NaN` / `n.d.` / `-` 单元格 | `chart.num()` 整格严格解析 | 不画该点，不补 0、不插值 | `figure.map.json`（无该元素）、`result.json.uncertainty`、`render_report.json.null_value_notes` |
| 2 | 表里没有数值列 | `plan_chart()` 找不到 `value` 列 | 不出图、不建空坐标系 | `status=failed` + `uncertainty[].why` |
| 3 | 找不到 `case.json` | 依次找 `/input/case.json`、`./case.json` | 仍写 `result.json` | `status=failed`、`uncertainty` 列路径，退出码 1 |
| 4 | `case.json` 解析失败 | `json.load` 异常捕获 | 记 gap，不中断写出 | `uncertainty[].why`，退出码 1 |
| 5 | 相对引用（表/材料） | `resolve_ref()`：case 目录 → cwd → `/input` | 取首个命中 | `result.json.resolved_from[].from` |
| 6 | 引用全未命中 | 同上 | 跳过该引用，继续找同级表 | `from="unresolved"` + `uncertainty` |
| 7 | 数量轴是物理量却无单位 | `unit_ok()`，无量纲词按**整词**匹配 | 出图但判缺陷并给修法 | `checks.axis_units.ok=false`、`status=partial` |
| 8 | 分类列重复取值 | `collect()` 去重 | 合并为同一分类，不报错 | 图元数可在 `figure.map.json` 核对 |
| 9 | 系列只有一个取值 | `plan_chart()` 要求 2–6 个不同值 | 退化为单系列图 | `figure.legend_entries` 长度=1 |
| 10 | 记录型 JSON（无数值字段） | `looks_table()` 要求某字段 60% 为数值 | 视为非表格，找下一候选 | `uncertainty[].why` |
| 11 | 画布为空（0 图元） | `main()` 空图守卫 | **不得**报 `success` | `status=partial` + `status_reason` |
| 12 | 颜色重复/色觉不可分 | `run_checks().cvd_grayscale`（Machado 2009 + CIE76） | ΔE<12 失败、12–20 警告，并给冗余通道建议 | `checks.cvd_grayscale.pairs[]` |
| 13 | 灰度打印不可分（\|ΔL\*\|<5） | 同上 | 仅当颜色是唯一通道（<3 系列）时失败 | `pairs[].greyscale` |
| 14 | 误差线未声明含义/n | `run_checks().error_bars` | `present=true` 必须有 `meaning`+`n` | `checks.error_bars.detail` |
| 15 | 文本被转曲 / 含位图 / 外链 | `verify.py` | 判失败（不可编辑/不自包含） | `verification_report.checks[]` |
| 16 | 产物被改动（数值不符/字节变化） | `verify.py` 的 `values_match_source` + `output_files_hashed` | 判失败并指出元素 id 与源值 | `verification_report.failed[]` |

## 退出码约定

| 命令 | 0 | 1 | 2 |
|-|-|-|-|
| `chart.py` | 图已交付（`success` **或** `partial`） | 未出图（`failed`，`result.json` 仍写） | — |
| `verify.py` | 全部复算通过 | 有任一条 FAIL | — |
| `benchmark.py` | 两探针通过且 4 条 gain 判定全 `pass` | 任一退化 | `--dump-case` 给了不存在的 id |

> `chart.py` 用 0 覆盖 `partial` 是有意的：图已交付、缺陷写在 `checks`/`uncertainty`；
> 若要"只有全绿才算成功"，以 `result.json.status == "success"` 为准。

## 未实现（明说，不假装）

图例重复单位检查；CJK 字体缺失探测（本版只声明字体族）；字号下限与 PNG dpi（本版只出 SVG）；
对数轴与 pie/box/scatter/heatmap（给了这类 `chart_type` 会退化为柱状，不会伪装成对数轴）。
