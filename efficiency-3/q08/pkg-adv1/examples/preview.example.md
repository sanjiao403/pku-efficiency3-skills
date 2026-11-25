# 示例预览（文本版）· **示意，非正式案例结果**

> 真实的 PDF/PNG 渲染预览由 `scripts/render_preview.py` 在**运行现场**产出，落在
> `<out>/preview/deck.pdf` 与 `<out>/preview/png/slide-NN.png`（不在提交包内，避免撑爆 ≤50 文件 / ≤2MB 限制）。
> 下面是同一次运行的文本化预览（每页标题 + 正文首行 + 页脚/页码形态），用于说明"导出件长什么样"。

```
[第 1 页] role=title   layout=Title Slide
  标题：<源材料标题，逐字，超长按小句边界截断并补省略号>
  副标题：<venue / EXAMPLE-001>
  元信息行：听众：… | 时长：10 分钟 | 材料：paper.md
  （封面无页脚/页码）

[第 2 页] role=agenda  layout=Title and Content
  标题：提纲 / Outline
  · <章节标题1>（kind=nav，只做导航，不做引文回源）
  · <章节标题2>
  页脚：EXAMPLE（示意，非正式案例结果）            页码：2（可编辑域 a:fld type="slidenum"）

[第 3 页] role=figure  layout=Two Content   ← 左栏文字 / 右栏图
  标题：<结果章节标题>
  主张：<含数值的逐字断言>
  · <证据句 1>   ← §3.2 ¶1
  · <证据句 2>   ← §3.2 ¶2
  [图] Figure 1 <与源材料一致的图注>   ← 等比放置，宽高比偏差 0.000%
  页脚：…            页码：3

[第 4 页] role=closing layout=Title Slide
  标题：谢谢 / Q&A
  （讲稿备注里有复跑命令与证据定位）
```

查看完整可编辑产物与真实预览：`python scripts/run.py --input examples/case.example.json \
--out <你的目录> --backend auto`，然后打开 `<你的目录>/preview/deck.pdf`。
