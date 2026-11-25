# 示例材料 C（示例，非正式案例结果）

> 自带**示例输入**，演示"在已有可编辑 SVG 上做保源修改"的调用方式。
> 非组织方固定案例，不含正式案例答案。

## 1 Existing figure

`source-figure.svg` is the current first draft of the mechanism panel produced by a
colleague. It is editable (real `<text>`, named elements) but two things are wrong:

1. the label `ER retention` on element `box-2-label` should read `ER exit`;
2. the highlight colour of element `box-3` is off-palette and should use the project
   accent `#0B4F8A`.

## 2 Workorder

Apply **only** those two edits, keep every other element byte-identical, and record
which element changed, its old value and the new value. Then re-export PNG and PDF
previews of the edited file.
