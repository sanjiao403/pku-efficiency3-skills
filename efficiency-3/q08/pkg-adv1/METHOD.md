# METHOD · 方法说明（为什么这样做，以及边界）

## 1. 问题的真实难点

"论文 → 学术 PPT"看起来是文字排版，实际有三类会互相牵制的约束：

1. **继承约束**：模板的价值在母版/版式/占位符/主题。用 `Presentation()` 新建再画文本框，
   视觉上像模板、结构上不是模板 —— 改主题色、换字体、插入新页都不会跟着变。
2. **容量约束**：固定版心 + 可读字号下限（正文 ≥14pt）时，一页能承载的文字是**有限且可估算**的。
   不估算就会出现两种坏结果：溢出被裁（导出后丢字）或把字号压到 9pt 硬塞。
3. **一致性约束**：整册的标题位置、页脚、页码、字号层级、图表比例必须一致；
   单页调好不算完成，批量一致 + 导出件与 pptx 一致才是。

本 Skill 的做法是：把这三类约束都变成**可由脚本核对的结构化事实**，而不是靠"看起来对"。

## 2. 三层模型

```
模板层 template_map.json          内容层 source_map.json            计划层 slide_plan.json
├ 母版/版式/占位符 idx·type·几何  ├ 块（段落/标题/图注）            ├ 页角色（封面/目录/内容/图/结论/收尾）
├ 主题字体 major/minor latin·ea   ├ 章节树 + locator               ├ 主张（逐字最强断言）+ 定位
├ 主题色 12 色 + Hans 脚本字体    ├ 图表（caption + 可嵌入图片）    ├ bullet（逐字摘录，超长则截断记账）
└ 系统字体可用性 + fallback 链    └ 抽取限制（扫描件/矢量图）       └ 字号阶梯与容器预算
                                            ↓ build_pptx.py
                                     deck.pptx（继承模板）+ build_log.json
                                            ↓ fit_check.py（静态复核）+ render_preview.py（渲染回测）
                                     result.json（页级证据 + 指标 + 诚实状态）
```

**关键设计**：`source_extract.make_figure`（出**等比原图**）与 `fit_picture`（在容器
里**等比放置**）分成两步，
"原图比例"与"放置偏差"才能分开核对；`aspect_deviation` 就是这两步之间的误差度量。

## 3. 版式映射规则（角色 → 版式）

不靠版式名硬匹配（模板常被改成中文名或被复制多份），而是**名称强信号 + 占位符构成**双通道：

> v1.1 起，占位符角色先按 **OOXML `p:ph@type`**（语言无关）判，type 缺失/未收录时按
> **占位符名称**兜底（`标题 1`/`副标题 2`/`内容占位符 3`/`正文 4`/`图片占位符 5`/`页脚占位符 6`/
> `幻灯片编号占位符 7`/`日期占位符 8`）。中文模板里常见"type=obj 但名字是内容占位符"，
> 只认 type 或只认名字都会漏。实测：4:3 + 中文版式名 + 中文占位符名的模板，7 类角色全部识别正确。

| 角色 | 优先版式（名称） | 占位符构成判据 | 没有时怎么办 |
|---|---|---|---|
| title 封面 | Title Slide / 标题幻灯片 | title+subtitle，无 body | 用首个有标题的版式 |
| agenda 目录 | Agenda / Outline / 目录 | title+body | 用 content 版式 |
| section 章节 | Section Header / 节标题 | 名称含 section/节标题 | 用 title-only |
| bullets 正文 | Title and Content / 标题和内容 | title + 1 个 body/object | 合成文本框并记录几何 |
| figure 图页 | Two Content / 比较（左文右图） | title + ≥2 body；有 picture 占位符则优先 | 图放正文容器下半部 |
| closing 收尾 | Title Slide / Blank | 同上 | 用 section 版式 |

`layout_roles.json` 可覆盖上述偏好；`plan_deck --validate` 会在越界时给 high。

## 4. 字号与间距阶梯（可解释，不硬塞）

```
标题：封面/章节 40→36→32；内容页 32→28→24（≥20pt）
正文：20→18→16→14（**下限 14pt**，低于下限不再降）
图注：14→12→11→10（下限 10pt）；页脚 9pt 单行截断
行距 1.0×；段前 3–6pt（首段无段前）
```

超容量的处置顺序（每一步都写进 `build_log` / `change_log`）：
1. 先在**当前字号**下算所需高度，缩放系数写进 `a:normAutofit@fontScale`（PowerPoint 会照此渲染）；
2. 仍不够 → 降到阶梯下一档，重复到下限；
3. 到下限仍溢出 → **把末条证据移入讲稿备注**并记账，绝不继续压字号；
4. 渲染回测（`--iterations`）发现 PDF 侧仍溢出 → 再移一条重建，最多 N 轮。

