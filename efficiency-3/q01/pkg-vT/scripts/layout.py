#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout -- figure IR -> deterministic drawing scene.

The scene is a flat list of primitives that three backends (SVG, PNG, PDF)
consume, so the editable source, the raster preview and the vector export can
never drift apart.  All geometry is derived from the canvas size and the text
metrics in ga_core; nothing depends on a clock, a random seed or a renderer
query, therefore two runs of the same IR are byte-identical.

Overflow is handled by a fixed repair ladder (see REPAIR_LADDER) and every step
that fires is recorded, so an "it does not fit" case is explainable after the
fact instead of silently producing a broken page.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # never leave __pycache__ behind


import ga_core as C

INK = "#1A1A1E"
MUTED = "#5A5F66"
LINE = "#9AA0A6"
PANEL_BG = "#F7F8FA"
PANEL_EDGE = "#D5D9DE"
ACCENT = "#0B4F8A"
ARROW = "#3C4043"

REPAIR_LADDER = [
    ("drop_low_priority", "删除 priority=low 的条目"),
    ("tighter_spacing", "行距/内边距压到最小值"),
    ("step_down_font", "按 6% 步进缩小正文字号（不低于 canvas.min_font_px）"),
    ("elide_text", "超长条目截断并加省略号"),
    ("shrink_claim", "面板 claim 由 2 行压为 1 行"),
]


def _r(v):
    """Round geometry so serialisation is stable and compact."""
    try:
        return round(float(v), 1)
    except Exception:
        return 0.0


def sizes(width):
    w = float(width)
    def clamp(v, lo, hi):
        return max(lo, min(hi, v))
    return {
        "title": clamp(0.0280 * w, 30, 72),
        "subtitle": clamp(0.0135 * w, 16, 36),
        "role": clamp(0.0090 * w, 12, 24),
        "ptitle": clamp(0.0115 * w, 13, 30),
        "body": clamp(0.0115 * w, 13, 30),
        "small": clamp(0.0090 * w, 10, 24),
        "tiny": clamp(0.0078 * w, 9, 20),
    }


# --------------------------------------------------------------------------
# primitive helpers
# --------------------------------------------------------------------------
def _rect(prims, x, y, w, h, fill="none", stroke="none", sw=1.0, rx=0,
          dash=None, pattern=None, layer="panels", pid="", opacity=None):
    prims.append({
        "t": "rect", "x": _r(x), "y": _r(y), "w": _r(w), "h": _r(h),
        "fill": fill, "stroke": stroke, "sw": _r(sw), "rx": _r(rx),
        "dash": dash or "", "pattern": pattern or "", "layer": layer,
        "id": pid or "", "opacity": opacity,
    })


def _line(prims, x1, y1, x2, y2, stroke=LINE, sw=1.0, dash=None, layer="frame", pid=""):
    prims.append({
        "t": "line", "x1": _r(x1), "y1": _r(y1), "x2": _r(x2), "y2": _r(y2),
        "stroke": stroke, "sw": _r(sw), "dash": dash or "", "layer": layer,
        "id": pid or "",
    })


def _poly(prims, pts, fill="none", stroke="none", sw=1.0, layer="relations", pid=""):
    prims.append({
        "t": "poly", "pts": [[_r(a), _r(b)] for a, b in pts],
        "fill": fill, "stroke": stroke, "sw": _r(sw), "layer": layer,
        "id": pid or "",
    })


def _circle(prims, cx, cy, r, fill="none", stroke="none", sw=1.0, layer="relations", pid=""):
    prims.append({"t": "circle", "cx": _r(cx), "cy": _r(cy), "r": _r(r),
                  "fill": fill, "stroke": stroke, "sw": _r(sw), "layer": layer,
                  "id": pid or ""})


def _text(prims, x, y, s, size, anchor="start", bold=False, italic=False,
          fill=INK, layer="labels", pid="", family="sans", role=""):
    prims.append({
        "t": "text", "x": _r(x), "y": _r(y), "s": s or "", "size": _r(size),
        "anchor": anchor, "bold": bool(bold), "italic": bool(italic),
        "fill": fill, "layer": layer, "id": pid or "", "family": family,
        "role": role or "",
    })


def _marker(prims, x, y, kind, color, size=7.0, layer="relations", pid=""):
    """Arrow head vocabulary -- one shape per relation type."""
    s = float(size)
    if kind == "bar":
        _line(prims, x, y - s * 0.85, x, y + s * 0.85, color, 2.2, layer=layer, pid=pid)
    elif kind == "circle":
        _circle(prims, x, y, s * 0.62, fill="#FFFFFF", stroke=color, sw=1.8, layer=layer, pid=pid)
    elif kind == "diamond":
        _poly(prims, [(x, y - s * 0.9), (x + s * 0.66, y), (x, y + s * 0.9),
                      (x - s * 0.66, y)], fill=color, stroke=color, sw=1.0, layer=layer, pid=pid)
    elif kind == "cross":
        _line(prims, x - s * 0.7, y - s * 0.7, x + s * 0.7, y + s * 0.7, color, 2.2,
              layer=layer, pid=pid)
        _line(prims, x - s * 0.7, y + s * 0.7, x + s * 0.7, y - s * 0.7, color, 2.2,
              layer=layer, pid=(pid + "-b") if pid else "")
    else:  # arrow
        _poly(prims, [(x, y), (x - s * 0.62, y - s * 0.66), (x - s * 0.62, y + s * 0.66)],
              fill=color, stroke=color, sw=1.0, layer=layer, pid=pid)


def _color_for(idx, explicit=""):
    if explicit and explicit.startswith("#"):
        return explicit
    return C.PALETTE[idx % len(C.PALETTE)]["hex"]


def _clip_seg(x1, y1, x2, y2, x, y, w, h):
    t0, t1 = 0.0, 1.0
    dx, dy = x2 - x1, y2 - y1
    for pp, qq in ((-dx, x1 - x), (dx, x + w - x1), (-dy, y1 - y), (dy, y + h - y1)):
        if abs(pp) < 1e-12:
            if qq < 0:
                return None
            continue
        r = qq / pp
        if pp < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return (x1 + t0 * dx, y1 + t0 * dy, x1 + t1 * dx, y1 + t1 * dy)


