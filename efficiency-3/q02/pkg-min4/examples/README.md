# Examples — 按案组织的最小示例（全部标「示例（非正式答案）」）

> **本目录所有内容是「示例（非正式答案）」。** 材料是**合成**的（p53/MDM2 课本式简化回路），
> 不对应任何真实论文，**不得当作科学数据或正式案例结果引用**。

## `case-01/` — 机制图 + 数据编码，**不需要任何 figure_spec**

| 文件 | 角色 |
|-|-|
| `case-01/case.json` | **输入**：`case_id` + `material_dir`（**刻意不声明 `figure_spec`**，证明纯启发式可跑） |
| `case-01/materials/m01.md` | **材料**：合成回路文字，每句一个判决关系（供启发式抽实体/关系）+ 两行表达量句子 |
| （运行产出） | **中间产物**：`figure.svg`（分层可编辑）+ `result.json`（28 键）；**不随包**（体积预算），一条命令即可再生 |

`case-01` 展示：从材料抽出 **6 实体 / 4 关系**、逐字引文核验 **10/10**、
并在同一个图里给出数据条带（把下面的 CSV 放进 `materials/` 即自动编码）。

## 最小调用示例（复制即用，`<P>` = 本包路径）

```bash
# 1. 主命令：零附加参数，材料与推导全自动
python3 <P>/scripts/schematic.py --case <P>/examples/case-01/case.json --out /tmp/o1
#    期望：exit 0，result.json.status = success，metrics.entities+relations+data_marks > 0

# 2. 只读复核（不写任何产物）：契约/来源/图例/几何
python3 <P>/scripts/verify.py --result /tmp/o1/result.json --case <P>/examples/case-01/case.json
#    期望：exit 0，末行 VERIFY_OK

# 3. 数据编码（把 CSV 放进材料目录即被自动发现并推断列角色）
mkdir -p /tmp/d/materials && cp <P>/examples/case-01/materials/m01.md /tmp/d/materials/
printf 'timepoint,gene,relative_expression,sd\ncontrol,CDKN1A,1.0,0.2\n24 h,CDKN1A,2.4,0.3\n48 h,CDKN1A,3.1,0.35\ncontrol,MDM2,1.0,0.2\n24 h,MDM2,1.8,0.25\n48 h,MDM2,1.5,0.2\n' \
  > /tmp/d/materials/d01.csv
printf '{"case_id":"demo","material_dir":"materials"}' > /tmp/d/case.json
python3 <P>/scripts/schematic.py --case /tmp/d/case.json --out /tmp/o3
#    期望：exit 0，data_mapping = timepoint/gene/relative_expression/sd，data_marks = 6
```


|-|-|

## 文件清单（sha256 见 `examples/CHECKSUMS.md`… 本包受 ≤14 文件预算限制，清单直接列在这里）

| 文件 | 说明 |
|-|-|
| `case-01/case.json` | 输入封装（无 spec） |
| `case-01/materials/m01.md` | 合成材料（示例） |

  runtime artifacts 单独保留），且再生只需上面第 1 条命令；
