# BENCHMARK（1 页）· 真实 baseline vs Skill，可复跑

同一份示例材料、同一 `slide_count=8`、同一台机器，两条路径各**真跑 1 次**；两条臂都用**同一组函数**
从各自产出的 `.pptx` 反算指标。复跑：`python3 tests/bench.py --report benchmark.json`
（数字由 `benchmark.json` 给出，生成逻辑在 `tests/bench.py`，不含手填值）。

| 指标 | baseline | skill | Δ |
|---|---:|---:|---:|
| 页数 / 页数=指令 | 8 / ✓ | 8 / ✓ | 0 |
| 页级证据覆盖 | 0.000 | **0.857** | **+0.857** |
| 来源页脚覆盖 | 0.000 | **1.000** | **+1.000** |
| 锚点句在材料中逐字存在 | 0.000（无锚点） | **1.000** | **+1.000** |
| 机检失败项 | 2（C08 无标题/备注/正文、C11 无锚点） | **0** | **−2** |
| 端到端耗时 s | 0.52 | 8.41 | +7.89 |

- **结论**：Skill 的价值全在**可核验**——证据锚点 0 → 0.86（8 页里 7 页是内容/路线页，封面不计，
  属真实值）、页脚 1.0、锚点句逐字存活 1.0；baseline 这三项都是 0，并留下 2 个机检失败项。
  页数两项打平，如实记录，不编造优势。
- **代价**：每例多约 9.5 秒（解析 PDF、生成、真实渲染 PDF+PNG、16 项机检、版本与产物落盘），900 秒预算内可接受。
- **局限**（同时写进 `benchmark.json.limitations`）：baseline 是**一个**诚实的极简实现（等分粘贴），
  不是调优竞品；单次计时、宿主相关；示例材料为合成文本（无图表/扫描页）；
  `failed_mechanical_checks` 复用 `scripts/verify.py`（溢出为估算口径，导出件为字节级重测）；
  `sentence_integrity` 只统计带锚点的要点，因此没有锚点的 deck 结构性地得 0。

## 机检不是空转：逐项覆盖矩阵（真实篡改 → 逐项变红）

`tests/lead-audit-report.json` 里保存了完整的命令与原始结果。做法：拿一份**通过**的 deck，
一次只改一处，然后重跑 `scripts/verify.py`，看对应 id 是否变红。

| id | 篡改 | 结果 |
|---|---|---|
| C01 | case 要求多一页 | C01 fail |
| C02 | case 把上限压到 4 页 | C02 fail |
| C03 | 正文框移出画布 | C03 fail |
| C04 | 正文框压到 0.2 in | C04 fail |
| C05 | 叠加一个重复正文框 | C05 fail |
| C06 | 表格列宽放大 4 倍 | C06 fail |
| C07 | 图片纵向拉 1.6 倍 | C07 fail |
| C08 | 去掉某页标题与备注 | C08 fail（同页失去锚点，C11 也 fail） |
| C09 | 正文字号改 7 pt | C09 fail |
| C10 | 换一份 4:3 无关模板当基线 | C10 fail |
| C11 | 保留正文、删掉全部锚点 | C11 fail |
| C12 | 换成编造句但保留真实引文 | C12 fail |
| C13 | 把一个数字改一位 | C13 fail |
| C14 | 预览 PDF 截成 1 页 | C14 fail |
| C15 | 真图换成 1×1 白图 / 全部预览换成纯白 | C15 fail |
| C16 | 把契约 `case_id` 改成别的值 / 把 `task.md` 推进 `sources[]` | C16 fail |

同一套篡改跑在父臂/对照臂上：`pkg-min2` 只覆盖 C02（其余 id 在它那里不存在或读的是内存页计划，
C12/C13 全绿）；`pkg-min4` 覆盖 C01–C10 但 **C11/C12/C13 全绿**；`pkg-adv1` 覆盖 C01–C15 但
**C08 空壳页 / C15 纯白预览 / C16 契约污染全绿**（这正是 QA-round-20261124 抓到的三条）。
未被篡改的表格/图片 deck 在 adv2 上仍是 0 失败（矩阵里的 `C01-aux` 行），说明不是把检查写成常红。

## 引文语料污染实测（哨兵法）

把 `SENTINELJUNKTEXT4417` 塞进 `task.md`、`case.json`、`*.example.json`、`*.template.json`，
材料做成比工单更大的 `.md`，再跑主命令：

| 臂 | 实际语料 | 非材料文件进引文索引 | 产物中哨兵次数 | 运行存活 |
|---|---|---|---:|---|
| `pkg-min2` | 未产出（`spec.template.json` 被当成页计划 → `AttributeError: 'str' object has no attribute 'get'` 崩溃） | — | — | 否 |
| `pkg-min4` | **`task.md`（工单）** | `sources[] = ["task.md"]` | source.json 1 次 | 否（同样崩溃，只留 partial） |
| `pkg-adv1` | `paper-fulltext.md` | 无（`task.md`、`spec.template.json` 被拒并记录原因） | **全 0** | 是（`status=success`） |

结论：父臂的「引文逐字真实性 / 数字保真」在真实 `/input` 布局下会**拿工单自证**，属结构性假绿；
adv1 用证据边界（`evidence_ok`）+ 形状校验（`usable_spec/usable_ops/usable_pptx`）+ 校验器第二道防线
（`corpus_verdict`）堵住，并有负向对照证明它不是空转。
