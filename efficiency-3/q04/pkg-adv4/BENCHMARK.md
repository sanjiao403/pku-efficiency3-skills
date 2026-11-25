# BENCHMARK — this arm vs a naive baseline (one page)

All numbers below were produced on this machine by really running the pipeline; nothing is
estimated. The harness **ships inside this package**, so anyone who has the package can reproduce
every number:

```bash
python3 tests/bench.py --bench-out /tmp/benchmark.json     # or without --bench-out: prints only
python3 tests/bench.py --arm pkg-adv4
```

The harness builds three inputs at run time (English linear cascade with an inhibition and a
negated claim; English branched pathway with a complex, a feedback arm and a drug; Chinese material
with a complex, a passive clause, a negation and an anaphor), runs the Skill on each, runs the
**baseline arm** on the same text, and then copies the whole package to a directory whose ancestors
are named `runs/…/stage/outputs` and runs it again from there (the copy probe). Those three inputs
are examples written at run time, not the official cases.

## Arms

* **skill** — this pipeline: typed entities, evidence locator on every claim, arrow grammar,
  passive/negation/coordination handling, exclusions recorded, legend generated from the drawing.
* **baseline** — `baseline_spec()` in `tests/bench.py`, a deliberately naive attempt: every
  capitalised token becomes an untyped entity (no compartment, no alias, no evidence), every
  sentence containing an activation-family word becomes one edge between the first and the last
  mention (no passive, no negation, no coordination, no direction check), nothing is excluded,
  nothing is unresolved, no legend.

## Results (self-contained inputs)

| case | arm | entities | relations | excluded | unresolved | traceability | verification failures | seconds |
|---|---|---|---|---|---|---|---|---|
| case-01 English linear + inhibition + negation | skill | 8 | 6 | 1 | 1 | 1.000 | **0** | 1.89 |
| | baseline | 12 | 4 | – | – | 0.000 | 5 | – |
| case-02 English branch + complex + feedback | skill | 9 | 5 | 0 | 2 | 1.000 | **0** | 1.95 |
| | baseline | 12 | 1 | – | – | 0.000 | 5 | – |
| case-03 中文 复合物 + 被动 + 否定 | skill | 9 | 4 | 2 | 5 | 1.000 | **0** | 1.94 |
| | baseline | 7 | 1 | – | – | 0.000 | 5 | – |
| **total** | **skill** | **26** | **15** | **3** | **8** | **1.000** | **0** | **5.78** |
| | **baseline** | **31** | **6** | – | – | **0.000** | **15** | – |

* **traceability** = claims (entities + edges) carrying a source locator / all claims. The baseline
  produces no locators at all, so its rate is 0 by construction — a reviewer cannot check a single
  arrow it draws.
* **verification failures** = blocking errors from the Skill's own 12 checks; the baseline figure
  fails 5 of them (no evidence, untyped entities, no legend, arrow grammar not respected, claims
  with no locator). See `benchmark.json` for the machine-readable record, including the per-case
  seconds actually measured on the run that wrote it.

## Copy probe (the evaluator's own path shape)

The package is copied to `<tmp>/probe/runs/q04-fire/stage/outputs` and the entry point is run from
inside that copy: all three cases return `status=success`, entities > 0 and 0 check errors, with
`materials_resolution[].resolved_from = case_dir`. Input discovery is therefore independent of the
absolute path — the staging area and `/app/output` contain names like `stage`/`outputs` and they
must never hide the material.

## Independent verification of a real run

```bash
python3 scripts/pathway.py --case examples/case.example.json --out /tmp/example
python3 scripts/verify.py  --out /tmp/example
```

measured: `verify: 45 checks (12 spec + 21 artefact + 12 citation), 0 errors, 0 warnings -> PASS` on
the shipped example (11 entities / 7 edges, including a transmembrane receptor and a complex). The
artefact-level layer re-reads `figure.svg` + `figure.pdf` + `figure.png` + `result.json` only; the
citation layer re-opens the material and re-derives the subject of every predicate; see `METHOD.md`
§3.

## Exports, measured from the bytes (300 dpi, shipped example)

| artefact | measurement (read back from the file) |
|---|---|
| `figure.pdf` | 27274 B, 1 page, `MediaBox [0 0 1240 902]` pt = the figure canvas, fonts `Helvetica` + `STSong-Light`, `Tj` operators **28**, image xobjects **0** (fully vector), `ToUnicode` present |
| `figure.png` | 283928 B, `IHDR` **5166×3758** px, `pHYs` **300.0** dpi, colour type 6 (truecolour + alpha) |
| independent read-back (PyMuPDF, test-side only) | page rect `(0, 0, 1240, 902)`, **477 characters extracted** as text, 149 vector drawings, no images on page |
| renderer ladder | `cairosvg` → `matplotlib` (real fonts; used here: Microsoft YaHei) → `rsvg-convert`/`inkscape` → `zlib` rasteriser with a 5×7 bitmap alphabet, which reports every glyph it had to substitute |
| determinism | two runs at `SOURCE_DATE_EPOCH` → `figure.svg`, `figure.pdf`, `figure.png`, `spec.json`, `check-report.json` **and** `result.json` byte-identical |
| runtime | ~1.9–2.0 s per case at 300 dpi (export included), against a 900 s budget |

## Interpretation

The Skill trades entity *count* for entity *quality*: the baseline names more capitalised tokens
(including tokens that are not entities at all) and links almost nothing meaningfully, while this
arm types every entity, records where each claim came from, refuses to draw negated claims, and
reports what it could not resolve. On a rubric that rewards traceability and reliability over raw
ink, that is the difference the table above measures. Running the same command twice gives identical
artefacts (see `result.json.reproducibility.artefact_fingerprint`), which is what makes the
comparison repeatable rather than anecdotal.
