# IR 模式（中间表示）· 可核对的契约

`apparatus.py` 读材料 → 生成 `figure.ir.json` → 由 IR 渲染 SVG 与 `result.json`。
**这份文件就是契约**：`scripts/validate_ir.py` 按它判 IR 自身；`scripts/check_consistency.py` 另判
"材料 ↔ IR ↔ SVG ↔ result.json 说的是不是同一件事"。

```bash
python3 scripts/apparatus.py --case <case.json> --out <out>       # 产出 <out>/figure.ir.json
python3 scripts/validate_ir.py --ir <out>/figure.ir.json          # 只判 IR（0/1）
python3 scripts/check_consistency.py --ir <out>/figure.ir.json --materials <case_dir> \
        --svg <out>/figures/figure.svg --result <out>/result.json # 只判一致性（0/1）
```

## 1. 顶层字段
| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| `schema` | `"apparatus/ir/1"` | ✓ | 版本标识 |
| `figure_type` | `apparatus` \| `route` | ✓ | 由 `figure_kind` 映射：`schematic→apparatus`，`flow`/`roadmap→route` |
| `figure_kind` | `schematic`\|`flow`\|`roadmap` | ✓ | 面板布局用 |
| `case_id` / `title` | string | ✓ | 原样回填 |
| `canvas_mm` | `[w, h]` | ✓ | 与 SVG `width="…mm"` 一致 |
| `elements` / `relations` | array | ✓ | §2 / §3 |
| `extraction_index` | array | ✓ | 覆盖索引（§4），正确性的抓手 |
| `numbers` | array | — | 材料的"数字+单位"：`label/value/unit/source` |
| `materials` / `unreadable` | array | — | 发现到的材料 / 读不出的文件 + 原因 |
| `resolved_from` | object | ✓ | 路径解析：`case_dir` / `search_order` / `refs[{ref,resolved,resolved_from}]` |
| `gaps` | array | — | 材料没写、因而不画的东西 + 原因 |

## 2. element
```json
{"id": "U2", "label": "蠕动泵 Peristaltic pump", "kind": "unit.instrument", "panel": "A",
 "seq": null, "certainty": "quoted",
 "source": {"locator": "methods.md#L5", "quote": "| 蠕动泵 Peristaltic pump | P-1 | 1 |"}}
```
* `kind` 必须来自 `references/symbol_library.md`；`panel` 是面板 id。
* `certainty` ∈ `quoted`（材料明示）| `inferred`（只在行文里出现，未在清单声明；照样画，但进 `uncertainty`）。
* `source.locator` = `文件名#Lnn`（行/表格）或 `文件名#Lnn-mm`（段落块）；`source.quote` **必须逐字**
  来自材料（空白归一化后可回溯，硬判）。键名用 `locator`（与 `result.json.sources[].path` 同键义）。

## 3. relation
```json
{"id": "E1", "from": "U1", "to": "U2", "kind": "material", "certainty": "quoted",
 "source": {"locator": "methods.md#L9", "quote": "将培养基储液瓶接入蠕动泵 P-1 进口。"}}
```
方向 = 流向（`from` 上游、`to` 下游；被动句也按上游→下游校正）。`kind` ∈ `material` | `signal` |
`energy` | `loop` | `dependency`。端点必须存在；**指代不明不产生连线**（改为写 `uncertainty`）。

## 4. extraction_index（覆盖索引）
材料里读到的**每个**部件/步骤/阶段一条：
```json
{"mention": "蠕动泵 Peristaltic pump", "quote": "| 蠕动泵 Peristaltic pump | P-1 | 1 |", "mapped_id": "U2"}
{"mention": "废液收集瓶", "quote": "…", "status": "omitted", "reason": "超出装置面板容量（最多 12 个）"}
```
不变量：① 每条要么 `mapped_id` 指向真实 element，要么 `status="omitted"` **且**有 `reason`；
② 每条必须有 `quote`；③ 反向：**每个画出来的 element 都必须在索引里出现**（防"画了没记账"）。

## 5. 两个校验器的边界
| | `validate_ir.py` | `check_consistency.py` |
|-|-|-|
| 输入 | 只有 IR（+ 图元库文档） | 材料 + IR + SVG + `result.json` |
| 只判 | IR **自身**（枚举/唯一性/端点/索引不变量/**库同步**） | **跨产物一致**（逐字回溯/覆盖/id 集合/哈希/箭头/数字来源/状态诚实） |
| 退出码 | 0 合规 / 1 有错误 | 0 通过 / 1 有硬失败 |

拆开的好处：IR 有问题时**报错点唯一**；一致性问题不必怀疑 IR 本身。两者都只读，不写产物。

## 6. 抽取规则（IR 从哪来）
材料发现只 glob `case.json` 所在目录之下（**绝不按绝对路径目录段过滤**）；`case.json` 点名的相对路径
按 `case_dir → cwd → /input` 解析。判据：实体=部件词表命中或 `A-1` 式位号；关系=显式流向动词；
步骤=编号 + 并行/终止/回流线索；阶段=`Phase/Stage/阶段 N`；数值=数字+单位成对。
**读不到的不写进 IR**——缺就缺，宁少勿错。
