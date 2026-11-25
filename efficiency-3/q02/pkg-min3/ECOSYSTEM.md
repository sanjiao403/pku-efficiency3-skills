# ECOSYSTEM — 别人怎么复用这个包

## 1. 复用入口（三条，按需要选）

```bash
# ① 直接跑最小示例（刻意不含 spec：证明启发式即可出图）
python3 scripts/schematic.py --case examples/case.example.json --out /app/output

# ② 换成自己的材料：case.json 只需 case_id + material_dir
#    material_dir 里的 md/txt/csv 会被自动读取；CSV 会被自动发现并推断列角色
python3 scripts/schematic.py --case /path/to/my/case.json --out /path/to/out

# ③ 想精确控制图模型（可选，不是必需）：在 case.json 里加 "figure_spec": "figure.json"
python3 scripts/schematic.py --case /path/to/my/case.json --out /path/to/out
```

## 2. 输入契约（最小可用）

```json
{"case_id": "my-case", "material_dir": "materials"}
```

可选字段：`task`/`title`（回显）、`figure_spec`（自备模型）、`edit_order`（改图）、
`output_contract`（四种形态：字段字典 / JSON-Schema / 字符串列表 / 对象列表）。

**自备模型（可选）**：`figure_type`、`canvas{width_mm,margin_mm,font_pt,line_pt}`、`title`、`caption`、
`nodes[]{id,label,kind,band,aliases,evidence[]}`、`edges[]{id,source,target,relation,evidence[]}`、
可选 `data{table,category_column,series_column,value_column,error_column,value_unit}`。

**关系词表（固定，不可自造）**：`activation` `inhibition` `binding` `transport` `modification`
`sequence` `inclusion` `unknown` —— 箭头语法见 `references/figure-rules.md §1`。

## 3. 产物契约（判分侧只需读两个文件）

| 文件 | 用途 |
|-|-|
| `figure.svg` | 可编辑源文件**兼**矢量导出：真实 `<text>`、`data-layer` 分层、元素 `id` + `data-source` |
| `result.json` | 主结果：`status`/`summary`/`element_sources[]`/`data_mapping`/`checks`/`uncertainty[]`/`gaps[]`/`metrics`/`resolved_from`/`contract_echo` 等 28 键 |

稳定字段（可放心依赖）：`case_id`、`status`、`status_reason`、`summary`、`editable_source`、
`exports[]`、`outputs[]`、`element_sources[].{element_id,source,locator,quote,verified_in_material}`、
`data_mapping.{category_column,series_column,value_column,error_column,categories,series,colors}`、
`checks.blocking.{model_errors,data_errors}`、`metrics.{entities,relations,data_marks,evidence_verify_rate}`、
`resolved_from`、`contract_echo`、`self_scored`（恒 `false`）。

## 4. 可直接搬用的资产

| 资产 | 位置 | 怎么用 |
|-|-|-|
| 关系语法（8 词 + 画法 + 禁止项） | `references/figure-rules.md §1` | 直接抄进任何绘图规范的 README |
| 启发式抽取/列推断规则 | `references/figure-rules.md §2–§3` | 换成你的领域词表/列名正则即可 |
| 失效清单 → 拦截手段表 | `references/figure-rules.md §5` | 当作图稿交付前的 checklist |
| 独立重算脚本 | `scripts/verify.py` | 换成你的产物字段即可复用到别的图表工程 |
| **带标签增益校验** | `scripts/gain_check.py` | 把三个内联案例换成你的材料/模型，保留「标签先写死、运行后判定」的方法 |
| 最小输入样例 | `examples/case.example.json` + `examples/materials/*` | 复制即可起步（合成材料，标「示例（非正式答案）」） |

## 5. 限制（复用前必读）

* 画布是**确定性 4 列网格**，不是排版引擎：>20 实体建议分批、或加 `canvas.width_mm`；
* 不读二进制/Office 材料（不 OCR、不猜），记 `not_reported[]`；
* 不内嵌字体；**不产出 PDF/PNG**（SVG 兼任矢量导出）；
* 数据编码是单面板柱状条带（无多轴/拟合/统计检验）；
* 编辑只支持 4 种操作，其余**阻塞拒绝**；
* 单案例 < 0.1 s、零第三方依赖、零网络；包体 ≤14 文件 / ≤110 KB。

## 6. 怎么扩展

| 想加什么 | 改哪里 |
|-|-|
| 新关系词/新动词 | `scripts/schematic.py` 的 `REL` / `VD`，同步更新 `references/figure-rules.md §1` |
| 新图型（如时序/流程图） | 在 `layout()` + `render()` 增加分支；保持 `id` / `data-*` 与 `element_sources` 契约不变 |
| 新列名习惯 | `find_table()` 里的正则与 `data_of()` 的列角色候选 |
| 新检查项 | `check_model()` / `run()` 内追加 `E(F, "<check>", "<message>", "warn"|"error")`；
  **阻塞项会自动把 `status` 变成 `partial`**，无需另写逻辑 |
| 新契约字段 | 不用改代码：`output_contract` 会自动回显；缺值进 `contract_missing_required` |

扩展后务必复跑：`python3 scripts/gain_check.py`（末行 `GAIN_OK`）与
`python3 scripts/verify.py --result <out>/result.json --case <case>`（末行 `VERIFY_OK`）。
