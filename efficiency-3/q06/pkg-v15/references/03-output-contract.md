# 03 · 输出契约与产物清单

平台契约可能以四种形态给出，`contract.py` 全部吃得下，并把**每个字段放到 `result.json` 顶层**：

| 形态 | 例子 |
|---|---|
| `{字段: 描述}` | `{"deliverable": "…", "evidence_map": "…"}` |
| JSON Schema | `{"type":"object","properties":{…},"required":[…]}` |
| 字符串数组 | `["deliverable","slides","evidence_map","status"]` |
| 缺失 | 使用默认集合 |

规则：文本字段无内容给 `""`，集合字段无内容给 `[]`，**绝不给 `null`**；读不懂的字段写进
`contract.unresolved`，不猜。

## 1. `result.json` 字段与来源

| 字段 | 类型 | 内容 | 可核验处 |
|---|---|---|---|
| `case_id` | str | 来自 `case.json` 的原值 | 与输入逐字一致 |
| `status` | str | `success` / `partial` / `unsupported` | 见 §3 |
| `deliverable` | str | 主线 + 页级主张阶梯（Markdown） | `deck-outline.md` |
| `deck` | obj | `pptx`/`pdf`/`slide_count`/`slides[]`/`template` | `deck.pptx`、`deck-readback.json` |
| `slides` | arr | 每页 `id/role/title/claim/bullets/evidence/numbers` | `plan.json` |
| `evidence_map` | arr | 每页 `claim/evidence_kind/label/locator/locator_verified/match/quote/numbers` | `evidence-map.json` |
| `notes` | str | 逐页讲稿 | `speaker-notes.md`、pptx 备注页 |
| `render` | obj | `engine`/`preview_mode`/`pdf`/`pngs`/`png_dir`/`fonts` | `render.json`、`slides/*.png` |
| `template` | obj | `available`/`path`/`layouts`/`slide_size_in` | `describe_template()` |
| `audit` | obj | `passed`/`total`/`dimensions`/`real_render` | `audit.json` |
| `sources` | arr | 实读材料 `path` + `reader` | `inventory.json` |
| `uncertainty` | arr | 材料缺口、无文字层、表体未还原、非真渲染、契约未解析字段 | 与 `audit`/`validation` 一致 |
| `changes` | arr | 每阶段一条 `{stage, note}` | `run.log` |
| `inventory` | obj | 证据底账统计（数字/图注/引文/局限…） | `inventory.json` |
| `validation` | obj | 证据锁结论（errors/warnings/metrics/**rigor_report**） | `validation.json` |
| `outputs` | arr | 交付物 `path`/`bytes`/`sha256`/`kind` | 逐条复算，见 §2 |
| `resolved_from` | obj | 每个材料/模板的 `{declared, resolved, resolved_from}` + `cwd` + 规则 | 本文件 §4 |
| `audit_deck` | obj | 只读产物重算的 A1–A8 结论 | `audit-deck.json` |
| `contract` | obj | 契约来源、字段名、未解析项、缺失项、命中计数、`self` | 本表 |
| `skill` | obj | `{"name":"paper2deck","version":"…"}` | `SKILL.md` |
| `runtime` | obj | 总耗时与阶段表 | `run.log` |

`contract.fields_total` / `fields_present` / `fields_empty` 给出契约键命中数（三案例均 8/8/[]）。

## 2. `outputs[]` 与 `contract.self`

每条含 `path`（相对 posix）/`bytes`/`sha256`/`kind`，在**写 `result.json` 之前**生成。
`result.json` **不入** `outputs[]`：文件无法诚实地携带自己的摘要（写进摘要就改变了被摘要的字节），
它由 `contract.self` 指认，并由 `audit_deck.py` 的 A2 复核其余每一条。

## 3. `status` 判定

- `success`：证据锁 0 error、六道闸全过（含真渲染成功或按请求跳过）、`outputs[]` 与独立审计无 fail。
- `partial`：以下任一情况——证据锁有 error、任一闸未过、渲染拿不到真预览、材料过薄、PDF 无文字层、
  表体未还原、**读到 0 段或产出 0 页**。此时 `uncertainty` 必须写明原因。
- `unsupported`：找不到可读材料（`materials` 全部缺失），无法建立任何证据。

## 4. 路径解析（与 cwd 无关）

相对路径按 `case.json` 所在目录 → `cwd` → `/input` 解析；绝对路径直接用（不存在记 `missing`）。
适用范围：`materials`/`material`/`sources`/`inputs`/`papers`/`files`/`input_files`/`paper`、`template`、
作者 `plan.json`、PDF 图提取输入。`sources[]` 每项也带 `resolved_from`。
目录遍历只按**相对 case 目录**的位置跳过 `output`/`outputs`（本包自己的输出），**绝不按绝对路径段过滤**：
包被 stage 到 `.../runs/.../stage/outputs/` 也不会吞掉输入。

## 5. 产物清单（`/app/output`）

`deck.pptx`（可编辑）· `deck.pdf`（真渲染）· `slides/slide-NN.png` · `plan.json` · `inventory.json` ·
`validation.json`（含 `rigor_report`）· `layout.json` · `render.json` · `deck-readback.json` · `audit.json` ·
`audit-deck.json` · `evidence-map.json` · `speaker-notes.md` · `deck-outline.md` · `run.log` · `result.json`
