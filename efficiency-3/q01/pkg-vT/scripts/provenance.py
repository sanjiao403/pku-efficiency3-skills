#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""provenance -- the part that makes the figure checkable.

Three families of checks:
  * quote gate     : every claimed locator quote really occurs in the material;
  * canvas gate    : every element in the content map exists on the canvas, every
                     number printed on the canvas traces back to a source or a
                     declared data point;
  * export gate    : the SVG/PNG/PDF are real, sized as declared, and the legend
                     describes exactly the categories that were drawn.

Nothing here re-renders; it only reads the scene, the IR and the files, so it can
also be used as a stand-alone validator on a finished submission.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # never leave __pycache__ behind


import re
import unicodedata
from pathlib import Path

import ga_core as C

_NUM_RE = re.compile(r"(?<![A-Za-z_#])(\d+(?:[.,]\d+)?)")


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def norm_key(s: str) -> str:
    """Aggressive normalisation for hit-testing: width, case, punctuation spacing."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def quote_hit(quote: str, haystack_norm: str) -> bool:
    q = norm_key(quote)
    if not q or len(q) < 4:
        return False
    return q in haystack_norm


def best_partial(quote: str, haystack_norm: str) -> float:
    """Rough longest-common-substring ratio, for diagnostics only."""
    q = norm_key(quote)
    if not q or not haystack_norm:
        return 0.0
    best, lo = 0, 0
    step = max(1, len(q) // 12)
    for i in range(0, len(q), step):
        for size in range(len(q) - i, 3, -step):
            if q[i:i + size] in haystack_norm:
                best = max(best, size)
                break
    return round(best / float(len(q)), 3)


def collect_numbers(texts):
    out = {}
    for t in texts:
        for m in _NUM_RE.finditer(t or ""):
            v = m.group(1).replace(",", ".")
            out.setdefault(v, 0)
            out[v] += 1
    return out


def build_content_map(ir, scene, id_map):
    """Element-level provenance: same ids as the SVG, same order as the canvas."""
    entries = []
    def final(pid):
        return id_map.get(pid, pid)

    for k, p in enumerate(ir["panels"][:4]):
        pid = "panel-%d" % (k + 1)
        panel_src = p.get("source") or {}
        if not (panel_src.get("quote")):
            for it in p["items"]:
                if (it.get("source") or {}).get("quote"):
                    panel_src = it["source"]
                    break
        entries.append({
            "kind": "panel", "id": final(pid), "order": p["order"], "role": p["role"],
            "title": p["title"], "claim": p["claim"],
            "items": [{"id": it["id"], "text": it["text"],
                       "element": final("%s-l0" % it["id"]),
                       "on_canvas": ("%s-l0" % it["id"]) in id_map}
                      for it in p["items"]],
            "source": panel_src,
        })
    for e in ir["entities"]:
        entries.append({
            "kind": "entity", "id": final("ent-%s" % e["id"]), "entity_id": e["id"],
            "label": e["label"], "entity_type": e["type"],
            "compartment": e["compartment"], "italic": e["italic"],
            "on_canvas": ("ent-%s" % e["id"]) in id_map,
            "source": e["source"],
        })
    for r in ir["relations"]:
        entries.append({
            "kind": "relation", "id": final("edge-%s-head" % r["id"]), "relation_id": r["id"],
            "from": r["from"], "to": r["to"], "relation_type": r["type"],
            "direction": "forward", "label": r["label"],
            "on_canvas": ("edge-%s-head" % r["id"]) in id_map,
            "source": r["source"],
        })
    for c in ir["claims"]:
        entries.append({
            "kind": "value", "id": final("ledger-%s-value" % c["id"]), "claim_id": c["id"],
            "label": c["label"], "value": c["value"], "unit": c["unit"],
            "compare": c.get("compare") or {},
            "on_canvas": ("ledger-%s-value" % c["id"]) in id_map,
            "source": c["source"],
        })
    for ch in ir["charts"]:
        for si, s in enumerate(ch["series"]):
            for pi, pt in enumerate(s["points"]):
                entries.append({
                    "kind": "data_point", "id": final("%s-bar%d-%d" % (ch["id"], si, pi)),
                    "chart": ch["id"], "series": s["name"], "x": pt.get("x"),
                    "y": pt.get("y"), "raw_value": pt.get("raw") or "",
                    "unit": ch.get("unit") or "", "err": pt.get("err") or 0,
                    "on_canvas": ("%s-bar%d-%d" % (ch["id"], si, pi)) in id_map,
                    "source": pt.get("source") or {},
                })
    for li in scene.get("legend", []):
        lsrc = li.get("source") or {}
        if not lsrc.get("quote") and li.get("category") == "relation":
            rt = li["key"].replace("rel-", "")
            for r in ir["relations"]:
                if r["type"] == rt and (r.get("source") or {}).get("quote"):
                    lsrc = r["source"]
                    break
        entries.append({
            "kind": "legend", "id": final("leg-%s-lb" % li["key"]), "key": li["key"],
            "label": li["label"], "channel": li["channel"],
            "color": li.get("color", ""), "pattern": li.get("pattern", ""),
            "category": li.get("category", ""),
            "on_canvas": ("leg-%s-lb" % li["key"]) in id_map,
            "source": lsrc,
        })
    for name in (scene.get("chart_series_in_chart_legend") or []):
        src = {}
        for ch in ir["charts"]:
            for s in ch["series"]:
                if s["name"] == name and s["points"]:
                    src = s["points"][0].get("source") or {}
                    break
        entries.append({"kind": "legend", "id": "", "key": "series-%s" % name,
                        "label": name, "channel": "fill", "category": "series",
                        "in_chart": True, "on_canvas": True, "source": src})
    return entries


def coverage_report(ir, materials_norm, content_map):
    def has_quote(src):
        q = (src or {}).get("quote") or ""
        return bool(q) and quote_hit(q, materials_norm)

    buckets = {"panel": [0, 0], "entity": [0, 0], "relation": [0, 0],
               "value": [0, 0], "data_point": [0, 0], "legend": [0, 0]}
    source_traced = 0
    total = 0
    for e in content_map:
        total += 1
        if has_quote(e.get("source") or {}):
            source_traced += 1
        b = buckets.get(e["kind"])
        if b is not None:
            b[1] += 1
            if has_quote(e.get("source") or {}):
                b[0] += 1
    on_canvas = sum(1 for e in content_map if e.get("on_canvas", True))
    return {
        "elements": total,
        "on_canvas": on_canvas,
        "with_verbatim_source": source_traced,
        "source_ratio": round(source_traced / float(total or 1), 3),
        "by_kind": {k: {"traced": v[0], "total": v[1]} for k, v in buckets.items()},
    }


def number_gate(scene, ir, materials_norm):
    """Every printed number must come from a quote, a claim, or a data point."""
    allowed = set()
    for c in ir["claims"]:
        for v in (c.get("value"), (c.get("compare") or {}).get("value")):
            try:
                allowed.add(("%g" % float(v)))
            except Exception:
                pass
        q = (c.get("source") or {}).get("quote") or ""
        allowed |= set(collect_numbers([q]).keys())
    for ch in ir["charts"]:
        for s in ch["series"]:
            for pt in s["points"]:
                allowed.add(("%g" % float(pt.get("y") or 0)))
                if pt.get("raw"):
                    allowed |= set(collect_numbers([str(pt["raw"])]).keys())
    for src in ir["sources"]:
        allowed |= set(collect_numbers([src.get("quote") or ""]).keys())
    texts = [p["s"] for p in scene["prims"] if p["t"] == "text"]
    used = collect_numbers(texts)
    traced, untraced = [], []
    for v in sorted(used):
        if v in allowed or norm_key(v) in materials_norm:
            traced.append(v)
        else:
            untraced.append(v)
    return {"checked": len(used), "traced": len(traced), "untraced": untraced,
            "ratio": round(len(traced) / float(len(used) or 1), 3)}


def legend_gate(scene, ir):
    """Legend entries must equal the categories actually drawn."""
    drawn_rel = []
    for r in ir["relations"]:
        if not r.get("unresolved") and r["type"] not in drawn_rel:
            drawn_rel.append(r["type"])
    drawn_series = []
    for ch in ir["charts"]:
        for s in ch["series"]:
            drawn_series.append(s["name"] or "")
    legend_rel = [li["key"].replace("rel-", "") for li in scene["legend"]
                  if li.get("category") == "relation"]
    legend_series = [li["label"] for li in scene["legend"] if li.get("category") == "series"]
    legend_series += list(scene.get("chart_series_in_chart_legend") or [])
    ok = (sorted(legend_rel) == sorted(drawn_rel)) and (sorted(legend_series) == sorted(drawn_series))
    return {"ok": ok,
            "relation_categories_drawn": drawn_rel,
            "relation_categories_in_legend": legend_rel,
            "series_drawn": drawn_series,
            "series_in_legend": legend_series,
            "legend_entries": len(scene["legend"]),
            "categories": len(drawn_rel) + len(drawn_series)}


def grayscale_gate(scene, ir):
    n_series = sum(len(ch["series"]) for ch in ir["charts"])
    patterned = [li for li in scene["legend"]
                 if li.get("category") == "series" and li.get("pattern") not in ("", "none")]
    return {"series": n_series, "patterned": len(patterned),
            "ok": (n_series <= 1) or (len(patterned) >= n_series)}


def compliance_checks(ir, scene, svg_info, png_rec, pdf_rec, font_rep, coverage, legend, nums):
    canvas = scene["canvas"]
    checks = []

    def add(name, required, measured, verdict, evidence=""):
        checks.append({"check": name, "required": required, "measured": measured,
                       "verdict": verdict, "evidence": evidence})

    add("canvas_size", "%d x %d px" % (canvas["width_px"], canvas["height_px"]),
        "%s x %s px" % (png_rec.get("width", "?"), png_rec.get("height", "?")),
        "pass" if (png_rec.get("width") == canvas["width_px"] and
                   png_rec.get("height") == canvas["height_px"]) else "fail",
        "export_artifact.png")
    add("resolution_dpi", ">= %d dpi" % canvas["dpi"],
        "%s dpi" % png_rec.get("dpi", "?"),
        "pass" if (png_rec.get("dpi") or 0) >= canvas["dpi"] else "fail",
        "PNG IHDR + canvas.dpi")
    add("png_real", "PNG 可解析 IHDR，非空白", "engine=%s ink=%s" %
        (png_rec.get("engine", "none"), png_rec.get("ink_ratio")),
        "pass" if png_rec.get("verified") and (png_rec.get("ink_ratio") or 0) > 0.004 else "fail",
        ",".join(a.get("engine", "") for a in png_rec.get("attempts", [])))
    add("pdf_real", "%PDF- 头 + >=1 页 + 矢量", "engine=%s pages=%s" %
        (pdf_rec.get("engine", "none"), pdf_rec.get("pages")),
        "pass" if pdf_rec.get("verified") and pdf_rec.get("pages", 0) >= 1 else "fail",
        pdf_rec.get("header", ""))
    add("editable_text", "SVG 内 <text> 数量 == 场景文本数",
        "%s / %s" % (svg_info.get("text_count"), scene["text_count"]),
        "pass" if svg_info.get("text_count") == scene["text_count"] and
        svg_info.get("text_count", 0) > 0 else "fail", "figure.svg")
    add("layers", ">= 4 个语义图层",
        "%d 层: %s" % (len(scene["layers"]), ",".join(scene["layers"])),
        "pass" if len(scene["layers"]) >= 4 else "warn", "layer-* groups")
    body_min = scene.get("min_font_body") or scene["min_font_used"]
    add("min_font_body_px", ">= %s px（正文/标签层）" % canvas["min_font_px"],
        "%.1f px" % body_min,
        "pass" if body_min >= canvas["min_font_px"] - 0.6 else "fail",
        "layout.sizes + tier=body")
    ann_min = scene.get("min_font_annotation") or 0
    ann_floor = canvas["min_font_px"] * 0.62
    add("min_font_annotation_px", ">= %.1f px（刻度/脚注层，下限为正文的 62%%）" % ann_floor,
        "%.1f px" % ann_min,
        "pass" if (not ann_min or ann_min >= ann_floor - 0.4) else "warn",
        "layout.sizes + tier=annotation")
    add("no_canvas_overflow", "0 个文本越界", str(len(scene["out_of_canvas"])),
        "pass" if not scene["out_of_canvas"] else "fail",
        ",".join(o["id"] for o in scene["out_of_canvas"][:5]))
    add("legend_consistency", "图例项数 == 图面分类数",
        "%d vs %d" % (legend["legend_entries"], legend["categories"]),
        "pass" if legend["ok"] else "fail",
        "rel=%s series=%s" % (legend["relation_categories_in_legend"],
                              legend["series_in_legend"]))
    add("source_verbatim", ">= 80% 元素有逐字来源",
        "%.1f%%" % (coverage["source_ratio"] * 100),
        "pass" if coverage["source_ratio"] >= 0.80 else "warn",
        json_dumps(coverage["by_kind"]))
    add("number_trace", "画布上每个数值都能回查来源",
        "%d/%d traced" % (nums["traced"], nums["checked"]),
        "pass" if not nums["untraced"] else "warn",
        "untraced=" + ",".join(nums["untraced"][:8]))
    add("id_map", "content_map 元素 id 全部存在于 SVG",
        "%d/%d" % (coverage["on_canvas"], coverage["elements"]),
        "pass" if coverage["on_canvas"] == coverage["elements"] else "fail", "content_map")
    import os as _os
    _fname = _os.path.basename(font_rep.get("sans") or "") or "none"
    add("font_provenance", "记录实际字体与替换情况",
        _fname + (" cjk" if font_rep.get("sans_cjk_capable") else " latin-only"),
        "pass" if font_rep.get("sans") or png_rec.get("engine") in ("pymupdf", "cairosvg") else "warn",
        "source=%s" % font_rep.get("source", ""))
    return checks


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def material_haystack(input_dir, files=None):
    """Concatenate every readable text-ish material into one normalised haystack."""
    parts = []
    base = Path(input_dir)
    if not base.is_dir():
        return ""
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip",
                                   ".pptx", ".docx", ".xlsx"):
            continue
        try:
            if path.stat().st_size > 2_500_000:
                continue
        except Exception:
            continue
        txt = C.read_text(path)
        if txt:
            parts.append(txt)
    return norm_key(" \n ".join(parts))


