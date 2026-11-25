# Arrow grammar and measured boundaries

One shape = one meaning. The table lives in `VOC` (top of `scripts/pathway.py`); `verify.py` asserts
the mapping stays one-to-one — twice: against `spec.json`, and again from the geometry actually
present in `figure.svg`.

A **structured work order** may name a relation instead of writing a sentence. `rel_type()` maps the
declared name onto the same vocabulary: `activation`→activates, `inhibition`/`suppression`→inhibits,
`binding`/`association`→binds, `phosphorylation`/`ubiquitination`→modifies, `transport`/
`translocation`→transports, `transcription`/`expression`→expresses, `degradation`→degrades,
`regulation`/`unknown`→regulates_unknown, plus the literal en/zh cues in the table below.

| type | line | head | cues (EN) | cues (中文) |
|---|---|---|---|---|
| `activates` | solid | filled triangle | activates, promotes, induces, stimulates, drives, triggers, mediates | 激活, 活化, 促进, 诱导, 增强, 上调, 增加, 驱动, 导致, 引起, 介导 |
| `inhibits` | solid | blunt T-bar | inhibits, suppresses, represses, blocks, prevents, reduces | 抑制, 阻断, 下调, 降低, 减少, 削弱, 拮抗, 限制, 沉默 |
| `binds` | solid | open circle | binds, interacts, associates, recruits | 结合, 相互作用, 互作, 形成复合物, 招募 |
| `modifies` | dashed | filled triangle + tag | phosphorylates, ubiquitinates, methylates, cleaves, hydroxylates | 磷酸化, 泛素化, 甲基化, 乙酰化, 羟化, 修饰 |
| `transports` | dash-dot | hollow triangle | transports, translocates, imports, exports, secretes | 转运, 转位, 易位, 入核, 出核, 分泌, 释放 |
| `expresses` | solid | double chevron | transcribes, encodes, expresses | 转录激活, 转录, 表达, 编码, 翻译 |
| `degrades` | dotted | filled triangle | degrades, destabilizes | 降解, 促降解, 清除 |
| `regulates_unknown` | dotted | hollow triangle | regulates, modulates, affects, controls | 调控, 调节, 影响, 相关, 参与 |

English cues match inflections (`activates` also matches *activate / activated / activating*),
which is what makes a negated English clause visible: `EGF does not activate …` is now caught and
excluded instead of being dropped. Width = evidence strength; `modifies` prints its tag at the
head; a feedback clause is routed on a local corridor so the loop reads as a loop.

## Direction rules

* active voice: the subject is the **matrix subject of the predicate's own clause** — the first
  entity in front of that clause's first finite verb — and never "the entity nearest the cue"; an
  entity that sits behind an object-taking preposition/conjunction (`with RPTOR`, `与 RPTOR`) is an
  object, not a subject. `A forms a complex with B and phosphorylates C` ⇒ **A→C**;
* Markdown headings (`# …`, `#…`, `> # …`) are blanked before sentences are cut, so a heading word
  is never an entity, a mention or a subject — `# MAPK1 pathway overview` + `Extracellular EGF binds
  EGFR.` ⇒ EGF→EGFR;
* passive voice: `B is phosphorylated by A` ⇒ **A→B**; the `by` match tolerates interposed adverbs;
* Chinese passive: `B 被/由/受 A 动词` ⇒ **A→B** (`AMPK 由 LKB1 磷酸化激活` ⇒ LKB1→AMPK);
* pair form: `A 与/和 B 结合` ⇒ A binds B;
* coordination: a subjectless second conjunct (`… and <verb>`, `… 并/从而 <动词>`) inherits the
  predicate it is coordinated with; a clause opening with 并且/同时/而且/并/从而/进而/因此/所以/也/则/而
  inherits the preceding subject; English `and/therefore/thus/then/thereby` likewise;
