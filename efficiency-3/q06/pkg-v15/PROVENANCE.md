# PROVENANCE.md · 每条内容的来路（一页）

本包的原则：**产物里每一个断言都必须能指回材料的某一行**；指不回去的，宁可标成「不可推导」，也不编。

## 1. 一个数字的全链路

以 `examples/case_zh_md/report.md` 里的 `11.1%`（平均绝对误差）为例：

| 阶段 | 落到哪里 | 记录内容 |
|---|---|---|
| 读取 | `papertext.ingest()` → `src.segments[]` | `{id:"seg-0007", source:"report.md", section:"§4 结果", line:57, text:"…11.1%…"}` |
| 底账 | `inventory.build()` → `inv.numbers[]` | `{value:"11.1", unit:"%", raw:"11.1%", seg:…}` |
| 计划 | `outline.py` → `plan.slides[i].numbers/evidence` | `numbers:["11.1%"]`、`evidence:[{locator:"report.md · §4 结果 · L57", quote:"…11.1%…"}]` |
| 闸门 | `validation.json` G1 判定 | `verify_value(inv,"11.1","%")` → `ok` |
| 交付 | `result.json.evidence_map[].locator` | `report.md · §4 结果 · L57`，`locator_verified:true` |
| 复核 | `rigor.py --item number:11.1:%` | 重新解压材料 → 命中 → `FOUND … [verbatim]` |

`python3 scripts/rigor.py --case examples/case_zh_md/case.json --all` → **53/53**（LaTeX 43/43、PDF 66/66）。

## 2. 材料读取与可追溯的形态

| 材料 | 读取器 | locator 形态 | 本机实测 |
|---|---|---|---|
| Markdown / 文本 | `papertext._read_md/_read_plain` | `文件 · §章节 · L行号` | `case_zh_md` 26 段 |
| LaTeX + .bib | `papertext._read_tex`（`.bib` 先读以便解 `\cite`） | `文件 · §section · L行号` | `case_latex` 20 段 |
| PDF（带文字层） | `papertext._read_pdf` → `pdf_lite.extract_pages` | `文件 · §小节 · p页码` | `case_en_pdf` 31 段 |
| 内联材料 | `case.json.material_text` | `material_text · L行号` | 自检与判定案例使用 |

无文字层的 PDF：`src.text_layer=false` → 写进 `uncertainty`（要求先 OCR），不假装读到内容。

## 3. 版本与产物血缘（可复算，不是自述）

`result.json` 里与「来路」有关的字段：

| 字段 | 含义 | 复核方式 |
|---|---|---|
| `sources[]` | 实读材料 `path` + `reader` | 与 `inventory.json` 一致 |
| `inventory.json` | 材料里的数字/图注/引文/主张/局限底账 | 可独立重跑 `inventory.build` |
| `validation.rigor_report` | 逐项 `{verbatim, line, locator, verify_cmd}` 台账（covered/uncovered/undecidable） | 每个 `verify_cmd` 可直接在 shell 运行 |
| `outputs[]` | 每件交付物的 `path`/`bytes`/`sha256` | 逐条复算（`contract.self` 说明为何不含 `result.json` 自身） |
| `audit_deck` | 只读产物重算的 A1–A8 结论 | `python3 scripts/audit_deck.py --out <out> --case <case.json>` |
| `changes[]` / `run.log` | 每阶段一条（init/plan/validate/layout/build/render/audit + 耗时） | 与 `result.runtime.stages` 对照 |
| `render.pdf` / `pngs[]` / `fonts` | 真渲染产物与实际用字 | 打开 `deck.pdf` 与 `slides/*.png` 核对 |

## 4. 明确「不可推导」的地方

材料确实没有对应句子时，页面写 `evidence_absent_reason` 并进 `uncertainty`，**不生成**内容；
`result.json.status` 只有在证据锁 0 error、六道闸全过（含真渲染或按请求跳过）时才可能是 `success`。
`refs.bib` 参与 `\cite` 键解析但不进 `sources[]`；PDF 段落切分是启发式的，个别页 locator 可能落在
邻近小节名（引文本身仍逐字可回查）。
