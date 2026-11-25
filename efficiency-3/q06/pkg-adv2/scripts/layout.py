"""layout.py - geometry, typography and the fit computation.

A deck fails in the real world for boring reasons: a bullet wraps to six lines
inside a four-line placeholder, or the generator "fixes" it by shrinking the
text until nobody in row 20 can read it.  So this module does three things and
nothing else:

1. turn a box (inches) into a text capacity (pt) with a real width model
   (:func:`util.display_width`, CJK aware);
2. choose the *largest* size from a declared ladder that fits, never below the
   declared minimum, and if nothing fits say which structural fix to apply
   (``split`` / ``trim`` / ``table-shrink``) instead of shrinking further;
3. expose the exact resolved geometry so the .pptx builder can place shapes at
   the computed positions - the audit then checks the file against this spec,
   not against a hope.

Units: inches for boxes, points for type.
"""
from __future__ import annotations

from util import clamp, display_width

EMU_PER_IN = 914400.0
PT_PER_IN = 72.0

# Built-in fallback geometry for a 16:9 deck (used when no template is supplied
# or the template has no usable body placeholders).
DEFAULT_SLIDE = {"w_in": 13.333, "h_in": 7.5}
DEFAULT_GEOMETRY = {
    "margin_x": 0.62, "margin_top": 0.45, "margin_bottom": 0.34,
    "title_h": 1.06, "footer_h": 0.30, "gutter": 0.28,
    "body_top": 1.62,
}

TITLE_LADDER = (34, 32, 30, 28, 26, 24)
BODY_LADDER = (22, 20, 18, 16)
NOTE_MIN = 16          # pt: never render an audience-visible glyph below this
CAPTION_LADDER = (13, 12, 11)
KPI_LADDER = (44, 40, 36, 32, 28)

LINE_SPACING = 1.16
SPACE_AFTER = 6.0


def in_to_pt(x: float) -> float:
    return x * PT_PER_IN


def in_to_emu(x: float) -> int:
    return int(round(x * EMU_PER_IN))


def pt_to_emu(x: float) -> int:
    return int(round(x * EMU_PER_IN / PT_PER_IN))


# ---------------------------------------------------------------- width model

def wrap_lines(text: str, width_in: float, size_pt: float, *, bold: bool = False,
               max_lines: int = 60) -> list[str]:
    """Greedy wrap using the em-advance model. Returns the visual lines."""
    text = (text or "").replace("\u00a0", " ")
    if not text.strip():
        return []
    width_pt = in_to_pt(width_in)
    bold_k = 1.045 if bold else 1.0
    # capacity in em units for this line width
    limit_em = width_pt / (size_pt * bold_k)
    lines: list[str] = []
    cur = ""
    curw = 0.0
    for token in _tokenize(text):
        tw = display_width(token)
        if cur and curw + tw > limit_em:
            lines.append(cur.rstrip())
            cur = "" if token == " " else token
            curw = 0.0 if token == " " else tw
        else:
            cur += token
            curw += tw
        if len(lines) >= max_lines:
            break
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def _tokenize(text: str):
    """Split into wrap atoms: CJK chars stand alone, Latin runs with trailing space."""
    out = []
    buf = ""
    for ch in text:
        if display_width(ch) >= 0.99:          # wide glyph: its own atom
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        elif ch == " ":
            buf += ch
            out.append(buf)
            buf = ""
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


def text_height_pt(lines: int, size_pt: float, *, spacing: float = LINE_SPACING,
                   space_after: float = 0.0) -> float:
    if lines <= 0:
        return 0.0
    return lines * size_pt * spacing + space_after


# ---------------------------------------------------------------- fit

