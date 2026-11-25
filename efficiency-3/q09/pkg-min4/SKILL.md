---
name: "academic-deck-min"
description: "Turn one paper or research material into an editable, template-inheriting academic deck (native PPTX + real PDF/PNG export + page-level evidence map), or edit an existing deck in place without touching its master. Every claim is extractive: bullets are verbatim source sentences with page anchors, every printed number must trace back to the material, and 13 machine-readable checks run before delivery."
---

# 学术 PPT 生成与编辑 — 执行卡（min4）

**触发**：运行时给 `/input/case.json` + 材料（pdf/md/txt，或结构化 material）+ 可选
`target-template.pptx` / `starting-deck.pptx` / 编辑指令，要产出可编辑学术演示稿、真实导出的
PDF/PNG 与页级证据映射。

## 预算换算式（先算再动手）

> 题面预算：**64 次模型请求 / 900 s / 16384 tokens 每响应**。
> 本 Skill 的换算：**脚本干重活、模型只做决策** ⇒
> `讲解+清点 1 次 + 读材料写计划 1–2 次 + 看机检报告 1–2 次 + 修复 1–2 轮 ≈ 8–12 次请求`；
> 单案例实测 **5–8 s**（含真实 PDF+PNG 导出与 13 项机检）⇒ **全程 <3 分钟**，
> 剩余预算全部留给"素材读不全时补读"和"机检不过时的最多 2 轮修复"。
> **不要把材料整篇读进上下文**：先让脚本抽取成 `_work/source.json`，再按需读片段。

## 七步执行卡（每步一条命令，失败就看 stdout / JSON）

**Step 1 清点输入（1 次请求）**
```bash
python3 $S/scripts/deck.py --case /input/case.json --out /app/output   # 主命令会自己清点
ls /input ; cat /app/output/result.json 2>/dev/null                     # 期望：见 Step 2
```
主命令内部先做 `discover`：按**文件名**归类材料/模板/既有稿/编辑指令/页计划（**cwd 无关**：
`case.json` 里声明的相对路径按 `case.json 所在目录 → cwd → /input` 依次解析，命中来源记进
`result.resolved_from`；全部未命中则进 `uncertainty` 的 `missing`，不静默跳过）。

**Step 2 立即落一版诚实的 partial result（防中断，0 决策）**
```bash
python3 $S/scripts/deck.py --case /input/case.json --out /app/output   # 与 Step 1 同一条命令
# 该命令在「清点+抽取材料之后、构建之前」先写出：
#   /app/output/result.json  {status:"partial", _partial:true, stages:[...], uncertainty:[...]}
# 若之后被杀（超时/中断），平台拿到的仍是一份合法、如实的结果，而不是空目录。
```

**Step 3 读抽取结果 → 决定页结构（1–2 次请求，唯一的重决策点）**
```bash
sed -n '1,120p' /app/output/_work/source.json      # 文本块 + 数字台账 numbers[] + limits
```
要点**只能取材料原文整句**（脚本已按长度/标点筛好候选）；页数取 `case.json` 的
`slide_count`（脚本会自动收敛/扩页，**不会超页**）；材料缺口写进 `uncertainty`，**没有的数字绝不编**。
想自己指定页计划时，写 `/input/deck_plan.json`（形状见 `_work/deck_plan.json`），主命令优先用它。

**Step 4 构建成稿（原生可编辑、模板继承）**
```bash
python3 $S/scripts/deck.py --case /input/case.json --out /app/output
# 有 starting-deck.pptx + ops → 走编辑分支（只动被点名的页/形状，留 v0/v1 快照）
# 否则 → 走生成分支（内容只进模板版式槽位；无模板则现场产中性 16:9 母版）
```

**Step 5 导出真实预览**
```bash
ls /app/output/preview/deck.pdf /app/output/preview/slide-*.png
# 渲染后端：LibreOffice → PowerPoint COM（重试 3 次）→ 都不可用则 render_status=unavailable
# 且不产出任何 PNG（不拿几何预览冒充渲染件）
```

