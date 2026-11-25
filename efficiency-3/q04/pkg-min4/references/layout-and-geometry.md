# Layout conventions and the geometry audit

## 1. Channels (never overload one channel with two meanings)

| channel | meaning | source of truth |
|---|---|---|
| head shape | regulation sign / direction (`tri` activation, `tbar` inhibition, `circ` binding, `tri_o` transport, `chev` expression, **`none` = direction not stated**) | `references/arrow-semantics.json` → `head_shapes`, `edge_types[].head` |
| line style | interaction family (solid / dash / dash-dot / dot) and, for the undirected types, "direction not stated" | `arrow-semantics.json` → `line_styles` |
| badge | covalent modification type (P, Ub, Me, Ac, OH) | `arrow-semantics.json` → `badges` |
| line width | evidence strength (strong 2.6 px, moderate 1.9 px, weak 1.3 px) | legend row per width used |
| node shape/fill | entity type (gene italic, protein, complex, drug, phenotype, compartment) | `TYP` in `scripts/pathway.py`, mirrored in the legend |
| band | anatomical compartment: extracellular → plasma membrane → cytosol → nucleus → cellular outcome | `CMP`; a transmembrane receptor straddles the membrane band |
| `?` annotation | direction not stated in the source | `arrow-semantics.json.direction_policy` |

The legend only advertises what is drawn, and each legend row carries a machine key
(`data-key="edge-activates"`, `data-key="node-protein"`) so a reviewer can diff legends without
parsing prose.

## 2. SVG structure

```
<g id="layer-compartments">  band rectangles + band labels
<g id="layer-membrane">      membrane double line + receptor anchors
<g id="layer-edges">         <g class="edge edge-<type>" data-edge-id data-edge-type> …
<g id="layer-nodes">         <g id="E01" class="node <type>" data-entity-id> rect + text
<g id="layer-legend">        one row per drawn token, data-key per row
<metadata id="q04-spec">     id maps (case_id, entity ids, edge ids)
```

Every node group id is the entity id, every edge group id the edge id, so read-back is a set
comparison rather than a heuristic.

## 3. The audit: `fig.checks.json` → `result.json.compliance_checks.geometry`

The run writes `fig.checks.json` and copies it into `result.json.compliance_checks.geometry`:

```json
{"passed": true, "checks": [{"check": "svg_readback_nodes", "passed": true, "level": "error", "detail": "18 entities -> 18 matched"}, …],
 "errors": [], "warnings": [], "canvas": {"width_px": 1508, "height_px": 921},
 "counts": {"entities": 18, "edges": 14, "edge_types": [...], "node_types": [...]},
 "semantics_version": "1.0.0"}
```

| check | error/warning | what it proves |
|---|---|---|
| `svg_readback_nodes` / `svg_readback_edges` | error | every model entity/edge really has an element in the drawn SVG |
| `svg_layers` | error | compartments / edges / nodes / legend layers all exist |
| `legend_covers_used_types` | error | every type drawn has a legend row (by machine key) |
| `legend_no_phantom_entries` | warning | the legend advertises no unused type |
| `label_overflow` | error | no node label is wider than its box |
| `canvas_limits` | warning | canvas ≤ 2400 × 1800 px |
| `direction_stated_when_required` | error | no edge claims a direction its own quote does not state |
| `head_style_matches_semantics` | error | every drawn head/line equals `arrow-semantics.json` |
| `exports_exist` | error | the declared artefacts were really written |
| `result_contract_nulls_explained` | warning | no unexplained null reaches the result |

`scripts/verify.py` re-derives the same audit **from `figure.svg` on disk** (not from memory) and
adds `geometry.producer_report_matches`, which fails when its recomputation disagrees with the
producer's `fig.checks.json`. Measured on the three bundled fixtures: `passed = true`, 0 errors,
0 warnings, `matches_producer_report = true`.

## 4. Layout rules that keep the audit meaningful

1. ranks come from the edge direction (feedback edges are excluded and routed on a local corridor),
   so a non-feedback edge normally points rightwards — deviations are reported as a warning;
2. nodes never overlap: each compartment band lays its nodes out per rank, the membrane band packs
   receptors along the membrane line, and label boxes are sized from the measured text width;
3. a transport whose object is a compartment becomes an arrow to a labelled compartment node rather
   than an endpoint floating in space;
4. text is live `<text>` (editable), never an image, so the figure stays re-editable and the audit
   can read it back.
