# 05 · 时长预算与问答（timing & QA）

## 时长预算

```
talk_seconds = (duration_min − qa_min) × 60
备用页数      = slide_count≥12→3 ｜ 8–11→2 ｜ 6–7→1 ｜ <6→0   （且 ≤ round(slide_count×0.28)）
正文页数      = slide_count − 备用页数（最少 3）
每页秒数      = talk_seconds × 页型权重 / ∑权重（标题页固定 3%），∑ 必须回到 talk_seconds
合格带        = 0.72×~1.55× (talk_seconds/60/正文页数)
```

冲突三种处置（不许静默）：① 材料够、页数被限死 → 减页，内容进 `outline.dropped_atoms[]`；
② 材料不够 → **不注水**，写 `outline.deck_shortfall{target_slides,produced,missing}` + `status=partial`；
③ 页数与时长无法两全 → `slide_plan.constraints.slides_match_target=false`，并在讲稿里给出"先砍哪两页"。

## 问答准备（`slide_plan.qa_prep`）

来源＝未上页 atom（优先 `limitation/setup/method/result`）；备用页 `timing_seconds=0`；每个追问指向可翻到的页
（`backup_slide_no`）；**回答强度 ≤ 被引页强度**；回答要点直接取材料原句，材料没写的口径是"材料未给出"。

## 讲稿（`slides[].notes`）

四行式：讲什么（那页主张）→ 指什么（材料·行号／图表编号）→ 强度（direct/comparative/background）→ 过渡。
备注与页面正文 Jaccard 必须 <0.8，否则视为"复读页面"。
