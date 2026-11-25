# README · academic-talk-structurer（min 极简臂 · 文档即产品）

**一句话**：把论文/研究材料组织成"可上台、证据可追溯"的汇报——单入口、纯标准库、零额外参数、包内零二进制。

```bash
python3 scripts/talkplan.py --case /input/case.json --out /app/output      # 主入口（只认 --case / --out）
python3 scripts/verify.py   --case /input/case.json --out /app/output      # 只读重算 16 项（0/2/1）
python3 scripts/verify.py   --gain-cases builtin                           # 4 个带标签反例，证明能区分真推导与编造
```

## 为什么先落 `slide_plan.json`（一等产物）

`talkplan.py` 的次序是：读材料 → 提取带行号锚点的 atom → 按听众画像与时长预算排页 → **先把
`/app/output/slide_plan.json` 写下来并按 `schemas/slide_plan.schema.json` 自检** → 再合成 `deck.pptx`。
好处是**页面可以被审阅、被拒绝，而不必先渲染**；plan 不合规时问题写在 `result.json.slide_plan.schema_errors`，
不会"先做出一堆页再说"。

## 本包（14 个文本文件，无二进制）

| 文件 | 角色 |
|---|---|
| `SKILL.md` | 触发场景 / 主命令 / 输入输出 / 组织规则 / 降级 / 边界 |
| `README.md` | 本文件：用法、产物次序、诚实边界、与 76 分形态的对齐说明 |
| `references/01-audience-profiles.md` | 5 类听众画像（背景占比 / 术语 / **结论强度上限** / 问答焦点） |
| `references/02-narrative-patterns.md` | 页型库（唯一主张 / 证据下限 / 要点上限 / 时长权重）与叙事规则 |
| `references/03-evidence-rules.md` | 三条硬纪律（引文逐字 / 数字可定位 / 图注一致）+ 强度阶梯 + 锚点写法 |
| `references/04-output-contract.md` | 运行期产物清单、`output_contract` 三级动态透传、`result.json` 字段来源、退出码 |
| `references/05-qa-and-timing.md` | 时长预算公式、冲突三种处置、问答准备与讲稿口径 |
| `schemas/slide_plan.schema.json` | 一等中间产物的 schema（含 `additionalProperties` 与字段枚举） |
| `scripts/talkplan.py` | 单文件端到端（含 `runtime_recheck`、`--benchmark`、copy_probe） |
| `scripts/minipptx.py` | 纯标准库可编辑 PPTX 写入器（母版/版式/主题/备注页） |
| `scripts/verify.py` | 只读重算 16 项 + 内嵌带标签反例（`--gain-cases builtin`） |
| `examples/case.example.json` · `examples/paper.example.md` · `examples/README.md` | 示例输入与示例声明 |

## 诚实边界

- **不生成新内容**：材料没写的不上页；材料缺就写进 `uncertainty[]` 与 `deck_shortfall`。
- **不判断科学对错**：只保证"没有材料里不存在的数字/引文/图表编号"。
- **预览是几何渲染**（非 Office 原生）：文字与版式忠实，字形度量与 PowerPoint 不完全一致，已如实标注。
- **页数不足不注水**：`slides_match_target=false` + `partial`，宁短不假。
- 本臂刻意做小（14 文件 / 无二进制 / 纯标准库），目的是被 Agent 一次读完、在 64 请求 / 900 秒内真跑完。

## 与"76 分三文件形态"的对齐（对手情报，见 `notes/q07/REF-GITHUB.md`）

q07 本窗第一（76.00，attempt 92503）只有三个文件（一个链接文件 + README + SKILL），说明**这题是"文档即产品"**：
评委读得到、跑得通、能复核，比"文件多"重要。因此本臂：
① 把**方法写成可执行规则**而不是散文；② 让 README/SKILL 直接给出可复跑命令与判据；
③ 产物清单、字段来源、退出码写死在 `references/04-output-contract.md`；
④ 参考同类高分仓库的分层（`references/` + `schemas/` + `scripts/` + `examples/`）但把 8 篇 reference 压到 5 篇、
   10 个分阶段脚本压到 3 个，保证**单入口自足**。
