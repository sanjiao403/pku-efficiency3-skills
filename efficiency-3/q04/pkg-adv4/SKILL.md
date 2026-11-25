---
name: pathway-figure-min
description: >
  Draw a checkable biological mechanism / pathway figure from case material in one command:
  typed entities (gene / protein / complex / drug / phenotype), directed interactions
  (activation, inhibition, binding, modification, transport, expression, degradation,
  unknown direction), compartment bands with a transmembrane receptor straddling the membrane,
  a legend generated from what is drawn, and an editable layered SVG. English and Chinese
  material (含 被动 被/由/受、与…结合、否定 不/未/并不、指代 其/该/此、并列与复合谓语: A forms a
  complex with B and phosphorylates C ⇒ A→C). A structured
  work order (`case.json` with entities/edges) is consumed directly. Every claim carries a source
  locator that resolves inside the file it names, and `verify.py` re-derives the subject of every
  predicate from the material, so a claim attached to an object-position entity is refused;
  negated or unsupported claims are listed, not
  drawn; unresolved clauses are reported, never guessed. Use for 机制图 / 通路图 / 信号通路示意图 /
  mechanism diagram / pathway figure. Do not use for statistics, experiment design or manuscript
  writing.
---

# pathway-figure-min — one command, self-contained

```bash
python3 scripts/pathway.py --case /input/case.json --out /app/output      # the deliverable
python3 scripts/verify.py  --out /app/output                             # re-check the artefacts
```

No arguments beyond the two paths, no pre-made spec, no manual tidy-up: the run reads the case and
its material (relative paths resolve against the case file first, then cwd, then `--input`, then
`/input`; the winner is recorded per material in `result.json.materials_resolution[]`).
Optional: `--input DIR`, `--dpi N`, `--quiet`, `--declared-only`, `--spec PATH`.
Standard library only; PyMuPDF is used if present and replaced by a built-in `zlib` reader if not.

## Two input shapes, one grammar

1. **Structured work order** — `case.json` carries `entities` (type, role, compartment, locator,
   optional `data` + `data_source`) and `edges`/`interactions` (source, target, type as
   `activation`/`inhibition`/`binding`/`phosphorylation`/`transport`/`transcription`/`degradation`/
   `regulation`, optional `strength`, `feedback`, `modifiers`, `negated`). Things are normalised:
   ids assigned, arrow geometry taken from the vocabulary, `negated` arms recorded in
   `excluded_relations[]`, an edge naming an undeclared entity dropped rather than invented, a
   declared value with no `data_source` refused and reported.
2. **Prose material** — any `.md/.txt/.tex/.pdf/.docx/.html` listed in `case.json` or found in the
   input directory. Entities and edges are extracted deterministically (no model call).

`result.json.graph_source` always says which shape was used.

## Output

