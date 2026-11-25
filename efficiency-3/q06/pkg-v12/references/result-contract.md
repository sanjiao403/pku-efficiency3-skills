# result.json 契约字段表

平台契约可能以四种形态给出，`contract.py` 全部吃得下，并把**每个字段放到 `result.json` 顶层**：

| 形态 | 例子 |
|---|---|
| `{字段: 中文描述}` | `{"deliverable": "…", "evidence_map": "…"}` |
| JSON Schema | `{"type":"object","properties":{…},"required":[…]}` |
| 字符串数组 | `["deliverable","slides","evidence_map","status"]` |
| 缺失 | 使用下表默认集合 |

规则：文本字段无内容给 `""`，集合字段无内容给 `[]`，**绝不给 `null`**；
读不懂的字段写进 `result.contract.unresolved`，不猜填。

## 本包产出并回显的字段

| 字段 | 类型 | 内容 | 可核验处 |
|---|---|---|---|
| `case_id` | str | 来自 `case.json` 的原值 | 与输入逐字一致 |
| `status` | str | `success` / `partial` / `unsupported` | 见下方判定 |
| `deliverable` | str | 主线 + 页级主张阶梯（Markdown） | `deck-outline.md` |
| `deck` | obj | `pptx`/`pdf`/`slide_count`/`slides[]`/`template` | `deck.pptx`、`deck-readback.json` |
| `slides` | arr | 每页 `id/role/title/claim/bullets/evidence/numbers` | `plan.json` |
| `evidence_map` | arr | 每页 `claim / evidence_kind / label / locator / locator_verified / match / quote / numbers` | `evidence-map.json` |
| `notes` | str | 逐页讲稿（Markdown） | `speaker-notes.md`、pptx 备注页 |
| `render` | obj | `engine` / `preview_mode` / `pdf` / `pngs` / `png_dir` / `fonts` | `render.json`、`slides/*.png` |
| `template` | obj | `available` / `path` / `layouts` / `slide_size_in` | `describe_template()` |
| `audit` | obj | `passed` / `total` / `dimensions` / `real_render` | `audit.json` |
| `sources` | arr | 实读材料 `path` + `reader` | `inventory.json` |
| `uncertainty` | arr | 材料缺口、无文字层、表体未还原、非真渲染、契约未解析字段 | 与 `audit`/`validation` 一致 |
| `changes` | arr | 每阶段一条 `{stage, note}` | `run.log` |
| `inventory` | obj | 证据底账统计（数字/图注/引文/局限…） | `inventory.json` |
| `validation` | obj | 证据锁结论（errors/warnings/metrics） | `validation.json` |
| `performance` | obj | `seconds` + 各阶段耗时 | `run.log` |
| `contract` | obj | 契约来源、字段名、未解析项、缺失项 | 本表 |
| `skill` | obj | `{"name":"paper2deck","version":"1.0.0"}` | `SKILL.md` |
| `runtime` | obj | 总耗时与阶段表 | `run.log` |

若契约里出现本包未产出过的字段名，会被映射到最接近的产出字段（`contract._FIELD_ALIASES`），
映射不到则按类型给 `""`/`[]` 并记入 `contract.unresolved`。

## `status` 判定

- `success`：证据锁 0 error、六道闸全过（含真渲染成功或按请求跳过渲染）、
  `result.json` 写入成功。
- `partial`：以下任一情况——证据锁有 error、任一闸未过、渲染拿不到真预览、
  材料过薄、PDF 无文字层、表体未还原等。**此时 `uncertainty` 必须写明原因**。
- `unsupported`：找不到可读材料（`materials` 全部缺失），无法建立任何证据。

## `deck.json` 之外的产物清单（供复核）

`deck.pptx`（可编辑）· `deck.pdf`（真渲染）· `slides/slide-NN.png`（逐页预览）·
`plan.json` · `inventory.json` · `validation.json` · `layout.json` · `render.json` ·
`deck-readback.json` · `audit.json` · `evidence-map.json` · `speaker-notes.md` ·
`deck-outline.md` · `run.log`
