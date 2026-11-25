# scientific-figure-adv2

科研数据图表生成与编辑的 Skill 包：**源数据 → 图元（可追溯）→ 可编辑源 + 投稿导出（可测量）→ 独立复算**。

## 1. 快速开始

```bash
python3 scripts/chart.py  --case /input/case.json --out /app/output      # 主命令，零附加参数
python3 scripts/verify.py --case /input/case.json --out /app/output      # 只读产物复算，失败退 1
python3 tests/selftest.py --out /tmp/selftest                            # 包自检（含降级与拷贝探针）
```

只看一眼接口长什么样：

```bash
python3 scripts/chart.py  --case examples/case.example.json --out /tmp/out
python3 scripts/verify.py --case examples/case.example.json --out /tmp/out
```

`examples/` 里的输入、图规范与导出证据都是**示例（非正式答案）**，不是平台正式案例。

## 2. 目录

```
SKILL.md                        触发场景 / 命令 / 输入输出契约 / 降级行为 / 边界
README.md                       本文件：安装、运行、产物、自检、限制
references/encoding-rules.md    数据编码 → 图例 / 单位 / 误差线 / 色盲-灰度的领域规则
references/exports.md           导出预设（89mm/7pt/Okabe–Ito/300dpi）、引擎链、证据字段、已知限制
scripts/chart.py                单入口构建器：三种渲染共用一份 layout()
scripts/verify.py               只读判定器：重读源单元格 + 交叉核对 SVG/PDF/PNG
examples/                       示例输入、示例图规范、示例导出证据（均标「示例（非正式答案）」）
tests/selftest.py               端到端自检脚本；tests/selftest-report.json 是它一次真实运行的输出
```

## 3. 运行环境

- Python 3.9+；**标准库即可**（`argparse/csv/json/os/re/math/hashlib/zlib/xml.sax`）。
- 可选：`matplotlib`（有则导出件用真字体渲染，支持 CJK；无则走标准库写出器）。
- 不需要网络、不需要预置模板或白板、不需要人工步骤。

## 4. 产物与判据

`/app/output` 下：`figure.svg`（可编辑源）、`figure.pdf`（矢量导出）、`figure.png`（300 dpi 预览）、
`figure.map.json`（图元↔源单元格）、`export_check.json`（导出证据）、`render_report.json`（渲染记录）、
`result.json`（输出契约：`case_id`/`status`/`summary`/`editable_source`/`exports`/`element_map`/`checks`/
`sources`/`change_log`/`uncertainty` + `output_contract` 声明的键 + `output_files[]` 的 bytes/sha256）。

判定器**当前为 19 项**（以 `python3 scripts/verify.py …` 每次运行打印的末行 `N/N recomputed checks passed`
为准，不以此处数字为准），包括：产物哈希、`export_check.json` 的 PDF/PNG 参数、每个图元 id 真在 SVG 里、
**每个数值回读源表物理行**是否一致、单位是否写在轴上、图例唯一且被画出、色觉与灰度分离度
（Machado 2009 + CIE76，从 SVG 填充色重算）、PDF 的矩形/颜色/文本算子是否与 SVG 对应、
**PNG 光栅是否与 SVG 图元一致**、定位器指向的是真表、`sources[]` 只含测量表、SVG 无位图/无外链、契约键齐全。

## 5. 限制（诚实列出）

见 `SKILL.md §7` 与 `references/exports.md §4`：不做统计推断；只做柱状/分组柱状；无多面板；
不输出 CMYK/PDF-X；标准库导出路径的 PNG 不画字形；扫描件 PDF 需先自行取文本。

## 6. 证据边界（本包的一等约束）

只有 `.csv` / `.tsv`（或工单内联表）会被当作测量数据。`.txt` / `.md` 是材料，仅登记为
`evidence_channels.materials_seen`；`case.json`、`task.md`、`*.example.json`、`*.template.json`
是工单/文档，同名 JSON 只登记为 `rejected_as_non_data`，**永远不会变成图上的数值或某个数值的引文**。
`result.json.evidence_channels.work_order_used_as_data` 恒为 `false`，`tests/selftest.py` 用两条
负向对照（`material_doc_is_not_data`、`sibling_example_json_not_data`）证明这条边界真的会拦住。

## 7. 可复现性（逐字节）

把 `SOURCE_DATE_EPOCH` 钉成任何整数后，**同输入两次运行的全部产物逐字节相同**（含 `figure.pdf`：
matplotlib 的 `/CreationDate` 由该变量决定；`result.json`/`render_report.json` 的时间戳与耗时字段
也一并改为该变量的函数）。不钉时按真实时间记录，产物照常可用。回归项：`tests/selftest.py` 的
`reproducible_byte_identical`（含 sha256 清单）。

## 8. 版本

`adv2-1.0`（脚本内 `VERSION`）。相对 `pkg-adv1` 只改两处：① 钉 `SOURCE_DATE_EPOCH` 实现逐字节可复现
（含 selftest 回归项）；② 文档漂移（检查项数 17→19、去掉重复的 `## 6.` 标题，并声明"检查项数以运行时输出为准"）。
`adv1` 冻结不再改。
