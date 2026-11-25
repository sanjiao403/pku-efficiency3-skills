# 示例输出（示例，非正式案例结果）

> 本目录是一次真实运行的文本产物，供人直接查看"交付长什么样"。
> **它对应 `examples/case-a-mechanism` 这个自带示例案例**，不是组织方 3 个固定案例的答案。
> 本包**只允许 UTF-8 文本文件**：渲染出的位图/PDF 预览不放在包内，见下。

| 文件 | 说明 |
|-|-|
| `figure.example.svg` | 可编辑源文件（文本）：8 个语义图层、74 个真实 `<text>`，图元 id 与 `result.example.json` 的 `content_map` 一一对应。**用它替代位图预览**：浏览器/Inkscape 打开即可看到成品。 |
| `result.example.json` | 该次运行的完整 `result.json`：七字段契约 + `content_map` + `compliance_checks` + `exceptions`；其中 `export_artifact.png` 记录了渲染成功的**文字证据**（引擎、IHDR 宽高、dpi、非白像素比例、逐级引擎尝试）。 |

## 渲染件放在哪里

渲染出的 `figure.png` / `figure.pdf` 属于**运行产物**，按纪律放在包外：
`questions/q01/runs/example-a-mechanism/`（含全尺寸 `figure.png` 2400×1350@300dpi、矢量 `figure.pdf`、
中间 `figure-ir.json` 与 `run.log`），另有一张 1200×675 缩略预览 `runs/preview-example-a/figure.preview.1200x675.png`。

## 复现方式（在本包根目录）

```bash
python3 scripts/ga_build.py init  --input examples/case-a-mechanism --work /tmp/w --output /tmp/o
cp examples/case-a-mechanism/figure-ir.example.json /tmp/w/figure-ir.json
python3 scripts/ga_build.py check     --input examples/case-a-mechanism --work /tmp/w --output /tmp/o
python3 scripts/ga_build.py build     --input examples/case-a-mechanism --work /tmp/w --output /tmp/o --fast
python3 scripts/ga_build.py selfcheck --input examples/case-a-mechanism --work /tmp/w --output /tmp/o
```

约定：`status=ok` 表示 IR 经撰写、引文 100% 命中、四要素齐、导出验真通过；
`exceptions` 中的"版式自动修复"是预期行为（关系列标签按栏宽自适应）。
