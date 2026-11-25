# paper2deck · README

把一篇论文（或一组科研材料）变成**可讲、可核验、可编辑**的学术汇报 PPT。
`SKILL.md` 是给 Agent 的执行说明；本文件是给人看的安装、使用、依赖、限制与维护说明。

## 1. 30 秒安装与运行

```bash
# 平台：输入 /input/case.json，产物写到 /app/output
python3 scripts/run.py

# 本地/自测
python3 scripts/run.py --case examples/case_en_pdf/case.json --out out --work work
```

零第三方服务、无网络调用。需要 `python-pptx`；`Pillow` 可选（图提取与模型预览）。
`lxml` 由 `python-pptx` 带入。

想先看有没有问题，用 8 秒冒烟：

```bash
python3 scripts/run.py --dry-run          # 只跑到「证据锁」，写 result.json 后就停
python3 scripts/run.py --plan-only        # 出 plan.json（可人工改页）后停
python3 scripts/run.py --no-render        # 没有 office 环境时
```

## 2. 目录与职责

```
SKILL.md            Agent 执行说明（frontmatter: name/description）
METHOD.md           方法：为什么这样拆、每步拦什么错
README.md           本文件
RUBRIC-MAP.md       五维度评分（40/25/15/10/10）→ 包内文件与证据对照
references/         slide-blueprint.md 页级骨架 · result-contract.md 契约字段表
scripts/
  run.py            主控：读 case.json → 证据锁 → 建 deck → 渲染 → 审计 → result.json
  papertext.py      材料读取（PDF/LaTeX/MD/DOCX/HTML/TXT）→ 带定位的段
  pdf_lite.py       PDF 文字层解析 + 论文夹具 PDF 生成（纯标准库）
  inventory.py      证据底账：数字+单位、图注、表格、引文、主张、局限
  outline.py        页级大纲（叙事骨架），含 plan.json 人工接口
  plan_validate.py  证据锁（4 硬闸 + 质量闸）
  layout.py         版式与字号：字宽模型、字号阶梯、溢出动作、表格列宽
  deck.py           pptx 生成（模板占位符、图/表、备注、页码域）+ 读回校验
  notes.py          演讲者备注生成与重复度门限
  assets.py         从 PDF 抽嵌图并按图注绑定
  render.py         真渲染：soffice → PowerPoint COM → 模型预览（标注清楚）
  qa.py             六道闸审计；`qa.py --out` 可对已产出目录复查
  contract.py       输出契约解析（4 种形态）与 result.json 回显
  selftest.py       单元 + 端到端自检，写 tests/selftest-report.json
  benchmark_local.py 与「段落贴页」基线的可比对照（机制对照，非平台分数）
  make_case_pdf.py  生成示例论文 PDF 夹具
  template_build.py 从声明式 spec 生成 master/layout .pptx 模板
templates/          slide-plan.template.json · result.template.json · template-spec.example.json
examples/           3 个示例（EN-PDF / LaTeX / ZH-MD+模板），全部标 EXAMPLE ONLY
tests/              selftest.py · selftest-report.json（真实自检结果）
```

## 3. 输入

`/input/case.json`（或 `--case` 指定的同构 JSON）。读取的字段：
`case_id`、`task`、`materials`/`material`/`sources`（文件或目录，相对 case.json）、
`template`（可选 `.pptx`）、`language`、`audience`、`duration_min`、`slide_limit`、
`output_contract`（四种形态皆可，见 `references/result-contract.md`）。

`materials` 缺失时回落到 case.json 所在目录（跳过 case 文件本身）。
**只依据实际文件内容**，不依据 `task` 里的领域标签推断数据。

## 4. 输出（`/app/output`）

