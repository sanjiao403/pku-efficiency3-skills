# ppt-template-fit · README（安装 / 使用 / 资源清单 / 预算）

学术 PPT 模板与格式适配 Skill：**论文或研究材料 → 按真实 pptx 模板生成可编辑演示文件 +
页级证据映射 + 版式与导出复核**。入口文档是 `SKILL.md`；方法取舍见 `METHOD.md`；
评分维度对照见 `RUBRIC-MAP.md`。

## 1. 安装与依赖

```bash
# 平台：Skill 会被装到 /skills/weekly-skill（本目录即 Skill 根）
python -c "import pptx, PIL, fitz"        # 必需：python-pptx / Pillow / PyMuPDF
python -c "import matplotlib"             # 可选：只影响 case.figure_specs 的数据出图
# 渲染后端（任选其一，都没有也能跑，只是导出降级）
#   Windows: PowerPoint（COM 自动化）    Linux: apt-get install libreoffice
```

| 依赖 | 必需性 | 用途 | 缺省时的行为 |
|---|---|---|---|
| `python-pptx` ≥1.0 | 必需 | 读写 pptx、母版/版式/占位符 | 无法运行（提前报错） |
| `Pillow` | 必需 | 读图片像素，算宽高比偏差 | 图片比例检查跳过并记录 |
| `PyMuPDF` | 必需（PDF 源/渲染回测） | PDF 抽文本与图、PDF 回测 | md/docx 源仍可用；回测降级 |
| `matplotlib` | 可选 | `figure_specs` 出图 | 该图缺失 → 记 warning，页退化为纯文字 |
| PowerPoint / LibreOffice | 可选 | pptx → PDF/PNG | `status=partial` + `preview/preview.html`，**不伪造 PDF** |

版本：Skill **1.1**（2026-11-22）——相比 1.0 新增：
① **中文母版/版式名/占位符名识别**（`标题 1`/`副标题 2`/`内容占位符 3`/`正文`/`图片占位符`/`页脚占位符`/
`幻灯片编号占位符`；OOXML `p:ph` 未带 `type` 时按名称兜底）；
② **「模板里没有你要的版式」降级实测**（`pptx_util.py --strip-body` 造出无正文占位符的模板 →
自动改走合成文本框并记账、仍产出可编辑 pptx）；
③ 夹具扩到 4 个（新增 F4：中文版式名+中文占位符名的 4:3 模板），自检断言 61→**82**。
脚本全部 Python 3.9+ 语法（`from __future__ import annotations`），无网络访问、无外部服务。

## 2. 一次完整调用

```bash
# D14-R1 零附加参数入口（模板由文本 spec 运行期合成）
python3 scripts/fit.py --case /input/case.json --out /app/output

python scripts/run.py --input /input/case.json --out /app/output --backend auto
# D14-R3 只读独立审计（不重跑生成，只读 result.json / pptx / preview 重算并对照自述值）
python scripts/audit_only.py --out /app/output --json /app/output/audit_only.json

# 常用变体
python scripts/run.py --input case.json --out out --backend none      # 只跑链，不渲染（最快）
python scripts/run.py --input case.json --out out --plan my_plan.json # 用 agent 改过的文案
python scripts/run.py --input case.json --out out --baseline          # 附"直接粘正文"基线对照
python scripts/run.py --input case.json --out out --iterations 3      # 渲染回测修正轮数
python tests/selftest.py --quick                                      # 10 秒自检
```

中间产物落 `--work`（默认 `<out>/work`），可单步重跑：

```bash
python scripts/template_probe.py --template t.pptx --out template_map.json
python scripts/source_extract.py --source paper.pdf --work work --out source_map.json
python scripts/plan_deck.py --case case.json --source-map source_map.json \
       --template-map template_map.json --out slide_plan.json
python scripts/plan_deck.py --case case.json --source-map source_map.json \
       --template-map template_map.json --validate slide_plan.json     # 只校验，不改
python scripts/build_pptx.py --plan slide_plan.json --template t.pptx --out deck.pptx
python scripts/fit_check.py --pptx deck.pptx --plan slide_plan.json \
       --source-map source_map.json --template-map template_map.json --out fit_report.json
python scripts/render_preview.py --pptx deck.pptx --out out --backend auto --plan slide_plan.json
python scripts/audit.py --case case.json --plan slide_plan.json --source-map source_map.json \
       --template-map template_map.json --build-log build_log.json --fit fit_report.json \
       --render render_report.json --pptx deck.pptx --out out
python scripts/pptx_util.py --out <pkg 外目录>/mine.pptx --size 16:9 --theme academic-cjk
python scripts/source_extract.py --csv data.csv --spec spec.json --figure-out figures/fig1.png
```

