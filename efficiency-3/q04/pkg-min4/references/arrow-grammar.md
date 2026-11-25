# Arrow grammar and measured boundaries

One shape = one meaning. The table lives in `VOC` (top of `scripts/pathway.py`); `verify.py`
asserts the mapping stays one-to-one.

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

* active voice: subject before the cue, object after it, inside the clause;
* passive voice: `B is phosphorylated by A` ⇒ **A→B**; the `by` match tolerates interposed adverbs;
* Chinese passive: `B 被/由/受 A 动词` ⇒ **A→B** (`AMPK 由 LKB1 磷酸化激活` ⇒ LKB1→AMPK);
* pair form: `A 与/和 B 结合` ⇒ A binds B;
* coordination: a clause opening with 并且/同时/而且/并/从而/进而/因此/所以/也/则/而 inherits the
  preceding subject; English `and/therefore/thus/then/thereby` likewise;
* anaphora: 其/该/此/这 → most recent entity; 该复合物 → most recent **complex**;
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
| English negation | fixed in this arm: `case-01` records 1 excluded claim; the earlier `pkg-min` arm recorded 0 | on the bundled fixtures: `case-a` excluded 1, `case-c` excluded 2 |
| Chinese anaphora beyond 其/该/此 | 前者/后者, zero-pronoun subjects, nested relative clauses are not resolved | they surface in `unresolved_statements[]` (case-c: 11) |
| numeric data encoding | this arm does not paint values (no colour/size channel for tables) | use the full package for data-encoding cases |
| raster export | not produced (`exports.raster.produced=false`) | the SVG is the preview; the full package adds PNG/PDF |
| very long Chinese sentences | clause splitting is punctuation-based | long clauses can stay unresolved rather than be guessed |

Extending: append one `type|label|line|arrow|colour|en cues|zh cues|passive zh` line to `VOC`;
the legend, the drawing and the `semantics.distinct` check follow automatically. Keep every
`(arrow, line)` pair unique or verification fails.
