# 期刊预设（journal profiles）

本极简版把样式**内建在 `scripts/chart.py` 的常量里**（不随包加载外部 profile 文件——单文件约束），
下表就是"当前实际生效的值"，以及改哪一个常量能改它。

| 参数 | 当前值 | 常量/位置 | 影响的产物字段 |
|-|-|-|-|
| 图宽 | **89 mm**（Nature 单栏宽） | `render_svg()` 的 `W = 89.0 * MM` | `render_report.json.figure_mm[0]`、SVG `width` |
| 图高 | 70 mm（内容自适应上限内的固定画布） | `W, H = 89.0 * MM, 70.0 * MM` | `figure_mm[1]` |
| 基础字号 | **7 pt**（所有轴标签/刻度/图例统一） | `FS = 7.0` | SVG `font-size`、`render_report.json` 不含字号明细（见下） |
| 字体族 | `Arial, Helvetica, sans-serif` | `render_svg()` 里每个 `<text>` 的 `font-family` | `render_report.json.font_family_used` |
| 调色板 | Okabe–Ito 8 色（色觉安全） | `PAL` 列表 | `render_report.json.series[].colour`、`checks.cvd_grayscale.pairs[]` |
| 轴/边框线宽 | 轴线 0.8 pt，柱边框 0.3 pt，误差线 0.8 pt | `render_svg()` 各 `stroke-width` | SVG 属性 |
| 导出格式 | **仅 SVG**（文本，可编辑） | `main()` 只写 `figure.svg` | `render_report.json.exports` |
| 栅格分辨率 | 不适用（本版不出 PDF/PNG） | — | — |

## 按目标期刊怎么选

| 案例里写到 | 建议 | 需要改的常量 |
|-|-|-|
| Nature / 89 mm 单栏 | **默认值即可** | 无需改动 |
| Cell / Science 单栏（约 85–90 mm） | 默认值可用；如需 85 mm | `W = 85.0 * MM` |
| Elsevier 双栏（约 170 mm） | 把宽度改成 170 mm，字号可升到 8 pt | `W`、`FS` |
| IEEE 单栏（3.5 in ≈ 88.9 mm） | 默认值（89 mm）即可，字号可升到 8–9 pt | `FS` |
| 未指定期刊 | 用默认 89 mm / 7 pt，并在 `result.json.uncertainty` 注明"journal 未指定" | — |

## 诚实说明（与"引用官方指南"的区别）

- 上表数值来自常见投稿下限的通行做法（89 mm、7 pt、Okabe–Ito），**本包不声称逐字引用任何期刊的作者指南**，
  也不随包保存 `source_urls`/`retrieved` 字段（大包有此机制，本极简版没有）。
- 若某期刊明确要求其它尺寸/字号，请直接改常量，并在产物里保留痕迹：
  改完重跑后 `render_report.json.figure_mm` 会反映新尺寸；把该期刊的原始要求写进你的 `case.json.notes`
  或 `result.json.uncertainty`，这样"为什么用这个样式"仍然可追。
- **字号下限没有闸**（本版不出位图，故无 dpi 限制、无字号越界检查）：这是已知边界，
  见 `references/exceptions.md` §未实现的判定。