## 3. `result.json` 契约字段（回显 + 自述）

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | str | 原样回写输入标识 |
| `task` | str | 任务名 |
| `status` | `success`\|`partial` | 只有全绿才 success |
| `status_reason` | str | 具体原因（缺哪个文件/哪项不达标），非套话 |
| `summary` | str | 一句话事实摘要（含页数/证据数/关键指标） |
| `results.template` | obj | 模板事实 + 继承核查（版式数/主题字体是否保持） |
| `results.plan` | obj | 页结构统计、被裁内容与理由、字体计划、字号阶梯 |
| `results.build` | obj | 逐页填充记录、合成占位符、`fontScale`、构建期警告 |
| `results.fit` | obj | 静态复核 metrics + issues + 一致性 |
| `results.render` | obj | 后端、页数、逐页覆盖率/边距/字体/图片、替换与问题 |
| `results.metrics` | obj | 汇总指标（见下表） |
| `slides[]` | array | 页级：角色/版式/标题/主张/定位/图/字号/溢出/渲染读数 |
| `evidence[]` | array | `page + locator + block_id + quote + verified` |
| `sources[]` | array | 源文件（名/类型/sha256/页数或字符数/抽取方法） |
| `uncertainty[]` | array | `item + why + handling`（材料/字体/渲染/裁剪四类） |
| `change_log[]` | array | 8 步流水线每一步做了什么、证据在哪 |
| `artifacts[]` | array | 每个产物的 `path/bytes/sha256/exists` |
| `capability_boundary[]` | array | 能证明什么、不能证明什么 |
| `reproduce` | str | 复跑命令 |
| `narrative` | str\|null | agent 写的叙述（脚本不代写），`narrative_source` 标来源 |
| `output_contract_echo` / `contract_unresolved_fields` | obj/array | 输入 `output_contract` 的回显与未决字段 |

关键指标（`results.metrics`）：`template_layouts_preserved`、`template_theme_preserved`、
`slides`、`slides_with_overflow`、`overflow_boxes`、`min_body_pt`、`figure_aspect_max_deviation`、
`locator_coverage`、`quote_verified_rate`、`pdf_pages`、`pdf_backend`、`font_substitutions`、
`min_pdf_text_coverage`、`page_number_slides`、`footer_slides`、`baseline_comparison`（可选）。

## 4. 资源清单（≤50 个文本文件 / 单文件 ≤500KB / 合计 ≤2MB / 无符号链接）

| 目录 | 文件 | 说明 |
|---|---|---|
| 根 | `SKILL.md` `METHOD.md` `README.md` `RUBRIC-MAP.md` | 调用入口 / 方法 / 说明 / 评分映射 |
| `scripts/` | `units.py` `pptx_util.py`（含模板生成/改造 + 文本 spec 合成）`template_probe.py` `source_extract.py`（含数据出图）`plan_deck.py` `build_pptx.py` `fit_check.py` `render_preview.py` `audit.py` `run.py` `fit.py`（零附加参数入口）`audit_only.py`（只读审计） | 12 个可独立运行的脚本 |
| `templates/` | `template-spec.json`（**文本模板规格**：3 套模板的画幅/主题字体配色/11 版式的占位符 idx·类型·名称·几何/角色映射）`case.template.json` `plan.template.json` `result.template.json` `layout_roles.json` | 包内**零二进制**：pptx 一律运行期合成 |
| `references/` | `result-contract.md`（result.json 字段表 + status 判据 + 独立审计口径） | D14-R3 |
| `examples/` | `README.md` `case.example.json` `plan.example.json` `result.example.json` | 最小调用示例（**示意输出，非正式案例结果**） |
| `tests/` | `selftest.py` `selftest-report.json` `fixtures/f1|f2|f3|f4/*` | 自检脚本 + 最近一次全量自检报告 + 4 个纯文本夹具（f2/f3/f4 的模板在自检时生成，不进包） |

## 5. 运行预算与降级策略（平台契约）

- 预算：**64 次模型请求 / 900 秒 / 单次响应 16384 tokens（含 reasoning）**。
  本 Skill 的脚本链路**零模型调用**；单案例端到端（含 PowerPoint 渲染）**6–25 秒**，
  因此预算几乎全部留给 agent 的文案与叙述工作。
- 时间纪律：`--backend none` 可把单案例压到 1–3 秒；`tests/selftest.py --quick` 10 秒完成自检；
  先用 `--backend none` 跑通链路、最后再渲一次预览，是最省时的用法。
- 降级顺序：缺模板→自带模板；缺材料→partial（不造内容）；无渲染后端→HTML 兜底（不伪造 PDF）；
  内容超容量→阶梯降字号（≥14pt）→余量入备注→记录；页数超限→按分值裁剪并记账。
- 幂等：所有产物带 sha256；中间产物分步落盘，可只重跑失败的那一步。

## 6. 维护与限制

- 模板多样性：角色识别依赖"名称强信号 + 占位符构成"；遇到结构异常模板（无 body、只有图片占位符）
  会走合成路径并把几何写进 `placeholders_synthesized`，评审可据此判断是否可接受。
- 字体：跨平台渲染必然存在回退，本 Skill 的选择是**显式记录替换**而非追求物理一致。
- 夹具说明：`tests/fixtures/*` 是为自检合成的材料（文件头标注 FIXTURE），不是真实发表论文，
  也不替代平台的组织方案例；`examples/` 中的输出一律标注"示意"。