def _hatch(prims, x, y, w, h, pattern, layer, pid, step=None, color="#1A1A1E", sw=1.05):
    """Greyscale-safe fill: real clipped line segments, not an SVG <pattern>.

    Patterns are emitted as geometry because renderer support for SVG <pattern>
    differs (some fill it solid black); drawing the lines ourselves keeps SVG,
    PNG and PDF pixel-identical.
    """
    if not pattern or pattern == "none" or w <= 1 or h <= 1:
        return 0
    step = float(step or max(5.5, min(9.5, h / 2.2)))
    segs = []
    if pattern in ("hatch45", "hatch135"):
        sign = -1.0 if pattern == "hatch45" else 1.0
        d = -h
        while d <= w:
            got = _clip_seg(x + d, y, x + d + sign * h, y + h, x, y, w, h)
            if got:
                segs.append(got)
            d += step
    elif pattern == "hatch90":
        xx = x
        while xx <= x + w:
            segs.append((xx, y, xx, y + h))
            xx += step
    elif pattern == "dots":
        yy = y + step * 0.5
        while yy < y + h:
            xx = x + step * 0.5
            while xx < x + w:
                segs.append((xx, yy, xx + 0.01, yy))
                xx += step
            yy += step
    elif pattern in ("cross", "grid"):
        xx = x
        while xx <= x + w:
            segs.append((xx, y, xx, y + h))
            xx += step
        if pattern == "cross":
            yy = y
            while yy <= y + h:
                segs.append((x, yy, x + w, yy))
                yy += step
    for i, (a, b, c, d) in enumerate(segs):
        if abs(c - a) < 0.02 and abs(d - b) < 0.02:
            _circle(prims, a, b, max(0.9, sw * 0.55), fill=color, layer=layer,
                    pid="%s-h%d" % (pid, i) if pid else "")
        else:
            _line(prims, a, b, c, d, color, sw, layer=layer,
                  pid="%s-h%d" % (pid, i) if pid else "")
    return len(segs)


def _pattern_for(idx):
    return C.PATTERNS[idx % len(C.PATTERNS)]


# --------------------------------------------------------------------------
# legend derivation -- legend is *derived from what is drawn*, never hand typed,
# so "legend entry count == category count on canvas" holds by construction and
# is then re-verified by provenance.legend_gate().
# --------------------------------------------------------------------------
def derive_legend(ir, include_series=True):
    items = []
    rel_types = []
    for r in ir.get("relations", []):
        if r.get("unresolved"):
            continue
        if r["type"] not in rel_types:
            rel_types.append(r["type"])
    for i, rt in enumerate(rel_types):
        g = C.RELATION_GRAMMAR.get(rt, C.RELATION_GRAMMAR["unknown"])
        items.append({
            "key": "rel-%s" % rt, "label": "%s / %s" % (g["zh"], g["en"]),
            "channel": "marker", "marker": g["marker"], "dash": g["dash"],
            "color": ARROW, "pattern": "none", "category": "relation",
            "source": {"id": "", "path": "", "locator": "", "quote": ""},
        })
    for ci, ch in enumerate(ir.get("charts", [])):
        if not include_series:
            break
        for si, s in enumerate(ch["series"]):
            key = s.get("color_key") or "c%d" % (si + 1)
            items.append({
                "key": key, "label": s["name"] or ("series %d" % (si + 1)),
                "channel": "fill", "color": _color_for(si, ""),
                "pattern": _pattern_for(si), "marker": "", "dash": False,
                "category": "series",
                "source": s.get("source") or {"id": "", "path": "", "locator": "", "quote": ""},
            })
    has_gene = any(e.get("italic") for e in ir.get("entities", []))
    if has_gene:
        items.append({
            "key": "note-italic", "label": "斜体=基因，正体=蛋白",
            "channel": "text", "color": INK, "pattern": "none", "marker": "",
            "dash": False, "category": "note",
            "source": {"id": "", "path": "", "locator": "", "quote": ""},
        })
    explicit = ir.get("legend") or []
    for li in explicit:
        if not li.get("key"):
            continue
        if any(x["key"] == li["key"] for x in items):
            continue
        items.append({
            "key": li["key"], "label": li["label"], "channel": li["channel"],
            "color": li["color"] or ARROW, "pattern": li["pattern"],
            "marker": li["marker"], "dash": False, "category": li.get("category", "declared"),
            "source": li.get("source") or {"id": "", "path": "", "locator": "", "quote": ""},
        })
    return items


# --------------------------------------------------------------------------
# panel bodies
# --------------------------------------------------------------------------
def _body_bullets(panel, box, S, body_size, spacing, prims, panel_idx, allow_extra):
    x, y, w = box["x"], box["y"], box["w"]
    pad = S["small"] * 0.62
    avail = box["h"]
    items = panel["items"]
    if not allow_extra:
        items = [it for it in items if it.get("priority") != "low"]
    ih = body_size * 1.45
    gap = spacing * body_size
    cy = y
    dropped = []
    usable = [it for it in items if (it.get("text") or "").strip()]
    extra = min(box.get("slack", 0.0) / max(1, len(usable)), body_size * 1.2)
    first = True
    for it in items:
        txt = (it.get("text") or "").strip()
        if not txt:
            continue
        lines = C.wrap_text(txt, body_size, w - pad * 2 - body_size * 0.9)
        need = len(lines) * ih + (gap if cy > y else 0)
        if cy + need > y + avail - 2:
            # one last chance: single elided line
            single = C.fit_text(txt, body_size, w - pad * 2 - body_size * 0.9)
            if single and cy + ih <= y + avail - 2:
                lines = [single]
            else:
                dropped.append(it["id"])
                continue
        cy += (gap + extra) if cy > y else 0
        _circle(prims, x + pad + body_size * 0.28, cy + body_size * 0.52,
                max(1.6, body_size * 0.14), fill=ACCENT, layer="entities",
                pid="%s-b%d" % (panel_idx, len(dropped)))
        lead = (it.get("kind") or "").strip()
        if lead and lead not in ("item", "bullet"):
            _text(prims, x + pad, cy + body_size, lead, S["tiny"], bold=True,
                  fill=ACCENT, pid="%s-tag" % it["id"], layer="labels")
            tx = x + pad + C.text_width(lead, S["tiny"], True) + S["tiny"] * 0.6
        else:
            tx = x + pad + body_size * 0.9
        for li, ln in enumerate(lines):
            _text(prims, tx, cy + body_size + li * ih, ln, body_size,
                  fill=INK, pid="%s-l%d" % (it["id"], li), layer="labels")
        cy += len(lines) * ih
    return cy - y, dropped


