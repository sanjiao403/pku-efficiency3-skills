# 01 · 听众画像（audience profiles）

命中规则：`audience / goal / presentation_type / task` 关键词命中最多者胜；无命中用 `reviewer-symposium`。
实现：`scripts/talkplan.py: ARCS`。

| 画像 | 关键词 | 背景占比 | 术语 | **结论强度上限** | 问答焦点 |
|---|---|---|---|---|---|
| `committee-defense` | 答辩/学位/评审/评委/defense/viva | 0.08 | 低 | **strong** | 创新点·基线·限制·失效条件 |
| `lab-meeting` | 组会/进度/合作者/同事/progress | 0.05 | 无 | **moderate** | 卡点·下一步·数据 |
| `reviewer-symposium` | 评审/会议/研讨会/同行/review/symposium | 0.15 | 中 | **strong** | 基线·数据·限制 |
| `teaching-seminar` | 教学/讲座/学生/course/tutorial | 0.30 | 高 | **moderate** | 机制·数据 |
| `grant-panel` | 立项/申请/项目/基金/grant/proposal | 0.20 | 中 | **moderate** | 可行性·风险·卡点 |

三条裁量：① 先验越低，背景/术语越多，但每页背景都必须"后面要用到"；② 组会/教学/立项封顶 `moderate`，
进度类汇报出现"显著优于"属高风险表述；③ **换听众要换弧而不是换措辞**——弧一换，页型顺序、秒数分配、
强度上限、问答焦点一起变。选择理由写进 `outline.audience_model.archetype_reason`，
生效上限见 `result.json.audience_model.strength_cap`（便于复核是否越级）。
