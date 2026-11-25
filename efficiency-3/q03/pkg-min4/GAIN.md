# GAIN — 朴素路线 vs 本 Skill（结论 + 原始数字 + 字段路径）

同样四份示例工单、**同一套校验器**：朴素脚本画出的图"好看但不可审"，本 Skill 多花约 50 ms，
换来每个数字可回溯、单位与图例有闸、色觉/灰度有量化，并且**编造的数值会被抓出来**。

复跑：`python3 scripts/benchmark.py --out benchmark.json`（约 1 秒；退出码 0 = 两探针 + 4 条判定全过）。

## 1. 同口径对照（两条路线都跑的两份工单：`gain-01`、`gain-04`）

| 指标 | 朴素路线 | 本 Skill | 差 | 字段路径 |
|-|-:|-:|-:|-|
| 可追溯率 | 0.000 | **1.000** | +1.000 | `aggregate.{naive,skill}.traceability_rate` |
| 单位正确率 | 0.000 | **0.500** | +0.500 | `aggregate.*.unit_correct_rate` |
| 违规数（28 项中） | 21 | **1** | −20 | `aggregate.*.{violations,checks_total}` |
| 耗时 | 0.024 s | 0.072 s | +0.048 s | `routes_detail[].{naive,skill}.seconds` |

单位正确率 0.500 而非 1.0 是**如实**的：`gain-04` 的输入本身没写单位，正确行为是判缺陷（`status=partial`）
而不是替读者补一个；唯一那条违规就是它（`routes_detail[3].skill.violation_names = ["axis_unit_declared"]`）。

## 2. 四条带标签案例的判定（全部 `verdict=pass`）

| 案例 | 标签 | 期望 → 实测 | 字段 |
|-|-|-|-|
| `gain-01` | grounded | `success` / 可追溯 1.0 / 有单位 → 一致 | `gain_cases[0].expected_vs_actual` |
| `gain-02` | **fabricated_number** | 编造的数值必须 `fail` → `value_fidelity: fail`，`verify_violations=["output_files_hashed","values_match_source"]` | `gain_cases[1]` |
| `gain-03` | off_topic | 跑题不得编造 → `status=failed`、`values_drawn=0` | `gain_cases[2]` |
| `gain-04` | unit_missing | 缺单位必须报缺陷 → `status=partial`、`axis_units=fail` | `gain_cases[3]` |

`gain-02` 是差异化关键：渲染完成后把图元映射里的一个数值改成源表不存在的 **7.77**（模拟"图上数字是编的"），
`verify.py` **只读产物**就同时抓到两处——数值回读不一致与产物哈希失配。朴素路线没有任何一层能发现它。

## 3. 逐案数字（`routes_detail[]`）

| id | label | naive 违规/项 | skill 违规/项 | naive 可追溯 | skill 可追溯 | skill 状态 | 秒(naive→skill) |
|-|-|-:|-:|-:|-:|-|-:|
| gain-01 | grounded | 11/14 | **0/14** | 0.0 | **1.0** | success | 0.012 → 0.037 |
| gain-02 | fabricated_number | — | 0/14（篡改发生在判定阶段） | — | 1.0 | success | — → 0.045 |
| gain-03 | off_topic | — | 6/14 | — | 0.0 | **failed** | — → 0.024 |
| gain-04 | unit_missing | 10/14 | **1/14** | 0.0 | **1.0** | **partial** | 0.012 → 0.035 |

skill 全量 4 案合计 7/56 违规，其中 **6 条来自 `gain-03`**（跑题输入本就不该出图，所以缺产物/映射/单位）——
这就是为什么 §1 用同口径两案（1/28）而不是 4 案合计来对比。字段：`routes_detail[i].{label,naive,skill}.*`。

## 4. 自足性探针（`copy_probe` / `cwd_probe`）

`copy_probe`：整包复制到 `<TEMP>/runs/q03-fire/stage/outputs` 再跑 → `status=success`、`elements=6`、`verify=14/14`、`ok=true`。
`cwd_probe`：在**无关 cwd**（目录里放了同名诱饵 `expression.csv`）运行 → `status=success`、`decoy_used=false`、`resolved_from=["case_dir"]`。
字段：`copy_probe.{staged_path,status,elements,verify,ok,seconds}`、`cwd_probe.{cwd,status,decoy_used,resolved_from,ok}`。

## 5. 不证明什么（诚实边界）

1. 朴素路线是本包内的**脚本化复现**（40 行 SVG 写入器），不是抓取的 LLM 轨迹，给的是差额**下界**；
2. 违规数用**本包自己的校验器**统计，两条路线一视同仁；换校验器数字会变；
3. `off_topic` 案朴素路线无法加载，未计入同口径汇总；**不声明任何分数**；耗时是单机单次测量。
