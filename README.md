# PKU Efficiency Challenge 3 — Skill Submissions

Nine self-contained **Agent Skills** built for the PKU *Efficiency* challenge (`efficiency-3`), covering scientific figures and academic slides. Each skill is a plain-text package (`SKILL.md` + scripts + references + examples) that runs **offline on ordinary Python**, takes a `case.json`, and writes deliverables plus a machine-readable `result.json` to an output directory.

> For every task the platform's fixed test cases are run by the organiser. The `examples/` folders here are **illustrative examples**, not official answers, and are labelled as such inside each package.

## Layout

```
efficiency-3/
├── q01/  Graphical abstract
├── q02/  Scientific schematic generation & editing
├── q03/  Scientific data charts with source links
├── q04/  Biological mechanism / pathway figures
├── q05/  Experimental apparatus & technical-roadmap figures
├── q06/  Paper → academic slide deck
├── q07/  Academic talk content organisation
├── q08/  Academic PPT template & format adaptation
└── q09/  Academic PPT generation & editing
```

Each `qNN/<arm>/` directory is one complete, runnable skill submission. If a question contains more than one arm, the arm that was submitted is named explicitly in the submission's `GITHUB_URL.txt`.

## Entry points

| Task | Directory | Command |
|---|---|---|
| q01 Graphical abstract | `q01/pkg-vT` | `python3 scripts/ga_build.py init` → `show` → `check` (multi-step, see `SKILL.md`) |
| q02 Scientific schematic | `q02/pkg-min3`, `q02/pkg-min4` | `python3 scripts/schematic.py --case <case.json> --out <outdir>` |
| q03 Data charts | `q03/pkg-min4`, `q03/pkg-adv2` | `python3 scripts/chart.py --case <case.json> --out <outdir>` |
| q04 Pathway figures | `q04/pkg-min4`, `q04/pkg-min2` | `python3 scripts/pathway.py --case <case.json> --out <outdir>` |
| q05 Apparatus figures | `q05/pkg-min4`, `q05/pkg-min` | `python3 scripts/apparatus.py --case <case.json> --out <outdir>` |
| q06 Paper → slides | `q06/pkg-v12`, `q06/pkg-v15` | `python3 scripts/run.py` (zero-argument end-to-end) |
| q07 Talk content | `q07/pkg-min`, `q07/pkg-min5` | `python3 scripts/talkplan.py --case <case.json> --out <outdir>` |
| q08 Template adaptation | `q08/pkg-vT6`, `q08/pkg-adv1` | `python scripts/run.py --input <case.json> --out <outdir> --backend auto` |
| q09 PPT generation | `q09/pkg-min2`, `q09/pkg-min4` | `python3 scripts/deck.py --case <case.json> --out <outdir>` |

Every skill also ships a `tests/` self-check where applicable and a `references/` folder documenting the rules it enforces.

## Design principles

- **Evidence first.** Outputs are derived from the supplied material at run time; examples are marked as examples, and unsupported claims are rejected or explicitly downgraded rather than invented.
- **Editable deliverables.** Figures and decks are produced as editable sources (SVG/IR, `.pptx`) plus exports, with provenance for every labelled datum.
- **Self-verification.** Each package contains its own checker that reads the produced artefacts and recomputes the contract (counts, references, geometry) instead of trusting in-memory state.
- **No binaries in the package.** Everything is text; renders are produced at run time.

## Running

```bash
cd efficiency-3/q04/pkg-min4
python3 scripts/pathway.py --case /path/to/case.json --out /path/to/output
```

Check the per-skill `SKILL.md` for the exact contract, supported inputs, and degradation behaviour when an optional renderer is unavailable.