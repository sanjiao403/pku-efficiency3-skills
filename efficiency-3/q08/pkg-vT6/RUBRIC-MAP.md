# RUBRIC-MAP · 评分维度 → 包内文件与可核对证据

> 用法：评审/复核者按"看哪里"直接跳到文件；每条都给出**实测读数**（来自 `tests/selftest-report.json`
> 与 `runs/<case>/result.json`，可用 `scripts/run.py` 原样复跑复现）。
> 本表只映射"证据在哪"，不宣称分数。

## 0. 三个固定案例的自测读数（playground 复跑得到，3/3 success）

| 案例（自建夹具） | 页数（约束） | 溢出框 | 正文最小字号 | 图/比例偏差 | 引文可回源 | 定位覆盖 | PDF 页数=pptx | PDF 文本覆盖率 | 字体替换 |
|---|---|---|---|---|---|---|---|---|---|
| F1 中文·纳米酶（md 源，16:9） | 11（9–12） | 0 | 20.0 pt | 1 张 / 0.000% | 100% | 100% | 11=11 | 100% | 无 |
| F2 英文·随机对照（md 源，4:3 中文版式名） | 10（8–10） | 0 | 20.0 pt | 1 张 / 0.000% | 100% | 100% | 10=10 | 100% | 无 |
| F3 英文·消融研究（旧 deck 改造 + 思源主题字体缺失） | 12（9–12） | 0 | 20.0 pt | 1 张 / 0.000% | 100% | 100% | 12=12 | 100% | `Source Han Serif SC`→回退（已记录） |
| F4 中文·同一论文（**中文版式名+中文占位符名**的 4:3 模板） | 11（9–12） | 0 | 20.0 pt | 1 张 / 0.000% | 100% | 100% | 11=11 | 100% | 无 |

`tests/selftest.py` 全量：**82/82 通过，约 90 秒**（4 案例全链 + 3 项降级 + 1 项反例 + 6 项模块/中文/缺版式自测）。

## 1. 实际效果（40 分）

| 评分点 | 证据文件 | 怎么核 |
|---|---|---|
| 任务完成度（PPT 真套进指定模板，可打开可编辑） | `scripts/build_pptx.py`、`scripts/pptx_util.py`、产物 `<case_id>.pptx` | `template_map.json` 的版式表 vs `results.fit.inheritance`：版式数一致、主题字体一致；`fit_report` 里每页占位符**没有** `a:xfrm`（坐标来自版式继承，不是复制坐标） |
| 结果正确性（文字/数字/图号与源材料一致，母版版式继承真实发生） | `scripts/source_extract.py`、`evidence_map.json`、`results.evidence_summary` | 每条 `evidence[]` 带 `locator + quote + verified`；`quote_verified_rate=1.0` 表示每条断言都能在源材料里逐字找到 |
| 结果完整性（封面→结论的页类型、六类要素齐备） | `slide_plan.json`、`deck_report.md` §2 | 页角色序列 `title→agenda→bullets/figure→conclusion→closing`；§2 表逐页给主张+定位；讲稿在 pptx 备注页（`results.build.slides[].notes_chars`） |
| 结果可核验性（源/模板/导出/逐页偏差记录） | `result.json.artifacts`（每个带 `sha256`+`bytes`）、`results.fit.issues`、`results.render.pages[]`、`change_log` | `artifacts[].sha256` 可比对；逐页 `text_coverage`/`bbox_margins_pt`/`images` 是导出件的实测值；`change_log` 8 步逐条给证据位置 |

## 2. 使用增益（25 分）

