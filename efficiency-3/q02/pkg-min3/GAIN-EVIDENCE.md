# GAIN-EVIDENCE — 原始实测数字、探针与字段路径

本文件是 `GAIN.md` 的**原始数据页**。每个数字都来自 2026-11-22 对本包的真实运行；
凡未实测的一律不写。命令中的 `<P>` = 本包路径，`<T>` = 任意临时目录。

## 1. 主命令实测（`python3 <P>/scripts/schematic.py --case <case> --out <T>/o`）

| case | rc | status | 元素 | 实体/关系/数据标记 | 引文核验 | SVG B | `data-source` | `tee-bar` | `<text>` | result 键 | 契约回显 | 阻塞 |
|-|-|-|-|-|-|-|-|-|-|-|-|-|
| `examples/case.example.json`（启发式，无 spec） | 0 | **success** | **16** | 6/4/6 | **10/10** | — | — | — | — | 28 | — | {0,0} |
| `pkg-vT2/.../case-01`（机制，11 实体/11 关系） | 0 | **success** | **22** | 11/11/0 | **22/22** | 11,087 | **23** | **3** | 15 | 28 | 10/10 | {0,0} |
| `pkg-vT2/.../case-02`（数据图，3 类别×2 系列） | 0 | **success** | **6** | 0/0/**6** | **3/3** | — | — | — | — | 28 | — | {0,0} |
| `pkg-vT2/.../case-03`（编辑单含不支持操作） | 2 | **partial** | **22** | 11/11/0 | **22/22** | — | — | — | — | 28 | 10/10 | **{1,0}** ← `edit_order_refused`（如实拒绝，不是静默忽略） |

字段路径：`status`/`summary` → `result.json`；元素计数 → `metrics.{entities,relations,data_marks}`；
引文 → `metrics.{evidence_verified,evidence_quotes}` 与 `element_sources[].verified_in_material`；
阻塞 → `checks.blocking.{model_errors,data_errors}`；契约 → `contract_echo` / `contract_missing_required`（`[]`）。

## 2. baseline 对照（不使用 Skill，脚本不随包）

| 指标 | baseline 实测 | skill 实测（case-01） |
|-|-|-|
| `figure.svg` 字节 | 2,175 | 11,087 |
| `<text>` 元素 | 11 | 15 |
| `data-source` 属性 | **0** | **23** |
| 命名图层 | 0 | 4 |
| 元素 `id` | 0 | 22 |
| 抑制的 T 形横杠 | **0**（11 条关系全部画成箭头） | **2**（+1 图例样例） |
| `result.json` | **不存在** | 28 键，**10/10** 契约字段，`blocking={0,0}` |
| `element_sources` / 核验通过 | **0** / 0 | **22** / **22** |

## 3. 纯启发式实测（**不依赖任何外部 spec**）

| 场景 | 构造 | rc | status | 结果 |
|-|-|-|-|-|
| 材料抽实体/关系 | 把 `figure_spec` 从 case 里删掉 | 0 | **success** | 16 元素（6 实体/4 关系/**6 数据标记**），引文 **10/10**，`run_log.spec_source = mined draft` |
| 只给一个 CSV | `case.json` 仅 `case_id` + `material_dir`，目录里只有 `d01.example.csv` | 0 | **success** | **6 数据标记**，3 类别 × 2 系列，自动推断列映射 `category=timepoint, series=gene, value=relative_expression, error=sd` |

字段路径：列映射 → `data_mapping.{category_column,series_column,value_column,error_column}`；
模型来源 → `run_log.spec_source`；路径来源 → `resolved_from.{material,spec_source}`。

## 4. 探针实测（与 cwd / 路径 / 空产物有关的硬证据）

| 探针 | 命令要点 | 实测 |
|-|-|-|
| cwd 无关性 | 在**无关目录**用**绝对** `--case`/`--out` | rc=0 **success** 16 元素，`resolved_from.material = case_dir/materials`，`spec_source = mined draft` |
| copy probe | 整包拷到 `<T>/probe/runs/q02-fire/stage/outputs/` 后从无关 cwd 跑 | rc=0 **success** 16 元素，readable 材料 **2**，`material_from = case_dir/materials`（输入未被吞） |
| 纯散文材料守卫 | 材料只有天气散文 | rc=2 **partial**，`gaps=[everything]`，**无 traceback** |
| 空/不可用模型守卫 | 传入 `{"figure_type":"mechanism"}`（无节点无表） | rc=2 **partial**，**result.json 仍被写出**，无 traceback |
| 独立重算（R3） | `python3 <P>/scripts/verify.py --result <T>/o/result.json --case <case> --quiet` | rc=0，末行 **`VERIFY_OK`**（`checked: 19 pass, 0 fail, 1 note`） |

## 5. 带标签增益案例判定矩阵（`python3 <P>/scripts/gain_check.py`）

| 标签 | 期望（运行前声明） | 实测 | 判定 |
|-|-|-|-|
| `grounded` | `success`、阻塞 0、引文全通过 | `success`、引文 **7/7**、无阻塞项 | **PASS** |
| `fabricated` | `partial`、含 `polarity_inverted`、**编造引文核验失败**、编造元素仍被列出 | `partial`、`polarity_inverted`、**1/3**（唯一真实那句通过、两句编造的失败）、3 元素全部列出 | **PASS** |
| `off_topic` | `partial`、含 `evidence_unverified`、0/3 | `partial`、`evidence_unverified`、**0/3** | **PASS** |

```bash
python3 scripts/gain_check.py --json out.json    # {"verdicts":[{label,expected,actual,pass}],"all_ok":true}
```

字段路径：判定结果 → `gain_check --json` 的 `verdicts[].{expected,actual,pass}`；
`actual` 里含 `status` / `quotes_verified` / `quotes_total` / `verified_rate` / `error_checks` / `warn_checks` / `tee_bar`。

## 6. 复跑清单（复制即用）

```bash
# 主命令 + 契约/独立重算
cd "$(mktemp -d)" && python3 <P>/scripts/schematic.py --case <P>/examples/case.example.json --out <T>/o1
python3 <P>/scripts/verify.py --result <T>/o1/result.json --case <P>/examples/case.example.json --quiet
# 纯启发式：删掉 spec
python3 <P>/scripts/schematic.py --case <T>/nospec/case.example.json --out <T>/o2
# 只给 CSV
mkdir -p <T>/csv/materials && cp <P>/examples/materials/d01.example.csv <T>/csv/materials/ \
  && printf '{"case_id":"csv-only","material_dir":"materials"}' > <T>/csv/case.json \
  && python3 <P>/scripts/schematic.py --case <T>/csv/case.json --out <T>/o3
# copy probe
cp -r <P> <T>/probe/runs/q02-fire/stage/outputs \
  && python3 <T>/probe/runs/q02-fire/stage/outputs/scripts/schematic.py \
       --case <T>/probe/runs/q02-fire/stage/outputs/examples/case.example.json --out <T>/o4
# 带标签增益判定
python3 <P>/scripts/gain_check.py
```

> 说明：受 ≤14 文件 / ≤110 KB 预算限制，本包不随附 `tests/` 与 `benchmark.json`；
> 上表的数值即由上述命令在同一交付版本上实测得到，`gain_check.py` 可随时重算第 5 节。
