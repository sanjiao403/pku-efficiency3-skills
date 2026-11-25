# academic-deck-adv · README

最小、可复跑、**证据可核验**的学术 PPT Skill：输入一篇论文/材料（或一份既有 deck），
输出可编辑 `.pptx` + 真实渲染 `PDF/PNG` + 页级证据映射 + `result.json`。
`SKILL.md` 是给 Agent 的调用说明；本文件是给人看的使用/依赖/限制/自查说明。

## 1 安装与依赖

- Python 起步版本：`3.10+`（本包在 `3.14.3` 上实测）。
- 必需：`python-pptx>=0.6.21`（读写 pptx）、`PyMuPDF>=1.23`（读 PDF 文本、渲染 PNG、C14 重测 PDF）。
- 可选：LibreOffice（`soffice`）或 Windows PowerPoint（COM）之一，用于导出 PDF/PNG。
  两者都没有时：`render_status=unavailable`，**不伪造预览**，C14/C15 记 `n/a` + 原因。
- 无网络、无外部模型、无账号依赖。安装：`pip install python-pptx PyMuPDF`。

## 2 调用

```bash
python scripts/deck.py --case /input/case.json --out /app/output
```

零附加参数。`/input` 里按文件名识别：材料 `*.pdf|*.md|*.txt`、模板 `*template*.pptx`、
既有稿 `*starting*.pptx|*existing*.pptx`、编辑指令 `*ops*.json`、页计划 `deck_plan.json`。
产物全部落在 `--out`：`deck.pptx`、`preview/deck.pdf`、`preview/slide-NN.png`、
`evidence_map.jsonl`、`slide_plan.json`、`result.json`、`_work/`。

## 3 输入契约

`case.json` 需带 `case_id` 与 `output_contract`（字段会被逐个回显，缺失记 `contract_missing_fields`）；
`slide_count`/`num_slides`/`max_slides`/`duration_min`/`audience`/`language` 可选，顶层或一层嵌套均可识别。
材料里**不能**混入工单/示例/模板——它们会被证据边界拒绝并记录（见 `references/deck-rules.md` §4）。

## 4 输出契约

见 `SKILL.md`「输出契约」与 `examples/case.example.json`（**示例，非正式答案**）。
关键字段：`case_id`、`status`、`deliverable`（页数/可编辑/PDF/PNG）、`evidence_map`（页级锚点）、
`claim_support`（改写条数 + entailment 未机检声明）、`checks`（15 项机检 + n/a 原因）、
`stages`（每阶段状态，含 `refused_as_evidence`/`partial_result`）、`uncertainty`、`change_log`。

## 5 异常与降级

| 情况 | 行为 |
|---|---|
| 无材料、或唯一的材料候选被拒 | 不生成 deck，`status=partial/failed` + 原因（`stages.ingest=refused`） |
| `/input` 里混入 example/template JSON | 拒收并记 `refused_as_evidence`，不改用、不崩 |
| PDF 无文本层 / 解析器缺失 | 只留骨架 + `limitations`，不补造数据 |
| 无渲染器 | 无 PDF/PNG，`uncertainty` 明写；C14/C15 `n/a` |
| 文本超槽位 | 降到 12 pt 下限并在 `build_report.warnings` 记所需/可用高度 |
| 机检器自身异常 | `checks.passed=null` + `uncertainty`「本次未被自证」，`status=partial` |
| 契约字段与交付物不一致 | C16 判红（`case_id`/`sources[]`/`notes[]`/`outputs[].bytes` 逐项比对） |
| 预览目录里有上一轮的 PDF/PNG | 渲染前删除；没删干净 C14 会判红 |
| 材料整句用完、页数没填满 | 剩余页写成声明式备用页（备注 `[备份]`），并进 `uncertainty` 与 `deliverable.declared_backup_pages` |
| 一页放不下要点（即便 12 pt） | 从末尾丢要点并记 `build_report.dropped_for_fit`，不缩到 12 pt 以下、不裁切 |
| 运行被中断 | 进入渲染前已写 `_partial: true` 的诚实 `result.json` |

## 6 自查

```bash
python tests/selftest.py --report tests/selftest-report.json     # T1–T13，含 7 个负向对照
python scripts/verify.py --pptx <out>/deck.pptx --result <out>/result.json   # 只读重算
python scripts/verify.py --pptx <out>/deck.pptx --contract <out>/result.json # 16 项 + 契约审计
```

- `tests/selftest-report.json`：真实运行的 expected vs actual（含 cwd 无关、整目录拷贝、空输入守卫）。
- `tests/lead-audit-report.json`：哨兵污染实测（task.md / case.json / *.example.json / *.template.json）
  + 逐项覆盖矩阵（每一 id 都被一次篡改打红，未被篡改的表格/图片 deck 仍 0 失败）。

## 7 版本与变更

- `pkg-adv4`：修掉聚焦复检的 **P0 过度拦截**：`评分维度`/`评分点`/`评分细则`（中文评测论文的
  常规写法）与 `prepared answer`/`预置答案`（NLP 标准术语）**不再作为判据**，只作 corroborating 记录；
  内容嗅探只认**合同独占词 ≥2 个**（`output_contract`/`runtime contract`/`提交材料`/`提交目录`/
  `交付要求`/`交付标准`/…）或无歧义提交警告句。代价（写明）：只提一个合同词的工单会漏拦。
- `pkg-adv3`：修掉聚焦复检的 **P1-高（内容嗅探双向误判）**：`grader`/`rubric` 这类评估词汇
  不再作为判据（LLM-as-a-judge / 评分维度方向的真论文必须照读，误拒会让案例 `slides=0/failed`），
  嗅探改为**只认合同式结构标记**（≥3 个互异）或**提交警告句**；每个候选的嗅探结论写进
  `discover.evidence_sniff`。另在限制节写明 `DENY_EXACT` 里 `notes.md`/`readme.md` 的已知误拒面。
- `pkg-adv2`：在 `pkg-adv1` 基础上修掉 QA-round-20261124 的 1 条 P0 契约错误 + 2 条机检假绿 + 2 条 P1
  （`case_id` 被 n/a 检查 id 覆盖；`sources[]` 与锚点来源无审计；预览 PNG 不读像素；正文空壳页全绿；
  `notes` 契约字段与交付物不一致），检查扩到 **16 项**（新增 C16「契约=交付物」）、预览改为像素级校验、
  材料句池按轮转分配（不再出现空壳页/结论页空白）、一页放不下时丢要点而不是裁切、渲染前清除残留预览。
- `pkg-adv1`：在 `pkg-min2` 基础上做对抗式自审的产物。相对父臂的关键变更（详见题目 `NOTES.md`）：
  ① 引文语料加了证据边界（工单/示例/模板绝不入索引）与形状校验；
  ② C11/C12/C13 改为读**交付物**并逐字/按页核验（原版读的是内存里的页计划，等于自证）；
  ③ 编辑模式的 C10 基线改为被编辑的既有稿（原先拿另造的母版比，产生假红 → `status=partial`）；
  ④ 备注新增 `改写自原句：` 声明；⑤ 新增 C14/C15（导出件字节级重测 + 无占位图）；⑥ 中断安全的部分交付。
- 历史：`pkg`/`pkg-v11`（完整版）、`pkg-min`/`pkg-min2`（极简）、`pkg-min3`/`pkg-min4`（机检扩展）。

## 8 已知限制

见 `references/deck-rules.md` §8：C12 不判语义支撑；C13 只管数字；C04 是估算；不裁剪/不重绘论文图。