| 评分点 | 证据文件 | 怎么核 |
|---|---|---|
| 质量增益（同输入同模板下比基础做法好） | `runs/f1/baseline_comparison.json`（`scripts/run.py --baseline` 生成） | 基线（900 字整段粘进占位符、18pt 无 autofit、图按容器宽高硬塞）实测：溢出 2 页、图宽高比偏差 **46.5%**、PDF 文本覆盖 **95.1%**、定位覆盖 0、引文回源 0；本 Skill：0 溢出、0.000%、100%、100%、100% |
| 效率增益（减少排版耗时与返工页数） | `run.py` 的 `pipeline.elapsed_s`、`baseline_comparison.plan_slides` | 单册 6–25 秒内完成"解析→成册→复核→导出"，无人工逐页搬版；被裁内容与理由进 `dropped_content`，不需要事后人工找 |
| 增益可验证性（公平对照） | `--baseline` 开关 + `baseline_comparison.json` 的 `note` | 基线在**同一模板、同一材料、同一渲染后端**下跑；文件里明确写"这是自建基线，不代表组织方白板" |

## 3. 创新增益（15 分）

| 评分点 | 证据文件 | 怎么核 |
|---|---|---|
| 新增能力 | `pptx_util.theme_info/clone_placeholder/set_run_fonts`、`render_preview.check_pdf` | ① 直接把主题 XML 读成 major/minor 的 latin·ea·cs + Hans 脚本表并沿用；② 克隆 latent 的 footer/slide-number 占位符并写可编辑 `a:fld slidenum`（python-pptx 默认不克隆，页脚页码就不会显示）；③ 字体名对齐表（黑体↔SimHei、Times New Roman↔TimesNewRomanPSMT）才判得准"是否被替换" |
| 方法改进 | `fit_check.py`（含 fontScale 的溢出估算 + `a:xfrm` 继承判据）、`run.py`（渲染回测-修正循环） | 溢出不是"看起来挤"，而是按每段**实际字号×normAutofit fontScale** 估算高度/容器；修正循环用 PDF 回测结果把末条证据移入备注，字号永不低于 14pt |
| 创新证据（边界与价值） | `results.capability_boundary`、`deck_report.md` §6–7、本文件 §0 | 明确写"技术检查不证明学术质量"；对照读数可复跑；图表适配把"原图比例"与"容器放置"分成两步（`make_figure` 出等比原图 → `fit_picture` 等比放置并回报偏差） |

## 4. 可靠体验（10 分）

| 评分点 | 证据文件 | 怎么核 |
|---|---|---|
| 调用与易用性 | `SKILL.md` §0/§2/§3、`templates/case.template.json` | 一条命令跑通：`python scripts/run.py --input /input/case.json --out /app/output`；输入契约带默认值表；`--plan` 允许 agent 先改文案再成册 |
| 运行稳定性 | `tests/selftest-report.json`（82/82）、`pipeline.steps` | 四个异构案例（中文/英文、16:9/4:3、**中文版式名+中文占位符名**、旧 deck 改造、主题字体缺失、**模板缺正文版式**）全绿；每步中间产物落盘，后步失败不影响前步交付 |
| 异常处理 | `SKILL.md` §5 表、selftest `degradation` 段 | 缺材料→partial+原因（B1）；缺模板→自带模板+uncertainty（B2）；无渲染后端→HTML 兜底+不伪造 PDF（B3）；反例 plan 被 high 拦截（C1） |

## 5. 生态贡献（10 分）

| 评分点 | 证据文件 | 怎么核 |
|---|---|---|
| 文档完整性 | `SKILL.md`、`METHOD.md`、`README.md`（含资源清单与预算声明）、`templates/result.template.json` | 用途/适用条件/调用/输入输出/异常降级/依赖/版本/限制/维护都在 README+SKILL；`result.json` 字段级说明单独成表 |
| 资源可复用性 | `scripts/*`（11 个可独立 CLI 运行的脚本）、`templates/*.json`、`tests/fixtures/*` | 每个脚本都有 `--help` 与独立入口（`template_probe`/`source_extract`/`plan_deck --validate`/`build_pptx`/`fit_check`/`render_preview`/`audit`）；夹具是纯文本，可直接换自己的论文/模板复跑 |
| 分享推广价值 | `tests/fixtures/`（3 个异构学术场景）、`RUBRIC-MAP.md`、`examples/` | 沉淀了"页级证据映射 + 版式预算阶梯 + 渲染回测"的可搬运做法；夹具覆盖中英/横竖版/改造场景，可当模板题集用 |
