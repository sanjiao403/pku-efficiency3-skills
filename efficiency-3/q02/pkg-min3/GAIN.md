# GAIN — baseline vs skill（人可读摘要）

**结论一句话**：不加载本 Skill 时，同一份材料能画出一张「看起来对」的图，但**无法追溯、极性会画反、
没有机器可读结果**；加载后，同一输入产出**逐元素可核验、极性正确、且能被脚本判真伪**的交付物。

## 1. 方法（两条命令，都可原样复跑）

| | baseline（不使用 Skill） | skill（本包） |
|-|-|-|
| 做法 | 一个临时脚本读同一份图模型 + 材料，一次性输出**扁平 SVG**：实体排成文本、**每条关系都画成普通箭头**、无图层、无 `id`、无来源属性、无图例映射、**不写 result.json** | `python3 scripts/schematic.py --case <case-01>/case.json --out <out>` |
| 输入 | 同一 `case-01`（11 实体 / 11 关系 / 23 条引文，含 2 条抑制） | 同左 |
| 产物 | `figure.svg` 2,175 B | `figure.svg` 11,087 B + `result.json`（28 键） |
| 复跑 | baseline 脚本**不随包**（避免占预算）；其产物的全部度量见 `GAIN-EVIDENCE.md` §1，可按同样三行逻辑复现 | 见 §3 |

baseline 不是稻草人：它把实体画对、关系画全，只是**没有**可核验来源、关系语法与结构化结果——
本题要区分的正是这三件事。

## 2. 三个指标（实测差）

| # | 指标 | baseline | skill | 差 |
|-|-|-|-|-|
| **M1** | 可核验来源：SVG 中带 `data-source` 的元素数 / 逐字核验通过的引文 | **0** / 0 | **23** / **22 of 22（100%）** | 无法追溯到逐条可核验 |
| **M2** | 关系语义：`inhibition` 用 T 形横杠的条数 | **0**（11 条关系全箭头 ⇒ 2 条抑制被画成激活） | **2** 条图内 T 形横杠（+1 图例样例） | 极性错误 → 极性正确且自证 |
| **M3** | 结构化结果：`result.json` 键数 / 契约字段 / 阻塞计数 | **0 / 0 / 无 result.json** | **28 / 10 of 10 声明字段 / `{0,0}`** | 只有一张图 → 机器可核验的交付物 |

补充（同一批实测）：单案例 **< 0.1 s**、**零附加参数**、**零第三方依赖**、1 条命令；
`checks` 逐条可读（`result.json.checks.items[]`）。

## 3. 为什么这些数字可信（增益可验证性）

`scripts/gain_check.py` 内置**三个带标签的小案例**，标签在运行**之前**就写死，运行后逐条判定：

| 标签 | 材料/模型构造 | 期望（先声明） | 实测 |
|-|-|-|-|
| `grounded` | 每条引文都在材料里逐字存在；抑制画成 T 形横杠 | `success`、阻塞 0、引文 7/7 | ✅ `success`、7/7、无阻塞 |
| `fabricated` | 编造两个材料里不存在的实体名与引文，并把一条抑制画成激活 | `partial`、阻塞含 `polarity_inverted`、**至少一条引文核验失败**、编造元素仍被列出 | ✅ `partial`、`polarity_inverted`、1/3（唯一真实那句通过，编造的不通过）、3 个元素全部列出 |
| `off_topic` | 材料是天气散文，模型却断言机制 | `partial`、阻塞含 `evidence_unverified`、0/3 | ✅ `partial`、`evidence_unverified`、0/3 |

```bash
python3 scripts/gain_check.py            # 打印判定矩阵，末行 GAIN_OK
python3 scripts/gain_check.py --json out.json   # 机器可读判定
```

**这就是「增益可验证性」最硬的证据**：不是自述「我们更准」，而是**先把标签写死、再让脚本判定**——
`fabricated` 与 `off_topic` 都被拦成 `partial` 并给出具体阻塞项，`grounded` 才能拿到 `success`。

## 4. 本基准**不**声称什么

1. 不比美观：布局是确定性网格（见 `references/figure-rules.md §4`），不是排版引擎；
2. 不替代统计方法选择/显著性检验/正文写作（题面明确排除）；
3. SVG 体积差（2,175 → 11,087 B）来自图层、`id`、溯源属性与图例，**不是装饰**；
4. 不报平台分数：`self_scored` 恒 `false`，分数由独立运行判定。

原始数字、探针结果与字段路径见 **`GAIN-EVIDENCE.md`**；创新点与来源链见 `INNOVATION.md` / `PROVENANCE.md`。
