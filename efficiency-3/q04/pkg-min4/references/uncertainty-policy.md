# Uncertainty and downgrade policy

**Core rule: a pathway figure is a mechanism claim. When the source does not state something, the
figure must show that it is not stated — never fill the gap with a plausible guess.**

This file is the policy; `scripts/pathway.py` implements it, `scripts/verify.py` audits it, and
every downgrade leaves a machine-readable trace in `result.json`.

## 1. Direction not stated → undirected edge

* the source says "X interacts with Y", "X is associated with Y", "X–Y complex" without saying who
  acts on whom → the run emits an **undirected** edge: dashed line, **no arrowhead**, a `?`
  annotation at the midpoint, and the legend states *"no arrowhead / '?' = direction not stated in
  source"*;
* the run **downgrades** any edge whose type says `requires_direction: true`
  (`references/arrow-semantics.json`) when the quoted statement contains no directional cue
  (activates / inhibits / phosphorylates / promotes / blocks / 激活 / 抑制 / 促进 / 磷酸化 …):
  the edge becomes type `unspecified`, the original type is kept in `edges[].downgraded_from`, and
  `edges[].uncertainty` explains it (`geometry_checks` re-checks this as
  `direction_stated_when_required`);
* guessing a direction from biological plausibility ("a kinase phosphorylates what it binds") is
  forbidden on the canvas; such background knowledge may appear in `uncertainty[]`, never as a head.

## 2. Interaction type not stated → `unspecified`

"A regulates B" without a mechanism must not become activation: `regulates_unknown` and
`unspecified` both render undirected (dashed, no head, `?`) and are distinguished in the legend and
in `edges[].origin`. `unspecified` is preferred when neither mechanism nor direction is stated.

## 3. Compartment not stated

The layout has five anatomical bands (extracellular → plasma membrane → cytosol → nucleus →
cellular outcome). When the material states no localisation, the placement comes from the entity
type and the reason is written to `entities[].compartment_source` (`"type default"`), not presented
as a fact; explicit phrases yield `"explicit localisation phrase"`, roles yield
`"role: transmembrane receptor"` / `"role: transcription factor"`.

## 4. Indirect or hedged evidence

An edge whose sentence carries a hedge (`may`, `might`, `putative`, `可能`, `推测`) is drawn at the
**weak** line width (1.3 px) rather than the moderate 1.9 px, and the width scale is stated in the
legend. Certainty is a channel, not a word in a caption.

## 5. Conflicting statements

If the material states both activation and inhibition for the same pair, **both edges are drawn**
with their own quotes; nothing is averaged into one ambiguous arrow. The pair appears twice in
`edges[]` with different `origin` values, so the conflict is visible.

## 6. Quantitative data absent

This arm paints no numeric channel at all (`data_encoding.rows_matched` reports table rows that were
matched, and `entities[].data_source` records where a value came from). A value with no locator is
never attached. Cases that need fold-change colouring belong to the full package.

## 7. Entity ambiguity

A token that could be a gene or a protein without context support is drawn once and listed in
`uncertainty[]` with `{"item": "<name>: gene or protein", "why": "context does not decide",
"handling": "drawn as <type>"}`. Aliases (`EPAS1`/`HIF2A`, `EGLN1`/`PHD2`, `MTOR`/`mTORC1` …) are
merged to one node rather than drawn twice.

## 8. How downgrades reach `result.json`

| structure | content |
|---|---|
| `edges[].downgraded_from` | the type that was replaced (empty when nothing was downgraded) |
| `edges[].uncertainty` | why the edge is drawn undirected |
| `uncertainty[]` | every ambiguity: item, why, handling — an **empty list means "none found"**, never "not collected" |
| `unresolved_statements[]` | clauses whose two ends could not be resolved, with sentence + locator + reason |
| `excluded_relations[]` | negated / unsupported claims with `removed_because` and the quote |
| `gaps[]`, `not_reported[]` | what is missing and why, including an empty run |
| `compliance_checks.geometry` | the machine-readable audit of the figure (see `layout-and-geometry.md`) |

## 9. How to see the guard fire (reproducible)

The bundled fixtures need **no** downgrade (every claim there quotes a sentence that states a
direction), so the guard is demonstrated directly:

```bash
python3 -c "import sys; sys.path.insert(0,'scripts'); import pathway as P; \
print(P.direction_stated('A interacts with B.'), P.direction_stated('EGFR phosphorylates MAPK1.'))"
# False True
```

`direction_stated('A interacts with B.')` is `False` → such a statement becomes an undirected
`unspecified` edge; `direction_stated('EGFR phosphorylates MAPK1.')` is `True` → the edge keeps its
arrowhead. `result.json.compliance_checks.geometry.direction_stated_when_required` re-audits all of
them after the fact.
