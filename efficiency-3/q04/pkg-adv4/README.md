# README — pathway-figure-min (adv4)

Compact, dependency-free Skill that turns a biological mechanism text into **one checkable,
editable, layered SVG** plus a machine-readable result. English and Chinese material.

## 1. What it is for / when not to use it

Use it when the case gives you **prose or a work order** and expects:

* typed entities (gene / protein / complex / drug / phenotype / compartment),
* directed interactions with distinguishable arrows (activation, inhibition, binding,
  modification, transport, expression, degradation, unknown direction),
* compartment bands with a transmembrane receptor straddling the membrane,
* a legend generated from what is actually drawn, and every claim carrying a **source locator**;
  the subject of every predicate is checked against the material (`verify.py`), so an arrow that
  starts at an object-position entity is refused instead of delivered.

Do **not** use it for statistics, experiment design, manuscript writing or numeric data encoding:
this arm paints no colour/size channel from data tables. It does write all three artefacts — the
editable layered SVG, a vector PDF and a PNG preview at `--dpi` — and measures each of them back
from its bytes (see `BENCHMARK.md`). A larger sibling arm of the same family adds numeric
colour/size encoding.

## 2. Call it

```bash
python3 scripts/pathway.py --case /input/case.json --out /app/output   # the deliverable
python3 scripts/verify.py  --out /app/output                          # re-check the artefacts
```

Optional flags (never required): `--input DIR` (extra search root), `--dpi N` (PNG resolution;
default **300**, `--dpi 150` gives a lighter preview and changes nothing else), `--quiet`,
`--declared-only` (read only the files `case.json` declares).

> Reading the exports: the PDF does not embed a CJK font (a font file would be a binary resource),
> so **when labels are Chinese, `figure.png` is the preferred visual artefact** while `figure.pdf` is
> the vector + text-searchable one — its text layer is selectable and searchable via `ToUnicode`.
> `exports.pdf.font_embedded` / `checks.pdf_fonts_embedded` record this per run.

Requirements: **Python 3.8+ and the standard library only.** PyMuPDF is used *if present* to read
PDF material; if it is missing, a built-in `zlib` reader takes over, so a PDF case still produces a
figure instead of an empty one.

## 3. Input

`case.json` is read from `--case`. Every one of these keys is optional and all of them are searched:
`materials`, `files`, `documents`, `sources`, `inputs`, `attachments`, `text` (a string or a list of
relative paths). `case_id`, `title`, `figure.title` and `output_contract` are honoured when present.

Material paths are resolved in this order — `case.json` directory → current working directory →
`--input` → `/input` — and the file that won is recorded per material in
`result.json.materials_resolution[].resolved_from`. `\` and `./` in a declared path are normalised,
so a case authored on Windows resolves on a POSIX host.

### What is never read as material

* the **work order**: `task.md` / `instruction*.md` / `prompt*.md` / `rubric*.md` / `grading*.md`
  and similar. The runtime contract guarantees `/input/task.md` next to the case; reading it would
  inject format names, tool names and rubric ids into the entity table;
* the case descriptor itself (whatever it is named), `*.example.json`, `*.template.json`;
* **Markdown heading lines** (`# …`, `## …`, also `#…` without a space and `> # …`): a heading names
  the topic, so it is blanked before the prose is cut into sentences and can never become an entity,
  a mention or the subject of the sentence below. Without this, `# MAPK1 pathway overview` above
  `Extracellular EGF binds EGFR.` produced `MAPK1 --binds--> EGFR`;
* this Skill's own artefacts (`result.json`, `spec.json`, `check-report.json`, `figure.*`,
  `pathway.*`, `readme*`) and anything inside the output directory.

Files found by the directory scan are used *in addition to* the declared ones, so a case that
forgets to list a source does not lose it. The scan stays shallow on purpose — at most two directory
levels below the input root, and never inside a VCS / build / staging directory (`.git`,
`__pycache__`, `node_modules`, `runs`, `outputs`, `stage`, `dist`, `build`, `skills`, …) — so a
nested copy of this Skill or a previous run's staging area cannot be read as biological material.
`result.json.material_discovery` says which mode ran and `materials_skipped` names every **declared**
file that was deliberately not read.

## 4. Output (all under `--out`)

