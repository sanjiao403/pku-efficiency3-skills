# 数据编码 → 图例 / 单位 / 色盲灰度 规则（精简版）

一个数该画成什么，以及色觉异常与黑白打印的读者能否读回来。

## 1. 通道选择

| 数据角色 | 首选 | 禁止 |
|-|-|-|
| 连续量（mean/浓度/表达量） | 位置 + 长度（柱高） | 仅用色相深浅表示大小 |
| 分类系列（condition/treatment） | 位置分组 + 色相 | 仅靠相近明度区分 >6 系列 |
| 有序/等级（剂量 1/2/3） | 同色相顺序色阶 | 定性调色板乱序 |
| 双向变化（log2FC） | 发散色阶（0 为中点） | 彩虹色 |
| 显著性 | 符号（`*`/`ns`）+ 括号位置 | 仅靠颜色 |
| 机制关系（激活/抑制） | 箭头/bar-end 形状 + 线型 | 仅靠颜色 |

同一张图里**一个通道只编码一种含义**（色相已表示 treatment，就不能再表示显著性）。

## 2. 图例

- 系列 >1 个必须有图例；单系列不画图例，用轴标题说明。
- 图例顺序 = 绘制顺序；文本只用**系列名**：不重复轴单位、不重复分类名、互不相同。
- 两个系列颜色相同即为缺陷；颜色不同但**实际图元**颜色相同同样算冲突。
- 热图/连续色阶用 colorbar（必带单位与刻度），不进图例。
- 机制图的箭头语义需要自己的 key（激活/抑制/结合各一条）。

## 3. 单位与数量级

- 单位只出现在轴标签或 colorbar 上，用括号：`Relative mRNA expression (fold change)`。
- 无量纲白名单（不加单位、也不算缺）：`relative`、`fold change`、`ratio`、`%`、`a.u.`、`index`、`score`、`normalised`。
- 单位只从声明或列名括号/下划线后缀取（`vehicle_rfu`→`RFU`，`time_h`→`(h)`）；**不猜**没写出的单位。
- 数量级：值 ≥1e4 用 `×10^k` 或对数轴；最大/最小 >1e4 建议对数或分面；对数轴要写明是 log 且 0 值不进轴。
- 轴范围必须包含数据；刻度 3–7 个为宜。
- 误差线含义（s.d./s.e.m./95% CI）与 n 必须来自 caption/工单，不自造。

## 4. 色盲安全（CVD）

- 默认调色板 Okabe–Ito（`#0072B2,#D55E00,#009E73,#CC79A7,#E69F00,#56B4E9,#F0E442,#000000`）。
- 判定（Machado 2009 severity 1.0，sRGB→XYZ→CIELAB，CIE76 ΔE）：
  `score = min(ΔE_full, ΔE_deut, ΔE_prot)`；**≥20 ok，12–20 warn，<12 fail**。
- 红-绿对是典型反例（deuteranopia 下 ΔE 极小）：换色或加纹理。
- **不得只靠颜色编码**：系列 ≥3 时同时给填充纹理（hatch）或线型/点形差异；这也是 CVD fail 的第一修法。
- 语义色固定、跨图一致：up `#D55E00`、down `#0072B2`、unchanged `#999999`、
  activation `#009E73`、inhibition `#CC79A7`、uncertain `#E69F00`。

## 5. 灰度安全（黑白打印）

- 计算 `|ΔL*|`（CIELAB 明度差）：**≥8 ok，5–8 warn，<5 fail**。
- 整图仅靠颜色编码时，灰度 fail 直接算 fail；否则给建议（加纹理、错开明度）。
- 灰度印刷用 CIE L\* 等距的灰阶（`#000000,#5A5A5A,#9A9A9A,#D0D0D0`）或按 L\* 递增排列系列深浅。
- 检查顺序：定通道与纹理 → 挑 CVD-safe 调色板 → 看 ΔE 与 ΔL\* → 不达标就加 hatch/线型。

## 6. 落地检查（本包）

```bash
python3 scripts/chart.py --case /input/case.json --out /app/output    # 出图：单位/图例/误差线/映射
python3 scripts/verify.py --case /input/case.json --out /app/output   # 复算：值回读源表、图元存在、契约字段
```

`chart.py` 的 `checks` 覆盖 `axis_units / legend_series / value_fidelity / error_bars / export`；
`verify.py` 重新读源表逐点核对，不信任 `result.json` 的自述。
