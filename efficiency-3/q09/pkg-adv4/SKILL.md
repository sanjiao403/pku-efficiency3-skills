---
name: academic-deck-adv
description: Academic deck kit with an evidence policy — turns a paper or research material into an editable .pptx on a given template (or a neutral 16:9 master) with verbatim source bullets, a declared original sentence for every rewrite, page anchors in the speaker notes, a per-slide source footer and a result.json that echoes the runtime output_contract; also edits an existing deck in place without touching its master/layouts/theme, and refuses to cite anything that is not research material (task sheet, case file, template or example JSON). Use when a task asks for 学术汇报/组会/评审 slides from a paper, for compressing or retargeting an existing deck, or when an editable .pptx plus a rendered PDF/PNG preview and per-page citations must be delivered within a small package budget.
---

# academic-deck-adv

一个命令跑完一个案例：`python scripts/deck.py --case /input/case.json --out /app/output`

## 何时用

| 用 | 不用 |
|---|---|
| 从论文 PDF/Markdown/文本做组会、评审、答辩汇报稿 | 论文精读、文献综述、科研绘图算法本身 |
| 把上一版 deck 压缩 / 换受众 / 改术语（编辑既有 pptx） | 从零设计新母版（改模板文件即可） |
| 需要「可编辑 pptx + 渲染 PDF/PNG + 页级引用」三件套，且要求引用可核验 | 只要一段文字总结 |

## 输入 → 输出

- **输入**（`/input/`，名字即用途）：`case.json`（`case_id` + `output_contract` + 受众/时长/页数）、
  材料 `*.pdf|*.md|*.txt`、可选模板 `*template*.pptx`、可选**既有稿** `*starting*.pptx`、
  可选 `*ops*.json` 或 `case.json` 内联 `ops`（编辑指令）、可选 `deck_plan.json`（自己写的页计划）。
- **输出**（`--out`）：`deck.pptx`（可编辑）、`preview/deck.pdf` + `preview/slide-NN.png`（真实渲染）、
  `evidence_map.jsonl`（一行一个页级锚点）、`slide_plan.json`、`result.json`、`_work/`（source.json、
  deck_plan.json、build_report.json、render_report.json、checks.json、edit_report.json、versions/）。

## 证据边界（本包与「把材料整段塞进 PPT」的根本区别）

1. **只有研究材料能当引文语料。** `case.json`、`task.md`、`README`、模板、页计划、编辑指令、
   `*.example.json` 一律不得进入引文索引——否则每一条引文/数字都在拿工单自证（结构性假绿）。
   被拒的候选会写进 `result.json.stages[discover].refused_as_evidence` 并说明原因。
   判定规则见 `scripts/deck.py: evidence_ok()`：扩展名白名单（pdf/md/markdown/txt/text）
   + **锚定**文件名规则（只拒**恰好等于**工程名 `task.md`/`case.json`/`README.*`… 或**明确后缀**
   `*.example.*`/`*.template.*`/`*.schema.*`/`template-spec*`）+ **内容嗅探**。
   **名字里只是碰巧含 `case`/`task` 的真论文（`case-study-routing.md`、`case_report.md`、
   `task_notes.md`）一律当材料读取**：官方案例的材料文件名未知，把真材料判死（`slides=0/failed`）
   比漏拦严重得多。
   **内容嗅探只认「合同独占词」**（`output_contract`、`runtime contract`、`submission_contract`、
   `deliverable_contract`、`提交材料`、`收到材料`、`提交目录`、`交付要求`、`交付标准`、`提交要求`、
   `提交清单`）：**≥2 个互异**即拒；或出现**无歧义提交警告句**（`do not submit prepared answers` /
   `不得提交预制答案`）即拒。
   **评分类词汇一律只记录、不作判据**：`评分维度`/`评分点`/`评分细则`/`prepared answer`/`预置答案`/
   `case_id`/`task_id`（corroborating）与 `grader`/`rubric`/`whiteboard`/`llm-as-a-judge`（weak）——
   中文评测论文描述自己的标注方案（"评分维度包括…；每个评分点 1–5 分；评分细则见附录"）、
   检索问答论文写 `prepared answers`，都是**真论文**，必须照读（判死会让该案例归零）。
   代价：一份**只**写"提交材料/交付要求"两项以下的工单可能漏拦——**已知漏拦，接受**。
   每个候选文件的嗅探结论都写在 `result.json.stages[discover].evidence_sniff` 里
   （`contract_markers` / `corroborating_markers` / `weak_markers` / `decisive_phrase` / `verdict`）。