* relative clauses: `, which then activates C` takes the noun in front of the relative pronoun (the
  previous clause's object) — that is what keeps a layer-skipping `A→C` out of the figure;
* anaphora: 其/该/此/这/前者/后者 are used only to pick that antecedent. An anaphor is **never** a
  node and never an edge source: a clause whose only subject is `该复合物` is reported in
  `unresolved_statements[]`, not drawn;
* attributive cues: a Chinese cue directly followed by 的 describes a state, not an interaction
  (`缺氧诱导的糖酵解酶`), so no edge is produced;
* negation is **clause-local and CJK-aware**: `缺氧并不激活 MAPK1` ⇒ excluded. (Python treats CJK
  as word characters, so a `\b`-anchored search never finds 不/并不 inside a clause — this arm
  searches CJK negators literally and keeps `\b` for ASCII ones.)
* unresolved: if both ends cannot be resolved the statement lands in `unresolved_statements[]`
  with sentence + locator. Nothing is invented.

## Entity hygiene (Chinese)

A candidate is rejected when it is a bare class noun (转录因子 / 蛋白酶体 / 细胞膜 / 通路 …), when it
contains a cue verb (诱导 / 促进 / 激活 / 抑制 / 磷酸化 / 降解 / 结合 / 调控 / 表达 / 转录 — those are
clauses, not names), when it is a ≤3-character fragment ending in 酶/体/物/因 (a left-over of
phrase trimming), or when it is a phenotype phrase already covered by the phenotype list
(凋亡 / 增殖 / 血管生成 / 糖酵解 …). Terms are trimmed at the last particle or verb.

## Measured boundaries (honest, not hidden)

| boundary | measurement | consequence |
|---|---|---|
| English negation | fixed in this arm: `case-01` records 1 excluded claim; the earlier `pkg-min` arm recorded 0 | on the three run-time inputs of `tests/bench.py`: exclusions 1 / 0 / 2 |
| compound predicate subject | fixed in this arm: `MTOR forms a complex with RPTOR and phosphorylates S6K1` ⇒ `MTOR -> S6K1` (parent arm: `RPTOR -> S6K1`); 中文 `MTOR 与 RPTOR 形成复合物，并磷酸化 S6K1。` ⇒ `MTOR -> S6K1` | the predicate is attached to the matrix subject of its clause; `verify.py` re-derives that subject from the quoted sentence and refuses an edge that starts at an object-position entity |
| Markdown heading leakage | fixed in this arm: `# MAPK1 pathway overview` + `Extracellular EGF binds EGFR.` ⇒ `EGF -> EGFR` (adv3: `MAPK1 -> EGFR`); `#MAPK1` without a space and `# MAPK1 pathway overview` + `EGFR binds MAPK1.` (heading word is the object) ⇒ correct edge, not swallowed; measured on 6 fixtures, adv3 got 3 wrong / 2 swallowed | heading lines are blanked whole before clause cutting; `verify.py` re-reads the raw file and red-flags a citation that starts inside a heading line |
| compound *subject* (`A and B phosphorylate C`) | one arrow per predicate, from the first entity | the second subject is not drawn separately; listed in `README.md` §7 |
| Chinese anaphora beyond 其/该/此/前者/后者 | zero-pronoun subjects, nested relative clauses are not resolved | they surface in `unresolved_statements[]` (the Chinese benchmark input: 5); an anaphor is never a node |
| numeric data encoding | this arm does not paint values (no colour/size channel for tables) | use the full package for data-encoding cases; a declared value with no `data_source` is refused and recorded |
| exports | every run writes `figure.svg` + vector `figure.pdf` + `figure.png` at `--dpi`, then measures both from their bytes | the PDF's CJK font is **not embedded** (no font file may ship): rendering falls back to a viewer CJK pack, while the `ToUnicode` CMap keeps the text selectable/extractable |
| very long Chinese sentences | clause splitting is punctuation-based | long clauses can stay unresolved rather than be guessed |
| PDF material | PyMuPDF when present, otherwise a stdlib `zlib` text-operator reader | the fallback cannot read import-only streams or most CID/ToUnicode maps; the reader used is named in `sources[].notes` |
| locator attribution | the prose blob carries an offset → (material, line) map | a multi-file case cites `mat02#Lnn`, not `mat01#Lnn`; `verify.py` rejects a citation naming a material that was not read |
| instruction files | `task.md`/`instruction*`/`prompt*`/`rubric*`/`grading*` are never read as material | they are named in `materials_skipped[]`; without this, `/input/task.md` leaked `AI/ID/GitHub/YAML/LLM` into the entity table |
| additive directory scan | at most 2 levels below the input root, never inside `.git`/`__pycache__`/`node_modules`/`runs`/`outputs`/`stage`/`dist`/`build`/`skills` | a nested copy of the Skill under the case root is not eaten as material (measured: 41 → 4 entities in the copy probe) |

Extending: append one `type|label|line|arrow|colour|en cues|zh cues|passive zh` line to `VOC`;
the legend, the drawing and both verification layers follow automatically. Keep every
`(arrow, line)` pair unique or verification fails.
