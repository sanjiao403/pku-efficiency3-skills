# template-mapping · 模板事实 → 角色映射（含中文版式名/占位符名）

判据全部来自**模板文件本身**（OOXML），不靠约定：先读 `p:ph@type`，缺失/未收录时读**名称**。
中英文模板都走同一套判据，因此"标题幻灯片 / 标题 1 / 内容占位符 3"这类命名不需要特判分支。

## 1. 占位符角色（`ph_kind`）

| 角色 | OOXML `p:ph@type` | 名称兜底（含中文） |
|---|---|---|
| title | `title`(1)、`ctrTitle`(17) | 标题、題、title |
| subtitle | `subTitle`(4) | 副标题、subtitle（**先于 title 判**，"副标题"含"标题"） |
| body | `body`(2)、`obj`(7/12/15/18) | 内容占位符、正文、文本占位符、内容、body、content/text placeholder |
| picture | `pic`(3/8/13/14) | 图片、圖、picture、image |
| slide_number | `sldNum`(6) | 幻灯片编号、页码、slide number |
| footer | `ftr`(11) | 页脚、頁腳、footer |
| date | `dt`(10) | 日期、date |

**关键判据**：`<p:ph idx="1"/>` **不带 `type` 属性时语义是 obj（正文）**。只按
`type="body"` 或 `type="obj"` 匹配会漏掉这种最常见写法（我们在"缺版式降级"用例里踩过）。
映射全部记录在 `template_map.json`（每版式的 `placeholders[].{idx,kind,name,geometry}`）。

## 2. 版式角色（`classify`：名称强信号 → 占位符构成）

| 角色 | 名称强信号 | 占位符构成 |
|---|---|---|
| section | `section`、节标题、章节标题、过渡页 | title，无 body |
| title-only | `title only`、仅标题 | title，无 body |
| blank | `blank`、空白 | 无占位符 |
| agenda | `agenda`、`outline`、目录、提纲 | title + body |
| figure | `picture with caption`、图片、图表 | title + picture |
| title | `title slide`、标题幻灯片、封面 | title + subtitle，无 body |
| two-column | `two content`、`comparison`、两栏、比较 | title + ≥2 body |
| content | `title and content`、标题和内容、内容 | title + 1 body |

不写成硬编码版式序号：模板常被改名、复制、增删版式。判定结果进 `template_map.json.roles`
（角色 → 版式序号列表），评审可直接对着看。

## 3. 角色 → 版式回退顺序（`ROLE_ORDER`，可被 `templates/layout_roles.json` 覆盖）

| 内容角色 | 顺序 |
|---|---|
| title 封面 | title → section → blank |
| agenda 提纲 | agenda → content → two-column |
| section 章节 | section → title-only → content |
| bullets 正文 | content → two-column → title-only |
| figure 图页 | two-column → figure → content → title-only |
| conclusion 结论 | content → two-column |
| closing 收尾 | title → section → blank |

回退发生时在结果里可见：`results.build.slides[].layout` 与
`references/fallbacks-and-exceptions.md` 的 `LAYOUT_FOR_ROLE_FALLBACK`。

## 4. 容器与容量（映射之后才有意义）

- 正文容器：优先该版式的 body/object 占位符几何；没有则按版心推算（左右各 8%、标题下留 24%），
  并在 `placeholders_synthesized` 记明是合成的。
- 图容器：优先 picture 占位符 → 两栏第二 body → 正文容器下半部；等比放置后回报
  `aspect_deviation`（>0.5% 判 high）。
- 容量估算：CJK 逐字 1.0em、拉丁查表、宽度打 94 折、行高 1.2×（`fit.nh`）；
  **估算只用于预算与排序**，溢出的最终裁判是渲染后的 PDF（逐页文本覆盖率），
  两者不一致时以 PDF 为准并进 `results.fit.issues`。

## 5. 本仓库内的实测（判据的可信度）

| 场景 | 结果 |
|---|---|
| 16:9 + 英文版式名（Title and Content 等） | 7 类角色全部识别（`template_map.json.roles`） |
| 4:3 + **中文版式名**（标题幻灯片/标题和内容/节标题/两栏内容/仅标题/空白/图片与标题） | 同上，全部识别 |
| 4:3 + **中文版式名 + 中文占位符名**（标题 1/副标题 2/内容占位符 3/图片占位符 5/页脚占位符 6/幻灯片编号占位符 7） | 同上；夹具 f4 端到端 `success`、11 页（见 `RUBRIC-MAP.md` §0 与 `runs/f4/`） |
| 版式缺 body 占位符（人为删） | 自动走合成文本框并记账，仍产出可编辑 pptx（降级用例 M6） |
