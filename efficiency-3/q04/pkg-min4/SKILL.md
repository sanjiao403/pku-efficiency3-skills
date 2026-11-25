---
name: pathway-figure-min
description: >
  Draw a checkable biological mechanism / pathway figure from case material in one command:
  typed entities (gene / protein / complex / drug / phenotype), directed interactions
  (activation, inhibition, binding, modification, transport, expression, degradation,
  unknown direction), compartment bands with a transmembrane receptor straddling the membrane,
  a legend generated from what is drawn, and an editable layered SVG. English and Chinese
  material (含 被动 被/由/受、与…结合、否定 不/未/并不、指代 其/该/此、并列从句). Every claim
  carries a source locator; negated or unsupported claims are listed, not drawn; unresolved
  clauses are reported, never guessed. Use for 机制图 / 通路图 / 信号通路示意图 / mechanism
  diagram / pathway figure. Do not use for statistics, experiment design or manuscript writing.
---

# pathway-figure-min — one command, self-contained

```bash
python3 scripts/pathway.py --case /input/case.json --out /app/output      # the deliverable
python3 scripts/verify.py  --out /app/output                             # re-check the artefacts
```

No arguments beyond the two paths, no pre-made spec, no manual tidy-up: the run reads the case
and its material (relative paths resolve against the case file first, then cwd, then `--input`,
then `/input`; the choice is recorded in `result.json.materials_resolution[]`).

## Arrow semantics, geometry audit and uncertainty policy

* `references/arrow-semantics.json` — machine-readable mapping of every interaction type to its
  head, line style, badge and whether it *requires* a stated direction. The renderer, the legend and
  both audits read this file, so one table governs drawing and checking.
* **Direction not stated → undirected**: dashed line, no arrowhead, a `?` annotation, and a legend
  note. An edge whose type requires a direction but whose quote states none is downgraded to
  `unspecified` with `downgraded_from` + `uncertainty` recorded (`references/uncertainty-policy.md`).
* **Geometry audit**: every run writes `fig.checks.json` (read-back of nodes/edges, layers, legend
  coverage and phantom entries, label overflow, canvas limits, direction-stated-when-required,
  head-style-matches-semantics, exports) and copies it into
  `result.json.compliance_checks.geometry`. `scripts/verify.py` re-derives the same audit from
  `figure.svg` on disk and adds `geometry.producer_report_matches`
  (`references/layout-and-geometry.md`).

## Output

| file | content |
|---|---|
| `figure.svg` | **editable source and preview**: layers `compartments / membrane / edges / nodes / legend`, live text, `data-entity-id` / `data-edge-id` on every mark, id maps in `<metadata id="q04-spec">` |
| `result.json` | main result: `case_id`, `status` + `status_reason`, `summary`, `entities[]`, `edges[]`, `excluded_relations[]`, `unresolved_statements[]`, `legend[]`, `sources[]`, `evidence[]`, `checks{}`, `metrics{}`, `uncertainty[]`, `gaps[]`, `materials_resolution[]` and every key the case declares in its `output_contract` |
| `spec.json` | the intermediate representation (edit it and re-run with `--spec` to correct semantics) |
| `check-report.json` | the 12 machine checks |

This arm is vector-only (no raster is written; `exports.raster.produced=false` says so) and needs
no third-party package. The full package adds PNG/PDF export and numeric data encoding.

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
  `B 被/由/受 A 动词` ⇒ A→B); `A 与 B 结合` ⇒ A binds B; a clause opening with
  并且/同时/从而/因此/也/则/而 inherits the previous subject; 其/该/此 resolves to the most recent
  entity (该复合物 → the most recent complex); a cue followed by 的 is attributive and ignored;
* negation is clause-local and CJK-aware — 不/未/并不/尚未/未见 work inside a clause, not only at
  its start; a negated claim goes to `excluded_relations[]` with the negator that removed it;
* a clause whose two ends cannot both be resolved goes to `unresolved_statements[]` with sentence
  and locator; nothing is invented to fill a sentence;
* every entity and edge carries `evidence[].locator` (`matNN#Lnn`) and a quote.

## Status and degradation

`success` only when at least one entity was extracted and no blocking check failed; `partial` when
the material was read but yielded no entity (the figure stays empty on purpose) or a check failed;
`failed` when there is no readable material at all. No raster backend and no network are required.

## Cheapest route to a good score

1. run the one command; 2. read `result.json.status_reason`, `.checks.errors`,
`.unresolved_statements`, `.gaps`; 3. if a clause is unresolved, add it to the case as structured
`entities`/`edges` (or fix `spec.json` and re-run with `--spec`) — never edit the SVG by hand;
4. re-run `verify.py`, which reads only `figure.svg` + `result.json` and re-derives the claims.

See `references/arrow-grammar.md` for the grammar and its measured boundaries.
`BENCHMARK.md` + `benchmark.json` hold the baseline comparison; the harness that produced
them is `questions/q04/tools/bench-min2.py` (kept outside this arm so the shipped entry
point stays small).
