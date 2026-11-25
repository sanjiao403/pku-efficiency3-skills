# 页级骨架（slide blueprint）

本文件是**页级主张的模板**：`outline.py` 生成的每一页都能对上这里的角色定义，
`plan_validate.py` 按这里的规则判分。人工改 `plan.json` 时请照此填。

## 叙事骨架（页序即讲解顺序）

| # | role | 这一页要回答的问题 | 必须带 | 常见错误 |
|---:|---|---|---|---|
| 1 | `title` | 这是什么汇报、听众能得到什么 | 标题 + 材料定位 | 封面堆满作者单位 |
| 2 | `question` | 为什么这件事值得听 | 至少一条 → 带定位的动机句 | 用「近年来广受关注」代替具体问题 |
| 3 | `gap` | 前人做到哪、留下了什么 | 已引工作的缺口句；推不出就写 `evidence_absent_reason` | 编一个空白 |
| 4 | `approach` | 你做了什么决定性设计 | 方法句 → 定位；不堆全部超参 | 把方法章节整段搬上来 |
| 5..k | `evidence` | 哪张图/表支撑哪条主张 | `figure`/`table` + 图注 + `evidence[]{label, locator, quote}` | 图号对不上、示意图当数据 |
| k+1 | `result` | 最重要的量化结论 | `kpis` + `numbers[]`（数值 + 单位 + 口径） | 数字被四舍五入/换单位 |
| k+2 | `limits` | 适用范围与失效条件 | 原文局限句；推不出就声明 | 淡化局限 |
| 末 | `takeaway` | 记住哪一条、下一步是什么 | 结论句 → 定位 | 复述全部要点 |

`backup` 为备用页，预算超限时优先砍。

## 每页字段（对应 `templates/slide-plan.template.json`）

```jsonc
{
  "id": "s05",                    // 稳定页 id，evidence-map 用它
  "role": "evidence",             // 见上表
  "title": "图 1 · <图注首句>",     // ≤ 48 字（CJK）/ ≤ 88 字符
  "claim": "这一页唯一的主张",       // 一句，≤ 140 字符，能在原文找到依据
  "bullets": ["可讲述短语", "..."],  // ≤ 5 条，单条 ≤ 96 字符
  "numbers": ["MAE = 3.7", "24.5%"],// 观众可见的全部数值（含单位/指标名）
  "kpis": [ {"value":"3.7", "label":"MAE (°C)"} ],   // 仅 result 页，≤ 3
  "figure": {                      // 与 table 二选一
    "label": "Figure 1",
    "caption": "<原文图注，逐字>",
    "kind": "figure|schematic|data",
    "asset": null,                 // 抽到嵌图时由 assets.py 填
    "source_locator": "paper.pdf · §3 · p4"
  },
  "table": { "label": "Table 1", "caption": "...", "columns": [...], "rows": [[...]] },
  "evidence": [                    // 内容页至少一条；推不出时用下面的声明代替
    {"kind":"figure|table|section|paragraph|equation",
     "label":"Figure 1", "locator":"paper.pdf · §3 · p4", "quote":"<原文逐字片段>"}
  ],
  "evidence_absent_reason": "……",   // 仅当确实无依据时写，会进入 uncertainty
  "density": "low|medium|high"
}
```

## 版式与字号约束（`layout.py`）

| 区域 | 字号阶梯 | 下限 |
|---|---|---|
| 标题 | 34 / 32 / 30 / 28 / 26 / 24 | 24 pt |
| 主张（lead） | 20 / 18 / 16 | 16 pt |
| 要点 | 22 / 20 / 18 / 16 | 16 pt |
| KPI 数字 | 44 / 40 / 36 / 32 / 28 | 28 pt |
| 图注 | 13 / 12 / 11 | 11 pt |
| 表体 | 14 / 13 / 12 / 11 | 11 pt |
| 页脚 / 页码 | 11 | 11 pt |

溢出处理顺序：**不缩到下限以下** →
①`trim`（把要点移入备注）②`split`（拆页）③`table-shrink`（只留决定性行）。
每个动作都带「差多少 pt」，写进 `layout.json.overflow` 与 `audit.json`。

## 备注模板（`notes.py`）

```
[过渡] 承接上一页的 <上页主张> → 这一页回答 <本页主张>
[讲解动作] 按 role 的固定动作（如 evidence 页先读图注、再指图、说明数据类型）
[证据] 本页依据 <locator>；被追问时翻到该处，不凭记忆复述数字
[可能被问] 问题 + 证据化回答（结果页问口径、证据页问数据/示意、局限页问外推范围）
[时间] 本页约 N 秒
```

门限：备注与观众可见文字的字符 4-gram Jaccard ≤ **0.34**；正文页必须有过渡与 ≥ 1 条问答。
