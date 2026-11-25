# GAIN · 真实两臂对照（使用增益，一页）

同一份材料，真跑两条**都随包发布、一条命令可复跑**的管线，用**同一个** `check_consistency.py` 当尺子。

```bash
python3 scripts/apparatus.py --case <c>/case.json --out <o_naive> --arm naive   # A 臂
python3 scripts/apparatus.py --case <c>/case.json --out <o_skill>               # B 臂
python3 scripts/validate_ir.py --ir <o>/figure.ir.json
python3 scripts/check_consistency.py --ir <o>/figure.ir.json --materials <c> \
        --svg <o>/figures/figure.svg --result <o>/result.json
```
A 臂 = 按材料顺序逐行画框（不分类/不溯源/不连线/无图例/不自检/**不产 IR**），同一入口内的真实实现；
B 臂 = 启发式抽取 → IR（含覆盖索引）→ 分层布图 → 导出 → 双重只读校验。

## 1. 三案例均值（`skill − baseline`）
字段：`tests/gain_cases.json → ab.metrics[]`（`{metric, baseline, skill, delta}`）

| 指标 | naive | skill | Δ |
|-|-:|-:|-:|
| 图元 `elements_drawn` | 11.333 | 8.667 | −2.667 |
| 连线 `relations_drawn` | 0.0 | **1.667** | +1.667 |
| 可追到原文的图元 | 0.0 | **8.667** | +8.667 |
| **来源可追率** `trace_rate` | 0.0 | **1.0** | **+1.0** |
| 带 `data-node` 的图元 | 0.0 | **8.667** | +8.667 |
| 命名图层 `named_layers` | 2.0 | **5.667** | +3.667 |
| **覆盖索引条目** `index_items` | 0.0 | **8.667** | +8.667 |
| `index_omitted`（未画但有原因） | 0.0 | 0.0 | 0 |
| **一致性硬失败** `consistency_hard_failures` | 1.0 | **0.0** | **−1.0** |
| 端到端耗时 (s) | 0.75 | 0.82 | +0.07 |
| 源文件体积 `svg_bytes` | 4302.333 | 14056.333 | — |

分案例图元（skill/base）：`ab.per_case_elements` → case-01 12/17、case-02 10/10、case-03 4/7；
两臂都 `status=success`。naive 的硬失败三案一致 = `ab.baseline_hard_failure_names` = `["ir.missing"]`
——它根本不产中间表示，于是没有可核对的契约对象。

## 2. 带标签反例：7/7 判定通过
字段：`tests/gain_cases.json → verdicts[]`（`actual` 含改写前后的 `ir_ok` / `consistency_ok`）

| 案例 | 标签 | tamper | before → after | verdict |
|-|-|-|-|-|
| case-01/02/03 | `grounded` | — | ir ✅ cons ✅ → 同 | pass ×3 |
| probe-fabricated-number | `fabricated_number` | 塞 `42` | cons ✅ → ❌ `provenance.no_invented_numbers` | pass |
| probe-missing-provenance | `missing_provenance` | 剥 `data-*` | cons ✅ → ❌ `provenance.blocks_have_quote` | pass |
| probe-invalid-ir | `invalid_ir` | 索引 omitted 缺 reason | **ir ✅ → ❌** `ir.index.omit_reason` | pass |
| probe-off-topic | `off_topic` | — | 图元 0 → `partial` + `empty figure` | pass |

## 3. 三项自证与测不到的项
`ab.cwd_independence`（包外 cwd + 绝对路径 → `success`、图元 15、`resolved_from` 三段顺序）；
`ab.copy_probe`（整包拷到 `<TMP>/probe/runs/q05-fire/stage/outputs/pkg-min4` → 3/3 `success`、图元 15/10/4）；
`probe-off-topic`（`status=partial`、图元 0、`status_reason` 含 `empty figure`）。
写 `null` 的指标与原因（`ab.null_metrics`）：**真实人工返工步数**（无人类受试者，用
`consistency_hard_failures` 作可测下界代理量，每项硬失败 ≥1 轮返工）、**含模型推理的总耗时**
（不属可复现的运行时）、**主观可读性**（需人工评分）。

## 4. 诚实结论
1. **质量增益成立**：来源可追率 0→100%、连线 0→1.67、命名图层 2→5.67、覆盖索引 0→8.67 条、
   一致性硬失败 1→0；每条都由只读产物的同一校验器量出。
2. **效率增益不在单次耗时**（0.75 s vs 0.82 s，基本持平），而在**免返工**：naive 不产 IR，
   连"画的是什么、依据哪一行"都无从核对；本包每案 0 硬失败。
3. naive 在"文本覆盖"上不吃亏（把材料全打印出来），但它**没有契约对象**——数字与这句话一致。
