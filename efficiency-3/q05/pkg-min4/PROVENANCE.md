# PROVENANCE · 来源可追（一页）

一句话：**图上每一个图元都能指回原文的一行**；指不回原文的东西，不画；画了没记账也不行。

## 1. 三本账：IR / SVG / result.json
| 账本 | 关键字段 | 谁核对 |
|-|-|-|
| `figure.ir.json` | `elements[].source{locator,quote}`、`relations[].source{…}`、`extraction_index[]` | `validate_ir.py`（结构）+ `check_consistency.py`（逐字回溯） |
| `figures/figure.svg` | 每块 `data-role`/`data-node`/`data-kind`/`data-quote`/`data-src`；连线 `data-fid`/`data-flow`/`data-from`/`data-to` | `check_consistency.py`（id 集合、引文覆盖、箭头几何） |
| `result.json` | `sources[]`、`provenance`、`outputs[{path,bytes,sha256}]`、`checks.ir` / `checks.consistency` | `check_consistency.py`（哈希、与 IR 同源、状态诚实） |

## 2. 定位符与引文
* `source.locator` = `文件名#Lnn`（表格/整行）或 `文件名#Lnn-mm`（段落块）；`data-src` 里 `#` 序列化为 `@`。
* `source.quote` **必须逐字**来自材料：校验时对双方做空白归一化（含软连字符、弯引号），
  归一化后必须能在材料文本中找到，否则硬失败（`source.quotes_verbatim`）。
* 本包用 `locator` 这个键名（不是 `location`），与 `result.json.sources[].path` 同一键义。

## 3. 覆盖索引：既防无中生有，也防漏画
`extraction_index[]` 把材料里读到的**每个**部件/步骤/阶段登记一条：
```json
{"mention": "蠕动泵 Peristaltic pump", "quote": "| 蠕动泵 Peristaltic pump | P-1 | 1 |", "mapped_id": "U2"}
{"mention": "废液收集瓶", "quote": "…", "status": "omitted", "reason": "超出装置面板容量（最多 12 个）"}
```
* `validate_ir.py`：omitted 必须写 reason；mapped_id 必须指向真图元。
* `check_consistency.py`：**反向**再查一遍——每个画出来的图元都必须在索引里出现（`coverage.every_element_in_index`），
  索引里每条提及也必须有归宿（`coverage.index_maps_every_mention`）。

## 4. 指代不明 → 不画，只记录
同一称呼在一句里对应多个具名单元时，该句**不产生连线**，改写入 `uncertainty[]` 与
`provenance.ambiguities[]`（原句、别名、候选、处置）。宁可少一条线，不错一条线。

## 5. 数字来源硬规则
图上每个数字都必须能由材料、图元序号或画布尺寸解释（`provenance.no_invented_numbers`，硬）。
反例实测：`tests/gain_cases.json → probe-fabricated-number`（材料无任何数值，塞一个 `42` 后
`consistency_ok` 由 `true` 翻 `false`）。

## 6. 自己查（两条命令，只读）
```bash
python3 scripts/validate_ir.py --ir <out>/figure.ir.json
python3 scripts/check_consistency.py --ir <out>/figure.ir.json --materials <case_dir> \
        --svg <out>/figures/figure.svg --result <out>/result.json
```
第一条的 `provenance` 相关项与第二条的 `source.quotes_verbatim` / `coverage.*` / `provenance.*`
就是这套来源体系的守门人；`result.json.provenance.trace_ok/trace_total` 给出可追条数（实体+步骤+阶段）。

## 7. 不做什么
不把"文中出现过的词"当图元；不替材料补来源；不因为某个图元好看就保留——**没有引文就没有图元**；
画了却不登记进覆盖索引，同样判失败。
