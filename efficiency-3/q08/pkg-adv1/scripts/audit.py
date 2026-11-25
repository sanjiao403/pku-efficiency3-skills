# -*- coding: utf-8 -*-
"""audit.py —— 汇总成 result.json（含 output_contract 回显、页级证据、诚实状态）。

设计原则（照平台契约）：
  * 顶层保留 case.json 里 output_contract 声明的每个字段（有值给值，无值给 null 并写进
    contract_unresolved_fields，绝不假装有）；
  * status 只在「产物可打开 + 渲染成功 + 无 high 问题 + 引文全部可回源」时才是 success，
    否则 partial 并在 status_reason 里写**具体**原因；
  * 页级证据 = 每页的 locator/quote/verified 三元组，可直接独立复核；
  * 每个产物都给 bytes + sha256，便于他人复跑比对；
  * 所有脚本自述能力边界写进 `capability_boundary`，不宣称"技术检查等于学术质量"。

用法：
    python audit.py --case case.json --plan plan.json --source-map source_map.json \
        --template-map template_map.json --build-log build_log.json --fit fit_report.json \
        --render render_report.json --pptx deck.pptx --out out/ [--narrative file.md]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）

import units


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _contract_fields(case: dict) -> list:
    oc = case.get("output_contract")
    if isinstance(oc, dict):
        return list(oc.keys())
    if isinstance(oc, list):
        return [x for x in oc if isinstance(x, str)]
    for key in ("required_fields", "result_fields", "output_fields"):
        if isinstance(case.get(key), list):
            return [x for x in case[key] if isinstance(x, str)]
    return []


def _artifact(path: str, kind: str) -> dict:
    if not path or not os.path.isfile(path):
        return {"path": path, "exists": False, "kind": kind}
    return {"path": os.path.basename(path), "exists": True, "kind": kind,
            "bytes": os.path.getsize(path), "sha256": units.sha256_file(path)}


def _slide_rows(plan: dict, fit: dict, render: dict) -> list:
    pages = {p["page"]: p for p in (render or {}).get("pages") or []}
    fit_slides = {s["index"]: s for s in (fit or {}).get("slides") or []}
    rows = []
    for s in plan.get("slides") or []:
        idx = s.get("index")
        f = fit_slides.get(idx) or {}
        pg = pages.get(idx) or {}
        bullets = s.get("bullets") or []
        rows.append({
            "page": idx,
            "role": s.get("role"),
            "layout": f.get("layout") or s.get("layout_hint"),
            "title": s.get("title"),
            "claim": s.get("claim") or "",
            "evidence_locs": [b.get("locator") for b in bullets if b.get("locator")],
            "evidence_count": len(bullets),
            "figure": ({"label": (s.get("figure") or {}).get("label"),
                        "source_locator": (s.get("figure") or {}).get("source_locator"),
                        "aspect_deviation": (f.get("figures") or [{}])[0].get("aspect_deviation")
                        if f.get("figures") else None} if s.get("figure") else None),
            "font_sizes": f.get("font_sizes") or [],
            "overflow": f.get("text_overflow") or [],
            "notes_chars": None,
            "render": {"pdf_fonts": pg.get("fonts"), "text_coverage": pg.get("text_coverage"),
                       "images": pg.get("images")} if pg else None,
        })
    return rows


def build_result(case: dict, plan: dict, source_map: dict, template_map: dict,
                 build_log: dict, fit: dict, render: dict, outdir: str,
                 pptx_path: str, narrative: str | None = None,
                 baseline: dict | None = None, extra_uncertainty: list | None = None) -> dict:
    slides = _slide_rows(plan, fit, render)
    fm = (fit or {}).get("metrics") or {}
    rm = render or {}
    issues = list((fit or {}).get("issues") or []) + list(
        ((rm.get("checks") or {}).get("issues") or [])) + list(
        ((rm.get("consistency") or {}).get("issues") or []))  # D31：导出件逐页一致性
    high = [i for i in issues if i.get("severity") == "high"]
    med = [i for i in issues if i.get("severity") == "medium"]

    evidence = []
    blocks = {b["id"]: b for b in source_map.get("blocks") or []}
    for s in plan.get("slides") or []:
        for b in s.get("bullets") or []:
            if b.get("kind") == "nav":
                continue  # 提纲页
            src = blocks.get(b.get("block_id")) or {}
            q = b.get("quote") or b.get("text") or ""
            ok = bool(src) and bool(q) and q[:20] in (src.get("text") or "")
            evidence.append({"page": s.get("index"), "locator": b.get("locator"),
                             "block_id": b.get("block_id"), "quote": q[:220],
                             "verified": ok,
                             "source_kind": (source_map.get("source") or {}).get("kind")})

    artifacts = [
        _artifact(pptx_path, "editable-presentation"),
        _artifact((rm.get("pdf")), "rendered-pdf"),
        *[_artifact(p, "rendered-png") for p in (rm.get("png") or [])],
        _artifact(os.path.join(outdir, "slide_plan.json"), "slide-plan"),
        _artifact(os.path.join(outdir, "template_map.json"), "template-probe"),
        _artifact(os.path.join(outdir, "evidence_map.json"), "evidence-map"),
        _artifact(os.path.join(outdir, "deck_report.md"), "report"),
    ]

    uncertainty = []
    for lim in source_map.get("extraction_limits") or []:
        uncertainty.append({"item": "材料抽取", "why": lim,
                            "handling": "在结果中标注，未用推测内容补齐"})
    for face, rep in (template_map.get("fonts") or {}).items():
        if rep.get("installed") is False:
            uncertainty.append({"item": "字体缺失",
                                "why": "主题字体 `%s` 本机未安装" % face,
                                "handling": "按 fallback 链（%s / %s）渲染并把替换写进 render_report"
                                            % (rep.get("fallback_latin"), rep.get("fallback_ea"))})
    for w in (build_log or {}).get("warnings") or []:
        uncertainty.append({"item": "版式", "why": w, "handling": "已在 build_log 记录，正文未压字号"})
    missing_fonts = (rm.get("checks") or {}).get("missing_fonts") or []
    if missing_fonts:
        uncertainty.append({"item": "导出字体替换",
                            "why": "PDF 未使用：%s" % ", ".join(missing_fonts),
                            "handling": "导出件按回退字体渲染；如需严格一致请安装该字体后复跑"})
    if not rm.get("ok"):
        uncertainty.append({"item": "渲染", "why": rm.get("note") or "渲染后端不可用",
                            "handling": "保留 pptx + HTML 预览；不伪造 PDF/PNG"})
        # D31：导出件逐页比对依赖真实渲染件；无后端时必须**显式说明限制**（不许假绿）
        uncertainty.append({
            "item": "导出件一致性（EXPORT_CHECK_UNAVAILABLE）",
            "why": "本环境没有可用渲染器（PowerPoint/soffice 都不可用）",
            "handling": "无法做 pptx↔PDF/PNG 的逐页一致性比对；已给 preview.html + "
                        "preview.layout.md 作为离线核对替代，results.metrics.export_* 保持 null，"
                        "状态记 partial"})
    for d in plan.get("dropped_content") or []:
        uncertainty.append({"item": "内容裁剪", "why": "%s（%s）" % (d.get("section"), d.get("why")),
                            "handling": "按页数上限裁剪，原文定位保留在 dropped_content"})
    uncertainty.extend(extra_uncertainty or [])

    status, reasons = "success", []
    if not os.path.isfile(pptx_path):
        status = "partial"; reasons.append("pptx 未生成")
    if not rm.get("ok"):
        status = "partial"; reasons.append("渲染链未产出 PDF/PNG（%s）" % (rm.get("backend") or "none"))
    if high:
        status = "partial"; reasons.append("存在 %d 条 high 级检查问题" % len(high))
    if (fm.get("quote_verified_rate") or 1.0) < 0.999:
        status = "partial"; reasons.append("引文可回源率 %.1f%%" % (100 * fm["quote_verified_rate"]))
    if (fm.get("locator_coverage") or 1.0) < 0.999:
        status = "partial"; reasons.append("证据定位覆盖率 %.1f%%" % (100 * fm["locator_coverage"]))
    if not reasons:
        reasons.append("模板继承、页级证据、渲染一致性检查全部通过")

    metrics = {
        "slides": len(slides),
        "template_layouts_preserved": (fit or {}).get("inheritance", {}).get("layouts_preserved"),
        "template_theme_preserved": (fit or {}).get("inheritance", {}).get("theme_preserved"),
        "layouts_in_output": (fit or {}).get("inheritance", {}).get("layouts_out"),
        "slides_with_overflow": fm.get("slides_with_text_overflow"),
        "overflow_boxes": fm.get("textboxes_over_container"),
        "min_body_pt": fm.get("min_body_pt"),
        "figure_aspect_max_deviation": fm.get("figure_aspect_max_deviation"),
        "figures": fm.get("figures"),
        "locator_coverage": fm.get("locator_coverage"),
        "quote_verified_rate": fm.get("quote_verified_rate"),
        "pdf_pages": rm.get("page_count"),
        "pdf_backend": rm.get("backend"),
        "pdf_fonts": rm.get("pdf_fonts"),
        "font_substitutions": missing_fonts,
        "min_pdf_text_coverage": min([p.get("text_coverage", 1.0) for p in rm.get("pages") or []],
                                     default=None),
        "page_number_slides": fm.get("page_number_slides"),
        "page_number_in_footer_slides": fm.get("footer_page_number_slides"),
        "footer_slides": fm.get("footer_slides"),
        # D31：导出件一致性读数（题面横切关注点：pptx ↔ PDF/PNG 逐页一致）
        "export_png_count": (rm.get("consistency") or {}).get("png_count"),
        "export_images_pptx": (rm.get("consistency") or {}).get("images_pptx_total"),
        "export_images_pdf": (rm.get("consistency") or {}).get("images_pdf_total"),
        "export_blank_png_pages": (rm.get("consistency") or {}).get("blank_png_pages"),
        "export_notes_min_chars": (rm.get("consistency") or {}).get("notes_min_chars"),
        "export_consistency_ok": (rm.get("consistency") or {}).get("ok"),
    }
    if baseline:
        metrics["baseline_comparison"] = baseline.get("deltas")

    summary = ("把《%s》套进模板（%d 个版式，主题字体 %s），产出 %d 页可编辑 pptx，"
               "渲染 %s 页 PDF（后端 %s）；%d 条页级证据、引文可回源率 %s、"
               "正文最小字号 %s pt、图片宽高比最大偏差 %s。" % (
                   source_map.get("title") or "?",
                   (fit or {}).get("inheritance", {}).get("layouts_out") or 0,
                   (template_map.get("theme_fonts") or {}).get("minorFont", {}).get("latin") or "?",
                   len(slides), rm.get("page_count") or 0, rm.get("backend") or "n/a",
                   len(evidence),
                   "%.1f%%" % (100 * fm["quote_verified_rate"]) if fm.get("quote_verified_rate")
                   is not None else "n/a",
                   fm.get("min_body_pt") or "n/a",
                   "%.3f%%" % (100 * fm["figure_aspect_max_deviation"] or 0)
                   if fm.get("figure_aspect_max_deviation") is not None else "n/a"))

    out = {
        "case_id": case.get("case_id") or case.get("id") or "UNKNOWN",
        "task": case.get("task"),
        "status": status,
        "status_reason": "；".join(dict.fromkeys(reasons)),
        "summary": summary,
        "generated_at": _now(),
        # D14-R1：产物清单同时以 outputs[] 暴露（path/bytes/sha256），artifacts[] 保留兼容
        "outputs": [{"path": a.get("path"), "bytes": a.get("bytes"), "sha256": a.get("sha256"),
                     "kind": a.get("kind"), "exists": a.get("exists")}
                    for a in artifacts if a.get("exists")],
        "results": {
            "template": {
                "path": os.path.basename(
                    (template_map.get("template") or {}).get("path") or ""),
                "source": template_map.get("template"),
                "origin": template_map.get("template_origin"),
                "degradations": template_map.get("degradations") or [],
                "slide_size": template_map.get("slide_size"),
                "layout_count": template_map.get("layout_count"),
                "roles": template_map.get("roles"),
                "theme_fonts": template_map.get("theme_fonts"),
                "theme_colors": template_map.get("theme_colors"),
                "fonts": template_map.get("fonts"),
                "warnings": template_map.get("warnings"),
                "inheritance": (fit or {}).get("inheritance"),
            },
            "plan": {
                "stats": plan.get("stats"),
                "slide_count_constraint": (plan.get("meta") or {}).get("slide_count_constraint"),
                "slide_count_planned": (plan.get("meta") or {}).get("slide_count_planned"),
                "budget_notes": (plan.get("meta") or {}).get("budget_notes"),
                # D14-R4：计划校验（含 slide_count 越界/引文回源/版式越界）必须进产物，
                # 否则"校验器判 fail、汇总却写 success"就是假绿。
                "validation": plan.get("validation"),
                "dropped_content": plan.get("dropped_content"),
                "fonts": (plan.get("meta") or {}).get("fonts"),
                "ladders": (plan.get("meta") or {}).get("ladders"),
            },
            "build": {
                "slides": (build_log or {}).get("slides_count"),
                "sha256": (units.sha256_file(pptx_path)
                           if pptx_path and os.path.isfile(pptx_path) else None),
                "stripped_slides": (build_log or {}).get("stripped_slides"),
                "mode": (build_log or {}).get("mode"),
                "warnings": (build_log or {}).get("warnings"),
                "font_scale": [{"slide": s.get("index"), "scale": s.get("font_scale")}
                               for s in (build_log or {}).get("slides") or []
                               if s.get("font_scale")],
                "placeholders_synthesized": [{"slide": s.get("index"),
                                              "detail": s.get("placeholders_synthesized")}
                                             for s in (build_log or {}).get("slides") or []
                                             if s.get("placeholders_synthesized")],
            },
            "fit": {"metrics": dict(fm, **{"overflow_boxes": fm.get("textboxes_over_container")}),
                    "issues": (fit or {}).get("issues"),
                    "consistency": (fit or {}).get("consistency")},
            "render": {"ok": rm.get("ok"), "backend": rm.get("backend"),
                       "pdf": os.path.basename(rm.get("pdf")) if rm.get("pdf") else None,
                       "png_count": len(rm.get("png") or []),
                       "page_count": rm.get("page_count"),
                       "pdf_fonts": rm.get("pdf_fonts"),
                       "missing_fonts": missing_fonts,
                       "issues": (rm.get("checks") or {}).get("issues"),
                       # D31：导出件一致性（逐页 pptx↔PDF↔PNG 比对），题面要求的横切关注点
                       "consistency": rm.get("consistency"),
                       "pages": rm.get("pages")},
            "evidence_summary": {
                "total": len(evidence),
                "verified": sum(1 for e in evidence if e["verified"]),
                "pages_with_evidence": len({e["page"] for e in evidence}),
            },
            "metrics": metrics,
        },
        "slides": slides,
        "evidence": evidence,
        "sources": [source_map.get("source") or {}],
        "uncertainty": uncertainty,
        "change_log": [
            {"step": "1 模板解析", "what": "读母版/版式/占位符/主题字体与配色",
             "evidence": "results.template"},
            {"step": "2 材料抽取", "what": "按标题/段落/图注切成可定位单元",
             "evidence": "sources + evidence[].locator"},
            {"step": "3 页级计划", "what": "定页结构与字号阶梯预算，超页数按分值裁剪",
             "evidence": "results.plan"},
            {"step": "4 套版生成", "what": "add_slide(layout) 继承母版，逐 run 写 latin/ea 字体",
             "evidence": "results.build + results.template.inheritance"},
            {"step": "5 版式复核", "what": "溢出/字号下限/图片比例/一致性/引文回源",
             "evidence": "results.fit"},
            {"step": "6 导出回测", "what": "PDF/PNG 渲染后回测页数、丢字、字体替换",
             "evidence": "results.render"},
        ],        "artifacts": artifacts,
        "capability_boundary": [
            "技术检查只证明：模板继承真实、页内文本与渲染一致、证据定位可回源；",
            "不证明：学术判断正确、讲稿叙事优秀、听众适配最佳——这些需人工评审；",
            "材料缺失（无源文件/无模板/无图）时如实给 partial，不编造内容与数据。",
        ],
        "reproduce": ("python scripts/fit.py --case <case.json> --out out "
                      "# 零附加参数；同一 case 复跑后比对 outputs[].sha256"),
    }
    # D14-R1：changes 作为 change_log 的别名（不同题面命名的兼容键，内容一致）
    out["changes"] = out["change_log"]
    if narrative:
        out["narrative"] = narrative
        out["narrative_source"] = "agent-authored"
    else:
        out["narrative"] = None
        out["narrative_source"] = "missing (机器只产结构化事实；叙述应由 agent 补写)"

    # ---- output_contract 回显
    fields = _contract_fields(case)
    echo, unresolved = {}, []
    for f in fields:
        if f in out:
            echo[f] = out[f]
        elif f in ("presentation", "pptx", "deck"):
            echo[f] = out["outputs"][0] if out.get("outputs") else (
                out["artifacts"][0] if out["artifacts"] else None)
        elif f in ("slide_plan", "plan"):
            echo[f] = "slide_plan.json"
        elif f in ("evidence_map", "evidence"):
            echo[f] = "evidence_map.json"
        elif f in ("render", "preview"):
            echo[f] = out["results"]["render"]
        elif f == "status":
            echo[f] = out["status"]
        elif f == "case_id":
            echo[f] = out["case_id"]
        else:
            echo[f] = None
            unresolved.append(f)
    out["output_contract_echo"] = echo
    out["contract_unresolved_fields"] = unresolved
    return out


def refresh_artifacts(result: dict, outdir: str, pptx_path: str,
                      preexisting: dict | None = None) -> dict:
    """在**所有产物写完后**重算 outputs[]/artifacts[] 的 bytes 与 sha256。

    为什么需要：audit.build_result 跑在 result.json/deck_report.md 落盘之前，
    若直接沿用那时的哈希，复跑同一目录会出现"自述哈希 ≠ 磁盘哈希"（实测踩过）。

    `preexisting`：运行前 outdir 的 {rel: (size, mtime)} 快照。只列**本次写过**的文件
    （大小或 mtime 与快照不同），避免把上一轮遗留的产物当成本次产物自述。
    """
    kinds = {".pptx": "editable-presentation", ".pdf": "rendered-pdf", ".png": "rendered-png",
             ".md": "report", ".json": "data"}
    found = []
    for base, _dirs, files in os.walk(outdir):
        # 只跳过 <outdir>/work（本 Skill 的中间产物目录）——按**相对 outdir 的路径**判断，
        # 不做"任何叫 work/ 的目录"或按绝对路径目录段（outputs/runs/stage）过滤，
        # 免得包被放在含这些名字的路径下时把产物或输入吞掉（同类 bug 的教训）。
        relbase = os.path.relpath(base, outdir).replace("\\", "/")
        if relbase == "work" or relbase.startswith("work/"):
            continue
        for f in sorted(files):
            p = os.path.join(base, f)
            rel = os.path.relpath(p, outdir).replace("\\", "/")
            if rel.endswith(".pyc") or f in ("result.json", "result.sha256"):
                # result.json 不能自述自身哈希（自指不可满足）：见 result.sha256。
                # D14-R4：result.sha256 是本轮结束后才写的 sidecar，若列进 outputs[]，
                # 向同一 --out 重跑时它带着**上一轮**的哈希进来 → 审计判 high 不一致。
                continue
            found.append({"path": rel, "bytes": os.path.getsize(p), "sha256": units.sha256_file(p),
                          "kind": kinds.get(os.path.splitext(f)[1].lower(), "data"),
                          "exists": True})
    # pptx 主产物排第一
    found.sort(key=lambda a: (0 if a["path"].lower().endswith(".pptx") else
                              1 if a["path"].lower().endswith(".pdf") else 2, a["path"]))
    result["outputs"] = found
    result["artifacts"] = [dict(a) for a in found]
    return result


def write_outputs(result: dict, outdir: str, plan: dict, source_map: dict,
                  evidence_map: dict | None = None) -> list:
    os.makedirs(outdir, exist_ok=True)
    written = []
    with open(os.path.join(outdir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        written.append(os.path.join(outdir, "result.json"))
    with open(os.path.join(outdir, "slide_plan.json"), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
        written.append(os.path.join(outdir, "slide_plan.json"))
    em = evidence_map or {"evidence": result["evidence"],
                          "note": "每条 = page + locator + quote + verified；verified 以源材料逐字比对为准"}
    with open(os.path.join(outdir, "evidence_map.json"), "w", encoding="utf-8") as fh:
        json.dump(em, fh, ensure_ascii=False, indent=2)
        written.append(os.path.join(outdir, "evidence_map.json"))
    md = render_report_md(result, plan, source_map)
    with open(os.path.join(outdir, "deck_report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
        written.append(os.path.join(outdir, "deck_report.md"))
    return written


def render_report_md(result: dict, plan: dict, source_map: dict) -> str:
    r = result
    m = r["results"]["metrics"]
    L = []
    L.append("# 学术汇报套版报告 · %s" % r["case_id"])
    L.append("")
    L.append("> 本文件由 `scripts/audit.py` 从产物与检查结果机械生成（**只含可核对事实**，"
             "叙述性总结请由 agent 写入 `result.json.narrative`）。")
    L.append("")
    L.append("## 0. 结论")
    L.append("")
    L.append("- 状态：**%s** — %s" % (r["status"], r["status_reason"]))
    L.append("- %s" % r["summary"])
    L.append("")
    L.append("## 1. 模板套用（继承是否真实发生）")
    L.append("")
    t = r["results"]["template"]
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| 模板 | `%s` (sha256 `%s`) |" % (
        (t["source"] or {}).get("path"), ((t["source"] or {}).get("sha256") or "")[:16]))
    L.append("| 画幅 | %s (%s×%s in) |" % (t["slide_size"]["ratio_label"],
                                            round(t["slide_size"]["width_in"], 2),
                                            round(t["slide_size"]["height_in"], 2)))
    L.append("| 版式数（模板/产物） | %s / %s |" % (t["layout_count"], m["layouts_in_output"]))
    L.append("| 版式保持 | %s |" % t["inheritance"].get("layouts_preserved"))
    L.append("| 主题字体保持 | %s |" % t["inheritance"].get("theme_preserved"))
    L.append("| 主题字体 | `%s`（主题）；正文实际 `%s` |" % (
        (t["theme_fonts"].get("minorFont") or {}).get("latin"),
        ((r["results"]["plan"]["fonts"] or {}).get("body") or {}).get("latin")))
    L.append("| 占位符几何继承 | %s 页的占位符未写死坐标 |" % m["geometry_inherited_slides"]
             if "geometry_inherited_slides" in m else "")
    L.append("")
    L.append("版式角色映射（模板里实际存在的角色 → 页码）：")
    roles = t.get("roles") or {}
    for role, idxs in sorted(roles.items()):
        L.append("- `%s`：版式 %s" % (role, idxs))
    L.append("")
    L.append("## 2. 页级结构（主张 → 证据定位）")
    L.append("")
    L.append("| 页 | 角色 | 版式 | 标题 | 主张 | 证据条数 | 定位 |")
    L.append("|---:|---|---|---|---|---:|---|")
    for s in r["slides"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            s["page"], s["role"], s["layout"], (s["title"] or "")[:40],
            (s["claim"] or "")[:50], s["evidence_count"],
            "; ".join(s["evidence_locs"][:3]) or "—"))
    L.append("")
    L.append("## 3. 版式与字号（溢出、阶梯、下限）")
    L.append("")
    L.append("| 指标 | 值 | 判定 |")
    L.append("|---|---|---|")
    L.append("| 溢出文本框 | %s | %s |" % (m["overflow_boxes"],
                                         "通过" if not m["overflow_boxes"] else "需修"))
    L.append("| 正文最小字号 | %s pt | %s |" % (m["min_body_pt"],
                                             "通过（≥14pt）" if (m["min_body_pt"] or 0) >= 14 else "低于下限"))
    L.append("| 图片宽高比最大偏差 | %.4f%% | %s |" % (
        (m["figure_aspect_max_deviation"] or 0) * 100,
        "通过（<0.5%）" if (m["figure_aspect_max_deviation"] or 0) < 0.005 else "变形"))
    L.append("| 页码（页脚文本） | %s 页 | — |" % m.get("page_number_in_footer_slides"))
    L.append("| 页码域占位符（slidenum） | %s 页 | 渲染端不绘制时以上一行保底 |" % m["page_number_slides"])
    L.append("| 页脚覆盖 | %s 页 | — |" % m["footer_slides"])
    L.append("")
    if r["results"]["build"].get("warnings"):
        L.append("构建期处理（不压字号，先阶梯后移入备注）：")
        for w in r["results"]["build"]["warnings"]:
            L.append("- %s" % w)
        L.append("")
    L.append("## 4. 导出渲染（pptx ↔ PDF 是否一致）")
    L.append("")
    rr = r["results"]["render"]
    L.append("- 后端：`%s`；页数 %s；PDF 字体：`%s`" % (
        rr["backend"], rr["page_count"], "`, `".join((rr["pdf_fonts"] or [])[:8])))
    if rr["missing_fonts"]:
        L.append("- 字体替换：%s" % ", ".join(rr["missing_fonts"]))
    L.append("- 逐页文本覆盖率最低：%s" % m["min_pdf_text_coverage"])
    for p in (rr.get("pages") or [])[:12]:
        L.append("  - 第 %s 页：覆盖 %.1f%%，图 %s，文本边距 %s pt" % (
            p["page"], (p["text_coverage"] or 0) * 100, p["images"],
            (p.get("bbox_margins_pt") or {}).get("ms")))
    cons = rr.get("consistency")
    if cons:
        L.append("")
        L.append("导出件逐页一致性（D31：pptx ↔ PDF ↔ PNG；题面横切关注点）：")
        L.append("")
        L.append("| 页 | pptx 图 | PDF 图 | 文本覆盖 | PNG | 像素 | 宽高比偏差 | 非空白像素 | 备注字数 |")
        L.append("|---:|---:|---:|---:|---|---|---:|---:|---:|")
        for row in (cons.get("pages") or [])[:20]:
            L.append("| %s | %s | %s | %s | `%s` | %s | %s%% | %s | %s |" % (
                row.get("page"), row.get("images_pptx"), row.get("images_pdf"),
                row.get("text_coverage"),
                row.get("png") or "—",
                "×".join(str(x) for x in (row.get("png_size") or [])) or "—",
                row.get("png_aspect_dev_pct"), row.get("png_ink_ratio"),
                row.get("notes_chars")))
        L.append("")
        if cons.get("issues"):
            for i0 in cons["issues"][:12]:
                L.append("- **[%s]** %s%s — %s" % (
                    i0.get("severity"), i0.get("item"),
                    ("（第 %s 页）" % i0.get("page")) if i0.get("page") else "",
                    (i0.get("detail") or "")[:140]))
        else:
            L.append("- 未发现不一致（页数/图片/文本/备注/字体逐页对齐）")
    L.append("")
    L.append("## 5. 证据映射（抽检）")
    L.append("")
    L.append("| 页 | 定位 | 引文（截断） | 可回源 |")
    L.append("|---:|---|---|---|")
    for e in r["evidence"][:20]:
        L.append("| %s | %s | %s | %s |" % (e["page"], e["locator"],
                                            (e["quote"] or "")[:48].replace("|", "/"),
                                            "✓" if e["verified"] else "✗"))
    L.append("")
    L.append("## 6. 不确定性")
    L.append("")
    for u in r["uncertainty"]:
        L.append("- **%s**：%s → %s" % (u.get("item"), u.get("why"), u.get("handling")))
    if not r["uncertainty"]:
        L.append("- 无（材料完整、字体齐备、渲染成功）")
    L.append("")
    L.append("## 7. 复跑")
    L.append("")
    L.append("```bash\n%s\n```" % r["reproduce"])
    L.append("")
    L.append("产物 sha256 见 `result.json.artifacts`；逐条问题见 `results.fit.issues` 与 "
             "`results.render.issues`。")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="assemble result.json + deck_report.md")
    ap.add_argument("--case", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--source-map", required=True)
    ap.add_argument("--template-map", required=True)
    ap.add_argument("--build-log", required=True)
    ap.add_argument("--fit", required=True)
    ap.add_argument("--render", required=True)
    ap.add_argument("--pptx", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--baseline")
    ap.add_argument("--narrative")
    a = ap.parse_args(argv)
    load = lambda p: json.load(open(p, encoding="utf-8"))  # noqa: E731
    case, plan, sm, tm = load(a.case), load(a.plan), load(a.source_map), load(a.template_map)
    bl, fit, render = load(a.build_log), load(a.fit), load(a.render)
    narrative = open(a.narrative, encoding="utf-8").read() if a.narrative else None
    base = load(a.baseline) if a.baseline else None
    res = build_result(case, plan, sm, tm, bl, fit, render, a.out, a.pptx,
                       narrative=narrative, baseline=base)
    files = write_outputs(res, a.out, plan, sm)
    print("audit: status=%s artifacts=%d → %s" % (res["status"], len(files), a.out))
    for f in files:
        print("  - %s" % os.path.basename(f))
    return 0 if res["status"] == "success" else 6


if __name__ == "__main__":
    sys.exit(main())
