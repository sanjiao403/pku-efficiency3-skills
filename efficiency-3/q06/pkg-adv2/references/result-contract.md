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
| `render` | obj | `engine` / `preview_mode` / `pdf` / `pngs` / `png_dir` / `fonts` / **`verification`** | `render.json`、`slides/*.png` |
| `render.verification` | obj | **预览件的实测记录**：`checked` / `issues[]` / `warnings[]` / `pdf.pages` / `pdf.page_size_in` / `pdf.fonts_embedded` / `pdf.fonts_are_subset_embedded` / `fonts_requested_not_embedded` / `pages[].px` / `pages[].dpi` / `pages[].ink_ratio` / `pages[].blank` / `shapes.declared_without_object` / `summary` | 由 `render.verify()` 在渲染后当场测量；`audit_deck.py` A9 独立复算 |
| `materials_resolved` | arr | 每条声明材料 `declared` / `path` / `resolved_from`（`case_dir` / `cwd` / `input_dir` / `absolute`） | `run.log`、`_find_materials()` |
| `inventory.non_material_excluded` | arr | 被判定为工单/契约/示例而**排除**的文件 `path` + `reason`；`counts.non_material_excluded` / `counts.control_chars_removed` 给计数 | `inventory.json`、`result.json.uncertainty` |
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

- `success`：证据锁 0 error、**七道闸**全过（含真渲染成功、且预览件实测合格）、产物根无未声明栅格、
  独立审计 `audit_deck.py` 无失败项、`result.json` 写入成功。
- `partial`：以下任一情况——证据锁有 error、任一闸未过、渲染拿不到真预览、
  **预览件实测出现 `render.verification.issues`**（页数/尺寸/字体/空白/压印/掉件）、
  独立审计失败、材料过薄、PDF 无文字层、表体未还原等。**此时 `uncertainty` 必须写明原因**。
- `unsupported`：找不到可读材料（`materials` 全部缺失），无法建立任何证据。

## 哪些文件不会被当作论文材料

`task.md`（题面/评分表）、`case.json` 与任何顶层带 `case_id` / `output_contract` /
`slide_limit` 等键的 JSON、`*.example.json` / `*.template.json` / `*.sample.*`、
`readme.md`，以及 `--out` / `--work` 两个运行期目录。排除是**精确**的（文件名精确匹配 +
双扩展名 + JSON 内容形状），不做前缀匹配，所以论文自带的 `tables.tex`、`data.json`
仍会被读。每一处排除都记录在 `inventory.json.non_material_excluded`，并进入
`result.json.uncertainty`。

## `deck.json` 之外的产物清单（供复核）

`deck.pptx`（可编辑，母版/版式驱动）· `deck.pdf`（真导出件）· `slides/slide-NN.png`（逐页预览）·
`plan.json` · `inventory.json` · `validation.json` · `layout.json` · `render.json` ·
`deck-readback.json` · `audit.json` · `audit-deck.json` · `evidence-map.json` ·
`speaker-notes.md` · `deck-outline.md` · `run.log`

`result.json` 与 `audit-deck.json` **不在 `outputs[]`** 里：前者无法携带自己的哈希，
后者每次复查都会被 `audit_deck.py` 重写（把它的哈希写进产物会让每次复查都报不一致）。
两者由 `contract.self` 与 `audit_deck.report` 分别点名，其余产物逐字节哈希。
