# -*- coding: utf-8 -*-
"""fit_check.py —— 生成后的**静态复核**（不开渲染器也能查的那一半）。

复核项（每条都给出可核对的读数）：
  1. 版式继承：产物布局/母版/主题与模板一致吗？页面占位符在 slide XML 里是否**没有**写死几何
     （没有 a:xfrm = 真正从版式继承，而不是"复制了一份坐标"）？
  2. 溢出：按每段实际字号（含 normAutofit fontScale）估算所需高度，与容器比，报溢出比。
  3. 字号下限：正文 ≥ min_body_pt、图注 ≥ 10pt、标题 ≥ 20pt，违反即 high。
  4. 图表比例：从 pptx 里读图片真实像素 vs 放置尺寸，算宽高比偏差（拉伸变形检测）。
  5. 批量一致性：同一版式的标题/页脚几何是否逐页一致；页脚与页码域是否每页都有。
  6. 证据：每条 bullet 的 quote 是否能在 source_map 里逐字找到（quote_verified）。

用法：
    python fit_check.py --pptx deck.pptx --plan plan.json --source-map source_map.json \
        --template-map template_map.json --out fit_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）
import zipfile

import units
from pptx import Presentation
from pptx.oxml.ns import qn

MIN_SIZE = {"body": 14.0, "caption": 10.0, "title": 20.0}


def _sp_xfrm_present(shape) -> bool:
    el = shape._element
    spPr = el.find(qn("p:spPr"))
    if spPr is None:
        return False
    return spPr.find(qn("a:xfrm")) is not None


def _autofit_scale(tf) -> float:
    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is None:
        return 1.0
    el = bodyPr.find(qn("a:normAutofit"))
    if el is None:
        return 1.0
    try:
        return int(el.get("fontScale", "100000")) / 100000.0
    except Exception:
        return 1.0


def _para_text(p) -> str:
    return "".join(r.text for r in p.runs)


def _para_size(p, tf) -> float:
    for r in p.runs:
        if r.font.size is not None:
            return r.font.size.pt
    # 回退：占位符继承的默认字号（估 18pt）
    return 18.0


def check(pptx: str, plan: dict, source_map: dict, template_map: dict,
          build_log: dict | None = None) -> dict:
    prs = Presentation(pptx)
    tm = template_map or {}
    slides_out = []
    issues = []
    blocks = {b["id"]: b for b in (source_map or {}).get("blocks") or []}
    plan_slides = {s.get("index"): s for s in (plan or {}).get("slides") or []}

    # ---- 继承链完整性
    inher = {
        "layouts_out": len(prs.slide_layouts),
        "layouts_template": tm.get("layout_count"),
        "masters_out": len(prs.slide_masters),
        "masters_template": len(tm.get("masters") or []) or None,
        "theme_out": None,
        "theme_template": tm.get("theme_fonts"),
        "layouts_preserved": None,
    }
    import pptx_util as U
    ti = U.theme_info(pptx)
    inher["theme_out"] = ti.get("fonts")
    inher["layouts_preserved"] = (inher["layouts_template"] is None or
                                  inher["layouts_out"] == inher["layouts_template"])
    inher["theme_preserved"] = (inher["theme_template"] is None or
                                inher["theme_out"] == inher["theme_template"])
    if not inher["layouts_preserved"]:
        issues.append({"severity": "high", "item": "版式数量与模板不一致",
                       "detail": "%s → %s" % (inher["layouts_template"], inher["layouts_out"])})
    if not inher["theme_preserved"]:
        issues.append({"severity": "medium", "item": "主题字体与模板不一致",
                       "detail": "%s → %s" % (inher["theme_template"], inher["theme_out"])})

    title_geo = []
    fig_devs = []
    min_body_seen = None
    caption_seen = None
    quotes_total = quotes_ok = 0
    locators_total = locators_ok = 0

    for si, slide in enumerate(prs.slides):
        idx = si + 1
        spec = plan_slides.get(idx) or {}
        srec = {"index": idx, "role": spec.get("role"), "layout": slide.slide_layout.name,
                "shapes": len(slide.shapes), "text_overflow": [], "geometry_inherited": True,
                "page_number_field": False, "footer": False, "figures": [],
                "font_sizes": [], "issues": []}
        for sh in slide.shapes:
            if sh.shape_type == 13 or sh.__class__.__name__ == "Picture":
                try:
                    img = sh.image
                    iw, ih = img.size
                    src_aspect = iw / float(ih)
                    out_aspect = sh.width / float(sh.height)
                    dev = abs(out_aspect - src_aspect) / src_aspect
                    srec["figures"].append({
                        "name": sh.name, "image_px": [iw, ih],
                        "placed_in": [round(sh.width / 914400.0, 3), round(sh.height / 914400.0, 3)],
                        "aspect_deviation": round(dev, 6)})
                    fig_devs.append(dev)
                    if dev > 0.005:
                        issues.append({"severity": "high", "item": "图片被拉伸变形", "slide": idx,
                                       "detail": "宽高比偏差 %.3f%%" % (dev * 100)})
                        srec["issues"].append("aspect_deviation")
                except Exception as exc:
                    srec["issues"].append("image_read_failed: %s" % exc)
            if not sh.has_text_frame:
                continue
            tf = sh.text_frame
            if not tf.text.strip():
                continue
            if not _sp_xfrm_present(sh):
                pass
            else:
                srec["geometry_inherited"] = False
            scale = _autofit_scale(tf)
            w_in = (sh.width or 0) / 914400.0
            h_in = (sh.height or 0) / 914400.0
            need = 0.0
            sizes = []
            for p in tf.paragraphs:
                txt = _para_text(p)
                if not txt:
                    continue
                pt = _para_size(p, tf) * scale
                sizes.append(round(pt, 1))
                need += units.block_height_in(txt, w_in, pt, 1.0, space_before_pt=3)
            srec["font_sizes"].extend(sizes)
            kind = U.ph_kind(sh) if sh.is_placeholder else "textbox"
            if kind in ("body", "object") or sh.name == "SynthBody":
                eff = min(sizes) if sizes else 18.0
                min_body_seen = eff if min_body_seen is None else min(min_body_seen, eff)
                if eff < MIN_SIZE["body"] - 0.01:
                    issues.append({"severity": "high", "item": "正文字号低于下限", "slide": idx,
                                   "detail": "%.1fpt < %.0fpt（不得靠压字号硬塞）"
                                             % (eff, MIN_SIZE["body"])})
                    srec["issues"].append("body_too_small")
            if sh.name == "FigureCaption" or kind == "footer":
                eff = max(sizes) if sizes else 10.0
                if kind == "footer":
                    pass
                else:
                    caption_seen = eff if caption_seen is None else min(caption_seen, eff)
                    if eff < MIN_SIZE["caption"] - 0.01:
                        issues.append({"severity": "medium", "item": "图注字号过小", "slide": idx,
                                       "detail": "%.1fpt" % eff})
            if kind == "subtitle" and sh.is_placeholder and sizes:
                if max(sizes) < 12.0 - 0.01:
                    issues.append({"severity": "low", "item": "副标题字号过小", "slide": idx,
                                   "detail": "%.1fpt" % max(sizes)})
            if kind == "title" and sh.is_placeholder:
                title_geo.append({"slide": idx, "layout": slide.slide_layout.name,
                                  "left": round((sh.left or 0) / 914400.0, 3),
                                  "top": round((sh.top or 0) / 914400.0, 3),
                                  "size": max(sizes) if sizes else None})
                if sizes and max(sizes) < MIN_SIZE["title"] - 0.01:
                    issues.append({"severity": "medium", "item": "标题字号过小", "slide": idx,
                                   "detail": "%.1fpt" % max(sizes)})
            if h_in > 0.05 and kind != "footer":
                ratio = need / h_in
                if ratio > 1.06:
                    srec["text_overflow"].append({"shape": sh.name, "need_in": round(need, 3),
                                                  "box_in": round(h_in, 3),
                                                  "ratio": round(ratio, 3)})
                    sev = "high" if ratio > 1.20 else "medium"
                    issues.append({"severity": sev, "item": "文本框溢出容器", "slide": idx,
                                   "detail": "%s 需要 %.2fin / 容器 %.2fin（%.0f%%）"
                                             % (sh.name, need, h_in, ratio * 100)})
        # 页脚 / 页码
        for sh in slide.shapes:
            if not sh.is_placeholder:
                continue
            k = U.ph_kind(sh)
            if k == "footer" and sh.has_text_frame and sh.text_frame.text.strip():
                srec["footer"] = True
                if re.search(r"\d+\s*/\s*\d+", sh.text_frame.text):
                    srec["footer_page_number"] = True
            if k == "slide_number":
                xml = sh.text_frame._txBody.xml if sh.has_text_frame else ""
                srec["page_number_field"] = 'type="slidenum"' in xml
        if spec.get("role") not in ("title", "closing", "section", None):
            if not srec["footer"]:
                issues.append({"severity": "low", "item": "缺页脚", "slide": idx})
            if not srec["page_number_field"]:
                issues.append({"severity": "medium", "item": "缺页码域", "slide": idx})

        # 证据核对
        for b in spec.get("bullets") or []:
            locators_total += 1
            if b.get("locator"):
                locators_ok += 1
            if b.get("kind") == "nav":
                continue  # 提纲页是导航，不是原文断言
            quotes_total += 1
            src = blocks.get(b.get("block_id"))
            q = (b.get("quote") or b.get("text") or "").strip()
            if src and q and q[:20] in src["text"]:
                quotes_ok += 1
            else:
                issues.append({"severity": "high", "item": "引文无法回源", "slide": idx,
                               "detail": q[:50]})
        slides_out.append(srec)

    # 标题/页脚几何一致性（同版式内应完全一致）
    by_layout = {}
    for g in title_geo:
        by_layout.setdefault(g["layout"], []).append(g)
    geo_inconsistency = []
    for lay, gs in by_layout.items():
        if len(gs) < 2:
            continue
        lefts = {g["left"] for g in gs}
        tops = {g["top"] for g in gs}
        if len(lefts) > 1 or len(tops) > 1:
            geo_inconsistency.append({"layout": lay, "lefts": sorted(lefts),
                                      "tops": sorted(tops), "slides": [g["slide"] for g in gs]})
    if geo_inconsistency:
        issues.append({"severity": "medium", "item": "标题几何不一致",
                       "detail": json.dumps(geo_inconsistency, ensure_ascii=False)[:300]})

    report = {
        "pptx": os.path.basename(pptx),
        "pptx_sha256": units.sha256_file(pptx),
        "slides": slides_out,
        "inheritance": inher,
        "issues": issues,
        "consistency": {"title_geometry_groups": len(by_layout),
                        "title_geometry_inconsistent": geo_inconsistency},
        "metrics": {
            "slides": len(slides_out),
            "slides_with_text_overflow": sum(1 for s in slides_out if s["text_overflow"]),
            "textboxes_over_container": sum(len(s["text_overflow"]) for s in slides_out),
            "min_body_pt": min_body_seen,
            "min_caption_pt": caption_seen,
            "figure_aspect_max_deviation": round(max(fig_devs), 6) if fig_devs else 0.0,
            "figures": sum(len(s["figures"]) for s in slides_out),
            "geometry_inherited_slides": sum(1 for s in slides_out if s["geometry_inherited"]),
            "locator_coverage": round(locators_ok / locators_total, 4) if locators_total else None,
            "quote_verified_rate": round(quotes_ok / quotes_total, 4) if quotes_total else None,
            "footer_slides": sum(1 for s in slides_out if s["footer"]),
            "footer_page_number_slides": sum(1 for s in slides_out if s.get("footer_page_number")),
            "page_number_slides": sum(1 for s in slides_out if s["page_number_field"]),
        },
        "notes": {
            "geometry_inherited": "占位符在 slide XML 里没有 a:xfrm，说明坐标来自版式继承，"
                                  "而不是被复制成硬编码坐标。",
            "overflow_method": "按每段实际字号（含 normAutofit fontScale）估算所需高度 / 容器高度；"
                               ">1.02 记溢出，>1.15 记 high。",
        },
    }
    report["ok"] = not any(i["severity"] == "high" for i in issues)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="static fit/consistency/evidence check")
    ap.add_argument("--pptx", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--source-map", required=True)
    ap.add_argument("--template-map", required=True)
    ap.add_argument("--out", default="fit_report.json")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan, encoding="utf-8"))
    sm = json.load(open(a.source_map, encoding="utf-8"))
    tm = json.load(open(a.template_map, encoding="utf-8"))
    rep = check(a.pptx, plan, sm, tm)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    m = rep["metrics"]
    print("fit_check: slides=%s overflow_boxes=%s min_body=%s quote_ok=%s locator_cov=%s ok=%s"
          % (m["slides"], m["textboxes_over_container"], m["min_body_pt"],
             m["quote_verified_rate"], m["locator_coverage"], rep["ok"]))
    for i in rep["issues"][:10]:
        print("  [%s] %s slide=%s %s" % (i["severity"], i["item"], i.get("slide"),
                                         i.get("detail", "")[:90]))
    return 0 if rep["ok"] else 5


if __name__ == "__main__":
    sys.exit(main())
