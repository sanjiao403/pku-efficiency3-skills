# 图形摘要设计规则（可复用领域规则）

> 供 Agent 与评审共用：写 IR 时按这里的选择，评审时按这里的条目核对。

## 1 单页四拍（problem → method → results → conclusion）

| 面板 | 必须回答 | 常见错误 |
|-|-|-|
| problem | 研究缺口是什么（不是"背景介绍"）| 写成领域综述，缺口缺失 |
| method | 用了什么手段、几步、什么读出 | 步骤并列无因果，缺读出 |
| results | 核心结果与量级（图/通路/数值）| 只有结论句，没有编码 |
| conclusion | 意义与边界（能做/不能做）| 夸大（用 prove / 必然 / 治愈）|

四条信息必须**同时**出现在单页上；缺一条即 `partial`。阅读顺序由段间箭头与 ①②③④ 徽标固定。

## 2 实体与关系语法（避免张冠李戴）

| 关系 | 画法 | 语义判据 |
|-|-|-|
| activation | 实线箭头 | 材料出现 activate / promote / drive / 上调 |
| inhibition | T 形端 | inhibit / block / suppress / 下调 |
| binding | 空心圆端 | bind / interact / 结合 |
| modification | 菱形端 | phosphorylate / palmitoylate / 修饰 |
| transport | 虚线箭头 | transport / traffic / 转运 / 定位改变 |
| flow | 实线箭头（流程语义）| 步骤先后，不表示因果 |

方向必须与材料一致（"X 激活 Y" 不能画成 Y→X）。区室（胞外/膜/胞质/核）不能错位：
跨膜受体不能画进胞内；基因斜体、蛋白正体，两者不能混用。有向边数 = 材料中明确关系数；
不确定的关系写 `type: "unknown"` 并在 `uncertainty` 说明，**不要猜**。

## 3 数据编码与图例

- 长度/位置编码数值：柱高与数值线性对应，y 轴必须有单位与量级刻度。
- 颜色用色觉友好调色板（Okabe–Ito：`#0072B2 #D55E00 #009E73 #CC79A7 #E69F00 #56B4E9 #1A1A1A`）；
  **同时**用图案（斜线/点/网格）区分分类，保证灰度打印仍可读。
- 图例项数必须等于图面实际分类数（脚本按图面派生图例并在 `compliance_checks.legend_consistency` 断言）。
- 误差线必须有来源列（SD/SEM）与 n；缺失值不得当 0，缺单位不得自造单位。
- 图上每个数字都要能回到 `source.locator` + 逐字 `quote`（`invariants.numbers` 逐个数核对）。

## 4 版式与字号

- 默认画布 2400×1350 px @300 dpi（≈203×114 mm，整页宽）。可按工单覆盖；`min_font_px` 默认 20。
- 字号层级：标题 0.028W / 副标题 0.0135W / 正文 0.0115W / 注释 0.0078W（W = 画布宽）。
- 溢出修复阶梯（脚本自动、逐步记录在 `exceptions`）：
  1) 删 `priority=low` 条目 → 2) 压行距 → 3) 正文按 6% 步进降字号（不低于 `min_font_px`）
  → 4) 单行截断加省略号。**字号下限不可破**；宁可少一条，不可小到读不出。
- 文本测量用内置等宽近似（CJK=1em，ASCII 按 Helvetica 字宽表），三个导出引擎共用同一套度量，
  因此 SVG/PNG/PDF 的换行与截断一致，重跑亦一致。

## 5 可编辑源与导出规范

- 源文件必须是**分层 SVG**：`<g id="layer-*">`，文字是真实 `<text>`（不得转曲/不得内嵌位图文字）。
- 每个图元 id 要与 `content_map` 一一对应，便于第三方按 id 复核。
- 导出件：PNG（IHDR 尺寸 = 画布，dpi 写入 pHYs/元数据，非空白）、PDF（`%PDF-` 头 + 页对象 + 矢量文字）。
- 字体：显式声明字体栈并把实际探测结果写入 `font_report`；发生替换时写入 `exceptions` 并说明影响。
- 同一 IR 重跑两次必须得到相同 SVG（`sha256` 一致），脚本在 `selfcheck` 与自检报告中验证。