def _body_chain(panel, box, S, body_size, spacing, prims, panel_idx, allow_extra):
    x, y, w = box["x"], box["y"], box["w"]
    pad = S["small"] * 0.55
    avail = box["h"]
    items = [it for it in panel["items"] if (it.get("text") or "").strip()]
    if not allow_extra:
        items = [it for it in items if it.get("priority") != "low"]
    if not items:
        return 0.0, []
    fs = body_size - 1.2
    per_row = 1 if w < 260 else 2
    arrow_gap = fs * 1.5
    bw = (w - pad * 2 - arrow_gap * (per_row - 1)) / per_row
    cy = y
    dropped = []
    n = 0
    rows = max(1, (len(items) + per_row - 1) // per_row)
    row_extra = min(box.get("slack", 0.0) / rows, fs * 1.4)
    for row_start in range(0, len(items), per_row):
        chunk = items[row_start:row_start + per_row]
        heights = []
        for it in chunk:
            lines = C.wrap_text(it["text"], fs, bw - fs * 1.1)
            heights.append(max(1, len(lines)) * fs * 1.35 + fs * 0.9)
        bh = max(heights) if heights else fs * 2
        if cy + bh > y + avail - 1:
            for it in items[row_start:]:
                dropped.append(it["id"])
            break
        for k, it in enumerate(chunk):
            bx = x + pad + k * (bw + arrow_gap)
            _rect(prims, bx, cy, bw, bh, fill="#FFFFFF", stroke=PANEL_EDGE, sw=1.0,
                  rx=fs * 0.35, layer="entities", pid="%s-step%d" % (panel_idx, n))
            num = "%d" % (n + 1)
            _circle(prims, bx + fs * 0.72, cy + bh / 2.0, fs * 0.58,
                    fill=ACCENT, layer="entities", pid="%s-num%d" % (panel_idx, n))
            _text(prims, bx + fs * 0.72, cy + bh / 2.0 + fs * 0.4, num, fs * 0.8,
                  anchor="middle", bold=True, fill="#FFFFFF",
                  pid="%s-numt%d" % (panel_idx, n))
            lines = C.wrap_text(it["text"], fs, bw - fs * 1.9)
            ty = cy + bh / 2.0 - (len(lines) - 1) * fs * 0.68 + fs * 0.42
            for li, ln in enumerate(lines):
                _text(prims, bx + fs * 1.45, ty + li * fs * 1.35, ln, fs,
                      fill=INK, pid="%s-w%d-%d" % (panel_idx, n, li))
            if k < len(chunk) - 1:
                ax1 = bx + bw + fs * 0.18
                ax2 = bx + bw + arrow_gap - fs * 0.18
                mid = cy + bh / 2.0
                _line(prims, ax1, mid, ax2 - fs * 0.35, mid, ARROW, 1.6, layer="relations")
                _marker(prims, ax2, mid, "arrow", ARROW, fs * 0.62, layer="relations")
            n += 1
        cy += bh + fs * 0.9 + row_extra
    return cy - y, dropped


def _body_relations(panel, box, S, body_size, spacing, prims, panel_idx, allow_extra):
    """Vertical pathway: entity stacks with a left gutter of typed edges.

    Every edge gets its own lane so two relations that share a source never
    print on top of each other; the lane x position is a pure function of the
    edge index, so the drawing is reproducible.
    """
    x, y, w = box["x"], box["y"], box["w"]
    pad = S["small"] * 0.45
    avail = box["h"]
    rels = [r for r in panel.get("_relations", []) if not r.get("unresolved")]
    if not rels:
        return 0.0, []
    order, seen = [], set()
    for r in rels:
        for eid in (r["from"], r["to"]):
            if eid and eid not in seen:
                seen.add(eid)
                order.append(eid)
    ents = {e["id"]: e for e in panel.get("_entities", [])}
    fs = body_size - 1.6
    gutter = fs * 3.4
    box_h = fs * 1.95
    slots_n = max(1, len(order))
    gap = fs * 1.75 + min(box.get("slack", 0.0) / slots_n, fs * 1.5)
    bx = x + gutter
    bw = w - gutter
    dropped = []
    slots = []
    cy = y
    for eid in order:
        need = box_h if not slots else box_h + gap
        if cy + need > y + avail - 1:
            dropped.append(eid)
            continue
        cy += gap if slots else 0
        slots.append((eid, cy))
        cy += box_h
    if not slots:
        return 0.0, dropped
    idpos = dict(slots)
    # label size must fit the gutter (~4 CJK chars); never let it clip
    lab_size = S["tiny"] * 0.80
    lab_max = max(fs * 0.9, gutter - fs * 1.35)
    # edges first (so boxes overlap them cleanly)
    lanes = {}
    for r in rels:
        if r["from"] not in idpos or r["to"] not in idpos:
            continue
        key = r["from"]
        lane = lanes.get(key, 0)
        lanes[key] = lane + 1
        lx = x + pad + fs * 0.55 + (lane % 2) * fs * 0.75
        y1 = idpos[r["from"]] + box_h
        y2 = idpos[r["to"]]
        if y2 <= y1 + 1:
            y2 = y1 + gap
        g = C.RELATION_GRAMMAR.get(r["type"], C.RELATION_GRAMMAR["unknown"])
        dash = "5 3" if g["dash"] else ""
        label = (r.get("label") or "").strip()
        if label:
            # the label sits in the empty band just above the target node, where the
            # full panel width is free, so edges never clip their own text
            avail = max(fs * 1.2, (x + w) - (lx + fs * 0.6))
            lsize = lab_size
            while lsize > S["tiny"] * 0.62 and C.text_width(label, lsize) > avail:
                lsize *= 0.90
            _line(prims, lx, y1, lx, y2 - fs * 0.26, ARROW, 1.5, dash=dash,
                  layer="relations", pid="edge-%s-a" % r["id"])
            _text(prims, lx + fs * 0.6, y2 - fs * 0.32,
                  C.fit_text(label, lsize, avail), lsize, fill=MUTED,
                  pid="edge-%s-label" % r["id"], layer="labels")
        else:
            _line(prims, lx, y1, lx, y2 - fs * 0.26, ARROW, 1.5, dash=dash,
                  layer="relations", pid="edge-%s-line" % r["id"])
        _marker(prims, lx, y2 - fs * 0.05, g["marker"], ARROW, fs * 0.55,
                layer="relations", pid="edge-%s-head" % r["id"])
    for eid, by in slots:
        e = ents.get(eid, {"id": eid, "label": eid, "type": "", "italic": False})
        label = e.get("label") or eid
        _rect(prims, bx, by, bw, box_h, fill="#FFFFFF", stroke=PANEL_EDGE, sw=1.0,
              rx=fs * 0.4, layer="entities", pid="ent-%s" % eid)
        italic = bool(e.get("italic"))
        _text(prims, bx + fs * 0.45, by + box_h / 2.0 + fs * 0.38,
              C.fit_text(label, fs, bw - fs * 0.9, italic), fs, italic=italic,
              fill=INK, pid="ent-%s-label" % eid, layer="labels")
        if e.get("type"):
            _text(prims, bx + bw - fs * 0.4, by + box_h / 2.0 + fs * 0.30, e["type"],
                  S["tiny"] * 0.9, anchor="end", fill=MUTED,
                  pid="ent-%s-type" % eid, layer="labels")
    return cy - y, dropped + [eid for eid in order if eid not in idpos]


def _body_chart(panel, box, S, body_size, prims, panel_idx, allow_extra):
    chart = panel.get("_chart")
    if not chart or not chart["series"]:
        return 0.0, []
    x, y, w = box["x"], box["y"], box["w"]
    pad = S["small"] * 0.5
    fs = S["small"] * 0.95
    n_groups = max(len(s["points"]) for s in chart["series"])
    n_series = len(chart["series"])
    all_vals = [p["y"] for s in chart["series"] for p in s["points"]]
    if not all_vals:
        return 0.0, []
    vmax = max(max(all_vals), 0.0)
    vmin = min(min(all_vals), 0.0)
    top = _nice_max(vmax)
    bottom = _nice_min(vmin)
    span = (top - bottom) or 1.0
    left_w = max(C.text_width(_axis_txt(bottom), fs) for _ in [0]) + fs * 0.6
    left_w = max(left_w, C.text_width(_axis_txt(top), fs) + fs * 0.6)
    plot_x = x + pad + left_w
    plot_w = w - pad * 2 - left_w - fs * 0.2
    legend_rows = 1 if n_series <= 2 else 2
    legend_h = legend_rows * (fs * 1.5) + fs * 0.4
    title_h = (fs * 1.7) if chart.get("title") else 0.0
    axis_title_h = (fs * 1.4) if (chart.get("y_label") or chart.get("unit")) else 0.0
    xlab_h = fs * 1.5
    plot_y = y + pad + title_h + axis_title_h
    plot_h = box["h"] - pad * 2 - title_h - axis_title_h - xlab_h - legend_h
    if plot_h < fs * 3.2:
        return 0.0, ["chart:%s" % chart["id"]]
    if chart.get("title"):
        _text(prims, x + pad, y + pad + fs * 1.1,
              C.fit_text(chart["title"], fs * 1.05, w - pad * 2), fs * 1.05,
              bold=True, fill=INK, pid="%s-chart-title" % panel_idx, layer="data")
    if axis_title_h:
        ax_t = (chart.get("y_label") or "") + \
               ((" (%s)" % chart["unit"]) if chart.get("unit") else "")
        _text(prims, x + pad, y + pad + title_h + fs * 1.0,
              C.fit_text(ax_t, fs * 0.95, w - pad * 2), fs * 0.95, fill=MUTED,
              pid="%s-axis-title" % panel_idx, layer="data")
    # y axis + ticks
    ticks = 4
    for k in range(ticks + 1):
        v = bottom + span * k / ticks
        ty = plot_y + plot_h - plot_h * (k / ticks)
        _line(prims, plot_x, ty, plot_x + plot_w, ty,
              "#EAECEF" if 0 < k < ticks else LINE, 0.8, layer="data")
        _text(prims, plot_x - fs * 0.45, ty + fs * 0.34, _axis_txt(v), fs * 0.92,
              anchor="end", fill=MUTED, pid="%s-ytick%d" % (panel_idx, k), layer="data")
    _line(prims, plot_x, plot_y, plot_x, plot_y + plot_h, LINE, 1.1, layer="data")
    _line(prims, plot_x, plot_y + plot_h, plot_x + plot_w, plot_y + plot_h, LINE, 1.1,
          layer="data")
    gw = plot_w / n_groups
    bw = gw / n_series * 0.72
    for si, s in enumerate(chart["series"]):
        color = _color_for(si)
        pat = _pattern_for(si)
        for pi, pt in enumerate(s["points"]):
            gx = plot_x + gw * pi + gw * 0.5
            bx = gx - (n_series * bw) / 2.0 + si * bw
            frac = (pt["y"] - bottom) / span
            bh = plot_h * frac - (plot_h * (0 - bottom) / span if bottom < 0 <= pt["y"] else 0)
            bh = max(0.0, plot_h * frac) if pt["y"] >= 0 else 0.0
            y0 = plot_y + plot_h - plot_h * ((pt["y"] - bottom) / span)
            ybar = min(plot_y + plot_h, y0)
            hbar = ybar - y0 if pt["y"] >= 0 else 0
            hbar = max(0.0, hbar)
            if pt["y"] == 0:
                _line(prims, bx, plot_y + plot_h, bx + bw, plot_y + plot_h, color, 2.0,
                      layer="data")
            else:
                use_pat = pat if (pat != "none" and bw >= fs * 0.8) else None
                _rect(prims, bx, y0, bw, hbar, fill=color, stroke=INK, sw=0.6,
                      layer="data", pid="%s-bar%d-%d" % (chart["id"], si, pi))
                _hatch(prims, bx, y0, bw, hbar, use_pat, "data",
                       "%s-bar%d-%d" % (chart["id"], si, pi),
                       step=max(5.0, bw * 0.72))
            if pt["err"]:
                ey = plot_h * (pt["err"] / span)
                _line(prims, bx + bw / 2.0, y0 - ey, bx + bw / 2.0, y0 + ey, INK, 1.2,
                      layer="data", pid="%s-err%d-%d" % (chart["id"], si, pi))
                for sgn in (-1, 1):
                    _line(prims, bx + bw * 0.22, y0 + sgn * ey, bx + bw * 0.78, y0 + sgn * ey,
                          INK, 1.2, layer="data")
            lab = pt.get("raw") if pt.get("raw") else _axis_txt(pt["y"])
            vsize = fs * (0.9 if n_series <= 2 else 0.80)
            _text(prims, bx + bw / 2.0, y0 - fs * 0.30, C.fit_text(str(lab), vsize, gw * 0.94),
                  vsize, anchor="middle", fill=INK,
                  pid="%s-val%d-%d" % (chart["id"], si, pi), layer="data")
        for pi, pt in enumerate(s["points"]):
            gx = plot_x + gw * (pi + 0.5)
            _text(prims, gx, plot_y + plot_h + fs * 1.15,
                  C.fit_text(str(pt.get("x") or ""), fs * 0.92, gw * 0.95), fs * 0.92,
                  anchor="middle", fill=INK, pid="%s-xtick%d" % (chart["id"], pi), layer="data")
    # in-chart legend
    ly = y + box["h"] - pad - legend_h + fs * 1.1
    lx = x + pad
    for si, s in enumerate(chart["series"]):
        sw_w = fs * 1.1
        _rect(prims, lx, ly - fs * 0.75, sw_w, fs * 0.85, fill=_color_for(si),
              stroke=INK, sw=0.5, layer="legend", pid="%s-leg%d" % (chart["id"], si))
        _hatch(prims, lx, ly - fs * 0.75, sw_w, fs * 0.85, _pattern_for(si), "legend",
               "%s-leg%d" % (chart["id"], si), step=max(4.5, sw_w / 2.4))
        _text(prims, lx + sw_w + fs * 0.4, ly - fs * 0.03,
              C.fit_text(s["name"], fs * 0.92, w * 0.42), fs * 0.92, fill=INK,
              pid="%s-legt%d" % (chart["id"], si), layer="legend")
        lx += sw_w + fs * 0.4 + C.text_width(s["name"], fs * 0.92) + fs * 1.1
        if lx > x + w - pad - fs * 3 and si < n_series - 1:
            lx = x + pad
            ly += fs * 1.5
    return box["h"], []


def _num_of(v):
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _nice_max(v):
    if v <= 0:
        return 0.0
    import math
    exp = math.floor(math.log10(v))
    base = 10 ** exp
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * base * 1.0000001:
            return m * base
    return 10 * base


def _nice_min(v):
    if v >= 0:
        return 0.0
    m = _nice_max(-v)
    return -m


def _axis_txt(v):
    if abs(v) >= 1000:
        return "%g" % v
    if abs(v) >= 10:
        return ("%g" % v)
    return ("%g" % v)


# --------------------------------------------------------------------------
# main scene builder
# --------------------------------------------------------------------------
def build_scene(ir):
    canvas = ir["canvas"]
    W, H = canvas["width_px"], canvas["height_px"]
    S = sizes(W)
    min_font = canvas["min_font_px"]
    bg = canvas["background"]
    prims = []
    repairs = []
    dropped = []
    _rect(prims, 0, 0, W, H, fill=bg, stroke="none", layer="frame", pid="canvas-bg")

    M = W * 0.028
    # ---------------- header ----------------
    ty = M + S["title"] * 0.92
    _text(prims, M, ty, C.fit_text(ir.get("title") or "", S["title"], W - 2 * M),
          S["title"], bold=True, fill=INK, pid="hdr-title", layer="labels", role="title")
    hy = ty + S["title"] * 0.42
    if ir.get("subtitle"):
        hy += S["subtitle"] * 0.95
        _text(prims, M, hy, C.fit_text(ir["subtitle"], S["subtitle"], W - 2 * M),
              S["subtitle"], fill=MUTED, pid="hdr-subtitle", layer="labels")
    head_bottom = hy + S["subtitle"] * 0.55

    # ---------------- footer / band geometry (content-hugging) ----------------
    has_chart = bool(ir["charts"]) and any(
        p["kind"] in ("chart", "data") and p["chart"] for p in ir["panels"])
    legend = derive_legend(ir, include_series=not has_chart)
    chart_series_in_legend = [s["name"] for ch in ir["charts"] for s in ch["series"]] if has_chart else []
    fs = S["small"]
    cap = (ir["notes"].get("caption") or "").strip()
    fig_no = ir["notes"].get("figure_no") or "Figure 1"
    cap_txt = ("%s. %s" % (fig_no, cap)) if cap else (
        "%s. 图形摘要：研究问题—方法—核心结果—结论单页。" % fig_no)
    cap_lines = C.wrap_text(cap_txt, S["tiny"] * 0.98, W - 2 * M, max_lines=2)
    foot_h = fs * 2.0 + S["tiny"] * 1.9 + len(cap_lines) * S["tiny"] * 1.4 + S["tiny"]
    foot_top = H - foot_h
    panels_top = head_bottom + S["body"] * 0.7
    _line(prims, M, head_bottom + S["body"] * 0.18, W - M, head_bottom + S["body"] * 0.18,
          LINE, 1.2, layer="frame", pid="hdr-rule")

    claims = ir.get("claims", [])
    ledger_row_h = S["small"] * 2.5
    ledger_natural = (S["tiny"] * 2.6 + len(claims) * ledger_row_h) if claims else 0.0

    # ---------------- panels ----------------
    panels = ir["panels"][:4]
    while len(panels) < 4:
        panels.append({"order": len(panels) + 1, "role": C.PANEL_ROLES[len(panels)],
                       "title": "", "claim": "", "kind": "bullets", "chart": "",
                       "relations": [], "items": [], "source": {}})
    gap = M * 0.9
    pw = (W - 2 * M - gap * 3) / 4.0
    rel_by_id = {r["id"]: r for r in ir["relations"]}
    chart_by_id = {c["id"]: c for c in ir["charts"]}
    kinds = []
    for panel in panels:
        panel["_relations"] = [rel_by_id[r] for r in panel["relations"] if r in rel_by_id]
        panel["_entities"] = ir["entities"]
        panel["_chart"] = chart_by_id.get(panel["chart"])
        kind = panel["kind"]
        if kind in ("relations", "graph") and not panel["_relations"]:
            kind = "bullets"
        if kind in ("chart", "data") and not panel["_chart"]:
            kind = "bullets"
        kinds.append(kind)

    slack = 0.0

    def render_panel(idx, panel, kind, height, body_size, spacing, allow_extra,
                     claim_lines=2, paint=True, slack_px=0.0):
        """Draw one panel into its own primitive list and report what it needs."""
        trial = []
        px = M + idx * (pw + gap)
        bar_h = S["role"] * 2.05
        claim_h = 0.0
        claim_txt = []
        if panel["claim"]:
            claim_txt = C.wrap_text(panel["claim"], fs * 1.02, pw - S["body"] * 1.24,
                                    max_lines=claim_lines)
            claim_h = len(claim_txt) * S["small"] * 1.32 + S["body"] * 0.2
        body_top = panels_top + bar_h + S["body"] * 0.55 + claim_h
        body_h = max(S["small"] * 3.0, height - (bar_h + S["body"] * 0.55 + claim_h) - S["body"] * 0.75)
        body_slack = slack_px * 0.92
        if paint:
            _rect(trial, px, panels_top, pw, height, fill=PANEL_BG, stroke=PANEL_EDGE,
                  sw=1.1, rx=S["body"] * 0.6, layer="panels", pid="panel-%d" % (idx + 1))
            _rect(trial, px, panels_top, pw, bar_h, fill=ACCENT, stroke="none",
                  rx=S["body"] * 0.6, layer="panels", pid="panel-%d-bar" % (idx + 1))
        badge, _zh = C.ROLE_LABEL[panel["role"]]
        _text(trial, px + S["body"] * 0.62, panels_top + bar_h * 0.66, badge, S["role"],
              bold=True, fill="#FFFFFF", pid="panel-%d-badge" % (idx + 1), layer="labels")
        if panel["title"]:
            _text(trial, px + pw - S["body"] * 0.62, panels_top + bar_h * 0.66,
                  C.fit_text(panel["title"], S["small"], pw * 0.52), S["small"],
                  anchor="end", fill="#DCE7F2", pid="panel-%d-title" % (idx + 1),
                  layer="labels")
        for li, ln in enumerate(claim_txt):
            _text(trial, px + S["body"] * 0.62, panels_top + bar_h + S["body"] * 0.55 +
                  S["small"] * 1.02 + li * S["small"] * 1.32, ln, fs * 1.02, italic=True,
                  fill=MUTED, pid="panel-%d-claim%d" % (idx + 1, li), layer="labels")
        box = {"x": px + S["body"] * 0.58, "y": body_top,
               "w": pw - S["body"] * 1.16, "h": body_h, "slack": body_slack}
        if kind == "relations":
            used_h, dropped_ids = _body_relations(panel, box, S, body_size, spacing,
                                                  trial, idx + 1, allow_extra)
        elif kind == "chain":
            used_h, dropped_ids = _body_chain(panel, box, S, body_size, spacing,
                                              trial, idx + 1, allow_extra)
        elif kind == "chart":
            used_h, dropped_ids = _body_chart(panel, box, S, body_size, trial, idx + 1,
                                              allow_extra)
        else:
            used_h, dropped_ids = _body_bullets(panel, box, S, body_size, spacing,
                                                trial, idx + 1, allow_extra)
        needed = bar_h + S["body"] * 0.55 + claim_h + used_h + S["body"] * 0.75
        return {"trial": trial, "used": used_h, "needed": needed,
                "dropped": dropped_ids, "body_size": body_size, "box": box}

    panels_zone = foot_top - panels_top - (ledger_natural + S["body"] * 0.6 if ledger_natural else 0)
    natural = [render_panel(i, panels[i], kinds[i], 10 ** 6, S["body"], 0.30, True)["needed"]
               for i in range(4)]
    panel_h = max(natural)
    spare = max(0.0, panels_zone - panel_h)
    panel_h = min(panel_h, panels_zone)
    # breathing room is capped so the page never looks half empty
    slack = min(spare * 0.55, S["body"] * 7.0)
    panel_h += slack
    ladder = [("none", 0.30, 1.0, True, 2),
              ("drop_low_priority", 0.30, 1.0, False, 2),
              ("tighter_spacing", 0.16, 1.0, False, 2),
              ("step_down_font", 0.16, 0.94, False, 2),
              ("step_down_font", 0.14, 0.88, False, 1),
              ("elide_text", 0.14, 0.88, False, 1)]
    chosen = None
    for name, spacing, fscale, allow_extra, clines in ladder:
        bs = max(min_font, S["body"] * fscale)
        res = [render_panel(i, panels[i], kinds[i], panel_h, bs, spacing, allow_extra,
                            claim_lines=clines, slack_px=slack) for i in range(4)]
        if all(r["needed"] <= panel_h + 0.5 for r in res):
            chosen = (name, res, bs)
            break
    if chosen is None:
        name, spacing, fscale, allow_extra, clines = ladder[-1]
        bs = max(min_font, S["body"] * fscale)
        slack = 0.0
        res = [render_panel(i, panels[i], kinds[i], panel_h, bs, spacing, allow_extra,
                            claim_lines=clines, slack_px=0.0) for i in range(4)]
        chosen = ("clipped", res, bs)
    repair_name, results, body_size_final = chosen
    panel_metrics = []
    for idx, r in enumerate(results):
        prims.extend(r["trial"])
        dropped.extend(r["dropped"])
        if r["needed"] > panel_h + 0.5:
            repairs.append({"unit": "panel-%d" % (idx + 1), "role": panels[idx]["role"],
                            "action": "clipped",
                            "detail": "阶梯耗尽仍溢出，末行可能被截断",
                            "font_px": round(r["body_size"], 1)})
        panel_metrics.append({
            "panel": "panel-%d" % (idx + 1), "role": panels[idx]["role"], "kind": kinds[idx],
            "items": len(panels[idx]["items"]),
            "rendered": len(panels[idx]["items"]) - len(r["dropped"]),
            "dropped": r["dropped"], "font_px": round(r["body_size"], 1),
            "needed_px": round(r["needed"], 1), "height_px": round(panel_h, 1),
            "overflow": r["needed"] > panel_h + 0.5,
        })
    if repair_name != "none":
        repairs.append({"unit": "panels", "action": repair_name,
                        "detail": _repair_detail(repair_name),
                        "font_px": round(body_size_final, 1)})
    for idx in range(3):
        px = M + idx * (pw + gap)
        ax = px + pw + gap * 0.18
        ay = panels_top + panel_h * 0.5
        _line(prims, ax, ay, ax + gap * 0.64 - S["body"] * 0.42, ay, "#B0B6BC", 2.2,
              layer="annotations", pid="flow-arrow-%d" % (idx + 1))
        _marker(prims, ax + gap * 0.64, ay, "arrow", "#B0B6BC", S["body"] * 0.9,
                layer="annotations", pid="flow-head-%d" % (idx + 1))

    # ---------------- claims ledger: value -> visual channel, with locator ----------------
    band_top = panels_top + panel_h + S["body"] * 0.5
    band_h = min(ledger_natural, max(0.0, foot_top - band_top - S["body"] * 0.2))
    if claims and band_h > fs * 2.5:
        _text(prims, M, band_top + S["tiny"] * 1.5,
              "关键数值 → 图面编码（长度=数值，刻度线=对照值；每行右侧为来源定位）",
              S["tiny"], bold=True, fill=MUTED, pid="ledger-title", layer="data")
        lab_w = (W - 2 * M) * 0.19
        val_w = (W - 2 * M) * 0.13
        loc_w = (W - 2 * M) * 0.13
        bar_x = M + lab_w
        bar_w = W - 2 * M - lab_w - val_w - loc_w - S["small"] * 2.6
        row_h = min(ledger_row_h, (band_h - S["tiny"] * 2.6) / max(1, len(claims)))
        vmax = max([abs(_num_of(c.get("value"))) for c in claims] +
                   [abs(_num_of((c.get("compare") or {}).get("value"))) for c in claims] + [1e-9])
        for k, c in enumerate(claims):
            ry = band_top + S["tiny"] * 2.4 + k * row_h
            v = _num_of(c.get("value"))
            color = _color_for(k)
            _text(prims, M, ry + row_h * 0.62, C.fit_text(c.get("label") or c.get("id", ""),
                                                          fs * 0.98, lab_w - fs * 0.5),
                  fs * 0.98, fill=INK, pid="ledger-%s-label" % c.get("id", k), layer="data")
            _rect(prims, bar_x, ry + row_h * 0.22, bar_w, row_h * 0.56, fill="#EDEFF2",
                  stroke="none", rx=row_h * 0.1, layer="data",
                  pid="ledger-%s-track" % c.get("id", k))
            frac = min(1.0, abs(v) / vmax) if vmax else 0.0
            _rect(prims, bar_x, ry + row_h * 0.22, max(1.0, bar_w * frac), row_h * 0.56,
                  fill=color, stroke=INK, sw=0.5, rx=row_h * 0.1,
                  layer="data", pid="ledger-%s-bar" % c.get("id", k))
            _hatch(prims, bar_x, ry + row_h * 0.22, max(1.0, bar_w * frac), row_h * 0.56,
                   _pattern_for(k), "data", "ledger-%s-bar" % c.get("id", k))
            comp = c.get("compare") or {}
            cv = _num_of(comp.get("value"))
            if comp and cv:
                cx = bar_x + bar_w * min(1.0, abs(cv) / vmax)
                _line(prims, cx, ry + row_h * 0.10, cx, ry + row_h * 0.90, "#1A1A1E", 1.8,
                      dash="4 2", layer="data", pid="ledger-%s-ref" % c.get("id", k))
                _text(prims, cx, ry + row_h * 0.02,
                      C.fit_text(comp.get("label") or "", S["tiny"] * 0.85, bar_w * 0.3),
                      S["tiny"] * 0.85, anchor="middle", fill=MUTED,
                      pid="ledger-%s-reflab" % c.get("id", k), layer="data")
            unit = c.get("unit") or ""
            _text(prims, bar_x + bar_w + S["small"] * 0.4, ry + row_h * 0.62,
                  C.fit_text(("%g %s" % (v, unit)).strip(), fs * 0.98, val_w - S["small"] * 0.5),
                  fs * 0.98, bold=True, fill=INK,
                  pid="ledger-%s-value" % c.get("id", k), layer="data")
            src = c.get("source") or {}
            loc = "%s %s" % (src.get("id") or "", src.get("locator") or "")
            _text(prims, W - M - loc_w, ry + row_h * 0.62,
                  C.fit_text(loc.strip(), S["tiny"] * 0.92, loc_w),
                  S["tiny"] * 0.92, fill=MUTED,
                  pid="ledger-%s-src" % c.get("id", k), layer="data")
    elif claims:
        repairs.append({"unit": "ledger", "action": "band_omitted",
                        "detail": "剩余高度不足，数值编码带未绘制（数值仍在 content_map 中）",
                        "font_px": round(fs, 1)})

    # ---------------- footer: legend / notes / evidence / caption ----------------
    fy = foot_top
    _line(prims, M, fy, W - M, fy, LINE, 1.2, layer="frame", pid="foot-rule")
    ly = fy + fs * 1.9
    lx = M
    lh = fs * 1.75
    max_w = W - 2 * M
    shown = 0
    for li in legend:
        item_w = fs * 2.0 + C.text_width(li["label"], fs * 0.98) + fs * 1.6
        if lx + item_w > M + max_w:
            lx = M
            ly += lh
            if ly > fy + fs * 3.6:
                break
        if li["channel"] == "marker":
            _line(prims, lx, ly - fs * 0.32, lx + fs * 1.5, ly - fs * 0.32,
                  li["color"], 1.6, dash="4 2" if li.get("dash") else "",
                  layer="legend", pid="leg-%s-line" % li["key"])
            _marker(prims, lx + fs * 1.62, ly - fs * 0.32, li.get("marker") or "arrow",
                    li["color"], fs * 0.62, layer="legend", pid="leg-%s-head" % li["key"])
        elif li["channel"] == "text":
            _text(prims, lx, ly - fs * 0.2, "i", fs * 1.05, italic=True, bold=True,
                  fill=li["color"], layer="legend", pid="leg-%s-sl" % li["key"])
        else:
            _rect(prims, lx, ly - fs * 0.92, fs * 1.35, fs * 0.95, fill=li["color"],
                  stroke=INK, sw=0.6, layer="legend", pid="leg-%s-sw" % li["key"])
            _hatch(prims, lx, ly - fs * 0.92, fs * 1.35, fs * 0.95, li.get("pattern"),
                   "legend", "leg-%s-sw" % li["key"], step=5.5)
        _text(prims, lx + fs * 2.0, ly - fs * 0.18, li["label"], fs * 0.98, fill=INK,
              layer="legend", pid="leg-%s-lb" % li["key"])
        lx += item_w
        shown += 1
    if shown < len(legend):
        _text(prims, lx, ly - fs * 0.18, "+%d" % (len(legend) - shown), fs * 0.95,
              fill=MUTED, layer="legend", pid="leg-more")
    ny = ly + fs * 1.7
    notes_bits = []
    for key, label in (("units", "单位"), ("conditions", "条件"), ("scale_bar", "比例尺")):
        val = (ir.get("notes") or {}).get(key) or ""
        if val:
            notes_bits.append("%s: %s" % (label, val))
    if ir["sources"]:
        ev = "来源: " + " · ".join(
            "%s %s" % (s["id"], (s.get("locator") or s.get("path") or ""))
            for s in ir["sources"][:6])
        notes_bits.append(ev)
    if notes_bits:
        _text(prims, M, ny, C.fit_text("   |   ".join(notes_bits), S["tiny"], max_w - 2),
              S["tiny"], fill=MUTED, pid="foot-notes", layer="legend")
    cy2 = ny + S["tiny"] * 1.75
    for li, ln in enumerate(cap_lines):
        _text(prims, M, cy2 + li * S["tiny"] * 1.4, ln, S["tiny"] * 0.98, fill=MUTED,
              pid="foot-caption%d" % li, layer="frame")

    # ---------------- type-size tiers ----------------
    # body text must respect canvas.min_font_px; tick labels, source chips and
    # footnotes are annotations and only have to stay legible (>= 0.62x floor).
    body_floor = S["body"] * 0.70
    body_sizes, ann_sizes = [], []
    for p in prims:
        if p["t"] != "text":
            continue
        p["tier"] = "annotation" if p["size"] < body_floor else "body"
        (body_sizes if p["tier"] == "body" else ann_sizes).append(p["size"])

    # ---------------- text inside canvas check ----------------
    overflow_boxes = []
    for p in prims:
        if p["t"] != "text":
            continue
        tw = C.text_width(p["s"], p["size"], p["bold"])
        x0 = p["x"] if p["anchor"] == "start" else (
            p["x"] - tw if p["anchor"] == "end" else p["x"] - tw / 2.0)
        if x0 < -1 or x0 + tw > W + 1 or p["y"] > H + 1 or p["y"] < 0:
            overflow_boxes.append({"id": p["id"], "text": p["s"][:40],
                                   "x0": round(x0, 1), "x1": round(x0 + tw, 1)})
    if overflow_boxes:
        repairs.append({"unit": "canvas", "action": "text_out_of_canvas",
                        "detail": "%d 个文本超出画布，已记入 exceptions" % len(overflow_boxes),
                        "font_px": round(S["body"], 1)})

    # ---------------- layer bookkeeping ----------------
    layers = []
    for p in prims:
        if p["layer"] not in layers:
            layers.append(p["layer"])
    order = ["frame", "panels", "entities", "relations", "data", "labels", "legend",
             "annotations"]
    layers = [l for l in order if l in layers] + [l for l in layers if l not in order]
    ids = [p["id"] for p in prims if p["id"]]
    return {
        "canvas": canvas,
        "sizes": S,
        "prims": prims,
        "layers": layers,
        "ids": ids,
        "legend": legend,
        "chart_series_in_chart_legend": chart_series_in_legend,
        "legend_shown": shown,
        "repairs": repairs,
        "dropped": dropped,
        "panel_metrics": panel_metrics,
        "text_count": sum(1 for p in prims if p["t"] == "text"),
        "out_of_canvas": overflow_boxes,
        "min_font_used": min([p["size"] for p in prims if p["t"] == "text"] or [0]),
        "min_font_body": min(body_sizes or [0]),
        "min_font_annotation": min(ann_sizes or [0]),
        "patterns": sorted({p.get("pattern") for p in prims if p.get("pattern")}),
        "hatch_segments": sum(1 for p in prims if str(p.get("id", "")).find("-h") >= 0 and p["t"] == "line"),
        "ledger": {"rows": len(claims), "drawn": bool(claims and band_h > fs * 2.5),
                   "height_px": round(band_h, 1)},
        "panel_height_px": round(panel_h, 1),
        "fit": {"panels_top": round(panels_top, 1), "panels_zone": round(panels_zone, 1),
                "natural_max": round(max(natural), 1), "slack": round(slack, 1),
                "ledger_natural": round(ledger_natural, 1), "foot_top": round(foot_top, 1),
                "used_height": round(band_top + band_h, 1)},
    }


def _repair_detail(name):
    for n, d in REPAIR_LADDER:
        if n == name:
            return d
    return name














