# METHOD — how this arm works, and what it repairs

## 1. Pipeline (one file, no model call, no network)

```
case.json ─┬─ material files (declared + directory scan) ──► per-file text
           ├─ structured entities/edges (work order)     ──► normalisation
           └─ --spec spec.json (corrected IR)            ──► rebuild
                                   │
                 entities (typed, compartmented) + edges (typed, directed)
                                   │
             setcmp (compartment / role)  →  rels (cue grammar, direction, negation, anaphora)
                                   │
                    comp_targets (a compartment as an edge target)
                                   │
             layout (bands → ranks → columns, membrane straddle, orthogonal routes)
                                   │
   figure.svg (layered, live text, data-entity-id) + spec.json + check-report.json + result.json
                                   │
                    verify.py: 12 spec-level + 21 artefact-level + 12 citation-level checks
```

Every stage is deterministic and text-only; `result.json.graph_source` records which entry produced
the graph.

## 2. The invariant that makes the figure checkable

One arrow geometry per interaction meaning, one entry per claim, one locator per entry:

| relation | line | head | encoded from |
|---|---|---|---|
| activates | solid | filled triangle | cue `activates/promotes/诱导/激活 …` |
| inhibits | solid | T-bar | `inhibits/suppresses/抑制/阻断 …` |
| binds | solid | open circle | `binds/与…结合` |
| modifies | dashed | filled triangle + P/Ub/Me/Ac | `phosphorylates/磷酸化 …` |
| transports | dash-dot | hollow triangle | `transports/转运/入核 …` |
| expresses | solid | double chevron | `transcribes/表达/转录 …` |
| degrades | dotted | filled triangle | `degrades/降解 …` |
| regulates_unknown | dotted | hollow triangle | `regulates/调控` (direction not stated) |

Line width = evidence strength. A negated clause is *never drawn*: it goes to
`excluded_relations[]` with the negator that removed it. A clause with an unresolvable argument goes
to `unresolved_statements[]`, never to the figure. A declared or extracted value without a locator
is refused, not painted.

## 3. Why the artefact-level verification layer exists

