# result.json 字段契约与状态语义

`result.json` 是唯一被判分读取的文件；它引用的 `figure.svg / figure.png / figure.pdf` 必须真实存在。
脚本把 `/input/case.json` 里的 `output_contract` 全部键原样回填（不改名、不遗漏），缺值用 `""`/`[]`，
**不写 null**；无法填充的键会记入 `not_reported`。

## 1 契约键（本题家族默认七字段）

| 键 | 类型 | 内容 | 生成者 |
|-|-|-|-|
| `case_id` | str | 输入原值 | 脚本 |
| `status` | str | `ok` / `partial` / `insufficient_evidence` / `input_error` | 脚本按实情 |
| `editable_source` | obj | `{path, format, editable, layers[], text_count, sha256, model_copy}` | 脚本 |
| `export_artifact` | obj | `{png:{path,width,height,dpi,engine,verified,ink_ratio,attempts}, pdf:{path,pages,vector,engine,verified,page_pt}}` | 脚本 |
| `content_map` | list | 元素级溯源（见 §3） | 脚本，内容来自 IR |
| `compliance_checks` | list | 逐项 `{check, required, measured, verdict, evidence}` | 脚本 |
| `exceptions` | list | `{element, issue, detail, handling}` | 脚本 |

追加字段（只增不改）：`status_reason`、`summary`、`outputs`、`sources`、`uncertainty`、`changes`、
`coverage`、`invariants`、`degradations`、`gaps`、`errors`、`not_reported`、`runtime`、
`contract_echo`、`font_report`。

## 2 状态语义（写错即判错）

| 场景 | 应写 | 常见错写 |
|-|-|-|
| IR 经撰写、引文命中、四要素齐、导出验真 | `ok` | —— |
| IR 来自 `init` 草稿，或某导出件未验真，或有致命 errors | `partial` + 原因 | 用 `ok` 掩盖 |
| 材料无可用文本/无数据 | `insufficient_evidence` + `gaps` | 反推/编造内容 |
| `case.json` 缺失或坏 JSON | `input_error` + `errors` | 静默成功 |
| 降级但产物齐（换了 PNG 引擎、字体替换）| 保持 `ok`/`partial` + 写 `degradations`/`exceptions` | 静默降级 |

## 3 content_map 条目形状

| kind | 关键字段 |
|-|-|
| `panel` | `order` `role` `title` `claim` `items[]` `source` |
| `entity` | `entity_id` `label` `entity_type` `compartment` `italic` `on_canvas` `source` |
| `relation` | `relation_id` `from` `to` `relation_type` `direction` `label` `on_canvas` `source` |
| `value` | `claim_id` `label` `value` `unit` `compare{}` `on_canvas` `source` |
| `data_point` | `chart` `series` `x` `y` `raw_value` `unit` `err` `source{file,row,header,quote}` |
| `legend` | `key` `label` `channel` `color` `pattern` `category` `source` |

`id` 必须与 SVG 中的元素 `id` 一致（`compliance_checks.id_map` 逐条断言）。

## 4 机器断言（`invariants`，全部由脚本计算）

| 断言 | 判据 | 写入位置 |
|-|-|-|
| 图例一致 | 图例项数 == 图面分类数（关系类型 + 系列） | `invariants.legend` + `compliance_checks.legend_consistency` |
| 数值可回查 | 画布上每个数字命中 source quote / claim / 数据点 | `invariants.numbers`（未命中列入 `uncertainty`）|
| 灰度安全 | 系列数 >1 时每个系列都有图案 | `invariants.grayscale` |
| 版式适配 | 每面板 `needed_px <= height_px`，无文本越界 | `invariants.panels` + `invariants.fit` |
| 导出真实 | PNG 解出 IHDR 且非空白；PDF 有头与页对象 | `export_artifact.*.verified` |
| 可编辑 | SVG `<text>` 数 == 场景文本数 | `compliance_checks.editable_text` |
| 可复跑 | 同 IR 两次渲染 SVG `sha256` 一致 | `tests/selftest-report.json` |

## 5 交付清单（提交前逐项打勾）

- [ ] `/app/output` 内有 `figure.svg`、`figure.png`、`figure.pdf`、`result.json`、`figure-ir.json`、`run.log`。
- [ ] `result.json` 的契约键一个不少，`case_id` 与输入一致，`status` 与实情一致。
- [ ] `content_map` 每个条目都有 locator + 逐字 quote；未命中者已写进 `uncertainty`。
- [ ] `compliance_checks` 无 `fail`；有 `warn` 时在 `exceptions` 解释。
- [ ] `figure.svg` 打开可见分层与可选中文字；`figure.png` 能打开且不是空白。
