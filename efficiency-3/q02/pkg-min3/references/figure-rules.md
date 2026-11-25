# figure-rules — 关系语法、启发式抽取、布局与失效清单

`scripts/schematic.py` 遵循的规则。判断「图画对没有」看这里。

## 1. 关系语法（固定词表）

| 关系 | 画法 | 绝不能画成 |
|-|-|-|
| `activation` | **实心箭头**指向被调控者 | —— |
| `inhibition` | 目标端**垂直 T 形横杠** | **箭头**（画成箭头 = 生物学反了，最致命） |
| `binding` | **无箭头直线**（不断言因果） | 箭头 |
| `transport` | **虚线箭头** | 实线箭头 |
| `modification` | **空心箭头** | 实心箭头 |
| `sequence` | 带**编号**的连线（先后，不是调控） | 箭头 |
| `inclusion` | **嵌套虚线框**（组成/包含） | 箭头 |
| `unknown` | **虚线 + `?`**（材料说不清） | 悄悄升格成 `activation` |

极性**从引文原句重新推导**：在句内找关系动词与声明比对，不一致 → 阻塞 `polarity_inverted`；
无引文 → warn `edge_without_evidence`。

## 2. 启发式抽取（不依赖外部 spec）

1. 按 `.;!?` 断句，只处理**一句内 ≥2 个实体样式 token** 的句子。
2. 实体候选：`\b[A-Z][A-Z0-9]{1,6}\b`，排除 `DNA/RNA/EXAMPLE` 等噪声。
3. 关系：句内小写词命中固定动词表（`inhibits`→inhibition、`activates`→activation…）取第一个，
   首个实体为 source、第二个为 target；同句重复实体跳过。
4. 每条实体/关系带该句原文；脚本用 `find` 在材料里**逐字查找**，记
   `locator=文件#charNNNN` 与命中次数，查不到则 `verified_in_material=false`（warn）。
   （例：源写 `p53`，图用 `TP53` 时把 `p53` 放进 `aliases`）。

## 3. 数据编码与图例（启发式）

1. **发现**：材料目录（含 `materials/` 子目录）里第一个 `.csv`/`.tsv` 即数据表。
2. **列角色**：某列 ≥半数行可解析为数字 → 数值候选，其余为文本候选；数值列中命中
   `value|mean|expr|level|activity|rate|fold|值|表达|水平` → `value_column`，命中
   `sd|sem|se|std|stdev|error|ci|误差|标准差` → `error_column`；文本列中命中
   `time|condition|category|group|treat|时间|条件` → `category_column`，命中
   `gene|series|probe|sample|strain|基因|系列` → `series_column`。
4. 图例/配色/坐标由表现算：类别 × 系列逐条出柱，柱高按 `value/vmax` 归一，有误差列则画误差棒；
   颜色取色盲安全调色板（`#0072B2 #D55E00 #009E73 #CC79A7 #E69F00 #56B4E9`）循环。
5. 图例项数必须等于系列数（不等 → 阻塞 `legend_incomplete`）。

## 4. 布局与可编辑性

1. 内部按 **mm** 计算，输出 SVG 用户单位是 **pt**（`width/height` 仍标 `mm`），
   故 `font-size` 就是真实 pt，可直接核验字号。
2. 实体按 4 列网格排布；边从实体框边界出发（矩形裁剪），不穿过框；画布高度按内容算出，
   显式 `height_mm` 装不下时加高并记 `uncertainty`。
3. 图例一行为先关系（带箭头样例）后数据系列（带色块）。
4. **文字必须是真实 `<text>`**（可选可改），不许转曲、不许铺位图；分层为
   `layer-nodes` / `layer-edges` / `layer-data` / `layer-legend` / `layer-titles`。
5. 图元带 `id`（`node-n1`、`edge-e1`、`mark-<类别>-<系列>`）与溯源属性：
   实体/边 `data-source`+`data-quote`，边另有 `data-relation`/`data-glyph`，
   数据条带 `data-value`/`data-error`/`data-category`/`data-series`。
6. 不内嵌字体；本极简版不产出 PDF/PNG。

## 5. 失效清单 → 拦截手段

| 硬伤 | 拦截 |
|-|-|
| 抑制画成激活 / 上下游颠倒 | `polarity_inverted` 阻塞 + 原句对照 |
| 图里出现材料中没有的实体/数值/单位 | `entity_unverified` warn + `verified_in_material` 逐条记录 |
| 指定了不存在的列却照画 | `data_column_missing` 阻塞，不换列 |
| **输入被吞/模型为空却报成功** | `empty_figure` 阻塞：0 图元永不 `success`；异常转 `figure_not_drawable` 仍写 `result.json` |

## 6. 交付前自查

```bash
python3 scripts/schematic.py --case /input/case.json --out /app/output                  # 退出码 0
python3 scripts/verify.py --result /app/output/result.json --case /input/case.json      # 末行 VERIFY_OK
```

`element_sources` 无 `verified_in_material=false`；系列数与颜色数一致、图例覆盖全部系列；
有 warn 时 `uncertainty`/`manual_review` 必须给出处置。
