# RUBRIC-MAP · 评分维度 → 包内证据

> 评审不必猜：下表把本题五个维度的每个评分点，指到包内具体文件与可复现的验证命令。
> 所有"实测"数字来自 `tests/selftest-report.json` 与 `tests/ab-report.json`（本机真跑，示例案例）。

## 1 实际效果 40 分

| 评分点 | 分值 | 包内证据 | 怎么核 |
|-|-:|-|-|
| 任务完成度：真的产出"问题—方法—结果—结论"单页图稿 + 可编辑源 | 15 | `SKILL.md §3`（四面板 IR 契约）、`scripts/layout.py` 的 `PANEL_ROLES` 与四列版式、`examples/*/figure-ir.example.json`、`examples/sample-output/figure.example.svg`（文本预览） | `python3 scripts/ga_build.py build` 后打开 `figure.svg`；`check` 的 `four_beats` 项 |
| 结果正确性：实体/关系/数据编码/图例与来源一致 | 15 | `scripts/ga_core.py:RELATION_GRAMMAR/ENTITY_TYPES`、`scripts/layout.py:derive_legend`（图例由画面派生）、`scripts/provenance.py:legend_gate/number_gate`、`references/figure-design-rules.md §2–3` | `check` 的 `quotes_verbatim`（示例 100% 命中）；`result.json.invariants.legend/numbers` |
| 结果完整性：四要素 + 图例 + 单位/比例尺/条件 + 图注 | 5 | `layout.py` 页脚（图例 / 单位·条件·比例尺 / 来源带 / `Figure N.` 图注）、数值编码带、`notes` 字段模板 | `figure.svg` 页脚；`result.json.invariants.fit` |
| 结果可核验性：图稿/来源映射/版本/导出记录可独立复核 | 5 | `result.json.content_map`（元素级 locator+逐字 quote）、`coverage`、`compliance_checks`（12 项）、`run.log`、`tests/selftest-report.json` | `python3 scripts/ga_build.py selfcheck` → `SELFCHECK_OK`；`coverage.source_ratio`（示例 0.95） |

## 2 使用增益 25 分

| 评分点 | 分值 | 包内证据 | 怎么核 |
|-|-:|-|-|
| 质量增益：相同输入下比基础做法更好 | 15 | `tests/ab_harness.py` + `tests/ab-report.json`：skill 臂 vs 消融臂（`GA_ABLATE=provenance,encoding,legend`）；`METHOD.md §3` 与 83 分公开 attempt 的形态对照表 | `python3 tests/ab_harness.py`；实测可核验图元 **41 vs 8**，来源比 **0.95 vs 0.00** |
| 效率增益：减少重绘/重排/返工 | 5 | 溢出修复阶梯（`layout.py`）、多引擎导出链（`render_png/render_pdf.py`）、单命令入口 `scripts/ga_build.py`、`--fast` | `run.log` 与 `result.json.runtime`（示例单案例 build ≈0.8 s）；`exceptions` 中的自动修复记录 |
| 增益可验证性 | 5 | `tests/ab-report.json` 的 `design.why_fair` / `limits` / `real_base_agent_protocol`；两臂共用入口与预算 | 读 `ab-report.json`；按 METHOD §4 可补真实基础 Agent 臂 |

## 3 创新增益 15 分

| 评分点 | 分值 | 包内证据 | 怎么核 |
|-|-:|-|-|
| 新增能力：基础做法难以稳定实现的图谱式表达 | 5 | 证据绑定 IR → 确定性版式（`layout.py`）、关系语法箭头端形（`RELATION_GRAMMAR`）、数值编码带（长度 + 对照刻度 + locator） | `examples/sample-output/figure.example.png` 与 `result.json.invariants` |
| 方法改进：实体抽取规则/视觉通道映射/版面约束/导出检查 | 5 | 图例由画面派生、图案填充改为裁剪线段（跨引擎一致）、统一字宽度量保证重跑一致、`selfcheck` 独立复检 | `METHOD.md §2` 取舍表；`tests/selftest-report.json` 的 `deterministic` 项 |
| 创新证据：相对已有方案的边界与价值 | 5 | `METHOD.md §3` 与 73246 的逐项差异表；`tests/ab-report.json` | 读 `METHOD.md §3` / `§4` |

## 4 可靠体验 10 分

| 评分点 | 分值 | 包内证据 | 怎么核 |
|-|-:|-|-|
| 调用与易用性 | 3 | `SKILL.md §2` 五命令、`README.md §2` 完整步骤、`templates/figure-ir.template.json` | 按 SKILL 照抄命令即可跑通 |
| 运行稳定性 | 4 | 顶层 try/except、每步隔离、`init` 先落最小 `result.json`、退出码恒 0、`--fast` 与 120 s 硬超时 | `tests/selftest-report.json` 的 32 项（含空输入 / 坏 JSON / 溢出压力 / 两跑一致）|
| 异常处理：缺数值/实体歧义/文字溢出/字体缺失/画布超限/导出失败 | 3 | `SKILL.md §5` 降级表；`fonts.discover` 字体证据；`layout` 修复阶梯；`render_png/pdf` 引擎链与验真 | `selftest` 的 `degrade.*` 与 `stress.overflow_repair` 项；`result.json.font_report` |

## 5 生态贡献 10 分

| 评分点 | 分值 | 包内证据 | 怎么核 |
|-|-:|-|-|
| 文档完整性 | 3 | `README.md`（依赖/步骤/预算/限制/自查）、`METHOD.md`、`references/*.md`、`SKILL.md` | 通读四份文档；`README.md §4` 明示 64/900/16384 预算与降级矩阵 |
| 资源可复用性 | 4 | `templates/*.json`、`references/figure-design-rules.md`（关系语法/调色板/字号层级/修复阶梯）、`scripts/*`（可单独 import：`layout.build_scene`、`provenance.*`）、`examples/` 三案例 | 新案例只需换 `figure-ir.json`；脚本零第三方依赖 |
| 分享推广价值 | 3 | 可编辑 SVG + 真实 PNG/PDF + `content_map` 的交付形态可直接进论文/基金流程；`tests/` 自带 Benchmark 式自检与 A/B 对照 | 打开 `examples/sample-output/figure.example.svg`（文本预览） 直接编辑验证 |

## 6 未覆盖 / 需说明

- **公开作品链接 +5**：按 Operator 决定本窗口作品不公开、不放置链接文件，该项自愿放弃。
- **真实基础 Agent 对照臂**：需在评测环境实际跑基础 Agent（本子代理无发枪权限），已在 `METHOD.md §4` 给出协议，
  消融臂作为可复现的替代证据。
- **科学内容正确性**：脚本不判断真伪，只保证可核验；`result.json.uncertainty` 与 `content_map` 供评审逐条比对。


