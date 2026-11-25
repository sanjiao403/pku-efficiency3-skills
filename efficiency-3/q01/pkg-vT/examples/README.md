# examples/ · 三个自带示例案例（全部标「示例」）

> **这些是 skill 自带的示例输入，不是组织方 3 个固定案例，也不含任何正式案例答案。**
> 用途：说明接口、演示三种输入类型、给 `tests/selftest.py` 提供可复现夹具。

| 案例 | 输入类型 | 演示能力 | 夹具 IR |
|-|-|-|-|
| `case-a-mechanism/` | 纯文本机制材料（md）| 实体/关系抽取、关系语法箭头、数值编码带、四拍版式 | `figure-ir.example.json` |
| `case-b-results/` | 文本 + 源数据表（md + csv）| 真实数据编码：柱 + 误差线 + 单位 + 图例；数据点级 locator | `figure-ir.example.json` |
| `case-c-edit/` | 已有可编辑 SVG（+ 修改工单）| 保源编辑：只改点名元素、其余字节不变、记原图指纹 | `edit-ops.example.json` |

每个案例还含 `expected-shape.example.json`：只声明**应满足的结构与检查项**（面板角色、最少实体/关系数、
图例与分类一致、导出验真），不含任何正式案例的实体名或数值。

每个案例目录内容：

```
case-a-mechanism/
├── case.json                  # 示例输入契约（含 output_contract / canvas / expected_figure）
├── material.md                # 示例科研材料
└── figure-ir.example.json     # 示例 IR：Agent 照它写自己的 /app/work/figure-ir.json
case-b-results/  ├── measurements.csv（4 行 × 7 列真实源数据）
case-c-edit/     ├── source-figure.svg（示例可编辑源）+ edit-ops.example.json
sample-output/   └── 一次真实运行的文本产物（见该目录 README；位图预览移出包外，见 runs/）
```

## 怎么用这三个示例

```bash
python3 scripts/ga_build.py init --input examples/case-a-mechanism --work /tmp/w --output /tmp/o
cp examples/case-a-mechanism/figure-ir.example.json /tmp/w/figure-ir.json   # 正式案例里这一步是你自己写
python3 scripts/ga_build.py build --input examples/case-a-mechanism --work /tmp/w --output /tmp/o
```

正式评测时**不要**复制示例 IR 充当答案：组织方案例的材料不同，`check` 的引文命中会直接暴露
（示例 IR 的 `quote` 只存在于示例材料里）。

## 示例与正式案例的边界（自查）

- 示例材料中的实体（STING / DHHC3 / IFN-beta 等）与数值都是为演示编写的，不是任何正式案例的内容。
- 示例 IR 只演示"字段怎么写、证据怎么挂"，不演示"某个正式案例该怎么画"。
- 若正式案例材料与示例重合，仍必须以 `/input` 实际文件为准重新抽取并重新写 quote。