## 5. 中英文字体策略

- 段落逐 run 写 `a:latin` + `a:ea`（+`a:cs`）。**只写 latin 是常见 bug**：CJK 会走渲染端默认回退，
  行宽/行高与预期不同，中文模板整页错位。
- 优先沿用模板主题字体（major→标题，minor→正文）；主题字体缺失或有明确要求时用学术安全对：
  中文 标题 `Arial/黑体`、正文 `Times New Roman/宋体`；英文 `Arial` + `Times New Roman`。
- 字体可用性由 `template_probe` 探测（Windows 注册表/字体目录，Linux `fc-list`），
  不可用则记 `uncertainty` 并在导出回测里报**实际替换**（字体名对齐表避免误报）。

## 6. 证据映射与"不臆测"

- 页内每句都是源材料**逐字摘录**（`quote`），带 `locator`（`§章节 ¶n` / `p.4 §2.1 ¶2`）与 `block_id`；
  `fit_check` 逐条回源比对，`quote_verified` 才为真。
- 主张（claim）只做"挑最含数值/最像结论的句子 + 按小句边界截断"，截断处补省略号，全文进讲稿备注。
- 抽不到的东西（扫描件无文本层、矢量图无法取位图、docx 未抽嵌入图）写进 `extraction_limits` → `uncertainty`，
  不用"看起来像"的内容补齐。

## 7. 导出与回测

- 后端：PowerPoint COM（Windows，保真最高）→ LibreOffice（`soffice --headless`）→ none。
- PDF 回测四项：页数是否一致、逐页文本覆盖率（pptx 文本字符在 PDF 中出现的比例，<97% 判"丢字/被裁"）、
  文本包围盒是否越出页面、字体表是否覆盖请求字体。
- **导出件一致性（D31，逐页 + 像素级）**：题面要求"pptx 与导出 PDF/PNG 必须一致"，故对每一页重测
  `images_pptx vs images_pdf`（图片丢失）、PNG 张数与像素宽高比（偏差 >0.5% 判不一致）、
  PNG 非空白像素占比（整页空白 = 渲染丢失）、备注字符数与自述值、备注是否重复或漏进他页
  （备注错位）。读数落 `results.render.consistency.pages[]`，问题进
  `results.render.consistency.issues[]` 并**参与 status 判定**（high → partial）。
- 独立复核：`scripts/audit_only.py` 只读 pptx + `preview/deck.pdf` + `preview/png/*.png` **重算**
  上述全部读数（不信任 `result.json` 自述），并对自述值做 expected vs actual 对照。
- 全后端失败：写 `preview.html` + `preview.layout.md`，`status=partial`，**不伪造 PDF/PNG**，
  并在 uncertainty 明确"本环境无渲染器 → 无法做导出件逐页比对（限制已记录）"。

## 8. 能力边界（写进结果，避免过度声称）

技术检查能证明：模板继承真实发生、页内文本与渲染一致、证据定位可回源、图表未被拉伸、批量一致。
技术检查**不能**证明：学术判断是否正确、叙事是否打动听众、图的选择是否最优、演讲时长是否合适。
这些留给人工评审；本 Skill 只保证"把可核对的都摊开"。

## 9. 与公开同类做法的差异（契合题面点名的失败形态）

| 题面点名的失败 | 本 Skill 的对应机制 |
|---|---|
| 论文原文整段粘进默认模板，母版版式没真继承 | 只 `add_slide(layout)` + 克隆 latent 占位符；`fit_check` 用 `a:xfrm` 缺失/主题一致/版式数一致三条复核 |
| 文本框溢出后压字号硬塞 | 阶梯 + `normAutofit` + 余量入备注；下限 14pt 是不变量，构建与复核两侧都查 |
| 图表被拉伸变形 | `make_figure` 出等比原图 + `fit_picture` 等比放置（fit/cover 显式选择）+ 偏差度量 <0.5% 判据 |
| 图号与正文引用错位 | 图注按源材料 caption 原样带出，`label`/`source_locator` 进 `evidence_map.json` |
| 只修封面和前三页 | 逐页同一套规则（页脚/页码/标题几何/字号层级），`consistency` 段给同版式几何分组比对 |
| 导出后字体被替换、图片丢失 | 渲染回测报字体替换与图片计数，写入 `uncertainty`，不静默 |
