# GAIN — baseline vs skill：摘要 + 原始实测数字

**一句话**：不加载本 Skill 时，同一份材料能画出一张「看起来对」的图，但**无法追溯、极性会画反、
没有机器可读结果**；加载后，同一输入产出**逐元素可核验、极性正确、且能被脚本判真伪**的交付物。

## 1. 方法（可复跑）

| | baseline（不使用 Skill） | skill（本包） |
|-|-|-|
| 做法 | 临时脚本读同一份图模型 + 材料，一次性输出**扁平 SVG**：实体排成文本、**每条关系都画成普通箭头**、无图层/无 `id`/无来源属性/无图例映射、**不写 result.json** | `python3 scripts/schematic.py --case <case-01>/case.json --out <out>` |
| 输入 | 同一 `case-01`（11 实体 / 11 关系 / 23 条引文，含 2 条抑制） | 同左 |
| 产物 | `figure.svg` 2,175 B | `figure.svg` 11,087 B + `result.json`（28 键） |

baseline 不是稻草人：实体画对、关系画全，只是**没有**可核验来源、关系语法与结构化结果。

## 2. 三个指标（实测差）

| # | 指标 | baseline | skill | 差 |
|-|-|-|-|-|
| **M1** | 可核验来源：带 `data-source` 的元素 / 逐字核验通过的引文 | **0** / 0 | **23** / **22 of 22（100%）** | 无法追溯 → 逐条可核验 |
| **M2** | 关系语义：`inhibition` 用 T 形横杠的条数 | **0**（11 条关系全箭头 ⇒ 2 条抑制被画成激活） | **2** 条图内横杠（+1 图例样例） | 极性错误 → 极性正确且自证 |
| **M3** | 结构化结果：`result.json` 键 / 契约字段 / 阻塞 | **0 / 0 / 无 result.json** | **28 / 10 of 10 / `{0,0}`** | 只有一张图 → 机器可核验交付物 |

## 3. 主命令实测（同一交付版本，2026-11-22）

| case | rc | status | 元素 | 实体/关系/标记 | 引文核验 | SVG B | `data-source` | 横杠 | 阻塞 |
|-|-|-|-|-|-|-|-|-|-|
| `examples/case-01/case.json`（启发式，无 spec） | 0 | **success** | **16** | 6/4/6 | **10/10** | — | — | — | {0,0} |
| `pkg-vT2/.../case-01`（机制） | 0 | **success** | **22** | 11/11/0 | **22/22** | 11,087 | 23 | 3 | {0,0} |
| `pkg-vT2/.../case-02`（数据图） | 0 | **success** | **6** | 0/0/**6** | **3/3** | — | — | — | {0,0} |
| `pkg-vT2/.../case-03`（编辑单含不支持操作） | 2 | **partial** | **22** | 11/11/0 | **22/22** | — | — | — | **{1,0}** ← `edit_order_refused` |

字段路径：状态 → `result.json.status`；元素 → `metrics.{entities,relations,data_marks}`；
引文 → `metrics.{evidence_verified,evidence_quotes}`、`element_sources[].verified_in_material`；
阻塞 → `checks.blocking.{model_errors,data_errors}`；契约 → `contract_echo` / `contract_missing_required`。


| 指标 | baseline | skill（case-01） |
|-|-|-|
| `result.json` | **不存在** | 28 键，10/10 契约，`blocking={0,0}` |

## 5. 纯启发式与守卫实测

| 场景 | 构造 | rc | status | 结果 |
|-|-|-|-|-|
| 材料抽实体/关系 | 删掉 `figure_spec` | 0 | **success** | 16 元素、引文 **10/10**、`run_log.spec_source=mined draft` |
| 只给 CSV | 目录里只有 CSV，无任何模型 | 0 | **success** | **6 标记**，3×2，列映射 `timepoint/gene/relative_expression/sd` |
| cwd 无关性 | 无关目录 + 绝对 `--case/--out` | 0 | **success** | 16 元素，`resolved_from.material=case_dir/materials` |
| copy probe | 整包拷到 `.../stage/outputs/` 再跑 | 0 | **success** | 16 元素，readable 材料 2 |
| 纯散文材料 | 材料只有散文 | 2 | **partial** | `gaps=[everything]`，无 traceback |
| 空/不可用模型 | `{"figure_type":"mechanism"}` | 2 | **partial** | **result.json 仍写出**，无 traceback |
| 独立重算 | `verify.py --result <out>/result.json --case <case>` | 0 | **`VERIFY_OK`** | `checked: 19 pass, 0 fail, 1 note` |

## 6. 带标签增益判定（`python3 scripts/gain_check.py`，3/3 = `GAIN_OK`）

| 标签 | 期望（**运行前**写死） | 实测 | 判定 |
|-|-|-|-|
| `grounded` | `success`、阻塞 0、引文全通过 | `success`、**7/7**、无阻塞 | **PASS** |
| `fabricated` | `partial`、含 `polarity_inverted`、**编造引文核验失败**、编造元素仍列出 | `partial`、`polarity_inverted`、**1/3**（真实那句通过、两句编造的失败）、3 元素全列出 | **PASS** |
| `off_topic` | `partial`、含 `evidence_unverified`、0/3 | `partial`、`evidence_unverified`、**0/3** | **PASS** |

字段路径：`gain_check --json` 的 `verdicts[].{label,expected,actual,pass}`；
`actual` 含 `status`/`quotes_verified`/`quotes_total`/`verified_rate`/`error_checks`/`warn_checks`/`tee_bar`。

## 7. 不声称什么

1. 不比美观：布局是确定性网格（`references/symbol-conventions.md §4`）；
2. 不替代统计方法选择/显著性检验/正文写作（题面明确排除）；
3. SVG 体积差来自图层、`id`、溯源属性与图例，**不是装饰**；
4. 不报平台分数：`self_scored` 恒 `false`。