2. **页计划/编辑指令/模板同样要过形状校验**：`slides[]` 必须是对象列表才被当作页计划，
   `ops` 必须带 `op` 键，`*.pptx` 必须能被 python-pptx 打开；否则拒绝并在
   `discover.refused_as_evidence` 里记原因（`usable_spec/usable_ops/usable_pptx`），**绝不静默采用**。
3. **改写必须交代原句**：要点默认取材料逐字整句；若要点与被引原句不同，演讲备注里会多一行
   `改写自原句：<原文句>`，机检 C12 因此可以仍然逐字核验来源（见 `references/deck-rules.md` §3）。
4. **数字按页核验**：一页上的每个 ≥2 位数字必须出现在**该页自己**的引文或它引用的材料块/页里，
   只出现在论文别处的数字会被判 `wrong-page-scope`（C13）。

## 生成分支（给材料）

1. `scripts/deck.py` 按上面的证据边界选材料并抽正文与**数字台账**（`numbers.tsv`/`source.json`），
   要点只取材料原文整句，每条带 `{source, page, block_id, quote}`；
2. 叙事角色按材料章节推导：封面 → 路线 → 问题 → 方法 → 结果×2 → 限制 → 结论（页数按案例要求补足）；
3. 往**模板自己的版式槽位**里填内容（无模板则用 python-pptx 默认母版 + 16:9 画布）；
   超长文本按字符预算降字号（下限 12 pt）；页脚写 `来源 <材料> · p.N`，演讲备注写要点+锚点；
4. 渲染 PDF + 逐页 PNG，然后 `scripts/verify.py` 机检（16 项）写进 `checks.json`；
5. `result.json` = `case_id` + 契约每个字段（顶层 + `contract_echo`）+ `deliverable`/`evidence_map`/
   `claim_support`/`notes`/`change_log`/`uncertainty`/`sources`/`checks`/`stages`。
   `notes` 是**从 deck.pptx 读回来**的逐页备注（`notes_origin` 标明），不是计划里的空字符串；
   `contract_selfcheck` 另行声明 `case_id` 是否与输入一致。

## 运行期两条硬规则（QA-round-20261124 的教训）

1. **契约字段只能来自交付物**：`case_id`/`notes[]`/`deliverable.slides`/`outputs[].bytes`
   全部从产物重新导出；C16 会把它们与产物逐项比对。任何"计划里是这样所以就写这样"的字段都会被判红。
2. **预览必须属于本次运行**：渲染前先删掉 `preview/` 里上一轮遗留的 `deck.pdf` 与 `slide-*.png`，
   否则旧 PDF 会被当成本次渲染（实测文字存活率掉到 0.35 就是这么来的），C14 也会因此判红。
3. **页数由案例给、正文由材料给、放不下就减条目不缩字**：一页放不下时从末尾丢要点并记
   `build_report.dropped_for_fit`，绝不低于 12 pt，也绝不靠溢出裁切凑页。

## 编辑分支（给既有稿）

给 `*starting*.pptx` + `*ops*.json`（或 `case.json` 内联 `ops`）即进入编辑：
`set_title` / `set_text` / `replace_text` / `compress_bullets` / `set_notes` / `delete_slide`。
只改被点名的页与形状；编辑前后比对**设计指纹**（幻灯片尺寸 + 主题字体 + 每个版式的占位符几何），
结论写进 `edit_report.json.template_preserved`，并留 `versions/*-v0-original.pptx` 与 `-v1-edited.pptx`。
`ops` 缺失时**原样拷贝**并在 warning 里说明，绝不静默改写。
编辑模式下 C10 的对照基线是**被编辑的那份既有稿**（不是另造的模板），
输入 deck 自带的引用问题会记为 `inherited_from_input_deck`，不算这次运行的账。