**Step 6 机检 13 项 + 修复循环（≤2 轮）**
```bash
python3 $S/scripts/verify.py --pptx /app/output/deck.pptx --result /app/output/result.json
python3 $S/scripts/verify.py --pptx /app/output/deck.pptx --case /input/case.json \
  --source /app/output/_work/source.json --spec /app/output/_work/deck_plan.json \
  --template /input/target-template.pptx --render /app/output/_work/render_report.json
```
**13 项**（编号＝报告里的 `id`，不适用项记 `n/a` + 原因，绝不假装通过）：
`C01` 页数=案例指令 · `C02` 页数≤上限 · `C03` 形状不出界 · `C04` 文本不溢出 · `C05` 正文不重叠 ·
`C06` 表格溢出（本包不写表格 ⇒ n/a） · `C07` 图片等比（本包不插图 ⇒ n/a） · `C08` 每页有标题+备注 ·
`C09` 正文字号≥12 pt · `C10` 字体继承（设计指纹：尺寸+主题 typeface+版式几何） ·
`C11` 每页有证据锚点 · **`C12` 引文逐字真实性**（每条锚点 quote 必须逐字出现在材料里） ·
**`C13` 数字保真回查**（页面上每个 ≥2 位数字必须能在材料台账里查到）。
几何硬错误（C03/C04/C05）必须清零；改 `deck_plan.json` 对应页后重跑 Step 4–6，最多 2 轮。

**Step 7 终版 result.json + 交付核对（1 次请求）**
```bash
python3 -c "import json;r=json.load(open('/app/output/result.json'));print(r['status'], r['deliverable']['slides'], r['contract_missing_fields'])"
```
必须为 `success` / 页数正确 / `contract_missing_fields` 为空（或已在 `uncertainty` 说明）。

## 输出契约（`/app/output`）

| 文件 | 内容 |
|---|---|
| `deck.pptx` | 可编辑成稿（运行期合成；占位符继承母版） |
| `preview/deck.pdf` + `preview/slide-NN.png` | 真实导出（无渲染器则缺失并如实声明） |
| `evidence_map.jsonl` | 页级锚点：`{slide, role, claim, anchor{source,page,block_id,quote}}` |
| `slide_plan.json` | 页结构：`{index, role, title, claim}` |
| `result.json` | `case_id` + `output_contract` 全字段（顶层 + `contract_echo`）+ `outputs[]`(path/bytes/sha256) + `resolved_from` + `sources` + `uncertainty` + `change_log` + `checks` + `stages` |
| `_work/{source,deck_plan,build_report,edit_report,render_report,checks}.json`、`_work/versions/` | 复核用中间件与版本快照 |

## 降级（一律落盘、如实写 status）

| 情况 | 行为 |
|---|---|
| 无材料也无既有稿 | 不生成 deck，`status=failed/partial` + `uncertainty`（**空产物守卫**） |
| 无模板 | 现场产中性 16:9 母版 + warning（C10 记 `n/a`） |
| PDF 无文本层/解析器缺失 | 记 `limits`，页计划只留骨架，**不 OCR 不编造** → `status=partial` |
| 无 LibreOffice/PowerPoint | `render_status=unavailable`，不产出假 PNG |
| 文本超槽位 | 降字号到 12 pt 下限并记所需/可用高度（C04 暴露） |
| op 越界/找不到形状 | 该 op `skipped/failed` + 原因，其余继续 |
| 编辑后设计指纹变化 | `template_preserved=false` + 差异清单，`status=partial` |

## 自查

```bash
python3 tests/selftest.py --report tests/selftest-report.json   # 生成/编辑/只读重算/cwd/整目录拷贝/空输入
python3 tests/selftest.py --report tests/selftest-report.json && cat tests/selftest-report.json
```

依赖：Python 3 + `python-pptx`（PDF 文本需 PyMuPDF；渲染需 LibreOffice 或 PowerPoint）。无网络、无外部模型。
