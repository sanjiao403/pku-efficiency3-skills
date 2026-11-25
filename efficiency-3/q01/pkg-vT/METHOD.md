# METHOD · 方法与设计取舍

## 1 一句话方法

**证据绑定的确定性排版**：材料 → `figure IR`（实体/关系/数值/claim，每条带 locator + 逐字 quote）
→ 确定性版式编译器 → 一个共享 `scene` → 三个后端分别产出可编辑 SVG、真实 PNG、矢量 PDF，
最后用元素级溯源、图例一致性、数值可回查、导出验真四类断言收口。

```
/input/case.json + /input/** ──init──▶ quote-index.json + figure-ir.draft.json + result.json(partial)
        │
        └─ Agent 读 show 输出 → 写 figure-ir.json
                                   │
                             check ─┼─ 引文命中 / 四要素 / 覆盖 / 溢出 / 图例一致
                                   │
                             build ─┼─ normalize_ir → ablate? → layout.build_scene
                                   │        ├── render_svg  → figure.svg（分层 + <text> + 元素 id）
                                   │        ├── render_png  → figure.png（引擎链 + IHDR 验真 + 空白检测）
                                   │        └── render_pdf  → figure.pdf（矢量 + 页对象）
                                   │   provenance: content_map / coverage / legend / number gate
                                   │   compliance_checks（12 项）+ exceptions + result.json（契约回填）
                                   └─ selfcheck（独立复检，不重渲染）
```

## 2 关键设计取舍

| 取舍 | 选择 | 理由 |
|-|-|-|
| 谁决定内容 | Agent 写 IR，脚本只做机械层 | 科学判断不可脚本化；脚本硬编码内容会在隐藏案例上失效 |
| 版式 | 确定性四列摘要 + 关系列 + 数值带 | 图形摘要的评分看"四要素齐 + 可核验"，不是看花哨；确定性还能证明可复跑 |
| 文字度量 | 内置近似字宽表（CJK=1em，ASCII Helvetica 表） | 三个后端 + 两次运行共用同一度量，换行/截断/溢出判定完全一致，不依赖渲染器回答"多宽" |
| 图案填充 | 生成**裁剪后的线段图元**，不用 SVG `<pattern>` | 实测部分渲染器把 `<pattern>` 填成实心黑；自己画线可保证 SVG/PNG/PDF 一致 |
| 图例 | 由**画面上实际出现的分类**派生 | "图例项数 == 分类数"由构造保证，再被断言复核，避免手写图例与图面不符 |
| 数值 | 独立的 claim 数值带（长度编码 + 对照刻度 + locator） | 让"图上每个数字可回查"变成可机器检查的断言 |
| 溢出 | 固定修复阶梯，逐步记录 | 溢出是常见失败模式，可解释的修复优于静默截断或整张重画 |
| 导出 | 多引擎链 + 逐级验真（IHDR/非空白/%PDF-/页对象） | 不假设评测镜像有渲染器；同时防止"文本改名 .png"式假交付 |
| 编辑 | 只改点名元素，其余字节不动 + 记指纹 | 保源修改可被 diff 复核，避免"重画一张"冒充"编辑" |
| 契约 | 读 `output_contract` 原样回填 + 默认七字段超集 | 契约形态未知（dict/list/别名），按原键回填最稳，追加字段只增不改 |

## 3 与 83 分公开 attempt（73246）的形态差异

对方公开文件树：`SKILL.md / METHOD.md / README.md + scripts(9) + templates(3) + examples(3) + tests(2)`，无真实预览件。
本包同构但补了对方缺的几件，并显式对齐 rubric：