| file | content |
|---|---|
| `figure.svg` | the editable source: layers layers `compartments / membrane / edges / nodes / legend`, live text, `data-entity-id` / `data-edge-id` on every mark, id maps in `<metadata id="q04-spec">`, no embedded raster |
| `figure.pdf` | a **vector** PDF written at run time from the same primitive list: page box = the figure's own coordinate system, text emitted as real `Tj` operators so it is selectable, no image xobject anywhere in the file |
| `figure.png` | a raster preview at `--dpi` (default 300): pixel size and dpi are re-read from the file's own `IHDR` / `pHYs` chunks and reported in `exports.png` |
| `result.json` | `case_id`, `status` + `status_reason`, `summary`, `entities[]`, `edges[]`, `excluded_relations[]`, `unresolved_statements[]`, `legend[]`, `sources[]`, `evidence[]`, `materials_resolution[]`, `materials_skipped[]`, `materials_missing[]`, `material_discovery`, `checks{}`, `metrics{}`, `uncertainty[]`, `gaps[]`, `reproducibility{}`, `generated_at`, and every key the case declares in `output_contract` |
| `spec.json` | the intermediate representation — edit it and re-run with `--spec`-style reload by passing it as a material to correct semantics |
| `check-report.json` | the 12 spec-level machine checks |
| `verify-report.json` | written by `verify.py`: the 12 spec-level checks, **21 artefact-level checks** re-derived from `figure.svg` + `figure.pdf` + `figure.png` + `result.json` alone, and **12 citation-level checks** that re-open the material (line in range, quote present, and the subject of every predicate re-derived from the quoted sentence) — 45 in total |

## 5. Status, degradation and failure handling

| situation | behaviour |
|---|---|
| material read, entities extracted, checks pass | `status=success` |
| material read but no entity extractable | `status=partial`, figure stays empty on purpose, reason recorded |
| a blocking check fails | `status=partial` with the failing check ids in `status_reason` |
| nothing readable at all | `status=failed` (exit code 2) with `not_reported[]` |
| PDF, no PyMuPDF | stdlib `zlib` text reader; the reader used and its limits are written into `sources[].notes` |
| PNG, no renderer at all | `zlib` rasteriser: exact shapes plus a 5×7 bitmap alphabet, non-ASCII glyphs replaced by a placeholder and counted in `exports.png.writer.glyph_substitutions` |
| PDF/PNG export impossible | never silent: `exports.*.bytes`/`sha256` come from the file on disk, and `verify.py` fails if a claimed export is missing |
| `.docx` | read with the standard library (`zipfile` + tag stripping) |
| declared material missing / remote URL | `materials_missing[]` records it; nothing is fetched and no data is invented |
| unreadable file | `sources[].notes = "not readable: <Exception>: <message>"`; the run continues |
| a value with no locator | refused, not painted (`data.sourced` check) |

## 6. Verify it yourself

```bash
python3 scripts/pathway.py --case examples/case.example.json --out /tmp/example
python3 scripts/verify.py  --out /tmp/example
python3 tests/bench.py                       # prints the Skill-vs-baseline table, writes nothing
python3 tests/bench.py --bench-out /tmp/benchmark.json
```

`verify.py` exits 0 only if all 45 checks pass, and prints every failure with its check id.
Two runs of one input are byte-identical apart from `result.json:generated_at`; set
`SOURCE_DATE_EPOCH` to pin that too, and compare `result.json.reproducibility.artefact_fingerprint`
to prove it.

## 7. Limits (honest list)

* numeric data encoding (colour/size channel for table values) is out of scope; values are read and
  counted, not painted, and a declared value without a `data_source` is refused;
* the PDF's CJK face is not embedded (a font file would be a binary in the package): a viewer without
  CJK packs substitutes it, while the `ToUnicode` CMap keeps the text selectable and extractable;
* rounded rectangles become sharp corners in PDF/PNG (`rounded_corners_flattened: true`);
* Chinese anaphora beyond 其/该/此 (前者/后者, zero-pronoun subjects, nested relative clauses) is not
  resolved — such clauses land in `unresolved_statements[]`;
* a compound subject (`A and B phosphorylate C`) yields one edge, from the first entity; the second
  subject is not drawn separately;
* the stdlib PDF *reader* (used for PDF material, not for export) cannot read import-only streams or
  most CID/ToUnicode maps;
* very long Chinese sentences are split on punctuation, so they may stay unresolved rather than be
  guessed at;
* text width is computed from fixed per-character coefficients, not font metrics, so a very unusual
  font will reflow a label without changing the drawn box.

## 8. Version and maintenance

`pathway.py 1.3.0-adv4`. The grammar table (`VOC` at the top of `scripts/pathway.py`) is the single
extension point: append one `type|label|line|arrow|colour|en cues|zh cues|zh passive` row and the
legend, the drawing and both verification layers follow. Keep every `(arrow, line)` pair unique or
verification fails by design. See `METHOD.md` for the method and `BENCHMARK.md` for the measurements.
