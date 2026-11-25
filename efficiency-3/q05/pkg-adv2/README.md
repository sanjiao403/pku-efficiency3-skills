# README · apparatus-roadmap-figures-min（adv1）

一个**零依赖、单入口、可独立复核**的科研绘图 Skill：把实验装置清单 / 物料流向句 /
编号步骤 / 阶段计划变成**分层可编辑 SVG + 矢量 PDF + PNG 预览 + 结构化 result.json**。

| 项 | 值 |
|-|-|
| 版本 | `apparatus-adv1`（见 `result.json.skill_version`） |
| 入口 | `python3 scripts/apparatus.py --case <case.json> --out <outdir>`（**零附加参数**） |
| 复核 | `python3 scripts/verify.py --svg <svg> --result <result.json> --materials <dir> --case <case.json> [--edited <edited.svg>]`（38 项；只给 `--svg/--result` 时 31 项；只给 `--case` 时 36 项） |
| 编辑 | `python3 scripts/edit.py --svg <svg> --set-text <ID> "<新标注>"`（源文件保留式：**结构保持一致**，行级 `lines_changed=1`、`byte_identical_outside_target=true`；`--engine xml` 会整份重排、如实报 `lines_changed`） |
| 自检 | `python3 tests/selftest.py`（23 组断言，写 `tests/selftest-report.json`） |
| 污染审计 | `python3 tests/contamination_check.py`（三条件协议 + ghost/越界行/伪造引文，12 项） |
| 依赖 | Python ≥ 3.8 标准库；PDF/PNG 出图可选装 pymupdf 或 cairosvg |
| 输入 | `/input/case.json` + 同目录材料（`.md/.txt/.tex/.csv/.tsv/.json/.yaml/.yml/.log/.pdf`） |
| 输出 | `/app/output/figures/{figure.svg,figure.pdf,figure.png}`（+ 可选 `figure.edited.svg`）+ `result.json` |
| 用时 | 单案例 0.4–0.9 s（本机实测）；900 s 预算内可反复重跑 |

## 1. 最小调用（示例，非正式答案）

```bash
python3 scripts/apparatus.py --case examples/case.example.json --out /tmp/out
python3 scripts/verify.py --svg /tmp/out/figures/figure.svg --result /tmp/out/result.json \
        --materials examples --case examples/case.example.json
```

* `examples/case.example.json` —— 案例契约示例（含 `output_contract`）
* `examples/example-material.md` —— 一份 6 部件 / 5 条流向 / 5 步流程的小装置材料
* `examples/apparatus.example.json` —— 上面两条命令**真跑**得到的 result.json 节选（字段为真、长列表截断）

三者都标了「示例，非正式答案」；平台运行时材料来自 `/input`，与本目录无关。

## 2. 它到底做了什么（方法一行版）

1. **材料 -> 结构**：清单表行 -> 实体（`unit.*`，按语义归类）；显式流向句 -> 连线
   （`material/energy/signal/loop`，方向只来自句式，含 `is fed from` / `leaves` / `由…` 的反向修正）；
   编号步骤 -> 顺序边 + 显式回流弧；`Phase N` 标记 -> 阶段卡与依赖箭头。
2. **结构 -> 版面**：宽度固定 180 mm（投稿单栏），高度按内容算；装置按**流向拓扑序**铺 3 列
   （让上下游相邻，减少连线穿越）；步骤纵向编号 + 左侧回流走廊；阶段按可用宽度**分带**，
   不越页宽。画完实测包围盒，越界就加高重画。
3. **版面 -> 交付**：分层 SVG（真实 `<text>`、`font-family` 带 CJK 回退链、每图元带 `data-*` 溯源）
   + 矢量 PDF + 300 dpi PNG（可选后端；无后端则只交 SVG 并标 partial）+ `result.json`（含**四段式交付契约**：editable_sources / exports /
   data_mapping / element_traceability，以及 `change_log`、`review`、`source_files`）。
4. **交付 -> 字节级重测**：`scripts/measure.py` 回读写出的 PDF/PNG 字节（页盒 mm、位图数、字体程序数、**解压后内容流**里的 TJ/Tj 算子、PNG IHDR/pHYs、像素采样、**Unicode 抽取字符数**），逐项不符即降 `partial`。文字口径按 D40：本包 PDF 的 `Tj` 字面量为 0，真实文字全在 `TJ` 数组里，按字面量数会少报 88%。
5. **交付 -> 复核**：`verify.py` 只读产出文件，自己重算箭头/比例尺/包围盒/数字白名单，
   并检查"结果里声称的实体是否真的画在图上"。

## 3. 为什么它不会"假绿"（本轮最重要的一条）

父臂（`pkg-min`）里 `svgkit` 把内部 `role=` 直接写成 SVG 属性 `role=`，而复核脚本读
`data-role=` ⇒ 复核看到"0 个图元 / 0 条连线"，于是**所有与内容相关的检查都在空集上通过**，
末行照样打印 `ok=True`。本臂修掉了序列化层（`scripts/svgkit.py` 的 `_sem/_attrs`），
并让复核在"读到空集"时判**硬失败**（而不是跳过），再加三条**负向对照**证明它真会咬人：

