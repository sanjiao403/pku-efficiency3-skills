# 05 · 时长预算与问答（timing & QA）

## 时长预算

```
talk_seconds = (duration_min − qa_min) × 60
备用页数      = slide_count≥12→3 ｜ 8–11→2 ｜ 6–7→1 ｜ <6→0   （再取 min(上面, round(slide_count×0.28))）
正文页数      = slide_count − 备用页数（最少 3）
标题页秒数    = max(3, round(talk_seconds × 0.03))（无标题页则为 0）——即"标题页固定 3%"
其余页秒数    = max(5, round((talk_seconds − 标题页秒数) × 页型权重 / ∑其余权重))，再把整数残差折回
                ⇒ ∑ 全部页秒数 **精确等于** talk_seconds（`result.json.time_budget_alloc.sum`）
合格带        = 0.72×~1.55× (talk_seconds/60/正文页数)
```

早先版本对每页做 `max(5, …)` 后不再折回残差，短时长案例（如 3 min 讲述）会出现 ∑=65s ≠ 60s 的 8.3% 偏差，
被自己的闸门判 FAIL；现在残差折回后恒等成立（`verify.py` 仍独立重算 ±5% 这一档）。

冲突三种处置（不许静默）：① 材料够、页数被限死 → 减页，内容进 `outline.dropped_atoms[]`；
② 材料不够 → **不注水**，写 `outline.deck_shortfall{target_slides,produced,missing}` + `status=partial`；
③ 页数与时长无法两全 → `slide_plan.constraints.slides_match_target=false`，并在讲稿里给出"先砍哪两页"。

## 问答准备（`slide_plan.qa_prep`）

来源＝页型为 `limitation/setup/method/result` 的 atom，**优先取未上正文页的**（正好回答材料里没上页的部分）；
每条带 `backup_slide_no` 指向**真实存在**的页（正文页或备用页），`backup_linked` 说明是否有页可指；
备用页 `timing_seconds=0`；`answer_strength` 取被引页的 `evidence_strength`，因此**回答强度不超过被引页**
（`verify.py` 用强度阶梯独立复核：越级即 FAIL）；回答要点直接取材料原句，材料没写的口径是"材料未给出"。
当材料里连一条可指页的追问都凑不到 2 条时，才会回退到无页可指的 atom 并把 `backup_linked=false` 记在案。

## 讲稿（`slides[].notes`）

四行式：讲什么（那页主张）→ 指什么（材料·行号／图表编号）→ 强度（direct/comparative/background）→ 过渡（衔接下一页）。
备注与页面正文 Jaccard 必须 <0.8，否则视为"复读页面"。
