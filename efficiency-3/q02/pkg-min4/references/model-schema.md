# Model & result schema — 输入模型、数据块与产物契约

只列**实际会被读取/写出**的字段。语义规则见 `symbol-conventions.md`。

## 1. 输入：`case.json`（唯一必需的是 `case_id`）

| 字段 | 必填 | 说明 |
|-|-|-|
| `case_id` | ✓ | 回显进 `result.json.case_id`（缺失时用文件名） |
| `task` / `title` | — | 回显 |
| `material_dir` | — | 材料目录；**相对 `case.json` 所在目录解析**，再回退材料目录 → cwd → `/input` |
| `figure_spec` | — | 自备图模型路径；**没有也能跑**（启发式推导） |
| `edit_order` | — | 编辑单路径（或内联对象） |
| `output_contract` | — | 契约声明，四种形态都支持：字段字典 / JSON-Schema / 字符串列表 / 对象列表 |

## 2. 输入：材料（`material_dir` 内）

可读：`md / txt / tex / csv / tsv / json / rst / html / xml`。
二进制或 Office 件（`.pdf/.docx/.pptx/.xlsx/...`）**不读不猜**，只记进 `not_reported[]`。

## 3. 可选图模型（`figure_spec`）

| 字段 | 说明 |
|-|-|
| `figure_type` | `mechanism` / `chart`（缺省按是否有 `data.table` 判定） |
| `canvas` | `{width_mm, margin_mm, font_pt, line_pt}`；高度由内容算出 |
| `title` / `caption` | 文字 |
| `nodes[]` | `{id, label, kind, band, aliases, evidence[{source, quote}]}` |
| `edges[]` | `{id, source, target, relation, evidence[...]}`；`relation` 必须属于固定 8 词词表 |
| `data` | `{table, category_column, series_column, value_column, error_column, value_unit, x_title, y_title, show_values}` |
| `evidence[]` | 图级引文（会一起进 `element_sources`） |

## 4. 产物：`figure.svg`

分层可编辑 SVG：真实 `<text>`；图层 `layer-nodes` / `layer-edges` / `layer-data` /
`layer-legend` / `layer-titles`；元素 `id` + `data-*` 见 `symbol-conventions.md §5`。
**它同时是矢量导出件**（本极简版不产 PDF/PNG）。

## 5. 产物：`result.json`（28 个顶层键）

| 字段 | 来源 |
|-|-|
| `case_id` / `task` | 回显 `case.json` |
| `status` | **只由** `checks.blocking.{model_errors,data_errors}` 决定（两项为 0 ⇒ `success`） |
| `status_reason` | 为什么 `partial`（阻塞项名 / 输入缺失） |
| `summary` | 一行结论 + 实测数字 |
| `deliverable` / `editable_source` | 主产物说明 |
| `exports[]` | SVG 的实测属性：`vector`/`text_as_text`/`text_elements`/`raster_elements`/`canvas_mm`/`font_pt` |
| `outputs[]` | 产物清单：`kind`/`path`/`rel`/`bytes` |
| `element_sources[]` | 逐元素：`element_id`/`element_type`/`label`/`relation`/`source`/`locator`/`quote`/`verified_in_material` |
| `data_mapping` | 列映射 + `categories`/`series`/`colors`/`rows`/`unit` |
| `checks` | `ok`/`items[]`（`check`+`severity`）/`counts`/`blocking`/`legend`/`export` |
| `uncertainty[]` | `{item, why, handling}` 逐条 |
| `manual_review[]` | warn 级发现，默认「保留原样」 |
| `not_reported[]` | 材料里**没有**因此不报的内容（如未读的二进制件） |
| `gaps[]` | `{item, why, alternative_evidence}` |
| `changes[]` / `source_preservation` | 编辑案例的逐操作前后 + 未触及元素证明 |
| `change_log[]` | 人类可读时间线 |
| `sources[]` | 材料清单：`rel`/`bytes`/`readable`/`note` |
| `metrics` | `entities`/`relations`/`data_marks`/`categories`/`series`/`canvas_mm`/`font_pt`/`svg_text_elements`/`evidence_quotes`/`evidence_verified`/`evidence_verify_rate`/`seconds`/`spec_sha256` |
| `run_log` | `seconds`/`spec_source`/`spec_path`/`case_path`/`material_dir` |
| `resolved_from` | `case`/`case_dir`/`material_dir`/`material`/`spec`/`spec_source`/`order` |
| `contract_echo` / `contract_fields_declared` / `contract_missing_required` | 契约透传：逐字段回显；缺值的必填字段**列出而不编造** |
| `self_scored` | 恒 `false`（不自评分数） |

## 6. 契约透传规则

   必填者同时进 `contract_missing_required`；
   `export`/`preview` → `exports`，`files`/`artifacts` → `outputs`，
   `evidence`/`provenance` → `element_sources`，`notes` → `change_log`。

## 7. 校验产物（只读复核）

`scripts/verify.py --result <out>/result.json --case <case.json> [--svg <fig.svg>]`
读回 `result.json` 与 `figure.svg`，重算并输出 `pass`/`fail`/`skip` 行与总判定
（末行 `VERIFY_OK` / `VERIFY_FAIL`，退出码 0/1/2）。它**不写任何产物**。

**契约透传**：键名匹配 `contract|output|schema|expect` 的节点（含嵌套）会被解析；四种形态
（字段字典 / JSON-Schema / 字符串列表 / 对象列表）都支持；结果逐字段写进 `contract_echo`
（含 6 个别名映射），无值的必填字段进 `contract_missing_required`，**不编造**。
