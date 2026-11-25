# 图元库（symbol library）· 可核对的契约

IR 里每个 `kind` 在这里都有且只有一条：**一个类型一个画法**。`validate_ir.py` 会把 IR 用到的每个
`kind` 回查本文件——**这里漏写一个类型，校验直接硬失败**（文档即契约）。

## 1. 语义类型（`element.kind` → 填充/描边/文字）
| kind | 含义 | 配色 | 同义词（映射到本行） |
|-|-|-|-|
| `unit.vessel` | 容器/瓶/罐/腔/柱/捕集器 | `#E8F4EC`/`#2C6E49`/`#12351F` | reservoir, reactor, bottle, chamber, column, 储液瓶, 反应釜, 培养腔 |
| `unit.instrument` | 泵/阀/炉/离心机/氧合器/流量计 | `#E3F0F7`/`#1F6E8C`/`#0E3547` | pump, valve, furnace, centrifuge, oxygenator, 蠕动泵, 马弗炉 |
| `unit.utility` | 废液/废气/真空/冷却/气瓶 | `#F4F1E8`/`#7A6A3A`/`#3A3318` | waste, exhaust, vacuum, coolant, cylinder, 废液收集瓶, 气瓶 |
| `unit.sensor` | 传感器/探头/表/记录仪 | `#F3ECF9`/`#5B3E82`/`#2C1D40` | thermocouple, sensor, probe, gauge, 热电偶, 压力表 |
| `unit` | 未能归类（兜底，不硬凑） | `#EAF2FB`/`#1F4E79`/`#10314D` | 一切没有更贴近类型的部件 |
| `step.main` | 主序列步骤 | `#F2F7EE`/`#3F6B2C`/`#24391A` | `1.`/`步骤1`/`Step 1` 且无并行/终止/回流线索 |
| `step.parallel` | 并行支路 | `#FDF3E3`/`#A96B12`/`#4A2E05` | 含 同时/并行/parallel/simultaneous |
| `step.loop` | 回流/迭代 | `#EFF3F6`/`#3A5F7D`/`#1E3444` | 含 回到步骤N/返回/repeat/go to step N |
| `step.terminal` | 终止/判定 | `#E9EEF3`/`#243B53`/`#101E2B` | 含 结束/终止/判定/stop/end/terminate |
| `phase` | 技术路线阶段 | `#F7F4EC`/`#8A6D3B`/`#3D3018` | `Phase N`/`Stage N`/`WP-N`/`Task N`/`阶段N` |

**映射靠功能不靠词面**；材料自造的名称归不进就用 `unit`，不硬凑。同类多台用 id 区分（`U1`/`U2`），
`label` 保留材料原名（`P-1`/`P-2`）。

## 2. 连线类型（`relation.kind` → 线型/颜色）
| kind | stroke-dasharray | 颜色 | 含义 |
|-|-|-|-|
| `material` | 实线 | `#1F4E79` | 物料/气体流动 |
| `signal` | `2 3` | `#2E7D6F` | 信号/测量/记录 |
| `energy` | `6 3` | `#B4531A` | 加热/冷却/能量 |
| `loop` | `4 4` | `#8894A0` | 回流/循环 |
| `dependency` | `7 4 2 4` | `#7A4E9B` | 阶段依赖（roadmap 按阶段顺序生成） |

箭头：每条连线**恰好一个**，尖端与折线末点误差 ≤1.5 px。线宽：`material` 2.0、其余 1.5。

## 3. 语义图层（SVG `layer-*`）
`layer-rulers`（比例尺 40 mm）· `layer-units`（图元框）· `layer-connectors`（连线/箭头）·
`layer-labels`（真实 `<text>`，未转曲）· `layer-legend`（按用到的语义自动生成，颜色与图元同源）·
`layer-annotations`（标题/面板标题/页脚）。`check_consistency` 要求 ≥3 个语义图层（常态 5–6 个）。

## 4. data-* 属性（生成器写、校验器读，必须同名）
| 属性 | 位置 | 用途 |
|-|-|-|
| `data-role` | 所有元素 | `node-shape`/`node-label`/`phase-title`/`connector`/`arrowhead`/`legend-*`/`scale-bar*` |
| `data-node` / `data-kind` | 图元框与文字 | = `IR.elements[].id` / `.kind`（id 集合双向相等是硬检查） |
| `data-quote` / `data-src` | 图元框与文字 | 原文引文（≥80% 覆盖）/ 定位符（`#`→`@`） |
| `data-fid`/`data-flow`/`data-from`/`data-to` | 连线与箭头 | 连线 id / 语义 / 两端 id |

> `role` 由绘图层**统一序列化为 `data-role`**，且显式 `data-role` 优先。历史上这里曾写成 `role=`，
> 导致溯源检查恒定失败（`INNOVATION.md §4`）——**键名就是接口**。

## 5. 图例与比例尺
图例只为图里**真正用到**的 kind 生成条目，颜色/线型直接取自本文件（改本表 = 改图）；
比例尺固定 40 mm，`scale-bar` 折线长度与 `scale-bar-text` 标注误差 ≤1% 或 0.3 mm。