| 文件 | 说明 |
|---|---|
| `result.json` | 契约回显 + `deck`/`slides`/`evidence_map`/`render`/`notes`/`status`/`sources`/`uncertainty`/`changes` |
| `deck.pptx` | 可编辑演示文件（真占位符/表格/图片/备注/页码域） |
| `deck.pdf`、`slides/slide-NN.png` | 真渲染预览（引擎见 `render.json`） |
| `evidence-map.json` | 页级证据映射，含 `locator_verified` 与逐字/归一化匹配标记 |
| `plan.json` | 页级大纲（可手改后重跑） |
| `inventory.json` | 证据底账 |
| `validation.json` / `audit.json` / `layout.json` / `render.json` / `deck-readback.json` | 机器结论，逐项可复核 |
| `speaker-notes.md` / `deck-outline.md` / `run.log` | 讲稿 / 主线摘要 / 日志 |

`result.json` 的字段契约见 `references/result-contract.md`。

## 5. 依赖与版本

| 依赖 | 版本（自测环境） | 必需 | 用途 | 缺失时 |
|---|---|---|---|---|
| Python | 3.10+（自测 3.12.14） | 是 | 运行 | — |
| `python-pptx` | 1.0.2 | 是 | 写 pptx | 无法产出 deck，`status=unsupported` |
| `lxml` | 6.1.3 | 是（随 pptx） | OOXML | 同上 |
| `Pillow` | 12.3.0 | 否 | 抽图、模型预览 | 跳过抽图/预览，落到文字降级 |
| LibreOffice `soffice` | 任一近期版本 | 否 | 导出 PDF/PNG | 试 PowerPoint COM |
| Microsoft PowerPoint（Windows） | Office 16 | 否 | 导出 PDF/PNG（COM） | 落到模型预览并标 `preview_mode=model` |

字体不写死：标题/正文通过版式与主题继承模板字体；`render.json.render.fonts` 记录
文件实际引用的字体名，便于换机核对。示例夹具 PDF 使用 PDF 基础 14 字体，任何环境可读。

## 6. 预算与降级（平台契约）

- 平台预算：**64 次模型请求 / 900 秒 / 单次响应 16384 tokens（含 reasoning）**。
- 本包脚本是**确定性代码，不调用模型**：单案例实测 **3–10 秒**（含 PowerPoint COM 渲染 10 页），
  `--dry-run` < 8 秒。即便 3 个案例顺序执行也远在 900 秒内，模型请求数仅用于 Agent 编写/修改 `plan.json`。
- 脚本级超时保护：渲染引擎单次调用 150 秒上限（`render.DEFAULT_TIMEOUT`），超时即切换下一引擎
  或落到模型预览，绝不挂死。
- `result.json` **先写后改**：开工第一秒即写一份诚实的 `partial` 骨架，之后每阶段覆写；
  进程被杀也留下可复核产物（异常路径另写 `error.log`）。
- 缺输入：`materials` 不存在 → `status=unsupported` 并列出缺失项；
  材料过薄 → `partial` + `uncertainty`。

## 7. 限制

- 未做论文精读结论生成、未做科研绘图美化、未做论文润色（题目明确不负责）。
- 复杂多栏 PDF 的阅读顺序可能错；扫描版依赖平台 OCR。
- 图片抽取只处理 `DCTDecode`/`FlateDecode` 的嵌图；矢量图不会被重绘。
- 措辞压缩是规则化的（在分句边界截断、避免数字被截半），不是生成式改写。

## 8. 自查与维护

```bash
python3 scripts/selftest.py                 # 写 tests/selftest-report.json
python3 scripts/qa.py --out /app/output     # 对已产出目录重跑六道闸
python3 scripts/benchmark_local.py --case <case.json>
```

维护约定：任何新增校验都必须同时出现在 `plan_validate.py`（计划期）与 `qa.py`（产物期），
否则「计划的承诺」和「交付的事实」会脱钩。修改 `layout.py` 的阶梯或门限时，
同步更新 `references/slide-blueprint.md` 与 `SKILL.md` 的判据段。
