# 图面规则（精简版）

## 1. 语义配色（唯一来源：`apparatus.py` 的 `PAL`/`ECOL`）

块体：`unit` 通用装置、`unit.vessel` 容器、`unit.instrument` 仪器与执行器、`unit.utility`
公用工程（气/废液/冷却）、`unit.sensor` 传感器、`step.*` 步骤、`phase` 阶段卡。
连线：`material` 深蓝实线（物料）、`energy` 橙虚线、`signal` 青点线、`sequence` 灰实线（顺序）、
`dependency` 紫点划线（阶段依赖）、`loop` 灰蓝虚线（回流）。

规则：**一个语义 = 一个颜色 + 一种线型 + 一种线宽**；图例由实际用到的语义自动生成，
所以"图例颜色与图形不一致"在结构上不可能发生。

## 2. 连线与箭头

1. 方向只来自原句：`A is fed from B` ⇒ B→A；`A 接入 B` / `A flows into B` ⇒ A→B。
2. 每条连线**恰好一个箭头**，在目的地端；箭头必须落在末段端点上（`verify.py` 实测 ≤1.5 px）。
3. 回流（`loop`）从行下方绕行，不穿块体。
4. 没有显式句式就**不画**；一个称呼指向多个单元时也**不画**（写进 `uncertainty`）。

## 3. 画布与比例

* 画布以 mm 声明：`width="180mm"` + `viewBox="0 0 680.31 …"`，1 mm = 96/25.4 px ⇒ 打印 1:1。
* 高度按内容自动计算；页边距 10 mm。
* 右下角固定 40 mm 比例尺，长度经 `verify.py` 实测（误差 ≤1%）。

## 4. 文字与可编辑性

* 文本一律真实 `<text>`，不得转曲、不得嵌位图；字体族给出回退链。
* 字号台阶：标题 1.5×、面板标题 1.06×、块内 1.0×、注记 0.86×（基准 9 px）。
* 块宽按文本估宽（中文全角、拉丁约 0.55 em）自动加宽，上限 132 px，超出换行加省略号。
* 图层：`layer-units` / `layer-connectors` / `layer-labels` / `layer-legend` / `layer-rulers`
  / `layer-annotations`；每个图元带 `data-node`、`data-kind`、`data-quote`、`data-src`
  （`data-src` 用 `@` 代替 `#`，避免被 SVG 解析器当成颜色前缀）。

## 5. 数据与来源

* `data_mapping[]` 只收材料里带单位的数值；数字必须能在材料原文中找到（`verify.py` 硬检查）。
* 每个元素的 `source` = `{locator, quote}`，`locator` 精确到 `file#L行` 或 `file#L行-行`。
* `provenance.ambiguities` 记录指代不明；`provenance.unreadable` 记录读不了的材料。

## 6. 交付前 30 秒自查

1. `verify.py` 末行是 `ok=True`？
2. 图上每个箭头都能说出"材料哪句话支持这个方向"？
3. `result.json` 的 `status` 与 `checks/gaps/uncertainty` 自洽（partial 必须有理由）？
4. 用浏览器或 Inkscape 打开 `figure.svg`，能直接改一个标注吗？
