# ECOSYSTEM.md · 别人怎么复用（一页）

## 1. 30 秒上手

```bash
# 平台形态：/input/case.json -> /app/output
python3 scripts/run.py
# 本地形态
python3 scripts/run.py --case examples/case_zh_md/case.json --out out --work work
python3 scripts/audit_deck.py --out out --case examples/case_zh_md/case.json   # 只读产物复查
```

依赖：`python-pptx`（必需）、`Pillow`（可选，图提取/模型预览）、`lxml`（随 python-pptx）。不联网、不调用模型。

## 2. 可复用的资源（拿来即用 / 拿来即改）

| 资源 | 形态 | 复用方式 |
|---|---|---|
| `templates/slide-plan.template.json` | 页级大纲模板 | 改 `slides[]` 即为自己的汇报骨架；`outline.py` 直接吃 |
| `references/03-output-contract.md` | 结果契约字段表与四种契约形态 | 作为 `case.json.output_contract` 的骨架 |
| `templates/template-spec.example.json` | 声明式模板 spec | `python3 scripts/template_build.py --spec <spec> --out t.pptx` 现场合成母版 |
| `examples/case_zh_md` `case_latex` `case_en_pdf` | 三种材料形态（MD+模板 / TeX+bib / PDF） | **示例（非正式答案）**，只演示接口；替换材料即自己的案例 |
| `references/01-deck-blueprint.md` | 页级骨架与信息分层规则 | 直接作为写作规范给组内同学 |
| `references/03-output-contract.md` | `result.json` 字段表 + 路径解析/守卫规则 | 接别人下游系统时按此对齐字段 |
| `scripts/rigor.py` | 单条证据复核器 | 任何「论文结论→页面」的流程都能用它复证一句话 |
| `scripts/audit_deck.py` | 产出物独立审计器（A1–A8） | 也可用来审别人交付的 pptx + result.json |
| `scripts/benchmark_local.py` + `tests/benchmark-report.json` | 真实两臂对照 | 换成自己的基线实现即可对照 |
| `tests/gain_cases.json` + `scripts/gain_check.py` | 带标签判定案例 | 加一个 case 就能回归「证据锁是否还抓得住造假」 |

## 3. 迁移到自己的题

1. 复制 `templates/slide-plan.template.json` → 改 role 序列与页数上限 → 跑 `run.py` 看 `plan.json`；
2. 换 `examples/` 里的材料（PDF/MD/TeX 皆可）与 `output_contract`；
3. 若单位/指标名特殊：在 `inventory.py` 的 `U`（单位词表）/`NORM`（归一化）里加词，G1 立即生效；
4. 若模板是单位的 `.pptx`：把 `template` 写进 `case.json`（相对 `case.json` 解析），版式与配色随模板走；
5. 交付前跑三件：`selftest.py`、`audit_deck.py --out`、`rigor.py --all`。

## 4. 边界与维护

- **明确不做**：论文结论生成、科研绘图与美化、写作润色、LaTeX/.docx 直接解析、PDF 内嵌图抽取、扫描件 OCR。
- 渲染优先 `soffice`，无则 Windows PowerPoint COM，都没有则**标注清楚**的模型预览（`render.preview_mode` 不改口径）。
- 维护信息：`SKILL.md` 写用途/输入输出/异常处理；`METHOD.md` 写方法与判据；`RUBRIC.md` 是一张「哪条判据由哪个文件+命令证明」的总表；
  回归面：`tests/selftest.py`（9 项）、`tests/gain_cases.json`（4 例）、`tests/benchmark_local.py`（两臂）。
- 已知边界（如实）：字体依赖宿主机；PDF 段落切分是启发式的；无 office 的机器上预览形态会降级并在 `uncertainty` 说明。
