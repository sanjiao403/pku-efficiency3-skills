# result-contract · `result.json` 契约与状态判据（D14-R1/R3）

## 1. 顶层字段（全部必填；脚本产不出就写 null 并注明）
| 字段 | 含义 | 来源/判据 |
|---|---|---|
| `case_id` | 输入标识原样回写 | `case.json.case_id` |
| `task` | 任务名 | 输入 |
| `status` | `success` \| `partial` | 全绿才 success（见 §3） |
| `status_reason` | 具体原因（缺哪个文件/哪项不达标） | 由检查结果拼出 |
| `summary` | 一句话事实摘要（页数/证据数/关键读数） | 机器生成 |
| `generated_at` | 带时区 ISO8601 | 运行时刻 |
| `outputs[]` | **产物清单**：`path` + `bytes` + `sha256` + `kind` | 落盘后实测 |
| `artifacts[]` | 同上（兼容键，内容一致） | 同上 |
| `results` | 分步证据（见 §2） | 各脚段 |
| `slides[]` | 页级：`page/role/layout/title/claim/evidence_locs/figure/font_sizes` | 计划 + 复核 |
| `evidence[]` | `page + locator + block_id + quote + verified` | 逐字回源 |
| `sources[]` | 源文件：`file/kind/sha256/chars`（PDF 另有 pages） | 抽取阶段 |
| `uncertainty[]` | `item + why + handling` | 材料/字体/渲染/裁剪 |
| `change_log[]` / `changes[]` | 每步做了什么、证据在哪（两键同内容） | 流水线 |
| `capability_boundary[]` | 能证明/不能证明什么 | 固定文案 |
| `reproduce` | 复跑命令 | 固定文案 |
| `narrative` / `narrative_source` | agent 写的叙述（脚本不代写） | 可选 |
| `output_contract_echo` | 输入 `output_contract` 声明字段的回显 | 逐字段 |
| `contract_unresolved_fields[]` | 回显为 null 的字段名 | 诚实记账 |

## 2. `results` 分步
| 键 | 内容 | 复核要点 |
|---|---|---|
| `template` | 模板来源（`case-pptx` 或 `spec-synth(<spec名>)`）、画幅、版式数、角色映射、主题字体、`inheritance{layouts_out,layouts_template,layouts_preserved,theme_*}` | 版式数/主题字体与模板一致 = 继承链未被破坏 |
| `plan` | 页结构统计、`dropped_content`（被裁章节 + 理由）、字体计划、字号阶梯 | 页数在 `slide_count` 约束内 |
| `build` | 逐页填充记录、`fontScale`、合成占位符、构建期警告、pptx sha256 | 溢出处置有记录，不是压字号 |
| `fit` | `metrics`（溢出框、正文最小字号、图宽高比偏差、定位/引文覆盖率、`geometry_inherited_slides`）+ `issues[]` | 页面占位符无 `a:xfrm` ⇒ 真继承 |
| `render` | 后端、页数、逐页 `text_coverage`/`images`、PDF 字体表、`issues[]` | 页数=pptx 页数；覆盖 ≥97% |

## 3. `status` 判据（`partial` 必须给出具体原因）
判 `success` 需同时满足：
1. pptx 落盘且能被重新打开；
2. 渲染链产出 PDF（`results.render.ok=true`）——**无后端则 `partial`**，
   `results.render.backend="none"`、error 写原文、不写假 PDF、页数/覆盖率保持 null；
3. 无 `high` 级问题（版式数变化、正文 <14pt、图拉伸 >0.5%、引文无法回源、
   文本框溢出 >20%、PDF 页数≠pptx 页数、覆盖率 <97%）；
4. `quote_verified_rate == 1.0` 且 `locator_coverage == 1.0`。

## 4. 谁能证明什么（D14-R3）
- 生成器（`fit.py`/`run.py`）自证：**运行期**校验页数、占位符继承、引文回源、渲染一致性。
- 独立审计器（`audit_only.py`）**只读**产出的 `result.json` + `pptx`（+ 可选 `preview/deck.pdf`
  与 `template_map.json`/`source_map.json`）重算：页数、版式数、主题字体、`a:xfrm` 计数、
  正文最小字号、引文回源率、PDF 页数与逐页覆盖率、`outputs[]` 的 bytes/sha256，
  与 result.json **自述值逐项对照（expected vs actual）** 并给 pass/fail。
- `tests/selftest-report.json` 同时记录这两条路径的 expected/actual 与总通过数。
- 边界：技术检查不证明学术判断与叙事质量；材料/字体缺失会如实进 `uncertainty`。