| 篡改 | 复核必须报 |
|-|-|
| 把所有 `data-role=` 改成 `role=` | `arrow.one_head_per_connector` / `provenance.blocks_have_quote` 等（`C1`） |
| 往图上的标签里塞一个材料里没有的数字 | `provenance.no_invented_numbers`（`C2`） |
| 从 SVG 里删掉一个实体的 `<rect>` | `provenance.every_element_drawn`（`C3`） |

复现：`python3 tests/selftest.py`（`tests/selftest-report.json` 里有逐条结果）。

## 4. 确定性

同输入两次运行必须**逐字节一致**（SVG sha256 相等）。为此：

* 材料发现按字典序（不依赖文件系统枚举顺序）；
* 本次 `--out` 目录 + 任何"我们自己的产物目录"（带 `result.json` 且含 `case_id` 与契约段）
  都不作为材料 —— 否则第二次运行会把自己上一次的产物读成材料（`A2` 断言专门盯这个）；
* 无时间戳、无随机布局。

## 5. 证据范围（工单不是科学材料）

`case.json` / `task.md` / `*.example.json` / `*.template.json` / `*.schema.json` 被判定为
**workorder**：只读数（契约、标题、`case_id`）与**内联材料字段**，**不进证据索引**；
它们出现在 `provenance.excluded_workorder_files` 与 `source_files` 里可查。
真正的外部数据 JSON/CSV 仍是 material（题面要求图表用 actual source data）。负向对照见 `tests/selftest.py` 的 `B1`。

## 6. 限制与边界（如实写）

* 抽取是规则启发式：材料若既无清单表、也无编号步骤与 `Phase` 标记，图面会为空并如实给
  `partial`（不猜内容）；这种写法需要 Agent 按 `SKILL.md` 的降级表处理或补写结构化材料；
* PDF 只读文本层：扫描件（无文本层）按 `unreadable` 记录，不 OCR、不猜；
  无 pymupdf 时走 `scripts/pdftext.py`（纯标准库，FlateDecode + ToUnicode CMap），
  恢复不到有效文本时同样按不可读处理；
* 不做数据分析、不做期刊排版、不判断实验方案科学合理性；
* 平台正式案例的分数由平台判定；本包不提供、也不声称任何 benchmark 分数。

## 7. 文件清单

```
SKILL.md                     本 Skill 的 runbook（调用/契约/降级/自查）
README.md                    本文件：用途、方法、限制、复现
references/figure-rules.md   图面规范（配色/连线/画布/字体/溯源）
scripts/apparatus.py         主入口：材料 -> 图 + result.json（含顶层异常兜底）
scripts/extract.py           材料发现与结构抽取（角色判定/确定性遍历/内联材料）
scripts/svgkit.py            矢量场景与 SVG 序列化、PDF/PNG 导出（pHYs 按真实 dpi 重写）、包围盒自查
scripts/measure.py           产物字节级重测：页盒/位图数/字体/文本算子/PNG dpi/像素采样/字形着墨率
scripts/edit.py              源文件保留式编辑（改 1 个标注，其余逐字节不变，带计数证据）
scripts/pdftext.py           纯标准库 PDF 文本层抽取（无第三方依赖的兜底）
scripts/verify.py            独立复核：只读产出物，23 项检查，硬失败即退出码 2
examples/                    最小可跑示例（输入 + 材料 + 真跑输出节选，均标「示例」）
tests/selftest.py            19 组真跑自检（确定性 / 负向对照 / 降级 / 契约 / 兜底 / 三格式 / 编辑）
tests/contamination_check.py 证据污染三条件协议（可复跑，也可 --pkg 指向别的包做对照）
METHOD.md                    方法与判据（怎么做 + 怎么判真假 + 降级 + 边界）
tests/selftest-report.json   上面那次自检的真实报告
```


## 8. QA 终检（2026-11-24）修复的三处口径

| 问题 | 现象 | 现状 |
|-|-|-|
| 引文只跟"产物自述"比对（P1 假绿） | 把 locator 改成 `ghost.md#L1` 并把它写进 `provenance.materials` ⇒ 旧版仍 `ok=True` | 现在还要落回 `--materials` 下的**真实文件**：`provenance.locators_exist_in_input`（文件必须存在）、`locator_lines_in_range`（行号不越 EOF）、`quotes_found_in_material`（引文能在文件里找到）。负向对照 4a/4b/4c |
| `text_ops` 读压缩字节 | 旧口径报 34（压缩流里偶然命中），真实是解压后 103 个 TJ 数组 + 16 个 Tj | 先 inflate 再数；`text_ops_raw_compressed_scan` 仅留作对照；判据改用 **Unicode 抽取**（pypdf，本机 414 字符 / 0 个 U+FFFD / 覆盖率 1.000） |
| "其余逐字节不变"承诺失实 | 旧版 `edit.py` 用 ElementTree 整份重写，实测 105 行里 53 行变化 | 默认改成**行级外科编辑**：`lines_changed=1`、`byte_identical_outside_target=true`；`--engine xml` 保留但如实报 54 行变化。溯源字段（`data-quote` 等）默认**拒改**（改引文＝改证据来源） |

