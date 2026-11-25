# fallbacks-and-exceptions · 降级链与异常码字典

原则：**能自动补偿的补偿并记录，不能的显式标注为 `partial`，绝不静默吞掉、绝不假装成功。**
每个码都会出现在产物里：`result.json` 的 `uncertainty[]` / `results.build.warnings` /
`results.fit.issues[]` / `pipeline.guards[]`，或 `verify_report.json.issues[]`。

## 1. 输入解析（与 cwd 无关，见 `result.resolution`）

| 码 | 触发 | 自动处置 | 结果里怎么看 |
|---|---|---|---|
| `TEMPLATE_ABSENT` | 案例没给模板 | 用文本 spec（`case.template` 的 `.json` 或包内 `templates/template-spec.json`）**运行期合成** | `results.template.origin` 以 `spec-synth` 开头；`uncertainty[item=模板]` |
| `TEMPLATE_UNREADABLE` | 模板 pptx 打不开/损坏 | 回退文本 spec 合成；仍失败则用 python-pptx 默认模板并记 `partial` | `pipeline.errors[]`、`results.template.origin` |
| `TEMPLATE_SPEC_INVALID` | spec JSON 不合法 | 回退内置 `SPEC`（16:9 学术主题） | `uncertainty` 写明用了内置 spec |
| `SOURCE_NOT_FOUND` | 材料路径在 `case_dir`/`cwd`/`/input` 都找不到 | **终止**：写 `partial` 的 `result.json` 并说明原因，不造内容 | `status_reason`；`resolution.entries[kind=source].resolved_from="not_found"` |
| `SOURCE_EMPTY_TEXT` | 材料可读但抽不出内容块 | 空产物守卫 → `partial` | `pipeline.guards` 含「材料解析出 0 个内容块」 |
| `SOURCE_PDF_NO_TEXT` | PDF 无文本层（扫描件） | 继续（若有其它文本），记限制 | `uncertainty[item=材料抽取]` |
| `SOURCE_TYPE_UNSUPPORTED` | 非 .md/.txt/.pdf | **终止**并说明支持的类型 | 退出码 2；`status_reason` |
| `FIGURE_CSV_MISSING` | `figure_specs[].csv` 找不到 | 跳过该图，页退化为纯文字 | `results.figures[].error`、`build.warnings` |
| `FIGURE_MATPLOTLIB_ABSENT` | 无 matplotlib | 跳过出图（不伪造图） | 同上 |

## 2. 版式与占位符

| 码 | 触发 | 自动处置 | 判据/字段 |
|---|---|---|---|
| `LAYOUT_FOR_ROLE_FALLBACK` | 角色没有理想版式 | 按 `ROLE` 顺序回退（如 figure→two-column→content→title-only），再回退版式 0 | `results.template.roles`、`build.slides[].layout` |
| `NO_BODY_PLACEHOLDER` | 版式无 body/object | **合成文本框**并记几何 | `results.build.placeholders_synthesized` |
| `NO_PICTURE_PLACEHOLDER` | 无图片占位符 | 放两栏右栏/正文下半部（等比） | `build.slides[].figure.container_source` |
| `NO_TITLE_PLACEHOLDER` | 版式无标题 | 标题写入合成文本框 | `placeholders_synthesized` |
| `NO_FOOTER_OR_SLDNUM` | 版式无页脚/页码占位符 | 跳过克隆；页码仍写进页脚文本（若有页脚） | `build.slides[].page_number_field` 可能缺省 |
| `SLDNUM_NOT_RENDERED` | 克隆的 `sldNum` 域占位符渲染端不绘制 | **页脚文本兜底** `页脚 · n/总数` | `results.fit.metrics.footer_page_number_slides` |
| `LATENT_PLACEHOLDER_CLONE_FAIL` | 克隆页脚/页码失败 | 继续，不阻断 | `build.slides[].footer_page_number` 缺省 |

## 3. 容量、字号与溢出（不变量：正文 ≥14pt、图注 ≥10pt、标题 ≥20pt）

