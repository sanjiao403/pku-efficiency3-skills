# result-schema · `result.json` 字段表（人读版）

> 机器可读版随包：`references/result.schema.json`。校验命令：
> `python3 scripts/audit_only.py --out <out> --check-schema`（**零第三方依赖**，内置校验器）。
> 规则：字段**不允许缺失**——产不出就写 `null`，并在 `uncertainty` 说明为什么，绝不省略。

## 1. 顶层（全部必需）

| 字段 | 类型 | 含义 | 产生阶段 |
|---|---|---|---|
| `case_id` | string | 输入标识原样回写 | 输入 |
| `task` | string\|null | 任务名 | 输入 |
| `status` | `success`\|`partial` | 全绿才 success（判据见 §3） | 汇总 |
| `status_reason` | string | 具体原因（缺哪个文件/哪项不达标） | 汇总 |
| `summary` | string | 一句话事实摘要（页数/证据数/关键读数） | 汇总 |
| `generated_at` | string(ISO8601) | 带时区时间戳 | 汇总 |
| `outputs[]` | array | 产物清单：`path`+`bytes`+`sha256`（+`kind`/`exists`） | 汇总（写盘后重算） |
| `artifacts[]` | array | 同上（兼容键，内容一致） | 汇总 |
| `results` | object | 分步证据（§2） | 各阶段 |
| `slides[]` | array | 页级：`page`/`role`/`layout`/`title`/`claim`/`evidence_locs`/`figure`/`font_sizes`/`overflow`/`render` | 计划+复核 |
| `evidence[]` | array | `page`+`locator`+`block_id`+`quote`+`verified` | 证据 |
| `sources[]` | array | `file`/`kind`/`sha256`/`chars`（PDF 另有 pages） | 抽取 |
| `uncertainty[]` | array | `item`+`why`+`handling` | 全程 |
| `changes` / `change_log[]` | array | 每步做了什么、证据在哪（两键同内容） | 流水线 |
| `capability_boundary[]` | array | 能证明/不能证明什么 | 固定 |
| `reproduce` | string | 复跑命令 | 固定 |
| `narrative` / `narrative_source` | string\|null | agent 写的叙述与来源标注 | 可选 |
| `output_contract_echo` | object | 输入 `output_contract` 声明字段的回显 | 汇总 |
| `contract_unresolved_fields[]` | array | 回显为 null 的字段名 | 汇总 |
| `resolution` | object | 解析账本：`cwd`/`case_json`/`case_dir`/`entries[]`（`kind`/`given`/`resolved`/`resolved_from`） | 输入阶段 |
| `pipeline` | object | `steps[]`/`guards[]`/`errors[]`/`elapsed_s` | 编排 |

## 2. `results` 子结构

| 键 | 必需字段 |
|---|---|
| `template` | `path`、`origin`（`case(origin)` 或 `spec-synth(<spec>:<name>)`）、`slide_size`、`layout_count`、`roles`、`theme_fonts`、`inheritance{layouts_out,layouts_template,layouts_preserved,theme_out,theme_template,theme_preserved}` |
| `plan` | `stats{slides,bullets,figures_used}`、`dropped_content[]`、`font_plan`、`ladders` |
| `build` | `slides`、`warnings[]`、`sha256`、（逐页）`font_sizes`/`font_scale`/`placeholders_synthesized`/`footer_page_number` |
| `fit` | `metrics{slides,overflow_boxes,min_body_pt,figure_aspect_max_deviation,locator_coverage,quote_verified_rate,geometry_inherited_slides}`、`issues[]`（`severity`∈high/medium/low） |
| `render` | `ok`、`backend`(`soffice`/`powerpoint`/`none`)、`page_count`、`pages[]{page,text_coverage,images}`、`fonts[]`、`missing_fonts[]`、（失败时）`attempts[].error` |
| `figures`（可选） | `figure_specs` 出图记录：`out`/`csv`/`csv_sha256`/`rows` |

## 3. `status=success` 的判据（全部满足；否则 `partial` 且必须写具体原因）

1. pptx 落盘且可被重新打开（`outputs[]` 里有 `editable-presentation`）；
2. 渲染链产出 PDF：`results.render.ok=true`；**无后端 → partial**，`backend="none"`、error 原文、
   不写假 PDF、`page_count`/`text_coverage` 保持 `null`；
3. 无 `high` 级问题（阈值见 `fallbacks-and-exceptions.md` §5）：版式数变化、正文 <14pt、
   图宽高比偏差 >0.5%、引文无法回源、数字不在材料、文本框溢出 >20%、PDF 页数≠pptx 页数、覆盖率 <97%；
4. `results.fit.metrics.quote_verified_rate == 1.0` 且 `locator_coverage == 1.0`；
5. 空产物守卫未触发（0 页/0 内容块一律 partial）。

## 4. 两条证明路径（为什么 schema 有意义）

- **生成器自证**（运行期）：页数约束、占位符继承（`a:xfrm` 计数=0）、引文+数字溯源、渲染一致性。
- **只读重算**（`audit_only.py --out`）：只读 `result.json` + `pptx`（+`work/template.pptx`）重算同类指标，
  与自述值逐项对照（expected vs actual），写 `verify_report.json`；`--check-schema` 再校验字段完整性。
- `result.json` 的自身完整性由旁边的 `result.sha256` 承担（自指哈希放不进自身）。