def fit_text(text: str, box_in: dict, *, ladder=BODY_LADDER, bold: bool = False,
             min_pt: int = NOTE_MIN, spacing: float = LINE_SPACING) -> dict:
    """Find the largest size in *ladder* whose wrapped text fits *box_in*."""
    w, h = box_in["w_in"], box_in["h_in"]
    height_pt = in_to_pt(h)
    tried = []
    for size in sorted(set(ladder), reverse=True):
        if size < min_pt:
            break
        lines = wrap_lines(text, w, size, bold=bold)
        need = text_height_pt(len(lines), size, spacing=spacing)
        tried.append({"size_pt": size, "lines": len(lines), "need_pt": round(need, 1)})
        if need <= height_pt:
            return {
                "ok": True, "size_pt": size, "lines": len(lines),
                "need_pt": round(need, 1), "box_pt": round(height_pt, 1),
                "fill_ratio": round(need / height_pt, 3) if height_pt else 0.0,
                "lines_text": lines, "tried": tried, "action": "none",
            }
    size = max(min_pt, min(ladder) if ladder else min_pt)
    lines = wrap_lines(text, w, size, bold=bold)
    need = text_height_pt(len(lines), size, spacing=spacing)
    overflow = round(need - height_pt, 1)
    return {
        "ok": False, "size_pt": size, "lines": len(lines),
        "need_pt": round(need, 1), "box_pt": round(height_pt, 1),
        "fill_ratio": round(need / height_pt, 3) if height_pt else 0.0,
        "lines_text": lines, "tried": tried,
        "overflow_pt": overflow, "action": "split",
        "message": (f"does not fit at the {min_pt}pt floor (needs {overflow:.0f}pt more); "
                    f"split the page or move text to speaker notes rather than shrinking"),
    }


def fit_bullets(bullets: list[str], box_in: dict, *, ladder=BODY_LADDER,
                min_pt: int = NOTE_MIN, bullet_indent_in: float = 0.32,
                space_after: float = SPACE_AFTER) -> dict:
    """Fit an itemised list.  Per-item sizes are uniform (a slide is not a ransom note)."""
    items = [b for b in bullets if str(b).strip()]
    if not items:
        return {"ok": True, "size_pt": min(ladder) if ladder else min_pt, "items": [],
                "lines": 0, "need_pt": 0.0, "action": "none"}
    w = max(0.5, box_in["w_in"] - bullet_indent_in)
    height_pt = in_to_pt(box_in["h_in"])
    tried = []
    for size in sorted(set(ladder), reverse=True):
        if size < min_pt:
            break
        rendered = []
        total = 0.0
        for it in items:
            lines = wrap_lines(str(it), w, size)
            rendered.append({"text": it, "lines": lines})
            total += text_height_pt(len(lines), size, space_after=space_after)
        tried.append({"size_pt": size, "need_pt": round(total, 1)})
        if total <= height_pt:
            return {"ok": True, "size_pt": size, "items": rendered,
                    "lines": sum(len(r["lines"]) for r in rendered),
                    "need_pt": round(total, 1), "box_pt": round(height_pt, 1),
                    "fill_ratio": round(total / height_pt, 3), "tried": tried,
                    "action": "none"}
    size = max(min_pt, min(ladder) if ladder else min_pt)
    rendered, total = [], 0.0
    for it in items:
        lines = wrap_lines(str(it), w, size)
        rendered.append({"text": it, "lines": lines})
        total += text_height_pt(len(lines), size, space_after=space_after)
    overflow = round(total - height_pt, 1)
    return {
        "ok": False, "size_pt": size, "items": rendered,
        "lines": sum(len(r["lines"]) for r in rendered),
        "need_pt": round(total, 1), "box_pt": round(height_pt, 1),
        "fill_ratio": round(total / height_pt, 3), "tried": tried,
        "overflow_pt": overflow,
        "action": "trim" if len(items) > 3 else "split",
        "message": (f"{len(items)} bullets need {overflow:.0f}pt more than the box at the "
                    f"{min_pt}pt floor; move {max(1, len(items) - 3)} bullet(s) to the "
                    f"speaker notes or split the page"),
    }


