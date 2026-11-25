# RUBRIC-MAP · 评分维度 → 包内文件与证据

原题满分 100（+5 GitHub 链接，本题按 Lead 决定不提交公开链接）。下表把每一档评分点映射到
**本包里可打开、可运行、可复核的文件**，避免「文字自述代替运行证据」。

> 同名内容原先放在 `references/` 下；按 83 分包共性提到包根，便于评审直接定位。

## 1. 实际效果 40 分

| 评分点（分值） | 本包对应物 | 可复核证据 |
|---|---|---|
| 任务完成度 15：真正把论文变成主线成立、页序可讲、可在模板中交付的 PPT | `outline.py`（叙事骨架 `title→question→gap→approach→evidence→result→limits→takeaway`）；`deck.py`（模板占位符 + 真版式） | `runs/*/output/plan.json`、`deck.pptx`、`deck.pdf`、`slides/*.png` |
| 结果正确性 15：数字/单位/方法名/结论与论文一致；图号与引用对得上；不把示意图当实验数据 | `inventory.py`（数值+单位底账、指标名单位 `R²=0.86`、图注编号）；`plan_validate.py` 四道硬闸（`REF_NOT_IN_SOURCE`/`NUMBER_NOT_IN_SOURCE`/`QUOTE_NOT_FOUND`/`SCHEMATIC_AS_DATA`） | `validation.json`（errors=0）、`evidence-map.json` 的 `locator_verified` 与 `match` |
| 结果完整性 5：主线必需页齐全、六类要素覆盖 | 角色齐全度 + 七道闸 | `audit.json.dimensions`、`validation.json.metrics.role_coverage` |
| 结果可核验性 5：每页能回溯到图/表/章节/页码；提供页级金标准、源文件与导出文件 | `evidence-map.json`（页号 / claim / 图注编号 / locator / 逐字引文）；`deck.pptx`（可编辑，母版/版式驱动）+ `deck.pdf`（真导出件）+ `slides/*.png` | `runs/*/output/evidence-map.json`；`result.json.render.verification` 给出预览实测（PDF 页数 / 页面尺寸 in / 嵌入字体与子集判断 / 每页 dpi·墨迹·空白·压边 / 图表掉件）；`audit-deck.json` 的 A9 不读 `render.json` 独立复算；包内不放二进制（平台只收 UTF-8 文本资源，运行期产物才是二进制） |

## 2. 使用增益 25 分

| 评分点（分值） | 本包对应物 | 可复核证据 |
|---|---|---|
| 质量增益 15：同输入同模板同版本下，页级正确性/主线清晰度/版面合规稳定优于基础 Agent | `benchmark_local.py`（**可运行**）：同一材料、同一几何、同一判据下对比「段落贴页基线」 | `tests/benchmark-local.json`（命令默认输出到此）；EN-PDF 示例：定位页 0→9、证据覆盖率 0.0→1.0、备注重复度 1.0→0.061、图表页 0→2、证据锁 error 1→0；**如实记录一处未改善**：原文可核对数字数 37→35（压缩措辞的代价），三示例中另两例为 31→40、13→29 |
| 效率增益 5：端到端耗时、人工修改页数下降 | 脚本确定性、单案例 3–10 秒；`plan.json` 可直接手改页后重跑（改页不改脚本） | `result.json.performance`、`run.log`、`--plan-only` 用法（`SKILL.md`） |
| 增益可验证性 5：同输入、同模板、同版本的公平对照 | 上述对照使用与被测产物**相同的** `layout`/`notes`/`plan_validate` 函数，可被第三方重跑 | `python3 scripts/benchmark_local.py --case <case.json>`（零附加参数即落盘 `tests/benchmark-local.json`） |

## 3. 创新增益 15 分

