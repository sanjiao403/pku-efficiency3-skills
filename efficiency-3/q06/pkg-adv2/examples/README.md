# EXAMPLE ONLY · paper2deck 的最小调用示例

这三个示例用于说明**接口和完整流程**：输入长什么样、命令怎么调、产物有哪些。
它们都是**合成材料**（论文/报告由本包脚本生成或手写，内容为教学用虚构数据），
**不是任何评测案例的答案，也不冒充正式测试结果**。

## 三个示例的差异（覆盖三条输入路径）

| 示例 | 材料形态 | 契约形态 | 模板 | 验证的路径 |
|---|---|---|---|---|
| `case_en_pdf/` | 英文论文 **PDF**（由 `make_case_pdf.py` 生成，含图 1 与表 1） | `{字段: 描述}` | 无（内置 16:9 几何） | PDF 文字层、列分隔切分、表体重建、嵌图/示意图降级 |
| `case_latex/` | **LaTeX** 源 + `.bib` | JSON Schema | 无 | `\section/\label/\ref/\cite` 解析、图号解析、tabular 还原 |
| `case_zh_md/` | **中文 Markdown** 报告 | 字符串数组 | **.pptx 模板**（由 `template_build.py` 从 `templates/template-spec.example.json` 生成） | CJK 字宽与排版、单位模板占位符、中文备注 |

## 复现命令

```bash
PKG=<本包目录>
RUN=<输出根，例如 ./runs>

# A. 英文 PDF
python3 $PKG/scripts/make_case_pdf.py --src $PKG/examples/case_en_pdf/paper.src.json \
                                      --out $RUN/example-en-pdf/input/paper.pdf
cp $PKG/examples/case_en_pdf/case.json $RUN/example-en-pdf/input/
python3 $PKG/scripts/run.py --case $RUN/example-en-pdf/input/case.json \
                            --out $RUN/example-en-pdf/output --work $RUN/example-en-pdf/work

# B. LaTeX
mkdir -p $RUN/example-latex/input && cp $PKG/examples/case_latex/* $RUN/example-latex/input/
python3 $PKG/scripts/run.py --case $RUN/example-latex/input/case.json \
                            --out $RUN/example-latex/output --work $RUN/example-latex/work

# C. 中文 Markdown + 单位模板
python3 $PKG/scripts/template_build.py --spec $PKG/templates/template-spec.example.json \
                                       --out $RUN/example-zh-md/input/group-template.pptx
cp $PKG/examples/case_zh_md/* $RUN/example-zh-md/input/ -r
python3 $PKG/scripts/run.py --case $RUN/example-zh-md/input/case.json \
                            --out $RUN/example-zh-md/output --work $RUN/example-zh-md/work
```

## 示意输出（并非正式案例结果，仅示意形状）

`output/result.json` 顶层包含契约字段 + 本包附加字段：

```jsonc
{
  "case_id": "example-latex",
  "status": "success",
  "deliverable": "# Carbon-Aware Scheduling …\n## Storyline\n…\n## Page-by-page claim ladder\n| # | role | claim | source locator |",
  "deck": { "pptx": "deck.pptx", "pdf": "deck.pdf", "slide_count": 9, "slides": [ … ] },
  "slides": [ { "id": "s05", "role": "evidence", "title": "Figure 1 · Scheduling window of the proposed…",
                "claim": "…", "evidence": [ { "label": "Figure 1",
                "locator": "paper.tex · §3 Method · L20", "quote": "…" } ] } ],
  "evidence_map": [ { "page": 5, "locator": "paper.tex · §3 Method · L20",
                      "locator_verified": true, "match": "verbatim" } ],
  "render": { "engine": "powerpoint-com", "preview_mode": "real",
              "pdf": "deck.pdf", "pngs": ["slide-01.png", "…"] },
  "audit": { "passed": 6, "total": 6, "real_render": true },
  "uncertainty": ["1 table(s) reconstructed from source rows"]
}
```

配套产物：`deck.pptx`（可编辑）、`deck.pdf`、`slides/slide-NN.png`、`plan.json`、
`inventory.json`、`validation.json`、`layout.json`、`render.json`、`deck-readback.json`、
`audit.json`、`evidence-map.json`、`speaker-notes.md`、`deck-outline.md`、`run.log`。

## 人工改页（推荐的协作方式）

```bash
python3 $PKG/scripts/run.py --case <case.json> --plan-only     # 只出 plan.json
# 编辑 plan.json：改 claim / bullets / 增删页
python3 $PKG/scripts/run.py --case <case.json>                  # 自动采用同目录 plan.json
```

`plan.json` 放在 `case.json` 同目录即可被自动采用，`result.json.draft.drafter` 会记为 `plan.json`。

## 注意

- 示例材料中的数字**只用于教学**，不要引用为任何真实研究结论。
- 示例只为说明接口；正式判分使用组织方提供的固定案例，本包不预置其答案。
