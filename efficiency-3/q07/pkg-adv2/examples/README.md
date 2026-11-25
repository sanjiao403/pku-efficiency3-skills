# examples · 示例（**示例（非正式答案）**）

> 本目录所有文件都是**示例**：材料是合成的、结论不是任何真实研究，也不代表组织方固定案例的结果。
> `case.example.json` 带 `"_example": true`；`paper.example.md` 首行标注"示例材料（合成）"；
> `result.example.json` 是从这份**合成示例**真实跑出来的 `result.json` 形状摘录，**示意输出，不是正式案例答案**。

| 文件 | 用途 |
|---|---|
| `case.example.json` | 输入：6 分钟组会汇报（8 页目标）、动态契约字段 |
| `paper.example.md` | 示例材料：中文论文节选（问题/方法/数据与设置/结果含图注与 p 值/局限/下一步） |
| `result.example.json` | **示意输出**：`result.json` 的形状与字段来源（数值来自本示例的真实运行） |

## 复跑

```bash
cd <pkg>
python3 scripts/talkplan.py --case examples/case.example.json --out /tmp/o --work /tmp/w
python3 scripts/verify.py   --case examples/case.example.json --out /tmp/o --input examples
python3 scripts/verify.py   --refcheck                    # 核对包内引用全部存在
python3 scripts/verify.py   --gain-cases builtin          # 4 个带标签反例（grounded/fabricated_number/fabricated_quote/off_topic）
python3 scripts/talkplan.py --case examples/case.example.json --out /tmp/o2 --benchmark   # baseline vs skill + copy_probe
```

产物落在 `/tmp/o`：`slide_plan.json`（先写，按包内 schema 实校）→ `deck.pptx` → `outline.json` /
`speaker-notes.md` / `result.json`。二进制只在运行期产生，本包不携带。
