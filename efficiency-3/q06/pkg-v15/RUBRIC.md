# RUBRIC.md · 五维度 → 文件 → 可复跑命令 → 判据

本表逐一对应题面五维度。**每一行都能只靠本包与命令复现**；命令假定 `cd questions/q06/pkg-v14`，
`<T>` 为任意临时输出目录（由命令自己创建，包内不留运行期产物）。

| 维度（分值） | 承载文件 | 可复跑命令 | 判据（本机实测） |
|---|---|---|---|
| **实际效果 40**<br>完成度 15 | `scripts/run.py`、`scripts/outline.py`、`scripts/deck.py` | `python3 scripts/run.py --case examples/case_zh_md/case.json --out <T>/a --work <T>/wa` | 三案例 `status=success`、9 页、`deck.pptx`+`deck.pdf`+9 PNG 全出 |
| 结果正确性 15 | `scripts/plan_validate.py`（G1 数值 / G2 图注编号 / G3 引文逐字 / G4 locator） | 同上，读 `<T>/a/validation.json` | `errors=0`，`rigor_report.coverage=1.0` |
| 结果完整性 5 | `scripts/contract.py`、`scripts/notes.py`、`scripts/evidence-map.json` 产物 | 读 `<T>/a/result.json` | 契约键 `8/8`、`evidence_map` 每页一条、`notes` 每页非空 |
| 结果可核验性 5 | `scripts/rigor.py`、`scripts/audit_deck.py`、`tests/selftest-report.json` | `python3 scripts/rigor.py --case examples/case_zh_md/case.json --all`；`python3 scripts/audit_deck.py --out <T>/a --case examples/case_zh_md/case.json` | `53/53` 逐字回查；独立审计 `8/8`；自检 `9/9` |
| **使用增益 25**<br>质量增益 15 | `scripts/benchmark_local.py`（两臂真跑） | `python3 scripts/benchmark_local.py --reps 3` | 备注复述 `57→0`、页数预算 `0/3→3/3`、布局违规 `5→0`（见 `GAIN.md`） |
| 效率增益 5 | 同上 `.totals.*.e2e_seconds` | 同上 | **不主张**：耗时差落在重复极差内（见 `GAIN-EVIDENCE.md` 局限） |
| 增益可验证性 5 | `tests/benchmark-report.json`、`GAIN-EVIDENCE.md` | `python3 -c "import json;print(json.load(open('tests/benchmark-report.json'))['totals']['delta'])"` | 每条指标都带 `baseline/skill/delta` 与 JSON 字段路径 |
| **创新增益 15**<br>新增能力 5 | `scripts/plan_validate.py::rigor_report`、`scripts/rigor.py` | `python3 scripts/rigor.py --case <case.json> --item number:3.7:degC` | 单条证据可在 shell 独立重证；失败退出码 1 |
| 方法改进 5 | `scripts/plan_validate.py::_page_fields`（逐字段判 G1/G2） | `python3 scripts/gain_check.py` | `grounded` 案例 0 error（修掉跨字段数字/单位误判） |
| 创新证据 5 | `tests/gain_cases.json` + `tests/gain-report.json` | `python3 scripts/gain_check.py --json` | 4/4 带标签案例判定与标注一致 |
| **可靠体验 10**<br>调用与易用性 3 | `SKILL.md`、`README.md` | `python3 scripts/run.py`（零参数，走 `/input/case.json`→`/app/output`） | 单入口、零附加参数 |
| 运行稳定性 4 | `scripts/papertext.py`、`scripts/render.py` | 三案例三种材料形态（MD / TeX+bib / PDF） | 三形态均 `success`；无 office 时降级为模型预览并在 `uncertainty` 说明 |
| 异常处理 3 | `run.py::main`（异常兜底）、`run.py` 空产物守卫 | 读 `<T>/a/uncertainty`；`python3 scripts/run.py --case /nonexistent.json --out <T>/x` | 崩溃写 `error.log` + `status=partial` + 原因；0 段/0 页不报 success |
| **生态贡献 10**<br>文档完整性 3 | `SKILL.md` `README.md` `METHOD.md` `references/*.md` 本表 | 直接阅读 | 用途/输入输出/限制/失败处理/自查齐备 |
| 资源可复用性 4 | `templates/*.json`、`examples/*`、`references/01-deck-blueprint.md` | `python3 scripts/template_build.py --spec templates/template-spec.example.json --out <T>/t.pptx` | 页级大纲模板 + 契约模板 + 3 个（英-PDF/LaTeX/中文 MD）示例 |
| 分享推广价值 3 | `GAIN.md` `INNOVATION.md` `ECOSYSTEM.md` `RUBRIC.md` | — | 方法、对照数字、经验与边界可被他人直接复用 |

## 一次跑完全部证据（约 60 秒）

```bash
python3 tests/selftest.py                 # 单元 + 端到端 + 独立审计 → tests/selftest-report.json
python3 scripts/gain_check.py               # 带标签案例判定 → tests/gain-report.json
python3 scripts/benchmark_local.py --reps 3 # 真实两臂对照 → tests/benchmark-report.json
for c in case_zh_md case_latex; do python3 scripts/rigor.py --case examples/$c/case.json --all; done
```

判据：`selftest 9/9`、`gain_check 4/4`、`rigor 53/53·43/43·66/66`、三案例 `success` 且 `6/6` 闸。
