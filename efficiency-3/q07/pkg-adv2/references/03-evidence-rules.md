# 03 · 证据规则（evidence rules）

三条硬纪律 + 一张强度阶梯。全部由**运行期回查**（`scripts/talkplan.py` 的 `runtime_recheck()`）与
`scripts/verify.py` 的只读重算强制，不靠人眼；`verify.py` **再独立读一遍 `slide_plan.json` 与材料**核对引文，
所以它不依赖 `result.json.audit` 的自述。

## 三条硬纪律

| 纪律 | 机器怎么判 | 违反时 |
|---|---|---|
| **引文逐字** | 每页锚点的 `quote` 必须能在所标 `material` + **行号**上逐字命中（取前 40 字比对，NFKC + 空白折叠） | `result.json.audit.summary.fail > 0` → 该页不算通过；`verify.py` 的独立重查报 FAIL |
| **数字可定位** | 页面上每个数字（长度 >1）必须出现在材料文本里（不换算、不四舍五入、不新增；比对范围 = 主张 + 要点，标题不计入） | `number_traceability_rate < 100`；`verify.py` 内嵌反例 `fabricated_number` 必被 `reject` |
| **图表编号一致** | `figures[]` 必须是材料图注里出现过的编号（`Figure N / Table N / 图 N / 表 N`）；原文没给图 → 页面不写引用 | `caption_consistency_rate < 100`；材料无图时引用数必须为 0 |

## 强度阶梯（`evidence_strength`）

| 内部强度 | 本包字段 | 允许措辞 | 判据 |
|---|---|---|---|
| `strong` | `direct` | 显著/优于/提升 X（p=…） | 有统计量（`p` / `95% CI` / `n=` / `±`）**且**数字可定位 |
| `moderate` | `comparative` | 在本设置下观察到 | 有数字或图注，但无统计检验 |
| `weak` | `background` | 初步/可能/仅适用于本材料 | 仅文字论断 |

降级触发：① 原文含 hedge（may/suggest/可能/初步）→ 不得升为 `strong`；② 含强断言词但无统计量 → 降 `weak`；
③ 与画像的 `strength_cap` 取更严者；④ 单一锚点且无数字 → 最高 `moderate`。

## 锚点写法

```
"evidence": [{"kind": "section", "id": "paper.md", "page": 6,
              "section": "paper.md", "quote": "Macro F1 reaches 0.87±0.01 versus 0.83±0.02 …"}]
```

- `id` = 材料文件名；`page` = **材料行号**（本包 locator；PDF/docx 走文本层行号）；
- 跨材料分别列出（`material-zh.md:L30`、`supplementary.docx:L3`）；
- 一图一主张：一张图只支撑本页那一句结论；图上没有的数字若出现在页面，必须能在材料文字里找到，否则删。

## 可复跑的区分度证据（内嵌，无需额外文件）

```bash
python3 scripts/verify.py --gain-cases builtin
```

四个带标签案例用**同一套回查代码**判定：`grounded` → accept；`fabricated_number`（虚构 `+12.4%`）、
`fabricated_quote`（引文真实但**行号造假**）、`off_topic`（材料讲冻结注意力层、页面讲蛋白质折叠）→ 全部 reject。
每条判定都打印触发信号（`locators_verified` / `verbatim_failures` / `number_traceability` /
`caption_mismatches` / `first_failure`），所以"为什么 reject"是可核对的具体信号，不是标签自述。
加 `--out-dir <dir>` 可把同样的判定落成 `gain-cases.json`（写在 `--out-dir`，不进包）。
