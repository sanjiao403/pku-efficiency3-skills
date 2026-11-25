# 01 · 听众画像（audience profiles）

命中规则：`audience / goal / presentation_type / task` 关键词命中最多者胜；无命中用 `reviewer-symposium`。
实现：`scripts/talkplan.py` 的 `ARCS`（下表关键词与代码正则逐条对齐，`ARCS` 命中数写进
`result.json.audience_model.archetype_reason`）。

| 画像 | 关键词（= 代码正则） | 背景占比（人工裁量，脚本不读取） | 术语（人工裁量） | **结论强度上限** | 问答焦点 |
|---|---|---|---|---|---|
| `committee-defense` | 答辩/学位/评审/评委/defense/committee/viva | 0.08 | 低 | **strong** | 创新点·基线·限制·失效条件 |
| `lab-meeting` | 组会/进度/合作者/同事/lab meeting/group meeting/progress | 0.05 | 无 | **moderate** | 卡点·下一步·数据 |
| `reviewer-symposium` | 评审/会议/研讨会/同行/reviewer/review/symposium | 0.15 | 中 | **strong** | 基线·数据·限制 |
| `teaching-seminar` | 教学/讲座/学生/teaching/lecture/student/tutorial | 0.30 | 高 | **moderate** | 机制·数据 |
| `grant-panel` | 立项/申请/项目/基金/grant/proposal/funding | 0.20 | 中 | **moderate** | 可行性·风险·卡点 |

三条裁量：① 先验越低，背景/术语越多，但每页背景都必须"后面要用到"（"背景占比"是给写手的人读建议，
**脚本不强制**：页型与页数由 `ARCS[*][4]` 顺序与 `bud()` 预算决定，背景页只出现在 `teaching-seminar` 弧里）；
② 组会/教学/立项封顶 `moderate`，进度类汇报出现"显著优于"属高风险表述；
③ **换听众要换弧而不是换措辞**——弧一换，页型顺序、秒数分配、强度上限、问答焦点一起变。选择理由写进
`outline.json.audience_model.archetype_reason`（`result.json.audience_model` 也回显同一份，含 `strength_cap`），
生效上限见 `outline.json.audience_model.strength_cap`，便于复核是否越级。
