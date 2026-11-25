---
name: apparatus-roadmap-figures-min
description: 把实验材料（装置清单/工艺描述/研究计划）转成可核验、可编辑的科研图稿：中间表示 IR（含覆盖索引）+ 分层 SVG + PDF/PNG + result.json，每个图元都能指回原文行号，并由两个职责单一的校验器分别判 IR 合规与跨产物一致性。材料没写的一律不画、不补。适用"材料→图稿"的装置结构图、工艺流程图、技术路线图。
---

# apparatus-roadmap-figures（极简自足版 · IR 契约化）

**一条命令，零外部前提**（不依赖预置 IR、不依赖对照数据、无额外开关）：

```bash
python3 scripts/apparatus.py --case /input/case.json --out /app/output
```

读 `case.json` 与同目录材料 → 启发式抽取 → **IR（`figure.ir.json`，含覆盖索引）** → 分层 SVG →
PDF/PNG → `validate_ir.py` 判 IR 合规 → `check_consistency.py` 判跨产物一致 → `result.json`。

## 文件地图
| 文件 | 作用 |
|-|-|
| `scripts/apparatus.py` | **唯一入口**（材料 → IR/SVG/PDF/PNG/result.json；含 `--arm naive` 对照臂与绘图库） |
| `scripts/validate_ir.py` | 只判 **IR 自身**：schema/枚举/唯一性/端点/索引不变量 + **图元库文档同步** |
| `scripts/check_consistency.py` | 只判 **跨产物一致**：材料↔IR↔SVG↔result.json（逐字回溯、覆盖、id 集合、哈希、箭头、数字来源） |
| `references/ir_schema.md` | IR 契约（字段、不变量、两个校验器的边界） |
| `references/symbol_library.md` | 图元库契约（kind → 画法/配色/线型/图层/data-* 属性） |
| `examples/case-01-buffer-train/` | 三件套示例（`material.txt` / `intermediate.json` / `output.svg`，**示例，非正式答案**） |
| `tests/gain_cases.json` | 带标签案例 + 真实 A/B 原始数字 + `verdicts[]`（示例，非正式答案） |
| `RUBRIC.md` / `GAIN.md` / `INNOVATION.md` / `PROVENANCE.md` | 五维度判据 / 对照证据 / 创新点 / 来源可追 |

## 输出
| 文件 | 内容 |
|-|-|
| `figure.ir.json` | 中间表示：`figure_type`、`elements[]`、`relations[]`、`extraction_index[]`、`resolved_from` |
| `figures/figure.svg` | 分层 SVG：真实 `<text>` 未转曲；每块带 `data-role`/`data-node`/`data-kind`/`data-quote`/`data-src` |
| `figures/figure.pdf` / `.png` | 矢量导出与 300 dpi 预览（后端缺失时如实记录，不伪造） |
| `result.json` | 契约字段 + `elements/relations/data_mapping` + `provenance/sources/change_log` + `resolved_from` + `checks.ir` / `checks.consistency` + `outputs[]`（path/bytes/sha256） |

## 底线（硬规则，都由校验器兜底）
* 只画材料里读到的；**不补**部件/参数/连线；无数值就不标数值；无流向句就连线留空并进 `uncertainty`。
* 连线只认**显式流向动词**；被动句判上游→下游；**指代不明不画线**，只记录。
* 每条图元/连线/索引条目的 `source.quote` 必须**逐字**来自材料（空白归一化后可回溯）。
* 覆盖索引：材料里读到的每个部件/步骤/阶段要么 `mapped_id`，要么 `status=omitted` + `reason`。
* **0 图元 → `partial`** + `empty figure: 0 drawable elements (…)`；校验器有硬失败 → `status` 翻 `partial`。
* 输入发现只认 `case.json` 所在目录之下；**绝不按绝对路径目录段过滤**（包放在含 `outputs`/`runs`/`stage`
  的路径下照常工作）；`case.json` 点名的相对路径按 `case_dir → cwd → /input` 解析并记 `resolved_from`。

## 自检
```bash
python3 scripts/validate_ir.py --ir /app/output/figure.ir.json                    # 0 = IR 合规
python3 scripts/check_consistency.py --ir /app/output/figure.ir.json --materials /input \
        --svg /app/output/figures/figure.svg --result /app/output/result.json     # 0 = 跨产物一致
```
两个校验器**只读、不写产物**；IR 的问题与一致性的问题分别只在一个地方报出来（`INNOVATION.md §2`）。
