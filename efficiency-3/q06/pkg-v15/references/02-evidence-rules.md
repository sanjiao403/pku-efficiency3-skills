# 02 · 证据规则（四道硬闸 + 逐条重证）

一切「页面上的断言」都必须能在材料里找到；找不到就写 `evidence_absent_reason`，**不编**。

## 1. 四道硬闸（`plan_validate.py`，生成期）

| 闸 | 判什么 | 怎么判 | 违反时 |
|---|---|---|---|
| **G1 数值** | 页面上每个数值+单位是否在材料里 | `inventory.numbers[]` 存 `{value, unit_norm}`；`verify_value(inv, raw, unit)` 要求**值相等且单位一致** | `NUMBER_NOT_IN_SOURCE`（error）→ `status=partial` |
| **G2 图/表号** | `Figure N` / `Table N` 是否存在 | 材料里要有同名 caption（`inv.captions[]`） | `REF_NOT_IN_SOURCE`（error） |
| **G3 引文** | 每段 `evidence.quote` 是否逐字可定位 | `src.quote_locator(quote)` 在**重新抽取的**材料里查找（允许换行/空白归一化） | `QUOTE_NOT_FOUND`（error） |
| **G4 定位** | 每个内容页是否有 locator | `evidence[].locator` 或 `evidence_absent_reason` 二者必有其一 | `EVIDENCE_MISSING`（error） |

单位口径：`3.7 °C` 与 `3.7 kg` 不是一回事；`R2 = 0.86` 这类指标名会被识别为 metric 而不是单位。
归一化表 `inventory.NORM`（`℃→°c`、`r2→r²`、`hours→h`…）保证大小写/全角差异不误报。

**逐字段判定（v15 起）**：G1/G2 在 `plan_validate._page_fields()` 给出的**独立字段**上扫描。
把多个字段拼成一个字符串会让相邻字段**融合**出材料里不存在的数值-单位对
（页面同时有 `12` 与 `R2 = 0.86` 时拼接出 `12 R2`），那是假阳性，不是页面在断言。
`rigor_report`、`audit_deck.deck_facts()['blocks']`、`benchmark_local.measure()` 同口径。

## 2. 逐条重证（`rigor.py`，与生成器无关）

生成期把每条结论变成一个**可在 shell 直接运行**的命令：

```bash
python3 scripts/rigor.py --case examples/case_zh_md/case.json --item number:11.1:%
python3 scripts/rigor.py --case examples/case_zh_md/case.json --all          # 走完整台账
python3 scripts/rigor.py --case A/case.json --case B/case.json --all \
        --report reports/rigor-report.json                                   # 随包机读报告
```

`rigor.py` 不用 `plan_validate` 的中间结果：它**重新解压/读取材料**再查找，所以计划层的错
藏不住。退出码 `0`=全部命中、`1`=有未命中、`2`=材料读不了。随包报告见 `reports/rigor-report.json`
（三案例 162/162 项）。

## 3. 产出物独立审计（`audit_deck.py`）

只读 `deck.pptx` + `result.json` + 案例材料，**不读** `plan.json`/`inventory.json`/`validation.json`/`layout.json`：
A1 契约字段非空 → A2 `outputs[]` 的 bytes/sha256 → A3 页数一致且 1..上限 → A4 pptx 上的数字/图号在材料里
→ A5 每页有已核实 locator 或声明的「不可推导」→ A6 备注非空且 4-gram ≤0.34 → A7 无越界/字号 ≥11pt
→ A8 `status` 与结论自洽。三案例 8/8（`reports/audit-report.json`）。

## 4. 带标签判定案例（`tests/gain_cases.json` + `scripts/gain_check.py`）

| 案例 | 期望 | 实测 |
|---|---|---|
| `grounded` | 0 error、rigor 全命中 | 0 code |
| `fabricated_number`（3.7→4.2 degC） | `NUMBER_NOT_IN_SOURCE` + rigor 查不到 | 命中 |
| `fabricated_figure_ref`（引用 Figure 7） | `REF_NOT_IN_SOURCE` + rigor 查不到 | 命中 |
| `fabricated_quote`（改写句冒充原文） | `QUOTE_NOT_FOUND` + rigor 查不到 | 命中 |

判定器只调用 `plan_validate` + `rigor`，不读生成器自评；4/4 与标注一致（`tests/gain-report.json`）。
