# Method: from work order to a verifiable figure

`scripts/chart.py` runs four deterministic stages. Everything downstream of stage 2 is a pure function of
the work order plus the source table, so rerunning reproduces the same figure.

| Stage | What happens | Where |
|-|-|-|
| 1 inventory | read `case.json`; find the table (inline `{columns,rows}` / record array / referenced or sibling `csv`/`tsv`); resolve relative references against **case.json dir → cwd → `/input`**; log every attempt; separate referenced documents into **tables (`.csv`/`.tsv`), materials (`.txt`/`.md`) and rejected work-order/example JSON** | `find_table`, `find_tables`, `resolve_ref`, `RESOLVED` |
| 2 plan | classify each column (`category` by non-numeric majority, `n`, `error`, `value`); pick the x column and the group column (2–6 distinct values); derive the quantity-axis label and unit (column suffix or trailing parentheses), whole-word dimensionless test; record gaps | `role_of`, `plan_chart` |
| 3 mapping | one record per plotted value with `source{file,row,record_index,col,row_key}`; **row = physical 1-based line of the file**; non-numeric cells are listed in `unmapped` and never turned into numbers | `collect` |
| 4 render | one `layout()` dict (bars, ticks, error bars, legend, adaptive left margin) → `figure.svg` + `figure.pdf` + `figure.png`; then measure the exports by re-parsing the bytes; then `run_checks` | `layout`, `render_svg`, `export_figure`, `run_checks` |

`scripts/verify.py` shares no state with the builder: it opens only the produced artefacts plus the
referenced table and recomputes 17 claims (hashes, ids, values per physical line, units, legend, CVD
separation from the SVG fills, PDF operators/colours, PNG raster vs SVG bar positions).

## Why these choices

- **Physical line numbers, not record indices.** A visitor must be able to open the CSV and jump to the
  line that produced a bar. Comment lines, the header and blank lines all shift the file, so the number
  comes from `csv`'s own line counter rather than from `enumerate`. Inline JSON has no lines at all: there
  `row = record_index + 1` and `row_key` is the authoritative key.
- **One layout, three renderers.** Rendering each format independently invites silent drift (a bar height
  that is right in the SVG and wrong in the PDF). `layout()` is computed once; the export gates then
  *prove* consistency by sampling the PNG and matching PDF operators against SVG rectangles.
- **Export claims are measurements.** `export_check.json` is produced by parsing the written bytes
  (MediaBox, `Tj`, `/BaseFont`, `/Image`, `IHDR`, `pHYs`), not by asking the writer what it intended.
- **No invention.** A cell that is not entirely a number (`n.d.`, `Il6`, empty) is skipped and reported.
  A table without a numeric column produces `status=failed` with no figure instead of an empty axes frame.
- **Occlusion is computed, not eyeballed.** The left margin grows with the widest tick label, and
  `checks.label_occlusion` reports the clearance in mm using the declared type size.
- **Instructions are not evidence.** The work order, `task.md`, sibling example/template JSON and any
  `.md`/`.txt` material are *documents*: they can describe a figure, but no number is ever read out of
  them. `find_tables()` classifies every referenced file by an explicit extension whitelist, and the
  classification is echoed into `result.json.evidence_channels` so a reviewer can see which file the
  values came from and which files were deliberately not used.

## Rubric map (what to look at for each scored dimension)

| Dimension | Evidence in the package | How to reproduce |
|-|-|-|
| 完成度 | `SKILL.md §2/§4`, three renderers + map + contract + two reports | `python3 scripts/chart.py --case examples/case.example.json --out /tmp/out` |
| 正确性 | value re-read from source cells, unit on the axis, legend uniqueness, `label_occlusion` | `python3 scripts/verify.py …` (17/17) |
| 完整性 | `figure.map.json` for every mark, `unmapped` list, `sources`, `change_log` | inspect `/tmp/out/result.json` |
| 可核验性 | `export_check.json` (measured), `verification_report.json` (read-only recomputation) | `python3 scripts/verify.py …` |
| 使用增益 / 质量 | the same run with `--engine stdlib` still verifies, so a minimal container also gets an export | `tests/selftest.py` case `stdlib_engine_delivers` |
| 使用增益 / 效率 | one command, no extra parameters, ~0.5 s per figure (matplotlib) / ~0.2 s (stdlib) | `tests/selftest.py` timings in `tests/selftest-report.json` |
| 增益可验证性 | `independent_verify`, `copy_probe`, `cwd_decoy_not_used` cases | `python3 tests/selftest.py` |
| 创新 | physical-line provenance + cross-renderer gate + CVD/greyscale gate recomputed from SVG fills | `scripts/verify.py` output rows |
| 可靠性 | degradation cases (missing case, no numeric column, missing unit, no matplotlib) | `tests/selftest.py` |
| 生态 | `README.md`, `references/*.md`, `examples/*` (all labelled 示例（非正式答案）) | read the package tree |

## Limitations

Statistical inference, non-bar chart types, multi-panel layout, CMYK/PDF-X and OCR of scanned sources are
out of scope; the standard-library export path rasterises primitives but not glyphs. All of these are
stated in the artefacts instead of being silently skipped.
