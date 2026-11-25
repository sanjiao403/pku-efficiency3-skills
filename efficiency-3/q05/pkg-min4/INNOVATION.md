# INNOVATION · 创新点（一页）

## 1. IR 先行：把"中间表示"写成可核对的契约
材料 → **IR（`figure.ir.json`）** → 图。IR 是**交付物之一**而非内部草稿，字段与不变量写在
`references/ir_schema.md`：`figure_type`(apparatus|route)、`elements[]`(id/label/kind/panel/
certainty/source{locator,quote})、`relations[]`(from/to/kind)、`canvas_mm`、`resolved_from`，
以及 **`extraction_index[]`（覆盖索引）**：材料里读到的**每个**部件/步骤/阶段一条，要么 `mapped_id`
指向真画出来的图元，要么 `status="omitted"` **且写明 `reason`**。于是"漏画"与"画了没依据"都变成
可判真假的错误，而不是评审的主观印象。

## 2. 两个职责单一的校验器 + 文档即契约
| | `validate_ir.py` | `check_consistency.py` |
|-|-|-|
| 只读 | IR + 图元库文档 | 材料 + IR + SVG + `result.json` |
| 只判 | IR **自身**（schema/枚举/唯一性/端点/索引不变量） | **跨产物一致**（逐字回溯/覆盖/id 集合/哈希/箭头/数字来源） |
| 报错点 | IR 的问题只在这里出现 | 一致性的问题只在这里出现 |

再加一条**"文档即契约"**硬检查：`validate_ir.library.kind_documented` 把 IR 用到的每个 `kind`
回查 `references/symbol_library.md`——**图元库漏写一个类型，校验直接硬失败**。文档不再可能"写漏了
也没人发现"。

## 3. 对照臂与主路径**同入口**
`apparatus.py --arm naive` 是同一入口内的真实实现（按材料顺序逐行画框：不分类/不溯源/不连线/
无图例/不自检/**不产 IR**），不是模拟、也不是事后补的稻草人：两臂同输入、共用导出，再由**同一个**
`check_consistency.py` 量；任何人一条命令即可重跑（`GAIN.md`）。增益因此从自述变成算术，且不依赖
外部平台。

## 4. 先有反例、后有守卫：`role=` vs `data-role` 溯源 bug
**反例（真实发生过）**：早期绘图层把语义角色写成 `role="node-shape"`，而校验器读的是
`data-role="node-shape"`。后果有两层：
* **静默失效**：`provenance.blocks_have_quote` 永远数到 0 个图元 → 溯源检查**恒定失败**，而生成器侧
  一切"看起来正常"；
* **更硬的一层**：调用方显式传 `data-role` 时，旧写法又同时输出默认 `role`，被改写后产生**重复属性**
  → XML 不可解析 → 产物**打不开**（硬失败）。

**守卫（现已落地）**：
1. 绘图层统一把 `role` 序列化为 `data-role`，且**显式 `data-role` 优先**（不重复输出）；
2. `check_consistency.py` 保留 `provenance.blocks_have_quote` 作为**硬**检查（<80% 引文覆盖即失败）；
3. `tests/gain_cases.json` 两条回归反例：`probe-missing-provenance`（剥掉 `data-role`/`data-quote`/
   `data-src` → `consistency_ok` 由 `true` 翻 `false`）与 `probe-invalid-ir`（破坏索引不变量 →
   `ir_ok` 由 `true` 翻 `false`）。改写前后成对落盘，守卫"会不会响"可被判真假。

**教训（也写进 `references/symbol_library.md §4`）**：语义标记的**名字**就是接口。凡是"生成器写的键"
与"校验器读的键"不是一个字符串，就会得到最糟的失败——**看起来在跑、实际永远不通过**。所以本包把
"键名一致"变成会响的硬检查，而不是靠约定。

## 5. 零前提自足与路径无关
不依赖预置 IR、不依赖对照数据、无额外开关；核心布局零第三方依赖（仅 PDF/PNG 需渲染后端，缺失时
如实降级并保留 SVG）。输入发现只 glob `case.json` 所在目录之下，**绝不按绝对路径目录段过滤**；
`case.json` 点名的相对路径按 `case_dir → cwd → /input` 解析并记入 `resolved_from`——整包被拷到含
`outputs`/`runs`/`stage` 的路径下也照常工作（`GAIN.md §3`）。
