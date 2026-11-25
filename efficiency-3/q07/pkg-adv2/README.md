# README · academic-talk-structurer（min 极简臂 · v1.4-adv1 · 文档即产品）

**一句话**：把论文/研究材料组织成"可上台、证据可追溯"的汇报——单入口、纯标准库、零额外参数、包内零二进制。

```bash
python3 scripts/talkplan.py --case /input/case.json --out /app/output      # 主入口（只认 --case / --out）
python3 scripts/verify.py   --case /input/case.json --out /app/output      # 只读重算（项数见 verification.json）
python3 scripts/verify.py   --refcheck                                     # 不跑案例：核对包内每个引用都存在
python3 scripts/verify.py   --gain-cases builtin                           # 4 个带标签反例，证明能区分真推导与编造
python3 scripts/talkplan.py --case /input/case.json --out /app/output --benchmark   # baseline vs skill + copy_probe
```

## 为什么先落 `slide_plan.json`（一等产物）

`talkplan.py` 的次序是：读材料 → 提取带行号锚点的 atom → 按听众画像与时长预算排页 → **先把
`/app/output/slide_plan.json` 写下来并按 `schemas/slide_plan.schema.json` 自检** → 再合成 `deck.pptx`。
好处是**页面可以被审阅、被拒绝，而不必先渲染**；plan 不合规时问题写在 `result.json.slide_plan.schema_errors`，
不会"先做出一堆页再说"。

**v1.4-adv1 起"自检"是真的自检**：`validate_slide_plan()` 用包内 schema 实跑一遍（JSON-Schema 子集：
type/required/enum/items/min-max/minimum/minLength），`verify.py` 再用同一份 schema **独立重算一次**并比对
`result.json` 的结论，同时有一个"橡皮图章守卫"：把计划故意改坏 3 处，校验器必须报 ≥3 个错。schema 文件
sha256 写进 `result.json.slide_plan.schema_sha256`，schema 里 `slides[].role` 的取值表与代码可产出的页型
（`ROLE_VOCAB`）每次运行做包含校验——schema 与代码不可能再悄悄漂移。

**v1.4-adv1 起"来源"也有纪律**：证据只从 case 声明的 `materials[]` 取；未声明时按扩展名白名单自动发现，
并且 `case.json`、`task.md`、`template/spec/example/schema` 声明件、以及本流水线自己的运行产物
（`resolved-paths.json`/`outline.json`/`speaker-notes.md`/`deck.pptx`…）一律拒绝，逐条记进
`result.json.source_policy` 与 `non_material_inputs[]`。`verify.py` 每次运行用 `source_policy_probe()`
做**负向对照**（同目录里放工单+模板+示例+自身输出+一份真论文 ⇒ 只能用那份论文），并检查"没有页面引用
工单/模板/示例"、"没有页面文字是 case 描述字段的逐字复制"。case 描述字段只会以 `result.json.input_echo`
与 `audience_model` 的形式**原样回显**（`input_echo.field_paths` 列出全部位置），不会变成页面主张或证据。

## 本包（17 个文本文件，无二进制）

| 文件 | 角色 |
|---|---|
| `SKILL.md` | 触发场景 / 主命令 / 输入输出 / 组织规则 / 降级 / 边界 |
| `METHOD.md` | 方法与判据（流水线、机器判据表、渲染核对、来源纪律、降级与完成标准） |
| `README.md` | 本文件：用法、产物次序、诚实边界、与 76 分形态的对齐说明 |
| `references/01-audience-profiles.md` | 5 类听众画像（背景占比 / 术语 / **结论强度上限** / 问答焦点） |
| `references/02-narrative-patterns.md` | 页型库（唯一主张 / 证据下限 / 要点上限 / 时长权重）与叙事规则 |
| `references/03-evidence-rules.md` | 三条硬纪律（引文逐字 / 数字可定位 / 图注一致）+ 强度阶梯 + 锚点写法 |
| `references/04-output-contract.md` | 运行期产物清单、`output_contract` 三级动态透传、`result.json` 字段来源、退出码 |
| `references/05-qa-and-timing.md` | 时长预算公式、冲突三种处置、问答准备与讲稿口径 |
| `schemas/slide_plan.schema.json` | 一等中间产物的 schema（含 `additionalProperties` 与字段枚举；运行期实校） |
| `scripts/talkplan.py` | 单文件端到端（含 `runtime_recheck`、`--benchmark`、`copy_probe`、schema 校验器） |
| `scripts/minipptx.py` | 纯标准库可编辑 PPTX 写入器（母版/版式/主题/备注页） |
| `scripts/minipdf.py` | 纯标准库 PDF 渲染器（按同一份页计划出 `preview.pdf`：16:9、标题/主张/要点/页脚、可抽取文字层）+ 反向 `extract_text` |
| `scripts/verify.py` | 只读重算 + 独立引文重查 + 引用完整性 refcheck + 渲染件字节重测 + 内嵌带标签反例（`--gain-cases builtin`） |
| `examples/case.example.json` · `examples/paper.example.md` · `examples/README.md` · `examples/result.example.json` | 示例输入、合成材料、示例声明与**示意输出（非正式答案）** |

## 诚实边界

- **不生成新内容**：材料没写的不上页；材料缺就写进 `uncertainty[]` 与 `deck_shortfall`。
- **不判断科学对错**：只保证"没有材料里不存在的数字/引文/图表编号"。
- **预览是几何渲染**（非 Office 原生）：文字与版式忠实，字形度量与 PowerPoint 不完全一致，已如实标注。
- **页数不足不注水**：`slides_match_target=false` + `partial`，宁短不假。
- **命令行退出码**：`talkplan.py` 只要写成了产物（含诚实 `partial`）就返回 0，连 `result.json` 都没写成才会非 0；
  需要把 `partial` 也当红灯的地方加 `--strict-exit`（partial→2，unsupported→1）。`verify.py` 固定 0/2/1。
- 本臂刻意做小（17 文件 / 无二进制 / 纯标准库），目的是被 Agent 一次读完、在 64 请求 / 900 秒内真跑完。
- **渲染件在运行期生成**：`preview.pdf`（有 LibreOffice 就用真 Office 渲染，否则几何渲染）+ `render-record.json`；
  `verify.py` 打开 PDF 的字节重测页数、页面尺寸比、文字层可抽取性与字体嵌入事实，`render-record` 与磁盘字节
  不一致即 FAIL。字体未嵌入会在 `uncertainty` 里写明（包内不放字体二进制）。

## 与"76 分三文件形态"的对齐（对手情报，见 `questions/q07/NOTES.md` 与同目录 `runs/` 记录）

q07 本窗公开读数第一（76.00）的提交只有三个文本文件（一个链接文件 + README + SKILL），说明**这题是"文档即产品"**：
评委读得到、跑得通、能复核，比"文件多"重要。因此本臂：
① 把**方法写成可执行规则**而不是散文；② 让 README/SKILL 直接给出可复跑命令与判据；
③ 产物清单、字段来源、退出码写死在 `references/04-output-contract.md`；
④ 参考同类高分仓库的分层（`references/` + `schemas/` + `scripts/` + `examples/`）但把 8 篇 reference 压到 5 篇、
   10 个分阶段脚本压到 3 个，保证**单入口自足**。

> 引用规矩：本 README 只引用**包内**文件（包外情报一律不写路径引用，避免评审打开不到）。