| 评分点（分值） | 本包对应物 | 相对已有方案的边界 |
|---|---|---|
| 新增能力 5：基础 Agent 不具备的能力（图表定位与页级引用、模板占位符约束排版、备注与页面内容分离生成） | ① `inventory.py` 的「数值+单位」与「图注编号」底账；② `plan_validate.py` 证据锁；③ `layout.py` 容量计算；④ `notes.py` 重复度门限 | 通用 PPT 生成器（含部分竞品）没有「先查存在再上页」这一步；本包把引用正确性变成**可失败的闸**，而不是生成者的自觉 |
| 方法改进 5：实质性改进而非包装 | ① LaTeX `\ref` 在展平前解析为人类图号；② PDF 按 x 间距切列以还原表格；③ 表行高度写死避免 PowerPoint 撑行；④ 页码用 OOXML 域而非写死数字 | 每条都对应一个真实失败模式，`METHOD.md` §1/§5/§6 说明成因 |
| 创新证据 5：证明相对已有方案的价值 | 三案例真跑 + `validation.json` + `benchmark-local.json` + 渲染件 | `runs/example-*/output/`；`NOTES.md` 记录与 73247/86395 文件树的差异 |

## 4. 可靠体验 10 分

| 评分点（分值） | 本包对应物 | 可复核证据 |
|---|---|---|
| 调用易用性 3：能被正确触发、按说明跑出可打开可编辑的 PPT | `SKILL.md` frontmatter `name`/`description` 含中英文触发词；零参数 `run.py` | `python3 scripts/run.py` 一次成功日志 |
| 运行稳定性 4：不同论文类型/不同模板/重复运行下持续可交付 | 三种材料形态（PDF / LaTeX / 中文 MD）+ 两种模板路径（模板 .pptx / 内置几何）各真跑；重跑幂等 | `runs/example-en-pdf`、`example-latex`、`example-zh-md` 的 `result.json.status=success` |
| 异常处理 3：图无法提取/公式为图片/PDF 加密/占位符不足/字体缺失/页数超限的识别与处置 | `SKILL.md`「异常与降级」表；实现见 `render.py` 三引擎回退、`deck.py` 示意图与「表体未还原」标注、`text_layer=false`、`SLIDE_LIMIT` 警告、`contract.unresolved` | `audit.json`、`result.json.uncertainty` |

## 5. 生态贡献 10 分

| 评分点（分值） | 本包对应物 | 可复核证据 |
|---|---|---|
| 文档完整性 3：使用说明、依赖、模板要求、示例、适用范围、限制、维护 | `README.md`（依赖版本表、预算声明、限制、维护约定）、`METHOD.md`、`SKILL.md`、`references/*` | 文件本身 |
| 可复用性 4：Skill 本体、模板、页级大纲模板、证据映射表等可被他人复用 | `templates/slide-plan.template.json`、`templates/result.template.json`、`templates/template-spec.example.json`、`references/slide-blueprint.md` | `templates/`、`references/` |
| 分享推广价值 3：沉淀可分享的案例/方法/经验 | 三份形态各异的示例（英-PDF / LaTeX / 中文 MD + 单位模板）；`benchmark_local.py` 可复用的机制对照方法 | `examples/`、`tests/selftest-report.json` |

## 判分口径自查（本包自报，非平台分数）

| 检查 | 结果 |
|---|---|
| 四组真跑（EN-PDF / LaTeX / ZH-MD+模板 / 真实 arXiv PDF） | `success` ×4（证据锁 0 error、七道闸 7/7、独立审计 10/10） |
| 证据覆盖率 | 1.0（全部内容页带可定位依据） |
| 最小字号 | 11 pt（门限 11 pt） |
| 溢出页 | 0 |
| 备注最大重复度 | ≤ 0.10（门限 0.34） |
| 渲染 | 真渲染：PowerPoint COM 导出 PDF + 每页 PNG；`render.verification` 实测页数/页面尺寸/嵌入字体/每页 dpi/空白/压边 |
| 单案例耗时 | 3–10 秒（预算 900 秒） |
