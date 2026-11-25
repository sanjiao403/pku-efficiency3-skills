# INNOVATION — 相对基线/现成绘图工具新增了什么

## 1. 一句话差异

基线（含现成绘图库）保证「**画得出来**」；本包保证「**画之前判定对不对、画之后判定能不能投**」，
并且**判定失败时拒绝沉默**。

## 2. 新增能力（基线没有的三件事）

| 能力 | 基线 | 本包 | 证据 |
|-|-|-|-|
| **从材料直接推导图模型**（不需外部 spec） | 无：模型得由人或上游工具先写好 | 一句一关系的句式 → 实体/关系/逐字引文；关系用固定 8 词词表判定 | 删掉 `figure_spec` 仍 `success`：16 元素、引文 10/10、`run_log.spec_source=mined draft` |
| **数据表自动编码**（列角色启发式推断） | 无：列名/图例/配色要手写 | 材料目录里的 CSV/TSV 自动发现；数值列→value/error，文本列→category/series，常见列名优先 | 只给一个 CSV：`success`，6 标记 3×2，推断列映射与人工声明一致 |
| **可核验来源 + 判定真伪** | 无：图上没有任何来源信息，无法判真伪 | 每元素带 `locator`（`材料#charNNNN`）+ 逐字 `quote` + `verified_in_material`；并提供**带标签案例**让任何人对「真推导 vs 编造」做判定 | `element_sources` 22 条全部核验通过；`gain_check.py` 三例 3/3 判定正确 |

## 3. 方法改进（各自都对应一条真实缺陷）

1. **极性从引文重推**：不看模型怎么说，回到原句找关系动词（`inhibits`→inhibition…）；
   声明与原文冲突 ⇒ 阻塞 `polarity_inverted`。这是「抑制画成激活」唯一的机器拦截手段。
2. **零核验率即阻塞**：模型带引文但**一条都没在材料里找到** ⇒ `evidence_unverified`（阻塞）。
   没有这道守卫时，一份「完全离题」的答案会拿到 `success`（这是实测出来的漏洞，见 §4）。
3. **缺列不换列**：spec 指定了表里没有的列 ⇒ `data_column_missing`（阻塞）；绝不静默替换成另一列
   （换列等于画了另一个量）。
4. **空产物守卫**：实体+关系+数据标记全为 0 ⇒ `empty_figure`（阻塞），**空图永不 `success`**。
5. **异常兜底**：图构建/导出阶段任何异常 ⇒ `figure_not_drawable`（阻塞）+ **照常写出 `result.json`**，
   而不是留一个 traceback 与空目录。
6. **产物命名不得冒充模型**：发现扫描排除 `checks|result|used|edited|report|provenance|geometry|prims`
   命名的 JSON；读到不可用 JSON 时回退启发式推导（否则删掉 spec 后会「无输入」）。
7. **路径解析与 cwd 解耦**：case 声明的相对路径按 `case.json 目录 → 材料目录 → cwd → /input` 解析，
   并把来源写进 `resolved_from`。

## 4. 创新点是被实测逼出来的（可信度来源）

`scripts/gain_check.py` 的 `off_topic` 案例在**加守卫之前**跑出过 `success`（0/3 引文核验却报成功）——
即「编造的答案能被判成功」。加上 `evidence_unverified` 阻塞后，同一案例变为 `partial`。
这不是设计文档里的假设，而是**先有反例、后有守卫**：标签写死 → 运行 → 暴露漏洞 → 修 → 复跑判定通过。

## 5. 与现成绘图工具的边界

| 现成工具/基线负责 | 本包负责 |
|-|-|
| 把图元画到画布上（几何、样式、导出） | 画之前：实体/关系/方向/数值是否真的在材料里（逐字核验） |
| —— | 关系语义：抑制用 T 形横杠而不是箭头（固定词表 + 语法） |
| —— | 画之后：契约字段、证据、阻塞计数、独立重算（`verify.py`） |
| —— | 失败时的诚实降级（`partial` + `gaps`/`uncertainty`/`not_reported`） |

## 6. 复跑

```bash
python3 scripts/gain_check.py            # 3 个带标签案例，末行 GAIN_OK
python3 scripts/verify.py --result <out>/result.json --case <case>   # 末行 VERIFY_OK
```

指标原始数字见 `GAIN.md §2` 与 `GAIN-EVIDENCE.md`；来源与版本链见 `PROVENANCE.md`。
