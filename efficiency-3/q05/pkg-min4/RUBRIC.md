# RUBRIC · 五维度 → 文件 + 可复跑命令 + 判据

`<pkg>` = 本包目录；`<c>` = 一个案例目录（`case.json` + 材料，或把 `tests/gain_cases.json` 里
某条的 `material` 写到临时目录）；`<o>` = 输出目录。

| # | 维度 | 文件 | 可复跑命令 | 判据（可判真假） |
|-|-|-|-|-|
| 1 | **结果正确性** | `scripts/apparatus.py`、`references/ir_schema.md` | `python3 <pkg>/scripts/apparatus.py --case <c>/case.json --out <o>` | `figure.ir.json` 的 `figure_type/elements/relations` 齐全；每图元 `source.quote` 逐字可回溯（`check_consistency.source.quotes_verbatim`）；箭头一一对应且落端点 |
| 2 | **完整性** | 同上 + `result.json` | 同上，读 `<o>/result.json` | 六类要素齐备：`elements`/`relations`/`data_mapping`/`deliverable`/`provenance`/`checks.ir+checks.consistency`；契约键 `missing=[]`；`extraction_index` 覆盖每个画出的图元 |
| 3 | **可核验性** | `scripts/validate_ir.py`、`scripts/check_consistency.py`、`PROVENANCE.md` | `python3 <pkg>/scripts/validate_ir.py --ir <o>/figure.ir.json`；`python3 <pkg>/scripts/check_consistency.py --ir <o>/figure.ir.json --materials <c> --svg <o>/figures/figure.svg --result <o>/result.json` | 两条命令退出码均为 **0**（IR 合规 + 跨产物一致，0 硬失败） |
| 4 | **使用增益** | `GAIN.md`、`tests/gain_cases.json` | 第 1 条 + `python3 <pkg>/scripts/apparatus.py --case <c>/case.json --out <o2> --arm naive`，再各跑一次一致性校验 | 同输入下：来源可追率 0→1.0、连线 0→2、命名图层 2→5.7、覆盖索引 0→9.7 条、**一致性硬失败 1→0**（原始字段 `tests/gain_cases.json.ab.metrics[]`） |
| 5 | **创新与生态** | `INNOVATION.md`、`references/*.md`、`examples/case-01-buffer-train/` | `python3 questions/q05/min4-bench.py`（包外编排，仅回写证据） | 带标签反例 **7/7** 判 `pass`：3 条 `grounded` 双校验通过；`fabricated_number`/`missing_provenance` 改写后**一致性**由 ✅ 转 ❌；`invalid_ir` 改写后 **IR 校验**由 ✅ 转 ❌；`off_topic` 判 `partial` |

## 判据阈值速查
| 检查项 | 阈值 | 归属 |
|-|-|-|
| `source.quotes_verbatim` | 100% 引文可在材料中找到（空白归一化） | check_consistency（硬） |
| `coverage.index_maps_every_mention` / `every_element_in_index` | 无遗漏、无多画 | check_consistency（硬） |
| `svg.covers_ir` / `ir.covers_svg` | id 集合双向相等 | check_consistency（硬） |
| `provenance.blocks_have_quote` | ≥80% 图元带引文（本包实测 100%） | check_consistency（硬） |
| `arrow.one_head_per_connector` / `head_sits_on_endpoint` | 每条 1 个箭头、误差 ≤1.5 px | check_consistency（硬） |
| `outputs.hashes_match` | 每个产出文件的 bytes/sha256 与 result.json 一致 | check_consistency（硬） |
| `provenance.no_invented_numbers` | 图上数字全部可由材料/序号/画布解释 | check_consistency（硬） |
| `library.kind_documented` | IR 用到的每个 kind 都在图元库里 | validate_ir（硬） |
| `ir.index.omit_reason` | omitted 条目必须写 reason | validate_ir（硬） |
| 空产物 | 0 图元 → `partial` + `empty figure` | apparatus（守卫） |

## 反例优先
自证方式不是"我说我做到了"，而是**先把反例做出来**：`tests/gain_cases.json` 里每条反例都先写真产物，
再**改写字节**（塞材料外数字 / 剥来源标记 / 破坏 IR 索引），交给**同一批校验器**判 before/after，
`verdicts[].actual.*_before_tamper` 与改写后的值成对落盘。见 `GAIN.md §3`。
