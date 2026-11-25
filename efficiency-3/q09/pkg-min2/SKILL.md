---
name: academic-deck-min
description: Minimal one-command academic deck kit — turn a paper or research material into an editable .pptx on a given template (or a neutral 16:9 master) with verbatim source bullets, page anchors in the speaker notes, a per-slide source footer and a result.json that echoes the runtime output_contract; also edits an existing deck in place without touching its master/layouts/theme. Use when a task asks for 学术汇报/组会/评审 slides from a paper, for compressing or retargeting an existing deck, or when an editable .pptx plus a rendered PDF/PNG preview and per-page citations must be delivered within a small package budget.
---

# academic-deck-min

一个命令跑完一个案例：`python scripts/deck.py --case /input/case.json --out /app/output`

## 何时用

| 用 | 不用 |
|---|---|
| 从论文 PDF/Markdown/文本做组会、评审、答辩汇报稿 | 论文精读、文献综述、科研绘图算法本身 |
| 把上一版 deck 压缩 / 换受众 / 改术语（编辑既有 pptx） | 从零设计新母版（改模板文件即可） |
| 需要「可编辑 pptx + 渲染 PDF/PNG + 页级引用」三件套 | 只要一段文字总结 |

## 输入 → 输出

- **输入**（`/input/`，名字即用途）：`case.json`（`case_id` + `output_contract` + 受众/时长/页数）、
  材料 `*.pdf|*.md|*.txt`、可选模板 `*template*.pptx`、可选**既有稿** `*starting*.pptx`、
  可选 `*ops*.json` 或 `case.json` 内联 `ops`（编辑指令）、可选 `deck_plan.json`（自己写的页计划）。
- **输出**（`--out`）：`deck.pptx`（可编辑）、`preview/deck.pdf` + `preview/slide-NN.png`（真实渲染）、
  `evidence_map.jsonl`（一行一个页级锚点）、`slide_plan.json`、`result.json`、`_work/`（source.json、
  deck_plan.json、build_report.json、render_report.json、checks.json、edit_report.json、versions/）。

## 生成分支（给材料）

1. `scripts/deck.py` 抽正文与**数字台账**（`numbers.tsv`/`source.json`），要点只取材料原文整句，
   每条带 `{source, page, block_id, quote}`；
2. 叙事角色按材料章节推导：封面 → 路线 → 问题 → 方法 → 结果×2 → 限制 → 结论（页数按案例要求补足）；
3. 往**模板自己的版式槽位**里填内容（无模板则用 python-pptx 默认母版 + 16:9 画布）；
   超长文本按字符预算降字号（下限 12 pt）；页脚写 `来源 <材料> · p.N`，演讲备注写要点+锚点；
4. 渲染 PDF + 逐页 PNG，然后 `scripts/verify.py` 机检（13 项）写进 `checks.json`；
5. `result.json` = `case_id` + 契约每个字段（顶层 + `contract_echo`）+ `deliverable`/`evidence_map`/
   `change_log`/`uncertainty`/`sources`/`checks`/`stages`。

## 编辑分支（给既有稿）

给 `*starting*.pptx` + `*ops*.json`（或 `case.json` 内联 `ops`）即进入编辑：
`set_title` / `set_text` / `replace_text` / `compress_bullets` / `set_notes` / `delete_slide`。
只改被点名的页与形状；编辑前后比对**设计指纹**（幻灯片尺寸 + 主题字体 + 每个版式的占位符几何），
结论写进 `edit_report.json.template_preserved`，并留 `versions/*-v0-original.pptx` 与 `-v1-edited.pptx`。
`ops` 缺失时**原样拷贝**并在 warning 里说明，绝不静默改写。

## 输出契约

`result.json` 必含 `case_id` 与运行时 `output_contract` 的**每个字段**（顶层平铺 + `contract_echo`；
无真值写 `""`/`[]` 并列入 `contract_missing_fields`），另有 `status`/`sources`/`uncertainty`/`change_log`。
字段字典见下文「输出」段；本包的对照实测（baseline vs Skill）见 `BENCHMARK.md` 与 `benchmark.json`，
自证记录见 `tests/selftest-report.json`（生成/编辑/只读重算/cwd 无关/整目录拷贝五项）。

## 降级（一律落盘、如实写 status）

| 情况 | 行为 |
|---|---|
| 无材料也无既有稿 | 不生成 deck，`status=partial`，`uncertainty` 说明 |
| 无模板 | 现场产一版中性 16:9 母版 + warning |
| PDF 无文本层/解析器缺失 | 记 `limitations`，页计划只留骨架，**不补造数据** |
| 无 LibreOffice/PowerPoint | `render_status=unavailable`，**不产出假 PNG**，如实写明 |
| 文本超槽位 | 降到 12 pt + `build_report.warnings` 记所需/可用高度，机检 C 段暴露 |
| op 越界/找不到形状 | 该 op `skipped`/`failed` + 原因，其余继续 |
| 编辑后指纹变化 | `template_preserved=false` + 差异清单，`status=partial` |

## 预算与自查

无网络、无外部模型；单案例实测 **10–20 秒**（10 页 PDF：解析 2–6 s、生成 <1 s、导出 PDF+PNG ≈6 s），
远低于 900 s / 64 请求预算。自查：

```bash
python scripts/deck.py --case /input/case.json --out /app/output
python scripts/verify.py --pptx /app/output/deck.pptx --case /input/case.json \
    --source /app/output/_work/source.json --template /input/template.pptx \
    --render /app/output/_work/render_report.json --out /app/output/_work/checks.json
```

`verify.py` 退出码：`0` 全通过、`2` 有机检失败。