def fit_table(table: dict, box_in: dict, *, min_row_pt: float = 15.0,
              size_ladder=(14, 13, 12, 11)) -> dict:
    """Column widths from content, rows checked against the box."""
    cols = table.get("columns") or []
    rows = table.get("rows") or []
    if not cols and not rows:
        return {"ok": True, "size_pt": size_ladder[0], "columns_in": [box_in["w_in"]],
                "rows": 0, "need_pt": 0.0, "box_pt": round(in_to_pt(box_in["h_in"]), 1),
                "fill_ratio": 0.0, "action": "none", "missing": True}
    ncols = max(1, len(cols) or (max((len(r) for r in rows), default=1)))
    weights = []
    for j in range(ncols):
        head = str(cols[j]) if j < len(cols) else ""
        widest = max([display_width(head)] +
                     [display_width(str(r[j])) for r in rows if j < len(r)] or [1.0])
        weights.append(max(2.0, min(14.0, widest)))
    tot = sum(weights) or 1.0
    widths_in = [round(box_in["w_in"] * w / tot, 3) for w in weights]
    height_pt = in_to_pt(box_in["h_in"])
    nrows = len(rows) + (1 if cols else 0)
    for size in size_ladder:
        if size < 9:
            break
        # per-cell wrap determines the row height
        row_heights = []
        if cols:
            row_heights.append(max([len(wrap_lines(str(c), widths_in[j] - 0.09, size))
                                    for j, c in enumerate(cols)] or [1]))
        for r in rows:
            row_heights.append(max([len(wrap_lines(str(r[j]) if j < len(r) else "",
                                                    widths_in[j] - 0.09, size))
                                    for j in range(ncols)] or [1]))
        need = sum(max(min_row_pt, h * size * 1.12 + 4.0) for h in row_heights)
        if need <= height_pt:
            return {"ok": True, "size_pt": size, "columns_in": widths_in,
                    "rows": nrows, "need_pt": round(need, 1),
                    "box_pt": round(height_pt, 1),
                    "fill_ratio": round(need / height_pt, 3) if height_pt else 0.0,
                    "action": "none"}
    return {"ok": False, "size_pt": size_ladder[-1], "columns_in": widths_in,
            "rows": nrows, "need_pt": round(need, 1), "box_pt": round(height_pt, 1),
            "overflow_pt": round(need - height_pt, 1), "action": "table-shrink",
            "message": (f"table needs {need - height_pt:.0f}pt more than the box; "
                        f"show the decisive rows on the slide and keep the rest in the "
                        f"appendix or speaker notes")}


# ---------------------------------------------------------------- page spec

def slide_boxes(slide_w_in: float, slide_h_in: float, geometry: dict | None = None) -> dict:
    g = dict(DEFAULT_GEOMETRY)
    if geometry:
        g.update({k: v for k, v in geometry.items() if v is not None})
    m = g["margin_x"]
    content_w = slide_w_in - 2 * m
    return {
        "slide": {"w_in": slide_w_in, "h_in": slide_h_in},
        "title": {"x_in": m, "y_in": g["margin_top"], "w_in": content_w,
                  "h_in": g["title_h"]},
        "subtitle": {"x_in": m, "y_in": g["margin_top"] + g["title_h"] * 0.72,
                     "w_in": content_w, "h_in": 0.5},
        "body": {"x_in": m, "y_in": g["body_top"], "w_in": content_w,
                 "h_in": slide_h_in - g["body_top"] - g["margin_bottom"] - g["footer_h"]},
        "left": {"x_in": m, "y_in": g["body_top"],
                 "w_in": (content_w - g["gutter"]) / 2,
                 "h_in": slide_h_in - g["body_top"] - g["margin_bottom"] - g["footer_h"]},
        "right": {"x_in": m + (content_w - g["gutter"]) / 2 + g["gutter"],
                  "y_in": g["body_top"],
                  "w_in": (content_w - g["gutter"]) / 2,
                  "h_in": slide_h_in - g["body_top"] - g["margin_bottom"] - g["footer_h"]},
        "figure": None, "caption": None, "footer": {
            "x_in": m, "y_in": slide_h_in - g["margin_bottom"] - g["footer_h"] + 0.04,
            "w_in": content_w * 0.7, "h_in": g["footer_h"]},
        "pagenum": {"x_in": slide_w_in - m - 1.4,
                    "y_in": slide_h_in - g["margin_bottom"] - g["footer_h"] + 0.04,
                    "w_in": 1.4, "h_in": g["footer_h"]},
        "geometry": g, "content_w_in": content_w,
    }


