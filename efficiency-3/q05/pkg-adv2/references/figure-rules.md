# 图面规则（精简版）

## 1. 语义配色（唯一来源：`apparatus.py` 的 `PAL`/`ECOL`）

块体：`unit` 通用装置、`unit.vessel` 容器、`unit.instrument` 仪器与执行器、`unit.utility`
公用工程（气/废液/冷却）、`unit.sensor` 传感器、`step.*` 步骤、`phase` 阶段卡。
连线：`material` 深蓝实线（物料）、`energy` 橙虚线、`signal` 青点线、`sequence` 灰实线（顺序）、
`dependency` 紫点划线（阶段依赖）、`loop` 灰蓝虚线（回流）。

规则：**一个语义 = 一个颜色 + 一种线型 + 一种线宽**；图例由实际用到的语义自动生成，
所以"图例颜色与图形不一致"在结构上不可能发生。

## 2. 连线与箭头

1. 方向只来自原句：`A is fed from B` ⇒ B→A；`A 接入 B` / `A flows into B` ⇒ A→B；
   `A leaves B` / `A exits B` ⇒ **B→A**（主语是出口，宾语才是来源）。
2. 每条连线**恰好一个箭头**，在目的地端；箭头必须落在末段端点上（`verify.py` 实测 ≤1.5 px）。
3. 装置面板按**流向拓扑序**排布（同层按原文顺序），让上下游相邻，减少连线横穿整图；
4. 编号步骤：主序列箭头竖直连号；回流（`返回步骤 N`）从**左侧专用走廊**绕回目标步，不穿文字；
   终止步（`结束/终止/stop`）额外画一条终点横杠；
5. 路线图阶段卡按可用宽度**分带**（每行放得下的列数），行内横箭头、跨行走**行间走廊**，
   不越页宽；
6. 没有显式句式就**不画**；一个称呼指向多个单元时也**不画**（写进 `uncertainty`）；
7. 拉丁别名规则：标签含多个英文词时，丢掉 ≤5 字母的单个通用词（`vacuum pump VP-1` 不再用
   裸 `pump` 指代），避免把 `the peristaltic pump P-1` 误连到真空泵。

## 3. 画布与比例

* 画布以 mm 声明：`width="180mm"` + `viewBox="0 0 680.31 …"`，1 mm = 96/25.4 px ⇒ 打印 1:1。
* 宽度固定 180 mm（投稿单栏），高度按内容算；画完**实测内容包围盒**，越界就加高重画，
  仍越界则 `status=partial` 并在 `checks.layout.overflow` 写明（`verify.py` 独立重算同一件事）。
* 页边距 10 mm；右下角固定 40 mm 比例尺，长度经 `verify.py` 实测（误差 ≤1%）。

## 4. 文字、字体与可编辑性

* 文本一律真实 `<text>`，不得转曲、不得嵌位图（`verify.py` 硬检查 `svg.no_raster_or_foreign`）。
* **每段 `<text>` 必须带 `font-family` 回退链**（CJK 族优先 + `sans-serif` 收尾）：
  否则导出端可能把中文渲染成方框，而"字体未嵌入导致中文变方框"正是题面点名的失败。
* 字号台阶：标题 1.5×、面板标题 1.06×、块内 1.0×、注记 0.86×（基准 9 px）。
* 块宽按文本估宽（中文全角、拉丁约 0.55 em）自动加宽，上限 132 px，超出换行加省略号。
* 图层：`layer-units` / `layer-connectors` / `layer-labels` / `layer-legend` / `layer-rulers`
  / `layer-annotations`；每个图元带 `data-node`、`data-kind`、`data-quote`、`data-src`
  （`data-src` 用 `@` 代替 `#`，避免被 SVG 解析器当成颜色前缀）。
* **序列化不变量**：内部 API 的 `role=` 落地必须是 `data-role=`；显式 `data-role` 与默认
  `role` 不得同时出现（重复属性会让 XML 不可解析）。裸 `role=` 会让复核读到空集而"全绿空转"。

## 5. 数据、来源与证据范围

* `data_mapping[]` 只收材料里带单位的数值；数字必须能在材料原文中找到（`verify.py` 硬检查，
  且数字白名单**只收 material 角色文件**）。
* 每个元素的 `source` = `{locator, quote}`，`locator` 精确到 `file#L行` 或 `file#L行-行`；
  locator 指向的文件必须在 `provenance.materials` 内（`provenance.locators_resolve`）。
* 证据索引**只收 material 角色文件**：`case.json` / `task.md` / `*.example.json` /
  `*.template.json` / `*.schema.json` 是工单与示例，记为 `workorder` 并排除
  （见 `provenance.excluded_workorder_files`）；真正的数据 JSON/CSV 仍是材料。
* `provenance.ambiguities` 记录指代不明；`provenance.unreadable` 记录读不了的材料。

## 6. 确定性

* 材料遍历按字典序；产物目录（本次 `--out` 与任何"我们自己的产物目录"）永不作为材料；
* 不写时间戳、无随机量；同输入两次运行 SVG 逐字节一致（`tests/selftest.py` A1/A2 真跑断言）。

## 7. 导出与编辑（题面 `Real editable SVG/PNG/PDF and source-preserving edit`）

| 产物 | 硬要求 | 怎么量（`verify.py` 从字节重算） |
|-|-|-|
| SVG | 分层、真实 `<text>`、CJK 回退链、`data-*` 溯源 | 尺寸 mm ↔ viewBox、图层、图元数、文本数、位图数=0 |
| PDF | 页盒 = 画布 mm；矢量（0 个 `/Subtype /Image`）；文字是活文本（**解压后**的 TJ/Tj + 嵌入字体程序） | `/MediaBox` → mm、`/Subtype /Image` 计数、inflate 后 `TJ/Tj`、`/FontFile*` |
| PDF 文字 | 中文必须能被 **Unicode 抽取**（D40：本包 `Tj` 字面量 0 个，文字全在 `TJ` 数组）且真的着墨 | pypdf Unicode 抽取字符数 vs SVG 文本（覆盖率阈值 0.85）+ 逐字形 bbox 着墨率（阈值 0.98） |
| PNG | 像素数 = 画布 mm × dpi；`pHYs` 标的 dpi 与该 dpi 一致 | IHDR 宽高、`pHYs`、与 `画布×dpi` 的期望值比对（±2 px） |
| 编辑件 | 结构保持一致（图元 id/引文/图层不变），默认**行级**改动 `lines_changed=1` | `edit.py` 行级计数 + `verify.py --edited` 独立比对两份 SVG |

* MuPDF 写 PNG 的 `pHYs` 固定是 96 dpi，会让查看器按错误物理尺寸摆图 ⇒ 导出后按真实 dpi 重写（纯标准库）。
* 无 PDF/PNG 后端时只交 SVG 并如实 `partial`；页盒/DPI/字形任一不符同样 `partial`，并写明差多少。

## 8. 交付前 30 秒自查

1. `python3 tests/selftest.py` 末行 `failed=0`（23 组）？`tests/contamination_check.py` `failed=0`（12 项）？
2. `python3 scripts/verify.py --svg figures/figure.svg --result result.json --materials /input
   --case /input/case.json` 末行 `ok=True`？
3. 图上每个箭头都能说出"材料哪句话支持这个方向"？（不是任务书、不是示例、不是模板）
4. 用浏览器或 Inkscape 打开 `figure.svg`，能直接改一个标注吗？

