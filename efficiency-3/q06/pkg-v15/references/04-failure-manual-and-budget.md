# 04 · 失败手册与预算换算

## 1. 预算换算（题面：64 次模型请求 / 900 秒 / 16384 tokens 每次响应）

本包是**确定性代码，不调用任何模型**；模型请求只用在「Agent 读输入、决定要不要改 `plan.json`、
复核产物」这三件事上。按此换算：

| 阶段 | 是否需要模型 | 请求数 | 墙钟 |
|---|---|---|---|
| Step 1 读 `/input/case.json` + task.md | 是（1 次） | 1 | < 10 s |
| Step 2 跑 `run.py`（落 partial 保底 → 全流程） | 否 | 0 | 3–8 s/案例（含真渲染） |
| Step 3 读 `result.json` / `validation.json` 判读 + 决定是否改 `plan.json` | 是（1–3 次） | 1–3 | < 30 s |
| Step 4 若改 `plan.json`：重跑 `run.py`（幂等覆盖） | 否 | 0 | 3–8 s |
| Step 5 跑 `audit_deck.py` / `rigor.py` 复核 | 否 | 0 | < 1 s |
| Step 6 汇总回复 + 交付说明 | 是（1–2 次） | 1–2 | < 20 s |
| **合计** | — | **约 8–12 次**（上限 64，余量 >5×） | **< 3 分钟**（上限 900 s，余量 >5×） |

单次响应 16384 tokens 的用法：`result.json` 体量大（含 `inventory`/`validation`/`rigor_report`），
**不要把整份贴回上下文**——按需读字段（见 `03-output-contract.md` 的字段表），或读 `deck-outline.md`。

## 2. 七步执行卡（走一步勾一步）

```
- [ ] Step 1 读 /input/case.json 与 task.md（先读真实文件，不按领域标签假设材料）
- [ ] Step 2 立刻跑 run.py：它第一秒就写 partial 保底 result.json，随后原地增强、只增不删
- [ ] Step 3 读 result.json：status / uncertainty / checks.errors / evidence_map 的 locator_verified
- [ ] Step 4 需要改页就改 plan.json（放在 case.json 同目录，run.py 自动采用）后重跑 run.py
- [ ] Step 5 跑 audit_deck.py --out ... --report-out reports/audit-report.json（只读产物重算 A1–A8）
- [ ] Step 6 跑 rigor.py --all --report reports/rigor-report.json（逐条证据回查材料）
- [ ] Step 7 契约自检：契约键全在、outputs[] 哈希对、status 与闸一致；如实写 uncertainty
```

**保底优先于完美**：Step 2 的 `run.py` 先写 `{"status":"partial","uncertainty":["run started…"]}`，
再逐阶段覆盖。因此即使渲染器缺失、材料是扫描件、进程被杀，磁盘上永远有一份**可复核的诚实产物**。

## 3. 失败手册（都能交，都不编）

| 情况 | 识别方式 | 处置 |
|---|---|---|
| `materials` 全部缺失 / 读到 0 段 | `uncertainty` + `status=partial`（空产物守卫） | 不产出 deck 或产出即标注；**永不报 success** |
| PDF 无文字层 / 加密 | `src.text_layer=false`、`inventory.notes` | 提示先 OCR；页变薄；`uncertainty` 记录 |
| 材料只有摘要 | `len(src.segments)` 很小 | 缺的环节写 `evidence_absent_reason` |
| 材料没有 figure/table | `inv.captions` 为空 | 图页退回文字证据页（材料没有就没有） |
| 页数超 `slide_limit` | `checks.budget.over_by>0` | 按角色优先级截断 + `pages_wanted`/`dropped_by_limit` 记账 |
| 声明了模板但找不到 | `resolved_from.template.resolved_from="missing"` | 用内置几何（`describe_template(None)`），`uncertainty` 说明 |
| 模板占位符不足 | `qa.py` 版式维度 reasons | 同版式手动文本框补齐，notes 中说明 |
| 无 office（soffice 与 PowerPoint 都缺） | `render.preview_mode != "real"` | 出模型预览并**标注清楚**；`status` 降 `partial` |
| 契约字段读不懂 | `contract.unresolved` | 该字段给 `""`/`[]`，不猜 |
| 脚本崩溃 | `error.log` + `result.json.uncertainty` | `main()` 兜底：写 `error.log`，把 `status` 降 `partial` 并追加原因 |
| 需要 PDF/PNG 预览而渲染不可用 | `deck.pdf` 缺失 | 交付仍含可编辑 pptx；提示 `soffice --headless --convert-to pdf deck.pptx` |

## 4. 回归面（改完必跑）

```bash
python3 tests/selftest.py                                    # 9 项：单元 + 端到端 + 独立审计
python3 scripts/gain_check.py                                # 带标签判定案例 4/4
python3 scripts/benchmark_local.py --reps 3                  # 真实两臂对照 → tests/benchmark-report.json
python3 scripts/rigor.py --case <case.json> --all --report reports/rigor-report.json
python3 scripts/audit_deck.py --out <run> --case <case.json> --report-out reports/audit-report.json
```
