# GAIN-EVIDENCE.md · 原始数字与 JSON 字段路径

所有数字都由 `python3 scripts/benchmark_local.py --reps 3` 真实运行产生，文件 `tests/benchmark-report.json`。
下表左列即该 JSON 的**字段路径**（`{arm}` ∈ `baseline` / `skill`；逐案例再加 `.cases[i]`）。

## 1. 两臂合计（`totals`）

| 字段路径 | 含义 | baseline | skill | delta |
|---|---|---:|---:|---:|
| `.totals.{arm}.slides` | 页数 | 58 | 27 | −31 |
| `.totals.{arm}.page_budget_ok` | 三案例中「页数≤上限」的比例（mean） | 0.0 | 1.0 | +1.0 |
| `.totals.{arm}.page_budget_over_by` | 超出预算的页数 | 20 | 0 | −20 |
| `.totals.{arm}.verifiable_elements` | 可核验图元数（数字+图/表号） | 213 | 80 | −133 |
| `.totals.{arm}.source_traceability` | 来源可追率（逐字回查命中，mean） | 0.996 | 1.0 | +0.004 |
| `.totals.{arm}.caption_number_consistency` | 图注-数值一致率（mean） | 0.841 | 1.0 | +0.159 |
| `.totals.{arm}.layout_violations` | 越界形状 + 字号 <11pt 的页数 | 5 | 0 | −5 |
| `.totals.{arm}.max_page_chars` | 单页最多字符数 | 1465 | 1206 | −259 |
| `.totals.{arm}.notes_echo_pages` | 备注与页面 4-gram 重叠 >0.34 的页数 | 57 | 0 | −57 |
| `.totals.{arm}.content_pages_located` | 带**已核实** locator 的内容页 | 0 | 31 | +31 |
| `.totals.{arm}.locator_rate` | 定位覆盖率（mean） | null | 1.0 | null |
| `.totals.{arm}.audit_deck_failed` | `audit_deck.py` 失败项数 | 16 | 0 | −16 |
| `.totals.{arm}.e2e_seconds` | 端到端中位耗时（秒） | 0.22 | 17.69 | +17.47 |
| `.totals.{arm}.e2e_spread` | 单臂三次重复的极差（稳定性） | 0.02 | 3.4 | — |

`locator_rate` 的 baseline 是 `null`：该臂不产出 `evidence_map`，指标**不可测量**而不是 0——
原因写在同名 case 的 `.cases[i].baseline.unmeasurable.evidence_map`。

## 2. 逐案例（`.cases[i]`）

| 路径 | case | baseline | skill |
|---|---|---:|---:|
| `.cases[0].{arm}.page_budget_ok` | case_zh_md | false | true |
| `.cases[1].{arm}.caption_number_consistency` | case_latex | 0.857 | 1.0 |
| `.cases[2].{arm}.caption_number_consistency` | case_en_pdf | 0.667 | 1.0 |
| `.cases[0].{arm}.source_traceability` | case_zh_md | 0.989 | 1.0 |
| `.cases[i].{arm}.untraceable_examples` | — | 例：`["p11 number 26"]` | `[]` |
| `.cases[i].{arm}.unmeasurable` | — | `{}` | `{}` |

复算命令（任一字段）：

```bash
python3 -c "import json;r=json.load(open('tests/benchmark-report.json'));print(r['totals']['delta'])"
python3 -c "import json;r=json.load(open('tests/benchmark-report.json'));print([c['skill']['notes_echo_pages'] for c in r['cases']])"
python3 scripts/audit_deck.py --out <T>/baseline --case examples/case_zh_md/case.json   # 独立复看 baseline 的失败项
```

## 3. 带标签案例判定（`tests/gain-report.json`）

| `cases[i].id` | 标签 | `expect.error_codes` | `observed.error_codes` | `observed.rigor_missing` | verdict |
|---|---|---|---|---|---|
| `grounded` | grounded | `[]` | `[]` | `[]` | **pass** |
| `fabricated_number` | fabricated_number | `["NUMBER_NOT_IN_SOURCE"]` | `["NUMBER_NOT_IN_SOURCE"]` | `["number:4.2:degC"]` | **pass** |
| `fabricated_figure_ref` | fabricated_figure_ref | `["REF_NOT_IN_SOURCE"]` | `["REF_NOT_IN_SOURCE"]` | `["figure:7"]` | **pass** |
| `unlocatable_quote` | fabricated_quote | `["QUOTE_NOT_FOUND"]` | `["QUOTE_NOT_FOUND"]` | `["quote:The proposed model reports a mean absolute error of 3.7 degC"]` | **pass** |

字段路径：`.cases[i].expect.*` / `.cases[i].observed.*` / `.cases[i].verdict` / `.summary.passed`（=4）/ `.labels_covered`。
判定器 `scripts/gain_check.py` 只调用 `plan_validate.validate()`（四道硬闸）与 `rigor.check()`（从材料逐条重证），
**不读**生成器的自评；退出码 0 = 4/4 与标注一致。

## 4. 端到端案例证据（`tests/selftest-report.json`）

| 路径 | 值 |
|---|---|
| `.summary.passed` / `.summary.total` | 9 / 9 |
| `.checks[].check == "end_to_end_run"` → `.detail.status` | `success`，`gates_passed=6/6`，`real_render=true` |
| `.independent_audit_summary` | 1 案例 × 8 项，`passed=8`，`failed=0` |
| `.environment.python` / `.environment.powerpoint_com_available` | 3.14.3 / true |

## 5. 局限（如实记录，不粉饰）

- **效率不作为增益**：`.totals.delta.e2e_seconds = +17.47s`，但 skill 臂多做了真渲染、逐条审计与 27 页排版；
  且耗时在三次重复内波动明显（`.totals.skill.e2e_spread = 3.4s`）。故本包**不主张**效率增益。
- `.not_measured.human_edit_pages = null`：无人对照中无法产生真实数字，不估算。
- `.not_measured.platform_score = null`：机制对照不能换算成平台分数。
- baseline 由本包实现以复现「段落贴页」失败模式，代表**下界参照**，不是无 Skill Agent 的点估计。