## 机检 13 项（`scripts/verify.py`，全部只读产物重算）

| id | 检查 | 触发条件 |
|---|---|---|
| C01/C02 | 页数 = 案例指令 / ≤ 上限 | 用例。`case.json` 顶层或一层嵌套里的 `slide_count`/`max_slides` |
| C03 | 形状不出界（含表格框超界） | 有形状越界 |
| C04 | 字符预算估算不溢出 | 估算超槽位 |
| C05 | 正文形状不重叠 | 交叠 > 小框 12% |
| C06 | 表格不超自身框与画布 | 产物里真的有表格才评估，否则 `n/a` + 原因 |
| C07 | 图片等比（±2% 原始纵横比） | 产物里真的有图片才评估，否则 `n/a` + 原因 |
| C08 | 每页有标题+备注+**正文** | 缺标题/备注为空/正文为空且未声明 `[备份]` |
| C09 | 正文字号 ≥ 下限 | 低于 12 pt |
| C10 | 母版/版式/主题指纹未变 | 与基线指纹不一致 |
| C11 | 页级锚点存在、**来源是研究材料**且可解析 | 缺锚点、引用 `task.md`/`case.json`/示例、块 id 不存在、引用页不符 |
| C12 | 引文逐字真实性（**读交付物的备注**） | 引文不在材料里且没有 `改写自原句`；语料本身不是研究材料 |
| C13 | 数字保真（**按页**回查） | 数字不在本页引文/所引材料块里，或全篇都不存在 |
| C14 | 导出件字节级重测 | PDF 页数/页面尺寸/文字存活率(<0.82) 不符；**并拒绝上一轮遗留的预览** |
| C15 | 无占位图、预览**不是空白** | 图片部件 <2 KB/<16 px；PNG 全白、重复、缺页 |
| C16 | `result.json` 契约 = 交付物 | `case_id` 与输入不符、`sources[]` 非研究材料、`notes[]` 与实有备注不符、`outputs[].bytes` 不符 |

不适用项一律 `status="n/a"` + 原因，**绝不算通过**；`summary.not_applicable` 与
`coverage` 会写进 `result.json`。退出码：`0` 无失败项（允许 n/a）、`2` 有失败项。

## 降级（一律落盘、如实写 status）

| 情况 | 行为 |
|---|---|
| 无材料也无既有稿（或被拒后没有合法材料） | 不生成 deck，`status=partial/failed`，`uncertainty` 说明 |
| 材料候选被证据边界拒绝 | 记 `refused_as_evidence`;有合法材料则继续，没有则如实失败 |
| `case.json`/目录里出现 example/template JSON | 拒收并记原因，不采用（不崩） |
| 材料整句用完、页数还没填满 | 剩余页写成**声明式备用页**（备注 `[备份]`、不出主张），并进 `uncertainty` 与 `deliverable.declared_backup_pages`；C08 会点名这些页 |
| 一页放不下要点（即便 12 pt） | 从末尾丢要点并记 `build_report.dropped_for_fit`，不缩到 12 pt 以下、不裁切 |
| 无模板 | 现场产一版中性 16:9 母版 + warning |
| PDF 无文本层/解析器缺失 | 记 `limitations`，页计划只留骨架，**不补造数据** |
| 无 LibreOffice/PowerPoint | `render_status=unavailable`，**不产出假 PNG**，如实写明 |
| 文本超槽位 | 降到 12 pt 下限 + `build_report.warnings` 记所需/可用高度，C04 暴露 |
| op 越界/找不到形状 | 该 op `skipped`/`failed` + 原因，其余继续 |
| 编辑后指纹变化 | `template_preserved=false` + 差异清单，`status=partial` |
| 案例给了多份材料 | 只用**主材料**（PDF 优先，其次体积最大的文本文件）；其余材料登记在 `sources[].siblings` 与 `stages[discover].evidence_candidates` 但不引用。这是**声明的能力边界**：页数仍按案例给足（不足页为声明式 `[备份]` 页），`status` 最坏为 `partial`（**不会 `failed`**），原因写进 `uncertainty` |
| 预览文件残留 | 渲染前删除旧 `deck.pdf`/`slide-*.png`；C14 对不上即判红 |
| 机检器自身异常 | `checks.passed=null` + `uncertainty` 明写「本次未被自证」，`status=partial` |

