# METHOD.md · 方法与判据（apparatus-adv1）

本文件只写**方法**与**判据**（怎么做、怎么判定真假），不复述题面的评分表。

## 1. 处理链（全部在运行期、只用材料内容）

```
材料发现        按字典序遍历 case.json 所在目录；排除本次产物目录与历史产物目录；
                按角色分流：material（科学材料）/ workorder（工单、示例、模板）/ case
   ↓
结构抽取        实体：清单表行（3 列，或 2 列且第二列是计数/带单位数值）→ 语义类别
                连线：只认显式句式（is fed from / delivers to / is connected to /
                      is monitored by / leaves·exits（反向）/ 接入 / 泵入 / 排出 …）
                步骤：Step N / 步骤 N / N. ；“返回步骤 N”记回流
                阶段：Phase N / 阶段 N（标签截到下一个阶段标记或第一个句末）
                数值：带单位的数字（数字必须能在材料原文找到）
   ↓
布局            宽度固定 180 mm（投稿单栏）；高度先按内容估，画完再按实测包围盒加高重画。
                装置：三列网格，按流向拓扑序铺（上下游相邻，减少横穿）；
                步骤：纵向编号 + 左侧回流走廊；终止步加终点横杠；
                阶段：按可用宽度分带（行内横箭头、跨行走行间走廊）。
   ↓
渲染            分层 SVG：真实 <text>（不转曲）、font-family 带 CJK 回退链、
                每图元带 data-node/data-kind/data-quote/data-src，连线带 data-fid/data-flow/…。
   ↓
导出            PDF：页盒 = 画布 mm 的矢量页；PNG：目标 dpi 位图，并按真实 dpi 重写 pHYs。
   ↓
字节级重测      不看"调用成功"，回读写出的 PDF/PNG 字节：页盒、位图数、字体程序数、
                Tj/TJ 文本算子、PNG IHDR 宽高与 pHYs、像素数 = 画布 mm × dpi；
                有 pymupdf 时再回读 PDF 文本层与每个字形的着墨率。
   ↓
独立复核        scripts/verify.py 只读产出物（SVG + result.json + PDF/PNG 字节）重算全部结论。
```

## 2. 判据（可判真假，不靠自述）

| 主张 | 判据（谁在什么文件里怎么量） | 反例控制 |
|-|-|-|
| 图元都来自材料 | 每个图元 `data-quote`+`data-src`；`provenance.materials` 只含 material 角色；`locators_resolve`（在材料集合内；未给 `--materials` 时用 `--case` 的目录）+ `locators_exist_in_input`（`--materials` 下真有该文件）+ `locator_lines_in_range`（行号不越 EOF）+ `quotes_found_in_material`（引文能在文件里找到） | `tests/selftest.py` B1、C2；`tests/contamination_check.py` 4a ghost 材料 / 4b 越界行 / 4c 伪造引文（三条都必须变红） |
| 实体都真的画出来了 | `provenance.every_element_drawn`：result.json 声称的 id 必须在 SVG 里出现 | C3（删一个 `<rect>` → 判红） |
| 方向正确 | 方向只由句式决定；`leaves/exits` 反向；拉丁别名不收裸通用词 | NOTES D31 P1-6/P1-7 记录的两条实测反例 |
| 不越页 | 画布宽固定 180 mm；`layout.content_within_canvas` 由复核**独立重算**包围盒 | 30 部件（180×329.51 mm）与 8 阶段（180×123.56 mm）实测无越界 |
| 三格式真交付 | `export.three_formats_present / pdf_page_matches_canvas / pdf_vector_no_raster / pdf_has_live_text / pdf_text_unicode_extractable / pdf_glyphs_inked / png_px_matches_dpi / png_dpi_tag` 全部从**字节**量（文字按 D40 的 Unicode 抽取口径，不按 `Tj` 字面量） | I1/I1b/I1c（inflate 后算子数 + Unicode 抽取）、I2（删 pHYs → 判红）、I3（PDF 里塞位图 → 判红） |
| 文字可改（源文件保留式编辑） | `scripts/edit.py` 默认**行级外科编辑**：`lines_changed=1`、`byte_identical_outside_target=true`、结构（图元 id/引文/图层）不变、输出良构；复核 `edit.one_text_touched / edit.structure_preserved` 独立比对两份 SVG | I4/I5/I6（行级字节 + 改后仍过复核）；I7（改 `data-quote` 默认拒改） |
| 同输入同输出 | 两次运行 SVG sha256 相等；材料遍历有序；产物目录不进材料 | A1/A2（其中 A2 专门盯"第二次运行自喂"） |
| 不假绿 | 复核在"读到空集"时判硬失败，而不是跳过 | C1（剥掉 `data-role` → 立刻判红，而不是全绿空转） |

## 3. 降级策略（宁可 partial，不猜内容）

* 材料无清单/编号步骤/阶段标记 → 空图 + `partial` + `gaps`（复核把内容类检查标 `not_applicable`）；
* 有实体无流向句 → 连线留空并记 `uncertainty`；指代不明 → 不画并记 `provenance.ambiguities`；
* PDF 无文本层 → `provenance.unreadable`（不 OCR、不猜）；有 pymupdf 用 pymupdf，无则纯标准库兜底；
* 无渲染后端 → 只交 SVG + `partial`；页面/DPI/字形任一不符 → `partial` 并写明哪一项、差多少；
* 顶层异常 → 仍写 `partial` 的 result.json（含脱敏后的原始错误行）。

## 4. 已知边界

规则抽取是启发式：材料写法与"清单表 / 显式流向句 / 编号步骤 / Phase 标记"差异越大，抽取越少；
这类情况按第 3 节诚实降级，需要 Agent 按 `SKILL.md` 处理或补写结构化材料后重跑。
本包不判断实验方案的科学合理性，也不做数据分析与期刊排版。

