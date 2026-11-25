# RUBRIC — 五维度 × 包内文件 × 可复跑命令 × 通过判据

本页只写"拿什么文件、跑什么命令、看到什么才算过"。所有命令都在包根目录执行，且**零附加参数**。

## 1. 质量增益（图是否可信、可审）

| 项 | 文件 | 命令 | 通过判据 |
|-|-|-|-|
| 图元↔源单元格映射 | `scripts/chart.py`、`figure.map.json` | `python3 scripts/chart.py --case tests/gain_cases.json` 提取 `case` 后运行，或直接 `--case examples/case-01.example.json --out /tmp/o` | `figure.map.json.elements[]` 每条都有 `source.file/row/col`，`row` 是**物理行号**；`by_element` 可反查 |
| 随包报告（一等产物） | `render_report.json`、`verification_report.json`（每次运行都生成）+ `examples/case-01.*_report.json`（样例） | `chart.py … && verify.py …` | 两份报告出现；`render_report.mapping_coverage==1.0`；`verification_report.verdict=="pass"`；纯文本无二进制 |
| 数值必须回读源表 | `scripts/verify.py` | `python3 scripts/verify.py --case <case.json> --out /tmp/o` | `values_match_source` 行 PASS，`expected=… locator(s) re-read`、`actual=0 mismatch` |
| 单位/图例/误差线闸 | `scripts/chart.py`（`checks`） | 同上，然后看 `result.json.checks` | `axis_units`/`legend_series`/`error_bars` 全 `ok=true`；缺单位时必须 `ok=false` 且 `status=partial` |
| 色觉-灰度量化 | `scripts/chart.py` 的 `cvd_pairs()` | `python3 scripts/chart.py --case … --out …`；测试 | `checks.cvd_grayscale.pairs[].dE76`、`cvd.{deuteranopia,protanopia,tritanopia}`、`dL_greyscale`、`verdict`；ΔE<12 判 fail、12–20 warn |

## 2. 效率增益（一条命令出齐、不用手工对表）

| 项 | 文件 | 命令 | 通过判据 |
|-|-|-|-|
| 单入口端到端 | `scripts/chart.py` | `python3 scripts/chart.py --case /input/case.json --out /app/output` | 退出码 0/1、stdout 末行 `CHART_OK` 或 `CHART_PARTIAL`；`/app/output` 出现 `figure.svg`+`figure.map.json`+`result.json` |
| 契约化产物 | `result.json` | 同上 | `output_files[]` 每项含 `path/bytes/sha256`；`outputs`/`sources`/`changes`/`uncertainty` 非空 |
| 耗时可比 | `scripts/benchmark.py` | `python3 scripts/benchmark.py --out benchmark.json` | `aggregate.*.total_seconds` 有值；结论页见 `GAIN.md` |

## 3. 增益可验证性（对照实验可复跑）

| 项 | 文件 | 命令 | 通过判据 |
|-|-|-|-|
| 带标签案例 | `tests/gain_cases.json` | `python3 scripts/benchmark.py --out benchmark.json` | `benchmark.json.gain_cases[].verdict` 全为 `pass`，且每条的 `expected_vs_actual[]` 逐字段相等 |
| 原始数字 | `benchmark.json` | 同上 | `aggregate.{naive,skill}`、`delta`、`routes_detail[]` 三项齐全 |
| 人类可读结论 | `GAIN.md`、`GAIN-EVIDENCE.md` | 阅读 | 页内每个数字都能在 `benchmark.json` 找到对应字段路径（页里已标注路径） |

## 4. 方法改进（把"画图"拆成可检查的声明）

| 项 | 文件 | 命令 | 通过判据 |
|-|-|-|-|
| 规范→渲染→校验三段分离 | `scripts/chart.py` 的 `plan_chart()` / `render_svg()` / `run_checks()` | `python3 scripts/verify.py --case <case.json> --out <o>` | `verify.py` 只读产物即可复算，不需要 `chart.py` 的内存状态 |
| 失败给出定位与修法 | `checks.*.detail`、`uncertainty[]`、`references/exceptions.md`（16 行例外矩阵 + 退出码） | 同上 | 缺单位案 `axis_units.detail` 写明 label/unit；`uncertainty` 给出修法；例外矩阵每行指到真实代码分支 |
| 期刊预设可追 | `references/journal-profiles.md` | 阅读 + `render_report.json.figure_mm` | 预设表逐项对应 `chart.py` 常量；改常量后 `figure_mm` 反映新值 |
| 物理行号定位 | `figure.map.json.convention` | 直接读 | 文件里写明"row = 物理 1-based 行号（注释行与表头都算）" |

## 5. 创新证据（闸真的会失败）

| 项 | 文件 | 命令 | 通过判据 |
|-|-|-|-|
| 编造的数值会被抓 | `tests/gain_cases.json#gain-02`、`benchmark.py:tamper_map()` | `python3 scripts/benchmark.py --out benchmark.json` | `gain_cases[1].verdict=="pass"` 且其 `verify_violations` 含 `values_match_source` |
| 跑题/缺单位不伪装 | `tests/gain_cases.json#gain-03/#gain-04` | 同上 | gain-03 `failed`+`values_drawn=0`；gain-04 `partial`+`axis_units=fail` |
| 拷贝到别处仍可跑 | `benchmark.py:copy_probe()` | 同上 | `copy_probe.ok=true`、`verify=14/14` |
| 与 cwd 无关 | `benchmark.py:cwd_probe()` | 同上 | `decoy_used=false`、`resolved_from` 只有 `case_dir` |