## 预算与自查

无网络、无外部模型；单案例实测 **10–20 秒**（10 页 PDF：解析 2–6 s、生成 <1 s、导出 PDF+PNG ≈6 s），
远低于 900 s / 64 请求预算。局部交付：进入渲染前就先写一份诚实的 `result.json`（`_partial: true`），
即使中途被中断，平台也能拿到有效且不撒谎的文件。

```bash
python scripts/deck.py --case /input/case.json --out /app/output
python scripts/verify.py --pptx /app/output/deck.pptx --case /input/case.json \
    --source /app/output/_work/source.json --spec /app/output/_work/deck_plan.json \
    --template /input/template.pptx --render /app/output/_work/render_report.json \
    --edit /app/output/_work/edit_report.json --out /app/output/_work/checks.json
python scripts/verify.py --pptx /app/output/deck.pptx --result /app/output/result.json   # 只读重算
python tests/selftest.py --report tests/selftest-report.json   # 含 3 个负向对照
```

## 自证与可信度

- `tests/selftest.py` **T1–T20**：真实运行 + 七个**负向对照**（注入不存在的引文、改一位数字、
  把锚点指到不存在的页、截断预览 PDF、1×1 白图、清空某页正文、污染契约 `case_id`/`notes`/`sources`）
  + 七个**证据边界两向对照**（T14–T20：真论文名含 `case-`/`task_` 必须读、工单改名必须拒、
  含 `grader`/`rubric` 的评估类真论文必须读）—— 运行报告只有「绿」不算证据，必须同时证明
  「篡改会变红」**且**「真材料不会被误杀」。
- `tests/sniff-controls.json`：五个内容嗅探对照的**原始结果**（真论文 ×5 + 真工单 ×2，含 `brief.md`）。
- `tests/lead-audit-report.json` / `tests/probe-report.json` / `tests/qa-round-report.json`：
  哨兵污染实测、**逐项覆盖矩阵**（16 项机检各自被一次篡改打红，未被篡改的表格/图片 deck 仍 0 失败）、
  以及 QA-round-20261124 六条发现的**原件 vs 修复件对照**。
- `tests/selftest-report.json`、`BENCHMARK.md`、`benchmark.json`：baseline 对照与自证记录。
- 导出件质量指标 `C14.text_survival_min` 的**口径**：把每页自己的形状文本切成 `[A-Za-z]{3,}` 词
  + 每个 CJK 字符一个 token，再与 PyMuPDF 读出的对应 PDF 页文本（空白归一）算命中率，下限 0.82。
  别用「PDF 内容流里的 Tj 字面量个数」来对——那是另一个量，两边的数天然对不上。
- 已知边界（写在 `references/deck-rules.md` §8）：C12 只能证明「引文逐字真实」，
  **不能**判断原句是否在语义上支持被改写的要点；`claim_support` 会如实标注这一点。
- **多材料边界**：官方案例若给多份材料，本包只 ingest 主材料，**不合并**（合并需改 `source.json`
  schema 与 C11/C12/C13 的键，评估为 2.5–4 小时且会引入新的过度拦截/假红风险，已主动放弃）。
  最坏 `partial`，绝不 `failed`。
- **文件名边界（已知误拒面）**：为了不把工单当引文语料，`DENY_EXACT` 里列了
  `notes.md` / `readme.md` / `rubric.md` / `method.md` / `benchmark.*` 等**恰好等于**这些名字的文件；
  如果组织方**就用**这些名字命名**真材料**（例如把论文正文存成 `notes.md`），它会被按名拒掉，
  此时 `discover.refused_as_evidence` 会写明 `the file is the task sheet or a package document`。
  这是**声明的能力边界**：按名拒只是第一道闸，真材料若被误拒，把内容改存成别的名字即可；
  反过来放宽这层会重新打开「工单自证」的假绿（比误拒更贵），因此保持现状。
