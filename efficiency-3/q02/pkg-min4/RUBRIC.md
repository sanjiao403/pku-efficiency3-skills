# RUBRIC — 题面五维度 → 包内文件与可复跑命令

原题满分 100（实际效果 40 / 使用增益 25 / 创新增益 15 / 可靠体验 10 / 生态贡献 10）。
下表把每个维度映射到**包内文件**与**一条能原样跑的命令**。`<P>` = 本包路径，`<T>` = 任意临时目录。
本包不自评分数（`result.json.self_scored` 恒为 `false`）；下表只声明「证据在哪、怎么复跑」。

## 1. 实际效果 · 40 分

| 评分点 | 包内文件 | 证据字段 | 复跑 |
|-|-|-|-|
| 任务完成度 15 | `scripts/schematic.py`（单入口端到端） | `result.json.status/summary`、`outputs[]`、`figure.svg` | `python3 <P>/scripts/schematic.py --case /input/case.json --out /app/output` |
| 结果正确性 15 | `scripts/verify.py`、`references/symbol-conventions.md`、`scripts/gain_check.py` | `element_sources[].verified_in_material`、`checks.items[]`（`polarity_inverted` / `entity_unverified` / `evidence_unverified`）、SVG 的 `data-glyph="tee-bar"` | `python3 <P>/scripts/gain_check.py` → 三个带标签案例逐条判定 |
| 结果完整性 5 | `scripts/schematic.py`、`SKILL.md §3` | `result.json` 28 个顶层键、`exports[]`、`outputs[]`（含 `bytes`） | 见 `GAIN.md` 的「主命令实测」表 |

**实测（本包，2026-11-22）**：example `success` 16 元素 引文 10/10；case-01 `success` 22 元素 引文 22/22；
case-02 `success` 6 数据标记 引文 3/3；case-03 `partial`（编辑单含不支持操作，如实拒绝）22 元素 引文 22/22。

## 2. 使用增益 · 25 分

| 评分点 | 包内文件 | 证据 | 复跑 |
|-|-|-|-|
| 质量增益 15 | `scripts/schematic.py`（极性从引文重推 + 来源逐字核验） | 极化错误被拦下：`polarity_inverted`（阻塞）；0 核验率被拦下：`evidence_unverified`（阻塞） | `python3 <P>/scripts/gain_check.py`（`fabricated` / `off_topic` 两例必为 `partial` 且带对应阻塞项） |
| 效率增益 5 | 单入口、零附加参数、零第三方依赖 | 单案例 **< 0.1 s**（`result.json.run_log.seconds`）；`GAIN.md` 实测表 | `cd "$(mktemp -d)" && python3 <P>/scripts/schematic.py --case <P>/examples/case-01/case.json --out <T>/o` |

## 3. 创新增益 · 15 分

| 评分点 | 包内文件 | 证据 | 复跑 |
|-|-|-|-|
| 新增能力 5 | `scripts/schematic.py`（**完全启发式**：材料直接抽实体/关系；CSV 自动发现并推断列角色） | 删掉 `figure_spec` 仍 `success`（`spec_source=mined draft`，16 元素 10/10）；只给一个 CSV 也 `success`（6 标记，列映射自动推断） | 见 `GAIN.md`「纯启发式」两行 |
| 方法改进 5 | `INNOVATION.md`、`references/symbol-conventions.md` | 从引文重推极性；请求列不存在即阻塞（不换列）；空产物与 0 核验率两道阻塞守卫 | `python3 <P>/scripts/gain_check.py` |

## 4. 可靠体验 · 10 分

| 评分点 | 包内文件 | 证据 | 复跑 |
|-|-|-|-|
| 调用与易用性 3 | `SKILL.md`（runbook：触发/一条命令/输出契约/降级） | `SKILL.md` 首屏即主命令；frontmatter `name`/`description` | `python3 <P>/scripts/schematic.py`（缺省 `/input/case.json` → `/app/output`） |

## 5. 生态贡献 · 10 分

| 评分点 | 包内文件 | 证据 | 复跑 |
|-|-|-|-|
| 资源可复用性 4 | `references/symbol-conventions.md`（关系语法 + 启发式规则 + 列角色推断）、`examples/case-01/case.json`（可直接复用的最小案例，**刻意不含 spec**） | 词表固定且公开、列推断规则写明、输入契约极简 | `python3 <P>/scripts/schematic.py --case <P>/examples/case-01/case.json --out <T>/o` |


|-|-|
| 导出件（格式/尺寸/字体检查） | 同一 SVG 兼任矢量导出；`exports[]` 记 `vector`/`text_as_text`/`text_elements`/`canvas_mm`/`font_pt` |
| 来源与修改记录 | `element_sources[]` + `change_log[]` + `uncertainty[]` + `resolved_from` + `metrics.spec_sha256` |
| 结构化结果（输入标识/主结果/证据定位/状态/不确定性） | `result.json`：`case_id`、主结果字段、`element_sources[].locator`、`status`、`uncertainty[]` |
| 材料缺失/无法判断/运行失败分别说明 | `gaps[]` / `uncertainty[]`+`manual_review[]` / `status_reason` |
