# 典型失败模式：检测点 + 处置

> 题面点名了六类"画出来但进不了科研流程"的失败。每类给 **症状 / 检测点（谁在什么时候发现）/ 处置（脚本自动做什么，Agent 该做什么）**。
> 检测点都指向包内可运行的断言，因此评审与使用者可以逐条复核，而不是只读一段说明。

## 1 实体张冠李戴（entity confusion / 层级错位）

- **症状**：图上出现材料里没有的名字；基因写成蛋白正体；跨膜受体画进胞内；同名实体被当成两个。
- **检测点**
  - `ga_build.py check` → `quotes_verbatim`：每个 `entities[].source.quote` 必须在材料中逐字命中；
  - `ga_core.validate_ir`：实体 `label` 为空、`id` 重复直接报 error；
  - `result.json.content_map[kind=entity].on_canvas` + `compliance_checks.id_map`：图元与声明一一对应；
  - `references/figure-design-rules.md §2`：`entity_type`/`compartment`/`italic` 的判据表。
- **处置**：脚本不猜——未命中的实体保留在 `content_map` 但记入 `uncertainty`，`status` 降 `partial`；
  Agent 必须回材料取逐字名称/区室，或把该实体移出图面。斜体规则由 `entities[].italic` 显式声明，脚本按值渲染。

## 2 通路方向反 / 关系语义错（reversed causality）

- **症状**：激活画成抑制、上下游颠倒、反馈环丢失、箭头两端接错。
- **检测点**
  - `relations[].type` 决定端形（`activation` 箭头 / `inhibition` T 形 / `binding` 空心圆 / `modification` 菱形 / `transport` 虚线箭头）——形状由 `RELATION_GRAMMAR` 固定，选错类型必然画错；
  - `ga_core.validate_ir`：`from`/`to` 不在 `entities` 中 → `unresolved`，该边**不绘制**；
  - `figure-design-rules.md §2` 的"动词 → 边类型"词表（activate/inhibit/phosphorylate/transport…）。
- **处置**：端点缺失的边不画并写入 `uncertainty`（宁可缺一条，不可画一条错的）；
  关系类型不确定时写 `type: "unknown"` 并在 `uncertainty` 说明依据；方向存疑的边建议改为面板文字 + 图注陈述。

## 3 图例颜色/图案与数据不对应（legend mismatch）

- **症状**：图例有 4 项而图面只有 3 类；颜色与系列错配；缺单位/色阶说明；灰度打印后分不清。
- **检测点**
  - `layout.derive_legend`：图例**由画面上实际出现的分类派生**（关系类型 + 系列），不是手写；
  - `provenance.legend_gate` → `invariants.legend.ok` 与 `compliance_checks.legend_consistency`（图例项数 == 分类数）；
  - `provenance.grayscale_gate` → `invariants.grayscale`：系列数 > 1 时每系列必须有图案（斜线/点/网格）；
  - `invariants.numbers`：柱/数值带上的每个数字必须命中 source quote / claim / 数据点，轴必须有 `unit`。
- **处置**：断言失败时脚本把差异写进 `compliance_checks`（`fail`）与 `exceptions`；
  系列漏进图例通常是 `charts[].series[].name` 与源表头不一致——回材料逐字对齐表头；
  配色不交给"自动配色"，固定用 Okabe–Ito + 图案双通道。

## 4 画布溢出 / 文字被挤出（canvas overflow）

- **症状**：文字超出画布或压出面板；缩小到读不出；两次运行版面不一样。
- **检测点**
  - `compliance_checks.no_canvas_overflow`：逐文本算包围盒，越界数量必须为 0；
  - `compliance_checks.min_font_body_px`（正文 ≥ `canvas.min_font_px`）与 `min_font_annotation_px`（注释 ≥ 62% 下限）；
  - `invariants.panels[].overflow` / `needed_px <= height_px`；
  - `tests/selftest.py` 的 `deterministic`：同 IR 两跑 SVG `sha256` 必须一致。
- **处置**：固定修复阶梯（逐步记入 `exceptions`）：① 删 `priority=low` 条目 → ② 压行距 →
  ③ 正文按 6% 步进降字号（**不低于 `min_font_px`**）→ ④ 单行截断加省略号。
  阶梯耗尽仍溢出才写 `overflow: true`。文字度量用内置字宽表，三后端与重复运行完全一致，因此不会"这次能放下、下次放不下"。

## 5 字体被替换 / 缺字（font substitution）

- **症状**：导出后中文变方框、斜体丢失、期刊要求的字体被静默换掉。
- **检测点**
  - `fonts.discover()`：返回实际命中的字体文件、是否支持 CJK、来源（scan / fc-match）、替换清单；
  - `result.json.font_report`（只记文件名，不泄露本机路径）与 `compliance_checks.font_provenance`；
  - `exceptions` 中 `issue="字体替换"` 的条目（含影响范围）。
- **处置**：探测顺序 = 有界目录扫描 → fontconfig（仅当可执行文件存在）→ PyMuPDF 内置 CJK；
  无 CJK 字体时 PNG 引擎链会选到能画中文的后端；若最终只能用纯标准库光栅器，
  中文以占位块表示并**明确记为降级**（`export_artifact.png.degraded`），**绝不静默丢字**；
  SVG 始终用字体栈声明（`DejaVu Sans, Noto Sans CJK SC, …`），打开端有该字体即正常显示。
  PDF 末级用 STSong-Light CID（非嵌入），保证中文仍有字符、可搜索。

## 6 导出失败 / 假导出（export failure）

- **症状**：只交 PNG 截图；`.png` 实际是改了名的文本；PDF 空文件；文件大小 0。
- **检测点**
  - `render_png.png_info()`：解 `IHDR` 得宽高与位深，无效即判失败；
  - `render_png._nonwhite_ratio()`：非白像素比例 < 0.004 视为空白画布，继续降级；
  - `render_pdf.pdf_info()`：`%PDF-` 头 + 页对象 + 页数；
  - `compliance_checks.png_real / pdf_real`，以及 `export_artifact.*.attempts`（每一级引擎的成败）。
- **处置**：引擎链逐级降级并**每次都重新验真**（cairosvg → PyMuPDF → Pillow → matplotlib → CLI → 浏览器 → 纯标准库）；
  PDF 有纯标准库矢量兜底（文字仍可选中）；全失败时保留 SVG 并把失败原因写进 `exceptions`，
  `status=partial`——**不以"文件存在"冒充"导出成功"**。

## 7 使用方式（自查顺序）

```bash
python3 scripts/ga_build.py check      # 先在版式之前拦住 1/2/3 类（引文、端点、图例预算）
python3 scripts/ga_build.py build      # 4/5/6 类的检测结果写进 result.json
python3 scripts/ga_build.py selfcheck  # 独立复检：文件真实、id 对齐、无 compliance fail
```

对照位置：`checks` 结果 → `result.json.compliance_checks`；修复与降级 → `exceptions` / `degradations`；
无法判定 → `uncertainty` / `gaps`。任何一条都不允许只写在说明文字里而没有字段落点。