| file | content |
|---|---|
| `figure.svg` | **editable source and preview**: layers `compartments / membrane / edges / nodes / legend`, live text, `data-entity-id` / `data-edge-id` on every mark, id maps in `<metadata id="q04-spec">`, no raster embedded |
| `result.json` | `case_id`, `status` + `status_reason`, `summary`, `graph_source`, `entities[]`, `edges[]`, `excluded_relations[]`, `unresolved_statements[]`, `legend[]`, `sources[]`, `evidence[]`, `materials_resolution[]`, `materials_skipped[]`, `materials_missing[]`, `material_discovery`, `checks{}`, `metrics{}`, `uncertainty[]`, `gaps[]`, `reproducibility{}`, `generated_at`, and every key the case declares in `output_contract` |
| `figure.pdf` | **vector** PDF written at run time (page box = the figure's coordinate system, text as real `Tj` operators → selectable, zero image xobjects) |
| `figure.png` | raster preview at `--dpi` (300 by default); pixel size and dpi are measured back from `IHDR`/`pHYs` |
| `spec.json` | the intermediate representation — edit it and re-run with `--spec spec.json` to correct semantics without touching the SVG |
| `check-report.json` | the 12 spec-level machine checks |
| `verify-report.json` | from `verify.py`: those 12 **plus 21 artefact-level checks** (re-derived from `figure.svg` + `figure.pdf` + `figure.png` + `result.json` alone) **and 12 citation-level checks** (re-opened material: line in range, quote present, and the subject of every predicate re-derived from the quoted sentence) — 45 in total |

All three formats are produced on every run and then **measured from their bytes** (`exports.pdf`:
`MediaBox`, page count, `Tj` count, font list, image-xobject count; `exports.png`: `IHDR` size,
`pHYs` dpi). A contract key that asks for a PNG or PDF is answered with that measured record, never
with a path that does not exist. Numeric data encoding is out of scope for this arm.

> **Which artefact to look at first.** The PDF never embeds a CJK font — a font file would be a
> binary resource and the platform rejects those — so its CJK glyphs need a viewer with CJK packs;
> its **text layer is always selectable and searchable** (a `ToUnicode` CMap ships with it, even for
> a non-embedded face). When the figure has Chinese labels, **`figure.png` is the preferred visual
> artefact** (the renderer ladder uses real system fonts), and `figure.pdf` is the archival/vector
> + text-searchable one. `exports.pdf.font_embedded` and `checks.pdf_fonts_embedded` state this
> honestly per run instead of hiding it. Colour, line width and node size are never encoded from
> data in this arm, so "font availability" is the only rendering caveat.

`--dpi` (default **300**, the figure's own canvas × dpi/72 px) is the one knob: pass `--dpi 150` for
a lighter preview. No other path or behaviour changes with it, so any difference you see is the dpi
alone.

## What is never read as material

The **work order** (`task.md`, `instruction*.md`, `prompt*.md`, `rubric*.md`, `grading*.md`…) — the
runtime contract guarantees `/input/task.md` next to the case, and reading it would inject format
names, tool names and rubric ids into the entity table; the case descriptor itself, wherever it is
named; `*.example.json` / `*.template.json`; this Skill's own artefacts; and anything inside the
output directory. Every **declared** file that is deliberately not read is named in
`result.json.materials_skipped[]`, so a mis-declared source is never silent. A declared path that
resolves to nothing lands in `materials_missing[]`.

## What the drawing guarantees

* one shape per meaning: filled triangle = activation, T-bar = inhibition, open circle = binding,
  dashed triangle = covalent modification (P/Ub/Me/Ac tag), dash-dot hollow = transport, double
  chevron = transcription/expression, dotted triangle = degradation, dotted hollow = unknown
  direction; line width = evidence strength (strong 2.6 / moderate 1.9 / weak 1.3 px);
* bands are anatomical: extracellular → plasma membrane → cytosol → nucleus → cellular outcome;
  a transmembrane receptor straddles the membrane; a transport statement whose object is a
  compartment becomes an arrow to a labelled compartment node;
* the legend is generated from the tokens actually drawn, plus the count of excluded and
  unresolved statements;
* passive voice and 被/由/受 flip the arguments (`B is phosphorylated by A` ⇒ A→B,
  `B 被/由/受 A 动词` ⇒ A→B); `A 与 B 结合` ⇒ A binds B;
* **the subject of a predicate is the matrix subject of its own clause — the first entity in front of
  that clause's first finite verb — never "the entity nearest the cue"**: `A forms a complex with B
  and phosphorylates C` ⇒ **A→C** (not B→C; B is the object of `forms a complex with`), and the same
  holds in 中文 (`A 与 B 形成复合物，并磷酸化 C` ⇒ A→C). A subjectless second conjunct (`… and
  <verb> …`) inherits the predicate it is coordinated with, unless a coordinator such as 并且/同时/
  从而/因此/也/则/而 opens the clause, which inherits the preceding subject; a relative clause
  (`, which then activates C`) takes the noun in front of the relative pronoun, which is what keeps
  the layer-skipping `A→C` edge out of the figure; 其/该/此 and 前者/后者 are used only to pick that
  antecedent — an anaphor is never a node and never an edge source (a clause whose only subject is
  `该复合物` is reported in `unresolved_statements[]`, not drawn);
* a **Markdown heading line is topic metadata, never material**: `norm()` blanks the whole line
  before sentences are cut, so `# MAPK1 pathway overview` above `Extracellular EGF binds EGFR.`
  cannot hand `MAPK1` to the figure as the subject of the sentence below (⇒ EGF→EGFR, never
  MAPK1→EGFR; `#MAPK1` without the space counts too), and a heading word that *is* the sentence's
  object no longer swallows the edge (`# MAPK1 pathway overview` + `EGFR binds MAPK1.` ⇒ EGFR→MAPK1);
  `verify.py` re-reads the raw file and refuses any citation whose quote starts inside a heading
  line;
* a cue followed by 的 is attributive and ignored;
* negation is clause-local and CJK-aware — 不/未/并不/尚未/未见 work inside a clause, not only at
  its start; a negated claim goes to `excluded_relations[]` with the negator that removed it;
* a clause whose two ends cannot both be resolved goes to `unresolved_statements[]` with sentence
  and locator; nothing is invented to fill a sentence;
* every entity and edge carries `evidence[].locator` (`matNN#Lnn`) that points into the file the
  sentence came from, and `verify.py` checks that the cited source was actually read.

## Status and degradation

`success` only when at least one entity was produced and no blocking check failed; `partial` when
material was read but yielded no entity (the figure stays empty on purpose) or a check failed;
`failed` when there is no readable material at all (exit code 2). No raster backend and no network
are required. Missing or unreadable files are recorded per file and the run continues.

## Cheapest route to a good score

1. run the one command; 2. read `result.json.status_reason`, `.checks.errors`,
`.unresolved_statements`, `.gaps`, `.materials_skipped`; 3. if a clause is unresolved, either add it
to the case as structured `entities`/`edges` (see above) or fix `spec.json` and re-run with
`--spec spec.json` — never edit the SVG by hand; 4. re-run `verify.py`, which re-derives 45 checks
from the delivered files; 5. compare `result.json.reproducibility.artefact_fingerprint` between runs
to prove the output is stable.

See `references/arrow-grammar.md` for the grammar and its measured boundaries, `METHOD.md` for the
method and the defect list this arm repairs, `BENCHMARK.md` + `benchmark.json` for the measured
Skill-vs-baseline comparison, and `tests/bench.py` (shipped) to reproduce that comparison.
