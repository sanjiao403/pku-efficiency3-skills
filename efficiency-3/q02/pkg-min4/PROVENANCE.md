# PROVENANCE — 输入 → 产物的来源与版本链

本文件说明「图上的每一个东西是从哪来的、怎么被验证的、这一份产物对应哪个版本的输入」。

## 1. 链路总览

```
材料文件（md/txt/csv/…）                    case.json
        │ 逐字句子 / 表格行                      │ case_id / material_dir / figure_spec / output_contract
        ▼                                        ▼
   启发式推导：实体、关系、数据编码        ← 路径解析（case_dir → material → cwd → /input，记 resolved_from）
        │  每个实体/关系带 evidence.quote
        ▼
   figure.svg（分层可编辑）        result.json
   · 元素 id=node-n1 / edge-e1 / mark-<类别>-<系列>   · element_sources[]：locator + quote + verified_in_material
   · data-source = 材料文件；data-quote = 原句         · metrics.evidence_verify_rate（实测比率）
   · data-relation / data-glyph（tee-bar = 抑制）      · metrics.spec_sha256（模型快照指纹）
                                                     · resolved_from / run_log / change_log
```

## 2. 每个元素的来源怎么读

| 你想知道 | 字段 | 例 |
|-|-|-|
| 这个实体/关系出自哪份材料的哪一段 | `element_sources[].source` + `.locator` | `m01.md#char312` |
| 依据是哪一句（**逐字**） | `element_sources[].quote` | `MDM2 inhibits p53.` |
| 这句真的在材料里吗（脚本判定） | `element_sources[].verified_in_material` | `true`；命中次数见 `fig.provenance.csv`（若产出） |
| 相对路径到底解析到哪 | `resolved_from` | `material = case_dir/materials` |

## 3. 版本与一致性

* **模型版本**：`metrics.spec_sha256` 是产出这批文件时所用模型（含启发式推导结果）的快照指纹；
  同输入重跑应得到同一 `figure.svg`（确定性布局：无随机、无时间戳）。
* **脚本版本**：包内只有纯标准库单入口；不存在外部依赖版本漂移（无 `reportlab`/`Pillow` 依赖）。
* **材料版本**：`sources[]` 列出每个材料文件的 `rel` 与 `bytes`；`not_reported[]` 记录**没有**读的文件
  （二进制/Office 件不猜内容）。
* **契约版本**：`result.json.contract_echo` 回显 `output_contract` 的每个声明字段，
  `contract_missing_required` 列出确实无值的必填字段（**不编造**）。

## 4. 验证链（三道闸门）

| 闸门 | 谁做 | 失败时 |
|-|-|-|
| 逐字核验 | `scripts/schematic.py` 内部（`find` 在材料里查每句引文） | 查不到 ⇒ `verified_in_material=false` + warn `entity_unverified`；**一条都查不到 ⇒ 阻塞 `evidence_unverified`** |
| 语义核验 | 极性从原句重推；关系必须在固定词表内；指定列必须存在 | 阻塞 `polarity_inverted` / `relation_not_in_vocabulary` / `data_column_missing` |
| 独立重算 | `scripts/verify.py`（**只读产物**，不信任自述） | 末行 `VERIFY_FAIL`，非 0 退出；逐条列出期望与实际 |

`status` **只由** `checks.blocking.{model_errors,data_errors}` 决定：
两项为 0 ⇒ `success`；任一非 0 ⇒ `partial` + `status_reason` + `gaps`。空产物与 0 核验率都在这两项里。

## 5. 已知的来源边界（不撒谎）

1. **启发式抽取的边界**：只处理「一句一个判决关系」的写法；含糊句会落到 `unknown` 或只给 warn，
   不会被升格成确定因果；
2. **不读二进制**：PDF/DOCX/XLSX 不解析（无 OCR、不猜），一律进 `not_reported[]`；
   字形差异属预期，不影响可编辑性）；
   其他操作**阻塞拒绝**并逐条列出（`edit_order_refused`），绝不静默忽略；
