# Symbol conventions — 每个视觉 token 只有一个含义

每个 token 的含义由**渲染器、校验器、读者**三方共享：`scripts/schematic.py` 画它，
`scripts/verify.py` 读回来查它，读者按本表读它。每条约定都对应一个**已知失效模式**，
并给出**具体由哪个检查强制**——约定不是美学，是防错。

## 1. 边 token

| token | 含义 | 画法 |
|-|-|-|
| 实线 | 材料直接支持的交互 | 无 `stroke-dasharray` |
| 虚线 | 间接/推测/方向不明 | `stroke-dasharray="2.5 1.8"` |
| 目标端**实心三角** | 激活、促进、因果；**从 source 指向 target** | `<polygon fill="#111">` |
| 目标端**垂直横杠** | 抑制、阻遏、阻断；**横杠贴在被抑制者一侧** | `data-glyph="tee-bar"` |
| 目标端**空心三角** | 共价/酶学修饰 | `<polygon fill="#fff">` |
| 目标端**开放箭头**（虚线） | 跨区室运输 | 虚线线体 + 开放箭头 |
| **无端标记** | 非定向结合，不断言因果 | 仅 `<line>` |
| 目标端 `?` | 关系存在但方向未定 | 虚线 + `<text>?</text>` |
| **嵌套虚线框** | 包含/组成（不是因果） | 目标节点外侧虚线矩形 |
| 编号连线 | 时序先后（不是调控） | `sequence` 连线 |

## 2. 为什么是这些约定（失效模式 → 约定 → 强制检查）

| 经典失效 | 防止它的约定 | 由谁强制 |
|-|-|-|
| **抑制画成激活** | 抑制 = 横杠，永不用三角 | `marker_semantics`（`verify.py`）：`data-glyph` 必须与 `data-relation` 匹配；生成期 `polarity_inverted`（阻塞） |
| **上下游颠倒** | 箭头必须落在语义 target 一侧 | `marker_geometry`（`verify.py`）：线端点到 target 边框距离 ≤ 容差，且尾端靠近 source 框 |
| 间接证据画成直接 | 虚线 = 未被直接证明 | `data-relation="unknown"` ⇒ 虚线 + `?` |
| 包含画成并列 | 包含 = 嵌套框 | `inclusion` 无连线，改为嵌套矩形 |
| 并列被误读成交互 | 并列项之间不画边 | 不生成边即不进入图例 |
| 关系没有出处 | 每条关系都要逐字引文 | `edge_without_evidence`（warn）；**一条都查不到 ⇒ `evidence_unverified`（阻塞）** |
| 实体名不在材料里 | 标签 token 必须逐字出现在材料中 | `entity_unverified`（warn + `manual_review`） |
| 指定列不存在却照画 | 缺列即阻塞 | `data_column_missing`（阻塞，绝不换列） |
| 图例与实际不符 | 图例由实际画出的关系/系列生成 | `legend_incomplete`（阻塞）+ `legend_coverage`（校验） |
| **空图/输入被吞** | 0 图元永不 success | `empty_figure`（阻塞）+ `evidence_unverified`（阻塞） |

## 3. 关系类型 → 画法

| 关系 | 线 | 端标记 | 备注 |
|-|-|-|-|
| `activation` | 实线 | 实心三角 | 指向被调控者 |
| `inhibition` | 实线 | 垂直横杠 | **横杠在目标端** |
| `binding` | 实线 | 无 | 非定向，几何检查 **skip** |
| `transport` | 虚线 | 开放箭头 | 跨区室 |
| `modification` | 实线 | 空心三角 | 磷酸化/泛素化等 |
| `sequence` | 实线 | 无（编号） | 仅表先后 |
| `inclusion` | — | — | 嵌套框，无连线 |
| `unknown` | 虚线 | `?` | 材料说不清 |

## 4. 节点与画布 token

* 节点框：浅底 + 深色描边（`#33475B`），圆角 1.6；`kind` 只影响填充色，**不承载语义**；
* 语义只活在**边**上，因此灰度打印不丢信息；
* 图例一行：先关系（带样例箭头），后数据系列（带色块）；**图例项数 = 实际画出的类型数**；
* 画布内部按 **mm** 计算，输出 SVG 用户单位是 **pt**（`width/height` 仍标 `mm`），
  故 `font-size` 就是真实 pt，可直接核验字号。

## 5. 可溯源 token（机器可读）

| 元素 | `id` | `data-*` |
|-|-|-|
| 实体 | `node-<id>` | `data-entity`、`data-kind`、`data-band`、`data-source`、`data-quote` |
| 关系 | `edge-<id>` | `data-relation`、`data-glyph`、`data-source`、`data-quote` |
| 数据标记 | `mark-<类别>-<系列>` | `data-category`、`data-series`、`data-value`、`data-error`、`data-source` |
| 数据轴/误差棒 | — | `data-tick`、`data-role="error-bar"` |
| 图层 | `layer-<name>` | `data-layer` = `nodes`/`edges`/`data`/`legend`/`titles` |

**命名规则**：`id` 一律 `<类型>-<模型 id>`；类别/系列直接来自数据表**原值**（不改写、不拼音化），
便于与 CSV 逐字对照。

## 6. 编辑规则（保留来源）

* **允许**（`edit_order`）：`rename_node`（可带 `aliases`）、`set_relation`、`set_title`、`set_caption`；
  每次操作要求 `reason`；未触及元素 **逐字节保留**并写入 `source_preservation`；
* **设计上拒绝**：任何未列出的操作（如整图样式重排）⇒ `edit_order_refused`（**阻塞**）并逐条列出原因——
  **拒绝而不是静默忽略**，因为静默忽略等于交出一份「没有执行你要求」的图。

## 7. 启发式抽取与列推断（本包特有的约定）

1. 句子按 `.;!?` 切分，只处理**一句内 ≥2 个实体样式 token** 的句子；
   名字命中 `value|mean|expr|level|activity|rate|fold|值|表达|水平` 者为 `value_column`，
   命中 `sd|sem|se|std|stdev|error|ci|误差|标准差` 者为 `error_column`，
   文本列里 `time|condition|category|group|treat|时间|条件` → `category_column`，
   `gene|series|probe|sample|strain|基因|系列` → `series_column`。

## 7. 启发式抽取与列推断（摘要）

按 `.;!?` 断句 → 只取一句内 ≥2 个实体样式 token 的句子；实体 `\b[A-Z][A-Z0-9]{1,6}\b`（排除
`DNA/RNA/EXAMPLE`）；关系取句内第一个命中固定动词表的词（首个实体 source、第二个 target），
每条带原句并逐字回查材料；数据表取材料目录第一个 `.csv`/`.tsv`，列角色按「≥半数行为数字 → 数值列」
+ 列名关键词（`value|mean|expr|值|表达` / `sd|sem|error|误差` / `time|condition|条件` /
`gene|series|基因|系列`）推断。完整版与扩展方式见 `../ECOSYSTEM.md §6`。