def plan_slide_layout(slide: dict, boxes: dict, *, with_figure: bool = False,
                      with_table: bool = False, with_kpis: bool = False) -> dict:
    """Resolve one page to concrete, sized regions.  This is the spec the builder uses."""
    out = {"slide": slide.get("id"), "role": slide.get("role"), "regions": {},
           "fit": {}, "actions": []}

    title_fit = fit_text(slide.get("title") or "", boxes["title"], ladder=TITLE_LADDER,
                         bold=True, min_pt=24)
    out["fit"]["title"] = title_fit
    out["regions"]["title"] = dict(boxes["title"], size_pt=title_fit["size_pt"])

    claim = slide.get("claim") or ""
    bullets = [str(b) for b in (slide.get("bullets") or []) if str(b).strip()]
    kpis = slide.get("kpis") or []

    if with_kpis and kpis:
        kpi_box = {"x_in": boxes["body"]["x_in"], "y_in": boxes["body"]["y_in"],
                   "w_in": boxes["body"]["w_in"], "h_in": min(1.5, boxes["body"]["h_in"] * 0.34)}
        kpi_fit = []
        for k in kpis:
            kpi_fit.append(fit_text(str(k.get("value") or ""), kpi_box, ladder=KPI_LADDER,
                                    bold=True, min_pt=28))
        out["fit"]["kpis"] = kpi_fit
        out["regions"]["kpis"] = dict(kpi_box, size_pt=max(f["size_pt"] for f in kpi_fit))
        rest = {"x_in": boxes["body"]["x_in"],
                "y_in": kpi_box["y_in"] + kpi_box["h_in"] + 0.12,
                "w_in": boxes["body"]["w_in"],
                "h_in": max(0.6, boxes["body"]["y_in"] + boxes["body"]["h_in"]
                            - (kpi_box["y_in"] + kpi_box["h_in"] + 0.12))}
        body_box = rest
    elif with_figure or with_table:
        fig = slide.get("figure") or {}
        tbl = slide.get("table") or {}
        body = boxes["body"]
        col_w = (body["w_in"] - 0.3) / 2
        if with_figure:
            asset = bool(fig.get("asset"))
            fig_h = (min(body["h_in"] - 0.62, col_w * 0.68) if asset
                     else min(2.75, body["h_in"] * 0.62))
            fig_box = {"x_in": body["x_in"], "y_in": body["y_in"], "w_in": col_w,
                       "h_in": max(1.0, fig_h)}
            cap_box = {"x_in": body["x_in"], "y_in": fig_box["y_in"] + fig_box["h_in"] + 0.05,
                       "w_in": col_w, "h_in": 0.62}
            cap_fit = fit_text(fig.get("caption") or "", cap_box, ladder=CAPTION_LADDER,
                               min_pt=11)
            out["fit"]["caption"] = cap_fit
            out["regions"]["figure"] = dict(fig_box, size_pt=0)
            out["regions"]["caption"] = dict(cap_box, size_pt=cap_fit["size_pt"])
        else:
            fig_box = None
        text_box = {"x_in": body["x_in"] + (col_w + 0.3 if (with_figure or with_table) else 0),
                    "y_in": body["y_in"],
                    "w_in": col_w if (with_figure or with_table) else body["w_in"],
                    "h_in": body["h_in"]}
        if with_table:
            tbl_box = {"x_in": body["x_in"], "y_in": body["y_in"], "w_in": col_w,
                       "h_in": body["h_in"]}
            tfit = fit_table(tbl, tbl_box)
            out["fit"]["table"] = tfit
            out["regions"]["table"] = dict(tbl_box, size_pt=tfit["size_pt"],
                                           columns_in=tfit["columns_in"])
        body_box = text_box
    else:
        body_box = dict(boxes["body"])

    if claim and not with_kpis:
        lead_box = {"x_in": body_box["x_in"], "y_in": body_box["y_in"],
                    "w_in": body_box["w_in"], "h_in": 0.78}
        lead_fit = fit_text(claim, lead_box, ladder=(20, 18, 16), min_pt=16, bold=True)
        out["fit"]["claim"] = lead_fit
        out["regions"]["claim"] = dict(lead_box, size_pt=lead_fit["size_pt"])
        body_box = {"x_in": body_box["x_in"], "y_in": lead_box["y_in"] + lead_box["h_in"] + 0.08,
                    "w_in": body_box["w_in"],
                    "h_in": max(0.6, body_box["y_in"] + body_box["h_in"]
                                - (lead_box["y_in"] + lead_box["h_in"] + 0.08))}

    if bullets:
        bfit = fit_bullets(bullets, body_box)
        out["fit"]["bullets"] = bfit
        out["regions"]["bullets"] = dict(body_box, size_pt=bfit["size_pt"])
    elif "bullets" not in out["regions"]:
        out["regions"]["bullets"] = dict(body_box, size_pt=0)

    for name in ("title", "claim", "bullets", "caption", "table"):
        f = out["fit"].get(name)
        if isinstance(f, dict) and not f.get("ok", True):
            out["actions"].append({"region": name, "action": f.get("action", "split"),
                                   "message": f.get("message", "")})
    return out


def overflow_report(specs: list[dict]) -> dict:
    bad = [s for s in specs if s["actions"]]
    return {
        "slides": len(specs),
        "slides_with_overflow": len(bad),
        "min_font_pt": min((f["size_pt"] for s in specs for f in s["fit"].values()
                            if isinstance(f, dict) and f.get("size_pt")), default=None),
        "actions": [{"slide": s["slide"], **a} for s in bad for a in s["actions"]],
        "ok": not bad,
    }
