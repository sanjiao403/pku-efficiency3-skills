# graphical-abstract-svg · 使用说明

把科研材料变成**单页图形摘要**：分层可编辑 SVG + 真实 PNG + 矢量 PDF + 结构化 `result.json`，
每个图面元素都能回到材料的 locator 与逐字引文。

- 入口：`SKILL.md`（Agent 读它就知道怎么调）
- 方法：`METHOD.md` ｜ 评分对照：`RUBRIC-MAP.md`
- 领域规则：`references/figure-design-rules.md` ｜ 字段契约：`references/result-contract.md` ｜ 失败模式：`references/pitfalls.md`
- 模板：`templates/figure-ir.template.json`、`templates/result.template.json`
- 示例：`examples/`（**均标「示例」**，非组织方固定案例）
- 自检：`tests/selftest.py` → `tests/selftest-report.json`；增益对照：`tests/ab_harness.py` → `tests/ab-report.json`

## 1 安装与依赖

包被平台装到 `/skills/weekly-skill`；**全部脚本只用 Python 标准库**，不联网、不依赖当前工作目录。
可选渲染引擎按可用性自动探测（越高越优先）：

| 能力 | 首选 → 末选 | 说明 |
|-|-|-|
| PNG | cairosvg → PyMuPDF → Pillow → matplotlib → rsvg-convert/inkscape/ImageMagick → Chromium(playwright) → 纯标准库光栅器 | 每级都重新解 IHDR 验真，空白图会被判失败并继续降级 |
| PDF | cairosvg → PyMuPDF → 纯标准库矢量 PDF | 末级仍保留可选中文字（ASCII 用 Helvetica，CJK 用 STSong-Light CID）|

`environment/resources.yaml` 里声明的平台工具（pdf-text / pdf-render / ocr / office-renderer / font-discovery
/ scientific-python）都可以用：脚本不假设它们存在，存在则更好。

## 2 调用步骤（完整）

```bash
SK=/skills/weekly-skill
python3 $SK/scripts/ga_build.py init        # 扫 /input：quote 索引 + 草稿 IR + 最小 result.json
python3 $SK/scripts/ga_build.py show        # 打印带 locator 的材料原文
#  （写 /app/work/figure-ir.json；模板见 templates/figure-ir.template.json）
python3 $SK/scripts/ga_build.py check       # 引文命中 / 四要素 / 覆盖 / 溢出 / 图例一致
python3 $SK/scripts/ga_build.py build       # 渲染 SVG+PNG+PDF 并 finalize result.json
python3 $SK/scripts/ga_build.py selfcheck   # 只复检产物，不重渲染
```

编辑已有 SVG（工单说"在原图上改"时）：

```bash
python3 $SK/scripts/ga_build.py edit --ops /app/work/edit-ops.json
```

本地自测可覆盖路径（平台运行期不需要）：`--input / --work / --output`，以及 `--fast`（跳过浏览器与高开销引擎）。
退出码恒为 0；末行 `CHECK_OK` / `BUILD_OK` / `SELFCHECK_OK` 才是通过。

## 3 输入与输出

| | 内容 |
|-|-|
| 输入 | `/input/case.json`（含 `output_contract`）、`/input/task.md`、`/input/**` 材料（md/txt/csv/pdf/docx/…）|
| 中间 | `/app/work/figure-ir.json`（你写）、`figure-ir.draft.json`、`quote-index.json`、`check-report.json` |
| **产物** | `/app/output/figure.svg`（可编辑源）、`figure.png`、`figure.pdf`、`result.json`、`figure-ir.json`（模型副本）、`run.log`、`edit-record.json`（edit 模式）|

`result.json` 字段表与状态语义见 `references/result-contract.md`。

## 4 预算与降级策略（明示遵守）

- 执行预算：**64 次模型请求 / 900 s / 单次响应 16384 tokens（含 reasoning）**。
- 脚本时间：单案例目标 **≤ 20 s**，硬超时 **120 s**；超时只 finalize 已落盘产物并把缺口写进 `exceptions`。
  实测（本机、三示例案例，`--fast`）：init 0.02 s、check 0.01 s、build 0.8 s、selfcheck 0.01 s。
- 降级矩阵：

| 触发 | 行为 |
|-|-|
| `/input/case.json` 缺失/坏 JSON | 仍出图并写 `status=input_error` + `errors`（不猜内容）|
| 材料为空/无文本层 | `status=insufficient_evidence` + `gaps`；不反推数据 |
| 未撰写 IR | 用 `init` 草稿出图，`status=partial` + `degradations(ir_origin=draft)` |
| 字体缺失 | 记录替换与影响（`font_report` / `exceptions`），CJK 不可用时明确标注 |
| 画布溢出 | 修复阶梯（丢低优先→压行距→降字号至下限→截断），逐步写入 `exceptions` |
| PNG/PDF 导出失败 | 引擎链逐级降级；全失败则交付 SVG 并把失败写明 |

## 5 限制（诚实边界）

- 脚本**不判断科学真伪**：实体/关系/数值由 IR 声明，脚本只保证可核验与版式一致；
  科学正确性由写 IR 的 Agent 与评审负责。
- 位图材料（照片/扫描图）不能作为文字来源：需先 OCR/转写，否则列入 `gaps`。
- 不覆盖论文正文写作、统计分析与实验设计。
- 版面是确定性的四列摘要版式；不追求"花哨信息图"，追求可复核。

## 6 自查方法

```bash
python3 tests/selftest.py     # 32 项：三示例案例 + 空输入 + 坏 JSON + 溢出压力
python3 tests/ab_harness.py   # 增益对照：skill 臂 vs 消融臂
```

`tests/selftest-report.json` 记录每项检查、命令、耗时与环境；`tests/ab-report.json` 记录两臂指标差。