The spec-level checks (`check-report.json`) read `spec.json` on disk but compare it against the same
grammar table the writer used — necessary, not sufficient. `verify.py` therefore *also* re-derives 21
checks from the delivered artefacts only (`figure.svg` + `figure.pdf` + `figure.png` + `result.json`):
`svg_layers`, `no_raster` (the **SVG** embeds no image data), `node_ids_match`, `edge_ids_match`,
`arrow_geometry_stable`, `arrow_geometry_distinct` (signatures read out of the markup: primitive
sequence + dash pattern), `arrow_touches_declared_ends` (every edge's geometry must touch the
bounding box of the node it declares as source and of the node it declares as target),
`citations_name_read_sources`, `instructions_not_material`, `descriptor_only_when_structured`,
`export_claim_honest`, `raster_claim_honest`, `contract_echoed`,
`pdf_page_is_the_figure_box` (the PDF `MediaBox` must equal the SVG's own width/height),
`pdf_is_vector` (zero `/Subtype /Image`), `pdf_text_is_selectable` (`Tj`/`TJ` count > 0),
`pdf_export_record_matches_bytes`, `png_pixels_match_page_and_dpi` (`IHDR` = page box × `pHYs` dpi),
`png_export_record_matches_bytes`, `png_dpi_is_declared`, `deliverable_formats_on_disk`.

Nothing in that list can be satisfied by the writer asserting something: it is all recomputed from
the files a reviewer also has. Tampering with the delivered files turns them red (measured, see §4
P1-9/P0-2 rows, `NOTES.md` §13.5 and the `tests/regression.py` F1–F6 cases): renaming one
`data-edge-id`, deleting one node group, embedding a raster in the SVG, pointing one citation at an
unread material, or promoting `task.md` into `sources[]` each makes `verify.py` exit 2 with the
matching check id.

## 3c. The citation layer: what a "source locator" is worth

12 further checks re-open the material files themselves (`--input` / `--case`):
`sources_have_read_evidence` (bytes/lines/sha256), `sources_in_resolution`, `claims_have_evidence`,
`citations_registered`, `citations_have_line_locator`, `materials_reachable`,
`materials_hash_unchanged`, `citation_lines_in_range`, `citations_quote_present`,
`quote_is_its_own_sentence` (the quote may not start inside, or be cited on, a Markdown heading line
— a heading is topic metadata, and a sentence glued to one hands the heading's word to the figure:
`# MAPK1 pathway overview` + `Extracellular EGF binds EGFR.` ⇒ `MAPK1 -> EGFR`, QA 2026-11-24 P0-4),
and the two that guard the *semantics* of every arrow:

* `predicate_subject_located` — the entity the arrow starts from must really occur in the sentence the
  edge cites;
* `predicate_subject_not_in_object_slot` — it must have a subject position there: in front of the cue,
  or behind passive morphology that is read **from the text** (`by` after the cue, 由/被/受 at the cue)
  rather than from `result.json.voice`. This is the check that makes the 2026-11-24
  P0-3 defect impossible to ship: the parent arm drew `RPTOR -> S6K1` for
  `MTOR forms a complex with RPTOR and phosphorylates S6K1` and its own checks stayed green. The
  layer re-derives the subject from the quoted sentence; it does not import the writer's clause
  parser, so it cannot inherit the same mistake. Measured: the old (wrong) `result.example.json`
  goes red on exactly this id; the corrected one passes (control pair in `tests/regression.py`
  H0/H1/H2), and 17/17 ordinary English/Chinese materials stay green end to end.

## 3b. Exports: written from the same primitives, then measured from the bytes

`export_all()` writes `figure.pdf` and `figure.png` from the *same* `prims()` list the SVG uses, so
the three formats cannot drift apart:

* **PDF (stdlib, always available)** — a real vector PDF: `re`/`m`/`l`/`c`/`f`/`S` operators for
  every mark, `MediaBox` = the figure canvas, and text emitted as `BT … Tj … ET` in Helvetica
  (WinAnsi) for Latin and in a UCS2 `Type0` font for CJK. The CJK base font is **not embedded**
  (no binary may ship in the package), so a viewer without CJK packs substitutes the face — a
  `ToUnicode` CMap keeps the text selectable and extractable either way.
* **PNG** — renderer ladder, each step named in `exports.png.writer.engine`: `cairosvg` →
  `matplotlib` (real fonts; used on this machine: Microsoft YaHei) → `rsvg-convert`/`inkscape` →
  a `zlib` rasteriser with a 5×7 bitmap alphabet. The last rung has no CJK font, so it substitutes a
  placeholder and reports the count in `writer.glyph_substitutions` instead of pretending.
* Both files are then re-opened and measured (`measure_pdf` / `measure_png`): page box, page count,
  text-operator count, font names, embedded-font flag, image-xobject count, PNG `IHDR` size and
  `pHYs` dpi, plus a plain `sha256` per file that a reviewer can check with `sha256sum`.

## 4. Defects this arm repairs, each with the test that shows it

All figures below were produced by really running both arms on this machine (Python 3.14.3,
Windows). The tests are re-runnable: `scripts/pathway.py` for the arm under test.

| # | defect in the parent arm | evidence (measured) | repair |
|---|---|---|---|
| P0-1 | `scripts/__pycache__/*.pyc` shipped inside the package | `tools/check-pkg.ps1 -Pkg pkg-min2` → `[X] 二进制资源…pathway.cpython-314.pyc, verify.cpython-314.pyc` + `[X] 运行期残留` → `[FAIL]`; the platform rejects binary Skill resources before the sandbox | pycache not copied; the arm is text-only and the gate passes |
| P0-2 | `/input/task.md` — guaranteed by the runtime contract — was read as biological material | parent: 1 material file + `task.md` → entities `HIF1A, VEGFA, VHL, AI, ID, GitHub, YAML, DeepSeek, UTF-8, figure03, own16rubric, LLM`; this arm: `HIF1A, VEGFA, VHL`, `materials_skipped=[task.md]` | instruction / work-order / case-descriptor / own-artefact files are never material; the skip is recorded |
| P0-3 | with several material files every locator was attributed to the first file | parent: a sentence in `second-source.md` cited `mat01#L4` inside a one-line `mat01` — a citation that resolves to nothing; this arm: `mat02#L1`, and the "outside its own file" list is empty | the prose blob carries an offset → (material, line) map, so a locator points into the file the sentence came from |
| P1-4 | a PDF case collapsed when PyMuPDF was absent | parent with `import fitz` blocked: `status=partial`, `n_entities=0`, `notes=["not readable"]`; this arm: `status=success`, 5 entities / 3 edges, `sources[].notes` records the reader used | stdlib `zlib` text-operator reader as fallback, with its limits stated |
| P1-5 | files that `case.json` never mentioned were read as material | parent with an unrelated `unrelated-notes.md` in the input dir: it was read and its claims (`TP53 activates MYC`, `MDM2 degrades TP53`) were drawn; this arm names every declared skip and ignores incidental artefacts silently | declared files are authoritative; the scan is additive and reported; `--declared-only` is available |
| P1-6 | the shipped minimal example could not run | parent `--case examples/case.example.json` → `status=failed`, exit 2 (`materials.md` did not exist in the package); this arm ships `examples/materials.example.md` and a regenerated `examples/result.example.json` (measured: `status=success`, 11 entities / 7 edges) | the documented example is a real run of the documented command |
| P1-7 | the package claimed files and interfaces it did not have | parent `result.json.summary` = "… -> SVG + PNG + result.json" and stdout printed `figure.png`, while `png()` writes nothing; `BENCHMARK.md` told the reader to run a harness that is **outside** the package; `SKILL.md` offered `--spec` and structured `entities/edges`, neither of which existed | claims corrected, `echo()` answers a PNG/PDF contract key with `produced:false`, the harness ships as `tests/bench.py`, and both `--spec` and structured `entities`/`edges` input are implemented and tested |
| P1-8 | a declared material path with `\` or `./` could not resolve on a POSIX host | code-reasoned (the host here is Windows, so this one is not measurable locally): `os.path.join("/input", "materials\\fig.md")` cannot exist on POSIX | declared paths are normalised (`\`→`/`, `./` stripped, `//` collapsed); `http(s)://` is refused explicitly instead of being fetched |
| P1-9 | reproducibility was asserted, not checkable | this arm: two runs of one input → identical `figure.svg` / `spec.json` / `check-report.json` hashes and identical `reproducibility.artefact_fingerprint`; with `SOURCE_DATE_EPOCH` set, `result.json` is byte-identical too | `reproducibility{}` + `repo_hashes{}` in `result.json`; no wall-clock field other than `generated_at` |
| P1-10 | the additive directory scan walked arbitrarily deep | with a nested copy of the package under the case root the copy probe drew **41** entities read out of the package's own documentation; after the depth/blacklist rule it draws the 4 entities of the real material only | the scan stops after two directory levels and never enters `.git`/`__pycache__`/`node_modules`/`runs`/`outputs`/`stage`/`dist`/`build`/`skills`; a declared path is still honoured at any depth |
| P0-11 | **no PDF and no PNG at all**: the work order asks for real editable SVG/PNG/PDF, the parent printed `figure.png` in its log while `png()` wrote nothing | parent run: `/app/output` contains `figure.svg, spec.json, check-report.json, result.json` only — no `figure.pdf`, no `figure.png`; the platform keeps runtime binaries, so the gap was real, not a permission problem | `export_all()` writes a vector PDF and a 300 dpi PNG from the same primitive list every run, then re-reads both (`MediaBox`/`Tj`/image xobjects/`IHDR`/`pHYs`); `verify.py` re-measures them from the bytes (21 artefact checks) |
| P0-12 | **the compound-predicate subject was hijacked by the entity nearest the cue**: the previous arm attached the predicate of a second conjunct to the object of the first one, so the figure asserted a mechanism that the material does not state | parent (`pkg-adv2`) on `MTOR forms a complex with RPTOR and phosphorylates S6K1.` → `RPTOR --modifies--> S6K1` (adv1, before the coordination rework, drew `MTOR -> S6K1` correctly); the wrong edge was **shipped inside `examples/result.example.json`** and `verify.py` still reported `42 checks, 0 errors -> PASS`; 中文 `MTOR 与 RPTOR 形成复合物，并磷酸化 S6K1。` → `形成复合物 --modifies--> S6K1` | the subject of a predicate is the **matrix subject of its own clause** — the first entity in front of that clause's first finite verb (`fore()`), with a candidate that itself sits behind `with/与/和/…` refused as an object (`OBJE`/`OBJZ`); a subjectless second conjunct inherits the predicate it is coordinated with (`coord_before()`), a relative clause (`, which then …`) takes the noun before the pronoun, and an anaphor (`该复合物`) is never a subject. `examples/result.example.json` was regenerated by a real run, and `verify.py` gained the independent `citation.predicate_subject_not_in_object_slot` check (regression G/H) |
| P0-13 | **a Markdown heading leaked into the next sentence as its subject**: `norm()` blanked the `#` characters but kept the heading text, and since a heading does not end with sentence punctuation the line-join glued it to the line below, so the heading's word became the first mention — and therefore the subject — of that sentence | `pkg-adv3` on `# MAPK1 pathway overview` + `Extracellular EGF binds EGFR.` → `MAPK1 --binds--> EGFR` with the quote `MAPK1 pathway overview Extracellular EGF binds EGFR.` (parent `pkg-adv2`: `EGF -> EGFR`, correct); the same in 4 shapes (`# S6K1 …`, `#MAPK1` without a space, heading + compound sentence); when the heading word was the sentence's *object* the whole edge disappeared (`# MAPK1 pathway overview` + `EGFR binds MAPK1.` → no edge). Its own `verify.py` reported `44/44 PASS` | `norm()` blanks the **whole heading line** (same length, so locators still name the raw line) and never joins it to the line below; `heading_lines()` uses the same pattern; `verify.py` re-reads the raw file and red-flags a citation whose quote starts inside a heading line or which names a heading line (`citation.quote_is_its_own_sentence`, regression I/J) |

## 5. What was deliberately not changed

The cue vocabulary, the layout algorithm, the export writer and the 12 spec-level checks are
unchanged; the measured Skill-vs-baseline table moves only where the subject and heading repairs move
it (`case-01` 7→8 entities, relaunched timings; relations 6/5/4 unchanged, baseline 5 failures per
case, copy probe `all_pass=true`). The repairs are about *which entity a predicate belongs to* and
*what counts as prose at all*, not about re-tuning the vocabulary or the layout.

## 6. Known limits

* numeric colour/size encoding of data tables is out of scope for this arm (the table is read and
  counted, `data_encoding.rows_matched`, but values are not painted); a declared value with no
  `data_source` is refused and recorded;
* the PDF's CJK face is not embedded (no font file may ship), so a viewer without CJK packs
  substitutes it — `ToUnicode` keeps the text selectable; the stdlib PNG rung has no CJK font at all
  and reports every substituted glyph;
* rounded rectangles are flattened to sharp corners in PDF/PNG (`rounded_corners_flattened`);
* Chinese anaphora beyond 其/该/此/前者/后者 (zero-pronoun subjects, nested relatives) stays
  unresolved, and an anaphor is never used as a node or an edge source;
* the stdlib PDF fallback cannot read import-only streams or most CID/ToUnicode maps (that is the
  *reader* for PDF material, not the exporter);
* text width uses fixed per-character coefficients rather than font metrics;
* the directory scan still reads an incidental file if a case relies on it and the file is textual —
  this is why `materials_resolution[]` records `declared` for every material and
  `material_discovery` records the mode.
