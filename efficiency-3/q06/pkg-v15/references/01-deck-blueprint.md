# 01 · 页级蓝图（角色、顺序、密度）

一页一个主张；页序 = 讲解顺序，不跟论文章节顺序。

## 1. 角色序列（`outline.py::ROLE_LABELS`）

| # | role | 回答什么 | 必须带 | 材料推不出时 |
|---:|---|---|---|---|
| 1 | `title` | 这是什么汇报 | 标题 + 定位 | — |
| 2 | `question` | 为什么值得听 | 动机句 + 定位 | `evidence_absent_reason` |
| 3 | `gap` | 前人留下什么空白 | 缺口句 + 定位 | 同上 |
| 4 | `approach` | 做了什么决定性设计 | 方法句 + 定位 | 同上 |
| 5..k | `evidence` | 哪张图/表支撑哪条主张 | 图注**逐字** + 定位 + `label` | 材料无图 → 退回文字证据页 |
| k+1 | `result` | 最重要量化结论 | 数值 + 单位 + 口径 | 同上 |
| k+2 | `limits` | 适用范围与失效条件 | 局限句 + 定位 | 同上 |
| 末 | `takeaway` | 记住哪一条 | 结论句 + 定位 | 同上 |

超 `slide_limit` 时按角色优先级截断（先丢 evidence 之外的次要页），并把
`checks.budget.pages_wanted` / `dropped_by_limit` 如实记账——**不静默删页**。

## 2. 页级字段（`plan.json`，人工可改后重跑）

```jsonc
{
  "id": "s05",                       // evidence_map 用它
  "role": "evidence",
  "title": "Figure 1 · <图注首句>",    // ≤ 48 字（CJK）
  "claim": "这一页唯一的主张",          // 一句；与 title 相同则不重复渲染
  "bullets": ["可讲述短语"],           // ≤ 5 条，单条 ≤ 96 字符
  "numbers": ["MAE = 3.7", "24.5%"],  // 观众可见的全部数值（含单位/指标名）
  "figure": {"label": "Figure 1", "caption": "<原文图注，逐字>", "source_locator": "…"},
  "table":  {"label": "Table 1",  "caption": "<原文图注，逐字>", "source_locator": "…"},
  "evidence": [{"kind": "figure|table|paragraph", "label": "Figure 1",
                "locator": "paper.pdf · §4 Results · p4", "quote": "<原文逐字片段>"}],
  "evidence_absent_reason": "材料没有可锚定的句子时写这里",
  "density": "low|medium|high"
}
```

定位格式：`文件 · §章节 · p页码 · L行号`（有哪段写哪段；PDF 一定有 `p`，MD/文本一定有 `L`）。

## 3. 版式与字号（`layout.py` / `deck.py`，13.333 × 7.5 in）

| 区域 | 字号 | 说明 |
|---|---|---|
| 标题 | 24–28 pt | 占位符继承模板主题 |
| 主张（lead） | 18 pt 加粗 | 与标题相同则跳过，避免重复 |
| 要点 | 18 pt | 行距 1.16；最多 5 条 |
| 图注/示意图框 | 12 pt | 框内是原文图注 + 定位 |
| 页脚/页码 | 11 pt | 页码用 OOXML 域，重排后仍正确 |

边距 0.62，标题区 0.45–1.51，主张 1.62–2.40，正文 2.48–6.86，页脚 6.86–7.2。
**所有形状必须在页内、字号不缩到 11pt 以下**（`audit_deck.py` A7 检查）；
要点过长就在 `checks.warnings` 报 `trim`，要求把细节移到备注或拆页——
「塞不下就缩小到看不清」是题面明列的失败模式。

## 4. 备注（`notes.py`，与页面分离）

每页四类句子：过渡（承接上一页 → 本页回答什么）、讲解动作（按 role 固定）、证据位置、预设问答。
判据：与页面可见文字的字符 4-gram Jaccard **≤ 0.34**（`audit_deck.py` A6），且非空。