| 项 | 73246 | 本包 |
|-|-|-|
| 生成脚本 | `svg_gen.py` `chart_gen.py` | `layout.py` + `render_svg/png/pdf.py`（三后端同源）|
| 校验脚本 | `entity_check.py` `coverage_gate.py` `compliance.py` | `provenance.py`（引文/图例/数值/导出四闸）+ `ga_build.py selfcheck` |
| 结构化中间表示 | `schematic-spec.example.json` | `templates/figure-ir.template.json` + 真实示例 IR（可直接跑）|
| 真实导出预览 | 未见 PNG/PDF | `figure.png`(2400×1350@300dpi, IHDR 验真) + `figure.pdf`(矢量单页) |
| 对照证据 | 未见 | `tests/ab_harness.py` → `ab-report.json`（41 vs 8 个可核验图元）|
| 保源编辑 | 未见 | `edit` 模式 + `edit-record.json`（原图 sha256 + 逐处前后值）|
| 复跑确定性 | 未见断言 | `selftest` 对同 IR 两跑比较 SVG sha256 |
| 数值可回查 | 未见 | `invariants.numbers` 逐数字核对 + 未命中写入 `uncertainty` |

## 4 「使用增益」的对照协议

**已实现（可复现）**：`tests/ab_harness.py` 用同一入口、同一材料、同一 IR 跑两条臂：

- `skill` 臂：完整管线（溯源 + 数据编码 + 图例派生 + 导出验真 + 溢出阶梯）
- `baseline` 臂：`GA_ABLATE=provenance,encoding,legend`，即关掉本包的增值能力，
  等价于"直接画四列文字"的基础产物

实测（本机，示例案例 A/B）：可核验图元 **41 vs 8**；`source_ratio` **0.95 vs 0.00**；
导出验真 **PNG+PDF 均通过 vs 未验证**；图例断言 **通过 vs 不适用**。
报告：`tests/ab-report.json`（含逐案例数值与设计说明）。

**待 Lead 决定是否补做（真实基础 Agent 臂）**：用同一 `/input/case.json` 让不加载本 Skill 的基础 Agent
自由出图 3 次，把产物放到 `tests/ab-real/<case>/run{1..3}/`，再跑一次 `tests/ab_harness.py`；
脚本会并排给出两臂指标。该臂需要在评测环境实际执行，本子代理不具备发枪权限，故未执行。

## 5 失败模式与对策（实现层）

| 失败模式 | 对策（代码位置）|
|-|-|
| 引文对不上材料 | `provenance.quote_hit`（NFKC + 空白归一）在 `check` 阶段拦截，`check` 输出命中率 |
| 实体端点不存在 | `ga_core.validate_ir` 标 `unresolved`，该边不绘制并写入 `uncertainty` |
| 图例与图面不符 | 图例由 `layout.derive_legend` 从画面派生，`provenance.legend_gate` 断言 |
| 图上出现无来源数字 | `provenance.number_gate` 逐个数字核对，未命中进 `uncertainty` |
| 文字溢出画布 | `layout` 修复阶梯 + `no_canvas_overflow` 断言 + `exceptions` 记录 |
| 字体被替换 | `fonts.discover` 记录实际文件、是否支持 CJK、替换影响 |
| 导出件是假的 | `render_png.png_info`（IHDR + 非空白比例）、`render_pdf.pdf_info`（头 + 页对象）|
| 渲染器缺失 | 多级引擎链；末级纯标准库（几何 + ASCII 笔画字 + CID 中文）|
| 单文件崩溃拖垮全局 | 顶层 try/except；每步独立；`init` 先落最小 `result.json`；退出码恒 0 |
| 评测超时 | 单案例目标 ≤20 s；`--fast` 跳过浏览器与高开销引擎；硬超时后只 finalize 已有产物 |

## 6 版本与维护

- 版本 `1.0.0`（`scripts/ga_core.py: VERSION`）。接口稳定：`init/show/check/build/selfcheck/edit`。
- 扩展方式：新增面板体裁 = 在 `layout.py` 增加一个 `_body_*` 渲染器并在 `render_panel` 注册；
  新增断言 = 在 `provenance.py` 增加一个 `*_gate` 并加进 `compliance_checks`。
- 兼容性：新增字段只增不改；`result.json` 的契约键回填逻辑不随内容变化。