| 码 | 触发 | 自动处置 | 判据/字段 |
|---|---|---|---|
| `OVERFLOW_AUTOFIT` | 当前字号所需高度 > 容器 | 写 `normAutofit@fontScale`（≥0.62） | `build.slides[].font_scale` |
| `OVERFLOW_LADDER_DOWN` | autofit 仍不够 | 降到阶梯下一档（20→18→16→14） | `build.slides[].font_sizes.body` |
| `OVERFLOW_TO_NOTES` | 到下限仍溢出 | **末条证据移入讲稿备注**并记账，字号不再降 | `build.slides[].overflow_to_notes`、`plan.slides[].overflow_to_notes` |
| `FONT_SIZE_FLOOR` | 任何 run 低于地板 | 视为 high 级问题（`verify` 判 fail） | `results.fit.issues[item=正文字号低于下限]` |
| `TITLE_TOO_LONG` | 标题在最小档仍超容器 | 截断到大小时按小句边界补省略号，全文进备注 | `slides[].title_truncated`、`notes` |
| `PAGE_BUDGET_TRIM` | 章节数 > `slide_count.max` | 按章节分值裁剪（局限/结论加权保底） | `results.plan.dropped_content[]`（含原因与原文定位） |
| `REQUIRED_SECTION_VICTIM` | 为满足 `required_sections` 让位 | 记录让位了哪一节 | `dropped_content[].why` |

## 4. 字体、图与导出

| 码 | 触发 | 自动处置 | 判据/字段 |
|---|---|---|---|
| `FONT_MISSING` | 主题/计划字体本机未安装 | 按 fallback 链替换并记录，**不静默回退** | `uncertainty[item=字体缺失]` |
| `FONT_SUBSTITUTED_IN_PDF` | 导出件实际未使用某字体 | 报出"PDF 未使用哪些字体" | `results.render.missing_fonts`；有后端时才判 |
| `IMAGE_ASPECT_DISTORTION` | 放置后宽高比偏差 >0.5% | 判 high（不会发生：我们只等比放置） | `fit.metrics.figure_aspect_max_deviation` |
| `RENDER_BACKEND_ABSENT` | 无 soffice 也无 PowerPoint | 保留 pptx，**不伪造 PDF/PNG**；`status=partial` | `results.render.{ok:false,backend:"none"}`、error 原文、页数/覆盖率为 null |
| `RENDER_FAILED` | 后端存在但导出失败 | 失败原文入结果；`partial` | `results.render.attempts[]` |
| `PDF_PAGE_MISMATCH` | PDF 页数 ≠ pptx 页数 | 判 high | `results.fit.issues[item=PDF 页数 ≠ pptx 页数]` |
| `PDF_TEXT_LOSS` | 逐页文本覆盖 <97% | 判"丢字/被裁"（high） | `results.render.pages[].text_coverage` |
| `EMPTY_ARTIFACT` | 0 页 / 0 内容块 | **空产物守卫**：强制 `partial` + 具体原因 | `pipeline.guards[]`、`status_reason` 含「空产物守卫」 |
| `OUTPUT_WRITE_FAILED` | 产物写盘失败 | 抛错退出；已落盘的前序产物保留 | 退出码非 0 |

## 5. 证据与判定

| 码 | 级别 | 含义 | 处置 |
|---|---|---|---|
| `QUOTE_NOT_IN_SOURCE` | high（verdict `off_topic`） | 引文在材料里找不到 | 换回原文或修正 `block_id`/定位 |
| `NUMBER_FABRICATED` | high（verdict `fabricated_number`） | 引文可回源，但页内数字全材料都没有 | 改回原数字或删该断言 |
| `LOCATOR_MISSING` | high | 证据没有 `locator` | 补 `§章节 ¶n s句序` |
| `GEOMETRY_HARDCODED` | 计数（非 fail） | 页面占位符出现 `a:xfrm` = 不再证明"真继承" | 移除显式几何，交回版式继承 |
| `LAYOUT_COUNT_CHANGED` | high | 产物版式数与模板不一致 | 说明是否刻意改模板 |
| `THEME_FONT_CHANGED` | medium | 主题字体方案被改 | 记录原因 |

严重级语义：**high → 必须修或明确说明（`status=partial`）；medium → 应处理或说明；计数/提示 → 供复核**。
渲染端是溢出的最终裁判：估算模型只用于预算与排序（见 `template-mapping.md` §4）。
