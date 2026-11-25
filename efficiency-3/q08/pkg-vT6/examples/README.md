# examples · 最小调用示例（**示例（非正式答案）**）

> 本目录只为说明接口与完整流程：`case.example.json` 是输入，`plan.example.json` 是中间计划，
> `result.example.json` 是**示意**结果（键齐全、数值已脱敏为占位/截断示例）。
> **它不是平台 3 个固定案例的答案，也不是任何真实运行结果**；真实结果由
> `python scripts/run.py --input <case.json> --out <out>` 在评测环境现场生成。

## 一次调用

```bash
# 1) 直接用示例输入跑（示例里的 source 指 tests/fixtures/f1/paper.md，便于你立刻看到产出）
python scripts/run.py \
  --input examples/case.example.json \
  --out   /tmp/q08-example \
  --backend auto

# 2) 或先改文案再成册
cp /tmp/q08-example/slide_plan.json /tmp/my_plan.json
#    改 title / claim / bullets 的 text（保持 locator 与 quote 一致）
python scripts/plan_deck.py --case examples/case.example.json \
  --source-map /tmp/q08-example/source_map.json \
  --template-map /tmp/q08-example/template_map.json --validate /tmp/my_plan.json
python scripts/run.py --input examples/case.example.json --out /tmp/q08-example --plan /tmp/my_plan.json
```

## 文件

| 文件 | 说明 |
|---|---|
| `case.example.json` | 最小输入：source + template + 页数约束 + 一个 figure_spec + output_contract |
| `plan.example.json` | 中间计划骨架（页角色、主张、bullet+locator、字号预算）——**示意** |
| `result.example.json` | 结果骨架（键与取值形态）——**示意，非正式结果** |
| `preview.example.md` | 文本化预览（每页标题/正文/页脚页码形态）——**示意**；真实 PDF/PNG 由运行时产出到 `<out>/preview/` |

真实产物的字段含义见 `../templates/result.template.json` 与 `../README.md` §3。
