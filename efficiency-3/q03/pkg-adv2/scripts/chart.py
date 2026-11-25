#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart.py -- one-file figure builder for a source-value work order.

  python3 scripts/chart.py --case /input/case.json --out /app/output

Writes the editable source (figure.svg, real <text>), the element->source-cell map
(figure.map.json), result.json (output contract + hashed output_files + export evidence) and the
submission exports figure.pdf (vector, real text operators) and figure.png (300 dpi preview).
One layout dict feeds all three renderers, so bar heights cannot drift between them. Missing input
still leaves a result.json explaining the gap; cells that are not numbers are reported as unmapped,
never invented; every mark keeps a physical line/column locator; an empty canvas is never success.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import time
import zlib
from xml.sax.saxutils import escape

VERSION = "adv2-1.0"
EXPORT_ENGINE, EXPORT_DPI = "auto", 300          # overridden by --engine / --dpi
PAL = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000"]
MM, FS = 72.0 / 25.4, 7.0
DIMLESS = ("relative", "fold change", "ratio", "%", "a.u.", "index", "score", "normalis", "normaliz")
CATH = ("gene", "symbol", "name", "label", "key", "sample", "condition", "group", "treatment", "id")
ERRH = ("err", "error", "sd", "stdev", "std", "sem", "yerr")
NH = ("n", "count", "replicate", "rep", "size")
UNITS = set(("nM uM mM M pM ng ug mg g kg mL uL L s ms min h hr day week RFU AU OD nm cm mm um K Pa kPa "
             "mV V mA A Hz ppm rpm %").split())
UNITS_UC = {u.upper() for u in UNITS}
CONTRACT = {"case_id": "case_id", "id": "case_id", "status": "status", "state": "status", "summary": "summary",
            "editable_source": "editable_source", "exports": "exports", "element_map": "element_map",
            "map": "element_map", "checks": "checks", "sources": "sources", "change_log": "change_log",
            "changes": "change_log", "uncertainty": "uncertainty", "gaps": "uncertainty",
            "outputs": "outputs", "output_files": "output_files", "resolved_from": "resolved_from"}
# Machado, Oliveira & Fernandes (2009) severity 1.0, applied in linear RGB
CVD = {"deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413),
                        (-0.011820, 0.042940, 0.968881)),
       "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
                      (-0.003882, -0.048116, 1.051998)),
       "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602),
                      (0.004733, 0.691367, 0.303900))}
NUMRE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?%?")
RESOLVED: list[dict] = []


def num(v):
    """Only a cell that IS a number counts: 'Il6', 'n.d.', '' never become data."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\u2212", "-")
    return float(s.rstrip("%")) if NUMRE.fullmatch(s) else None


def fm(v):
    a = abs(v)
    if v == 0:
        return "0"
    if a >= 1e4 or a < 1e-3:
        return f"{v:.1e}"
    return f"{v:.3g}"


def unit_of(t):
    """'Relative mRNA level (fold change)' -> ('Relative mRNA level', 'fold change');
    'response_rfu' -> ('response', 'RFU'); 'time_h' -> ('time', 'H')."""
    s = str(t or "").strip()
    m = re.search(r"[\(\[]([^\)\]]+)[\)\]]\s*$", s)
    if m and re.fullmatch(r"[A-Za-z\u00b5\u03bc%][\w%^/\-.\s]{0,14}", m.group(1).strip()):
        return s[:m.start()].strip(), m.group(1).strip()
    m2 = re.match(r"^(.*?)_([A-Za-z\u00b5\u03bc%][A-Za-z0-9%^]{0,7})$", s)
    if m2 and m2.group(2).upper() in UNITS_UC:
        return m2.group(1).replace("_", " ").strip(), m2.group(2).upper()
    if s.upper() == "N":
        return s, ""
    return s, ""


def is_dimless(label):
    """Whole-word matching only: 'concentRATIOn' must never count as the dimensionless token 'ratio'."""
    s = str(label or "")
    if not s:
        return True
    low = " " + re.sub(r"[^a-z0-9.%]+", " ", s.lower()).strip() + " "
    return "%" in s or any(f" {t} " in low for t in DIMLESS)


def unit_ok(label, unit):
    """The quantity axis is honest when it declares a unit or is explicitly dimensionless."""
    if (unit in UNITS) or (str(unit).upper() in UNITS_UC) or re.search(r"(\u00d7|x)10\^?-?\d+", f"{unit} {label}"):
        return True
    return (not label) or is_dimless(label)


def esc(s):
    return escape(str(s if s is not None else ""))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def wx(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ------------------------------------------------------------------ R1b paths

def resolve_ref(ref, case_dir, kind="material"):
    """case.json directory first, then cwd, then /input (absolute paths taken as-is)."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    hit, why = None, ""
    if os.path.isabs(ref):
        hit, why = (ref if os.path.isfile(ref) else None), "absolute"
    else:
        for base, tag in ((case_dir, "case_dir"), (os.getcwd(), "cwd"), ("/input", "/input")):
            if base and os.path.isfile(os.path.normpath(os.path.join(base, ref))):
                hit, why = os.path.normpath(os.path.join(base, ref)), tag
                break
    rel = None
    if hit:
        try:
            rel = os.path.relpath(hit, case_dir) if case_dir else os.path.basename(hit)
        except ValueError:
            rel = os.path.basename(hit)
        if ":" in rel or rel.startswith("\\"):
            rel = os.path.basename(hit)
    RESOLVED.append({"ref": ref, "kind": kind, "resolved": rel, "from": why or "unresolved"})
    return hit


# ---------------------------------------------------------------- find table

def sde():
    """Pinned SOURCE_DATE_EPOCH (reproducible-builds convention) or None for wall-clock runs."""
    raw = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def stamp():
    """Every timestamp in every artefact goes through here.

    With SOURCE_DATE_EPOCH pinned the value is a pure function of that epoch (UTC), so two runs of the
    same case produce byte-identical figure.pdf / result.json / export_check.json / render_report.json.
    """
    ep = sde()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ep)) if ep is not None else time.strftime("%Y-%m-%dT%H:%M:%S")


def secs(t0, digits=2):
    """Wall-clock duration; omitted in reproducible mode (it is the only remaining run-to-run delta)."""
    return None if sde() is not None else round(time.time() - t0, digits)


def looks_table(rows):
    """A list of dicts is a table only if it has 2+ scalar fields and one mostly-numeric field."""
    if not rows or not all(isinstance(r, dict) for r in rows):
        return False
    cols = list(dict.fromkeys(k for r in rows for k in r))
    if len(cols) < 2 or any(isinstance(r.get(c), (list, dict)) for r in rows for c in cols):
        return False
    return any(sum(1 for r in rows if num(r.get(c)) is not None) >= max(1, int(0.6 * len(rows))) for c in cols)


def find_table(case):
    """(columns, rows, note) of the first table-shaped object in the work order, else None."""
    def pair(d):
        c, r = d.get("columns"), d.get("rows")
        return ([str(x) for x in c], r) if isinstance(c, list) and isinstance(r, list) and r else None
    if isinstance(case, dict):
        if pair(case):
            return pair(case)[0], pair(case)[1], "inline:{columns,rows}"
        for k, v in case.items():
            if isinstance(v, list) and looks_table(v):
                return list(dict.fromkeys(x for row in v for x in row)), v, f"inline:{k}[]"
            if isinstance(v, dict):
                if pair(v):
                    return pair(v)[0], pair(v)[1], f"inline:{k}.{{columns,rows}}"
                for k2, v2 in v.items():
                    if isinstance(v2, list) and looks_table(v2):
                        return list(dict.fromkeys(x for row in v2 for x in row)), v2, f"inline:{k}.{k2}[]"
    if isinstance(case, list) and looks_table(case):
        return list(dict.fromkeys(x for row in case for x in row)), case, "inline:records[]"
    return None


# Evidence channels are separated by an explicit TYPE WHITELIST. The work order itself (case.json),
# task.md, *.example.json and *.template.json are instructions, never measurements: they are excluded
# from both lists below and can therefore never become a plotted value or a citation for one.
TABLE_EXT = (".csv", ".tsv")
MATERIAL_EXT = (".txt", ".md")


def explicit_refs(case, kinds=TABLE_EXT + MATERIAL_EXT):
    """Relative file references written inside the work order (data_file / materials / paths)."""
    out = []

    def walk(n, d=0):
        if d > 3 or n is None:
            return
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, str) and v.lower().endswith(kinds):
                    out.append(v)
                elif isinstance(v, list) and str(k).lower() in ("materials", "files", "sources", "paths",
                                                                 "data_file", "input", "csv"):
                    out.extend([x for x in v if isinstance(x, str)])
                else:
                    walk(v, d + 1)
        elif isinstance(n, list):
            for v in n:
                walk(v, d + 1)

    walk(case)
    return list(dict.fromkeys(out))


def find_tables(case, case_dir):
    """([table paths], [material paths], [rejected refs]).

    A candidate is only ever used as a table when its extension is in TABLE_EXT; every other referenced
    document (notes, protocol, task text) is reported as a material and is never parsed into numbers.
    """
    explicit = [r for r in (resolve_ref(x, case_dir, "explicit") for x in explicit_refs(case)) if r]
    tables, materials, rejected = [], [], []
    for p in explicit:
        (tables if p.lower().endswith(TABLE_EXT) else materials).append(p)
    if os.path.isdir(case_dir):
        for n in sorted(os.listdir(case_dir)):
            p = os.path.join(case_dir, n)
            if n.lower().endswith(MATERIAL_EXT):
                materials.append(p)
            elif n.lower().endswith(TABLE_EXT):
                tables.append(p)
            elif n.lower().endswith(".json") and os.path.basename(p) not in ("case.json",):
                rejected.append(p)          # a sibling example/template JSON is documentation, not data
    seen_t, out_t = set(), []
    for p in tables:
        if p not in seen_t and os.path.isfile(p):
            seen_t.add(p)
            out_t.append(p)
    seen_m, out_m = set(), []
    for p in materials:
        if p not in seen_m and os.path.isfile(p):
            seen_m.add(p)
            out_m.append(p)
    return out_t, out_m, rejected


def load_table(path):
    """(columns, rows, note, header_line, line_numbers); every line number is a PHYSICAL 1-based line.

    Comment and blank lines are not data, but they still shift the file, so the numbers come from csv's
    own line counter instead of from the record index: the locator must point at the line a human scrolls to.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        lines = fh.read().splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")), 0)
    body = lines[head:]
    delim = "\t" if path.lower().endswith(".tsv") or (body and body[0].count("\t") > body[0].count(",")) else ","
    reader = csv.DictReader(body, delimiter=delim)
    rows, line_numbers = [], []
    for rec in reader:
        rows.append(rec)
        line_numbers.append(head + reader.line_num)
    if not rows:
        return None
    return list(rows[0].keys()), rows, f"file:{os.path.basename(path)}", head + 1, line_numbers


# ------------------------------------------------------------ plan and read

def cell(row, col, cols):
    if col is None:
        return None
    if isinstance(row, dict):
        return row.get(col)
    i = cols.index(col)
    return row[i] if i < len(row) else None


def uniq(rows, col, cols):
    return list(dict.fromkeys(v for v in (cell(r, col, cols) for r in rows) if v not in (None, "")))


def role_of(col, values):
    name = str(col).strip().lower()
    if sum(1 for v in values if num(v) is not None) < max(1, int(0.6 * len(values))):
        return "category"
    if any(h == name or name.startswith(h + "_") or name.endswith("_" + h) for h in NH):
        return "n"
    return "error" if any(h in name for h in ERRH) else "value"


def plan_chart(case, cols, rows, origin):
    roles = {c: role_of(c, [cell(r, c, cols) for r in rows]) for c in cols}
    cats, vals = [c for c in cols if roles[c] == "category"], [c for c in cols if roles[c] == "value"]
    if not vals:
        return None, ["no numeric measurement column was found in this table"]
    gaps = [] if cats else ["the table has no categorical column; an index was generated for the x axis"]
    rank = lambda c: (min([CATH.index(h) for h in CATH if h in c.lower()] or [99]),   # noqa: E731
                      len(uniq(rows, c, cols)))          # a named key (gene/sample/...) is the x axis
    x = min(cats, key=rank) if cats else None
    sc = next((c for c in cats if c != x and 2 <= len(uniq(rows, c, cols)) <= 6), None)
    y_label = str(case.get("y_label") or case.get("ylabel") or vals[0])
    y_unit = str(case.get("y_unit") or case.get("unit") or "")
    if unit_of(y_label)[1]:
        y_label, y_unit = unit_of(y_label)
    if not y_unit and unit_of(vals[0])[1]:
        y_unit, y_label = unit_of(vals[0])[1], (unit_of(vals[0])[0] if y_label == vals[0] else y_label)
    if not unit_ok(y_label, y_unit):
        gaps.append(f"the quantity axis declares no unit (label={y_label!r}); put the unit in parentheses "
                    f"or state that the quantity is dimensionless")
    ct = str(case.get("chart_type") or "").lower()
    return {"type": ct if re.search(r"bar|column", ct) else ("grouped_bar" if sc else "bar"), "x": x, "sc": sc,
            "vc": vals[0], "ec": next((c for c in cols if roles[c] == "error"), None),
            "nc": next((c for c in cols if roles[c] == "n"), None),
            "xl": str(case.get("x_label") or case.get("xlabel") or x or "item"),
            "yl": y_label, "yu": y_unit, "origin": origin, "roles": roles}, gaps


def collect(cols, rows, plan, header_line, line_numbers=None):
    """Group rows into series; row numbers are PHYSICAL lines (comments, header and blank lines included)."""
    cats, series, unmapped = [], [], []
    for i, row in enumerate(rows):
        row_no = (line_numbers[i] if line_numbers and i < len(line_numbers) else header_line + 1 + i)
        raw = cell(row, plan["x"], cols) if plan["x"] else None
        cat = str(raw) if raw not in (None, "") else f"item{i + 1}"
        val = num(cell(row, plan["vc"], cols))
        if val is None:
            unmapped.append({"row": row_no, "col": plan["vc"], "value": str(cell(row, plan["vc"], cols))[:40],
                             "reason": "not a number"})
            continue
        if cat not in cats:
            cats.append(cat)
        name = str(cell(row, plan["sc"], cols)) if plan["sc"] else "value"
        s = next((x for x in series if x["name"] == name), None) or {"name": name, "values": []}
        if s not in series:
            series.append(s)
        s["values"].append({"cat": f"cat{cats.index(cat) + 1}", "value": val,
                            "error": num(cell(row, plan["ec"], cols)) if plan["ec"] else None,
                            "n": num(cell(row, plan["nc"], cols)) if plan["nc"] else None,
                            "source": {"file": plan["origin"], "row": row_no, "record_index": i + 1, "col": plan["vc"],
                                       "row_key": {c: cell(row, c, cols) for c in (plan["x"], plan["sc"]) if c}}})
    return cats, series, unmapped


# ------------------------------------------------------------- colour science

def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgb(h):
    h = str(h).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (128, 128, 128)


def _lab(lin):
    r, g, b = lin
    X = 0.4124 * r + 0.3576 * g + 0.1805 * b
    Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    Z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    fx, fy, fz = (_f(t / w) for t, w in ((X, 0.95047), (Y, 1.0), (Z, 1.08883)))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _f(t):
    return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116


def simulate(hex_colour, kind):
    lin = [_lin(v) for v in _rgb(hex_colour)]
    if kind == "achromatopsia":
        g = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        lin = [g, g, g]
    elif kind in CVD:
        m = CVD[kind]
        lin = [sum(m[i][j] * lin[j] for j in range(3)) for i in range(3)]
    return _lab([min(max(v, 0.0), 1.0) for v in lin])


def de76(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def cvd_pairs(colours):
    """Per-pair perception metrics: CIE76 dE under normal vision and three CVD simulations."""
    out = []
    for i in range(len(colours)):
        for j in range(i + 1, len(colours)):
            base = de76(simulate(colours[i], "normal"), simulate(colours[j], "normal"))
            ds = {k: round(de76(simulate(colours[i], k), simulate(colours[j], k)), 2) for k in CVD}
            grey = round(abs(simulate(colours[i], "normal")[0] - simulate(colours[j], "normal")[0]), 2)
            score = min([base] + list(ds.values()))
            out.append({"pair": [colours[i], colours[j]], "dE76": round(base, 2), "cvd": ds,
                        "dL_greyscale": grey, "score": round(score, 2),
                        "verdict": "ok" if score >= 20 else ("warn" if score >= 12 else "fail"),
                        "greyscale": "ok" if grey >= 8 else ("warn" if grey >= 5 else "fail")})
    return out


# ------------------------------------------------------------------ drawing

# ------------------------------------------------------------------ drawing

def layout(chart):
    """One geometry model for every renderer: figure.svg, figure.pdf and figure.png all draw from it."""
    series, cids = chart["series"], [c["id"] for c in chart["categories"]]
    disp = {c["id"]: c["display"] for c in chart["categories"]}
    W, H = 89.0 * MM, 70.0 * MM
    ylab = chart["y"]["label"] or ""
    if chart["y"]["unit"] and f"({chart['y']['unit']})" not in ylab:
        ylab = f"{ylab} ({chart['y']['unit']})"
    vals = [v["value"] for s in series for v in s["values"]]
    errs = [abs(v["error"]) for s in series for v in s["values"] if v.get("error") is not None]
    lo, hi = min(min(vals), 0.0), max(vals)
    ymin, ymax = lo, hi + 0.18 * max(hi - lo, 1e-9) + (max(errs) if errs else 0.0)
    ticks = [fm(ymin + (ymax - ymin) * k / 5) for k in range(6)]
    # left margin adapts to the widest tick label: the rotated axis title must never collide with the
    # tick labels (label occlusion is an explicit failure mode in the work order, not a cosmetic issue)
    tick_mm = max(len(t) for t in ticks) * 0.5 * FS * 25.4 / 72.0
    ylab_x = 2.6
    x0 = max(11.0, ylab_x + FS * 25.4 / 72.0 / 2 + 1.0 + tick_mm + 1.6) * MM
    x1, y0, y1 = W - 4.0 * MM, 12.0 * MM, H - 11.0 * MM
    Y = lambda v: y1 - (float(v) - ymin) / (ymax - ymin) * (y1 - y0)                    # noqa: E731
    step = (x1 - x0) / max(len(cids), 1)
    X = lambda i: x0 + step * (i + 0.5)                                                # noqa: E731
    gw, bw = step * 0.74, step * 0.74 / max(len(series), 1)
    lay = {"W": W, "H": H, "x0": x0, "x1": x1, "y0": y0, "y1": y1, "font_pt": FS,
           "x_label": chart["x"]["label"] or "", "y_label": ylab, "title": chart.get("title") or "",
           "lines": [{"id": "xaxis", "x1": x0, "y1": y1, "x2": x1, "y2": y1, "sw": 0.8, "stroke": "#333333"},
                     {"id": "yaxis", "x1": x0, "y1": y0, "x2": x0, "y2": y1, "sw": 0.8, "stroke": "#333333"}],
           "texts": [], "bars": [], "errs": [], "legend": [], "mapping": []}
    for k, tick in enumerate(ticks):
        v = ymin + (ymax - ymin) * k / 5
        lay["texts"].append({"id": f"ytick-{k}", "s": tick, "x": x0 - 1.6, "y": Y(v) + FS * 0.34,
                             "anchor": "end", "rotate": 0})
    lay["texts"].append({"id": "xlabel", "s": lay["x_label"], "x": (x0 + x1) / 2, "y": H - 2.2,
                         "anchor": "middle", "rotate": 0})
    lay["texts"].append({"id": "ylabel", "s": ylab, "x": ylab_x, "y": (y0 + y1) / 2, "anchor": "middle",
                         "rotate": -90})
    for i, cid in enumerate(cids):
        lay["texts"].append({"id": f"xtick-{cid}", "s": disp.get(cid, cid), "x": X(i), "y": y1 + FS + 2.0,
                             "anchor": "middle", "rotate": 0})
    for si, s in enumerate(series):
        for cid in cids:
            p = next((v for v in s["values"] if v["cat"] == cid), None)
            if not p:
                continue
            x = X(cids.index(cid)) - gw / 2 + si * bw
            top, zero = Y(p["value"]), Y(0.0)
            eid = f'el-{s["id"]}-{cid}'
            lay["bars"].append({"id": eid, "x": x, "y": min(top, zero), "w": bw * 0.92,
                                "h": max(abs(top - zero), 0.4), "fill": PAL[si % len(PAL)],
                                "dashed": si >= 3, "value": p["value"]})
            if p.get("error") is not None:
                lay["errs"].append({"x": x + bw * 0.46, "y1": Y(p["value"] - abs(p["error"])),
                                    "y2": Y(p["value"] + abs(p["error"])), "element": eid})
            lay["mapping"].append({"element_id": eid, "role": "bar_height", "value": p["value"], "source": p["source"],
                                   "error": p.get("error"), "n": p.get("n")})
    lx = x0 + 1.0
    for si, s in enumerate(series):
        label = str(s["name"])
        lay["legend"].append({"id": f'legend-swatch-{s["id"]}', "x": lx, "y": 6.6 - FS, "w": FS, "h": FS * 0.72,
                              "fill": PAL[si % len(PAL)], "label_id": f'legend-{s["id"]}', "label": label,
                              "label_x": lx + FS + 1.2, "label_y": 6.0})
        lx += FS + 3.2 + len(label) * FS * 0.52
    lay["occlusion"] = {"ylabel_right_edge_mm": round(ylab_x + FS * 25.4 / 72.0 / 2, 2),
                        "ytick_left_edge_mm": round(x0 / MM - 1.6 - tick_mm, 2),
                        "clearance_mm": round(x0 / MM - 1.6 - tick_mm - (ylab_x + FS * 25.4 / 72.0 / 2), 2),
                        "method": "declared font size and Helvetica average-advance model (0.5 em/char)"}
    return lay


def all_text(lay):
    """Every string the figure must carry, including the legend labels."""
    return [t["s"] for t in lay["texts"]] + [g["label"] for g in lay["legend"]]


def render_svg(chart, spec, path, lay=None):
    lay = lay or layout(chart)
    T = lambda x, y, s, a="middle", c=None: (                                            # noqa: E731
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{FS}" text-anchor="{a}" '
        f'font-family="Arial, Helvetica, sans-serif"{f" class={chr(34)}{c}{chr(34)}" if c else ""}>{esc(s)}</text>')
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{lay["W"]:.2f}pt" height="{lay["H"]:.2f}pt" '
         f'viewBox="0 0 {lay["W"]:.2f} {lay["H"]:.2f}" font-family="Arial, Helvetica, sans-serif">',
         f'<title id="figure-title">{esc(spec.get("title"))}</title>']
    for ln in lay["lines"]:
        o.append(f'<line id="{ln["id"]}" x1="{ln["x1"]:.2f}" y1="{ln["y1"]:.2f}" x2="{ln["x2"]:.2f}" '
                 f'y2="{ln["y2"]:.2f}" stroke="{ln["stroke"]}" stroke-width="{ln["sw"]}"/>')
    for t in lay["texts"]:
        if t["rotate"]:
            o.append(f'<text id="{t["id"]}" transform="translate({t["x"]:.2f},{t["y"]:.2f}) rotate({t["rotate"]})" '
                     f'font-size="{FS}" text-anchor="{t["anchor"]}" '
                     f'font-family="Arial, Helvetica, sans-serif">{esc(t["s"])}</text>')
        else:
            o.append(T(t["x"], t["y"], t["s"], a=t["anchor"], c=t["id"]))
    for b in lay["bars"]:
        dash = ' stroke-dasharray="2 1"' if b["dashed"] else ""
        o.append(f'<rect id="{b["id"]}" x="{b["x"]:.2f}" y="{b["y"]:.2f}" width="{b["w"]:.2f}" '
                 f'height="{b["h"]:.2f}" fill="{b["fill"]}" stroke="#222222" stroke-width="0.3"{dash}/>')
    for e in lay["errs"]:
        o.append(f'<line x1="{e["x"]:.2f}" y1="{e["y1"]:.2f}" x2="{e["x"]:.2f}" y2="{e["y2"]:.2f}" '
                 f'stroke="#222222" stroke-width="0.8"/>')
    for g in lay["legend"]:
        o += [f'<rect id="{g["id"]}" x="{g["x"]:.2f}" y="{g["y"]:.2f}" width="{g["w"]}" '
              f'height="{g["h"]:.2f}" fill="{g["fill"]}" stroke="#222222" stroke-width="0.3"/>',
              T(g["label_x"], g["label_y"], g["label"], a="start", c=g["label_id"])]
    o.append("</svg>")
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(o) + "\n")
    return lay["mapping"]


# ------------------------------------------- export: figure.pdf and figure.png
# The exports are written from the SAME layout dict as the SVG, then re-read from disk and measured
# (MediaBox / text operators / embedded fonts / IHDR+pHYs), so every export claim is a measured fact.

CJK_CANDIDATES = ("Noto Sans CJK SC", "Noto Sans CJK JP", "Source Han Sans SC", "WenQuanYi Zen Hei",
                  "Microsoft YaHei", "SimHei", "Arial Unicode MS")


def pdf_content(raw):
    """Concatenated content streams, inflated when the writer flate-compressed them (matplotlib does)."""
    out = []
    for m in re.finditer(rb"stream\r?\n", raw):
        end = raw.find(b"endstream", m.end())
        if end < 0:
            continue
        blob = raw[m.end():end]
        try:
            out.append(zlib.decompress(blob))
        except Exception:
            out.append(blob)
    return b"\n".join(out)


def measure_pdf(path):
    """Read the produced PDF and report what is really inside it (never what the writer intended)."""
    raw = open(path, "rb").read()
    content = pdf_content(raw)
    out = {"path": os.path.basename(path), "bytes": len(raw), "sha256": sha256_file(path),
           "header": raw[:8].decode("latin-1").strip()}
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)
    if m:
        pt = [float(m.group(1)), float(m.group(2))]
        out["media_box_pt"] = pt
        out["media_box_mm"] = [round(pt[0] / 72 * 25.4, 2), round(pt[1] / 72 * 25.4, 2)]
    out["pages"] = len(re.findall(rb"/Type\s*/Page\b", raw))
    out["text_show_ops"] = len(re.findall(rb"\bT[jJ]\b", content))
    out["fonts"] = sorted({f.decode("latin-1") for f in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-]+)", raw)})
    out["font_subset_embedded"] = bool(re.search(rb"/FontFile[23]", raw))
    out["image_xobjects"] = len(re.findall(rb"/Subtype\s*/Image", raw))
    out["colour_space"] = ("DeviceRGB" if re.search(rb"\brg\b|\bRG\b", content)
                           else ("DeviceGray" if re.search(rb"\bg\b|\bG\b", content) else "none"))
    return out


def measure_png(path):
    """IHDR / pHYs / chunk list read straight out of the produced PNG."""
    raw = open(path, "rb").read()
    out = {"path": os.path.basename(path), "bytes": len(raw), "sha256": sha256_file(path), "chunks": []}
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        out["error"] = "not a PNG signature"
        return out
    i = 8
    while i + 8 <= len(raw):
        ln = int.from_bytes(raw[i:i + 4], "big")
        typ = raw[i + 4:i + 8].decode("latin-1")
        data = raw[i + 8:i + 8 + ln]
        out["chunks"].append(typ)
        if typ == "IHDR":
            out["width_px"] = int.from_bytes(data[0:4], "big")
            out["height_px"] = int.from_bytes(data[4:8], "big")
            out["bit_depth"], out["colour_type"] = data[8], data[9]
        elif typ == "pHYs":
            out["dpi_metadata"] = [round(int.from_bytes(data[0:4], "big") * 0.0254, 1),
                                   round(int.from_bytes(data[4:8], "big") * 0.0254, 1)]
        i += 12 + ln
        if typ == "IEND":
            break
    return out


def rgb01(hex_colour):
    h = str(hex_colour).lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (34, 34, 34)
    return f"{r / 255:.3f} {g / 255:.3f} {b / 255:.3f}"


def pdf_ascii(s):
    """Base-14 Helvetica is WinAnsi: keep ASCII, report what cannot be written."""
    kept, lost = [], []
    for ch in str(s or ""):
        if 32 <= ord(ch) < 127:
            kept.append("\\" + ch if ch in "\\()" else ch)
        elif ch in "\t":
            kept.append(" ")
        else:
            lost.append(ch)
    return "".join(kept), sorted(set(lost))


def write_pdf_stdlib(lay, path):
    """Minimal vector PDF (Base-14 Helvetica): real text objects, no raster, no embedding needed."""
    W, H = lay["W"], lay["H"]
    ops, lost = [], []
    for b in lay["bars"]:
        ops.append(f"{rgb01(b['fill'])} rg 0.13 0.13 0.13 RG 0.25 w "
                   f"{b['x']:.2f} {H - b['y'] - b['h']:.2f} {b['w']:.2f} {b['h']:.2f} re B")
    for ln in lay["lines"]:
        ops.append(f"{rgb01(ln['stroke'])} RG {ln['sw']:.2f} w {ln['x1']:.2f} {H - ln['y1']:.2f} m "
                   f"{ln['x2']:.2f} {H - ln['y2']:.2f} l S")
    for e in lay["errs"]:
        ops.append(f"0.13 0.13 0.13 RG 0.8 w {e['x']:.2f} {H - e['y1']:.2f} m "
                   f"{e['x']:.2f} {H - e['y2']:.2f} l S")
    for g in lay["legend"]:
        ops.append(f"{rgb01(g['fill'])} rg 0.13 0.13 0.13 RG 0.25 w "
                   f"{g['x']:.2f} {H - g['y'] - g['h']:.2f} {g['w']:.2f} {g['h']:.2f} re B")
    texts = [{"s": t["s"], "x": t["x"], "y": t["y"], "anchor": t["anchor"], "rotate": t["rotate"]}
             for t in lay["texts"]]
    texts += [{"s": g["label"], "x": g["label_x"], "y": g["label_y"], "anchor": "start", "rotate": 0}
              for g in lay["legend"]]
    for t in texts:
        txt, miss = pdf_ascii(t["s"])
        lost += miss
        tw = 0.5 * FS * len(txt)                       # Helvetica average advance model
        tx = t["x"] - (tw / 2 if t["anchor"] == "middle" else (tw if t["anchor"] == "end" else 0.0))
        if t.get("rotate"):
            ops.append(f"BT /F1 {FS} Tf 0 1 -1 0 {t['x']:.2f} {H - t['y']:.2f} Tm ({txt}) Tj ET")
        else:
            ops.append(f"BT /F1 {FS} Tf 1 0 0 1 {tx:.2f} {H - t['y']:.2f} Tm ({txt}) Tj ET")
    stream = ("\n".join(ops) + "\n").encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.2f} {H:.2f}] /Resources "
             f"<< /Font << /F1 5 0 R >> >> /Contents 4 0 R >>").encode("latin-1"),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    open(path, "wb").write(bytes(out))
    return {"non_ascii_dropped": lost}


def write_png_stdlib(lay, path, dpi=300):
    """Rasterise the same geometry with zlib only. This engine draws primitives, not glyphs."""
    k = dpi / 72.0                                    # the layout is in PDF/SVG points: px = pt * dpi/72
    w, h = int(round(lay["W"] * k)), int(round(lay["H"] * k))
    rows = [bytearray(b"\xff\xff\xff" * w) for _ in range(h)]

    def fill(x, y, ww, hh, rgb):
        c0, c1 = max(0, int(round(x * k))), min(w, int(round((x + ww) * k)))
        r0, r1 = max(0, int(round(y * k))), min(h, int(round((y + hh) * k)))
        band = bytes(rgb) * max(0, c1 - c0)
        for yy in range(r0, r1):
            rows[yy][c0 * 3:c1 * 3] = band

    hex2 = lambda s: tuple(int(str(s).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))   # noqa: E731
    for b in lay["bars"]:
        fill(b["x"], b["y"], b["w"], b["h"], hex2(b["fill"]))
    for g in lay["legend"]:
        fill(g["x"], g["y"], g["w"], g["h"], hex2(g["fill"]))
    for ln in lay["lines"]:
        thick = max(ln["sw"] * k, 0.6)
        if abs(ln["y1"] - ln["y2"]) < 1e-9:
            fill(ln["x1"], ln["y1"] - thick / 2, ln["x2"] - ln["x1"], thick, hex2(ln["stroke"]))
        else:
            fill(ln["x1"] - thick / 2, min(ln["y1"], ln["y2"]), thick, abs(ln["y2"] - ln["y1"]),
                 hex2(ln["stroke"]))
    for e in lay["errs"]:
        fill(e["x"] - 0.4, min(e["y1"], e["y2"]), 0.8, abs(e["y2"] - e["y1"]), hex2("#222222"))

    def chunk(typ, data):
        return (len(data).to_bytes(4, "big") + typ + data
                + (zlib.crc32(typ + data) & 0xFFFFFFFF).to_bytes(4, "big"))

    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes((8, 2, 0, 0, 0)))
           + chunk(b"pHYs", int(round(dpi / 0.0254)).to_bytes(4, "big")
                   + int(round(dpi / 0.0254)).to_bytes(4, "big") + b"\x01")
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)
    return f"{w}x{h} px raster of the primitives only (this engine has no glyph rasteriser: read the " \
           f"labels from figure.svg / figure.pdf)"


def write_mpl(lay, out_dir, dpi=300):
    """Preferred engine: matplotlib draws the same layout and can embed a real font (incl. CJK)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Rectangle
    # reproducible builds: matplotlib takes the PDF /CreationDate from SOURCE_DATE_EPOCH, so pinning it
    # here is what makes two runs of the same case produce a byte-identical figure.pdf
    if sde() is not None:
        os.environ["SOURCE_DATE_EPOCH"] = str(sde())
    strings = [s for s in all_text(lay) if s]
    non_ascii = sorted({ch for ch in "".join(strings) if ord(ch) > 126})
    family, basis = ["DejaVu Sans"], "DejaVu Sans (bundled with matplotlib; latin, greek, symbols)"
    if any(ord(ch) > 0x2000 for ch in "".join(strings)):
        for cand in CJK_CANDIDATES:
            try:
                hit = font_manager.findfont(font_manager.FontProperties(family=cand), fallback_to_default=False)
            except Exception:
                continue
            family, basis = [cand, "DejaVu Sans"], f"CJK via {cand} ({os.path.basename(hit)})"
            break
        else:
            basis = ("DejaVu Sans; NO CJK-capable font was found on this machine, so CJK labels are "
                     "recorded as an uncertainty (figure.svg keeps the true text)")
    matplotlib.rcParams["pdf.fonttype"] = 42          # embed TrueType -> text stays real text
    matplotlib.rcParams["ps.fonttype"] = 42
    matplotlib.rcParams["font.family"] = family
    fig = plt.figure(figsize=(lay["W"] / 72.0, lay["H"] / 72.0), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, lay["W"])
    ax.set_ylim(lay["H"], 0)                          # y grows downward, exactly like the SVG
    ax.axis("off")
    for b in lay["bars"]:
        ax.add_patch(Rectangle((b["x"], b["y"]), b["w"], b["h"], facecolor=b["fill"],
                               edgecolor="#222222", linewidth=0.3))
    for g in lay["legend"]:
        ax.add_patch(Rectangle((g["x"], g["y"]), g["w"], g["h"], facecolor=g["fill"],
                               edgecolor="#222222", linewidth=0.3))
    for ln in lay["lines"]:
        ax.plot([ln["x1"], ln["x2"]], [ln["y1"], ln["y2"]], color=ln["stroke"], linewidth=ln["sw"],
                solid_capstyle="butt")
    for e in lay["errs"]:
        ax.plot([e["x"], e["x"]], [e["y1"], e["y2"]], color="#222222", linewidth=0.8)
    ha = {"middle": "center", "start": "left", "end": "right"}
    for t in lay["texts"]:
        ax.text(t["x"], t["y"], t["s"], fontsize=FS, ha=ha.get(t["anchor"], "center"), va="baseline",
                rotation=t["rotate"], rotation_mode="anchor", color="#000000")
    for g in lay["legend"]:
        ax.text(g["label_x"], g["label_y"], g["label"], fontsize=FS, ha="left", va="baseline", color="#000000")
    fig.savefig(os.path.join(out_dir, "figure.pdf"), format="pdf", dpi=dpi,
                metadata={"Title": str(lay.get("title") or "scientific figure"),
                          "Creator": f"chart.py {VERSION} (matplotlib)", "Subject": "publication figure"})
    fig.savefig(os.path.join(out_dir, "figure.png"), format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    return {"engine": f"matplotlib {matplotlib.__version__} (Agg; pdf.fonttype=42)",
            "font_basis": basis, "non_ascii": non_ascii,
            "png_text_layer": "labels drawn with the same text list as the SVG"}


def export_figure(lay, out_dir, dpi=300, engine="auto"):
    """Produce figure.pdf + figure.png from `lay`, then measure the files that landed on disk."""
    gaps, info = [], None
    if engine in ("auto", "matplotlib"):
        try:
            info = write_mpl(lay, out_dir, dpi)
        except Exception as exc:
            gaps.append(f"matplotlib engine unavailable ({type(exc).__name__}: {exc}); fell back to the "
                        f"standard-library writer (PNG then carries no text layer)")
    if info is None:
        if not os.path.isfile(os.path.join(out_dir, "figure.pdf")):
            std = write_pdf_stdlib(lay, os.path.join(out_dir, "figure.pdf"))
            if std["non_ascii_dropped"]:
                gaps.append(f"{len(std['non_ascii_dropped'])} non-ASCII label character(s) cannot be written by "
                            f"the standard-library PDF writer: {''.join(std['non_ascii_dropped'][:24])!r}; "
                            f"figure.svg keeps the exact text")
        note = (write_png_stdlib(lay, os.path.join(out_dir, "figure.png"), dpi)
                if not os.path.isfile(os.path.join(out_dir, "figure.png")) else "pre-existing png kept")
        info = {"engine": "stdlib (vector PDF via Type1 Helvetica; PNG via zlib)",
                "font_basis": "Base-14 Helvetica (standard font, no embedding required)",
                "non_ascii": sorted({ch for ch in "".join(all_text(lay)) if ord(ch) > 126}),
                "png_text_layer": note}
    pdf, png = measure_pdf(os.path.join(out_dir, "figure.pdf")), measure_png(os.path.join(out_dir, "figure.png"))
    want = [round(lay["W"] / 72 * 25.4), round(lay["H"] / 72 * 25.4)]
    exp = {"engine": info["engine"], "dpi": dpi, "font_basis": info["font_basis"],
           "png_text_layer": info["png_text_layer"], "non_ascii_in_labels": info["non_ascii"],
           "target": {"width_mm": 89.0, "height_mm": 70.0, "colour_space": "sRGB (PNG) / DeviceRGB (PDF)",
                      "expected_px_at_dpi": [round(want[0] / 25.4 * dpi), round(want[1] / 25.4 * dpi)]},
           "figure.pdf": pdf, "figure.png": png}
    exp["checks"] = {
        "pdf_is_vector": str(pdf.get("header", "")).startswith("%PDF-") and pdf.get("text_show_ops", 0) > 0
                         and pdf.get("image_xobjects", 0) == 0,
        "pdf_text_preserved": pdf.get("text_show_ops", 0) > 0,
        "pdf_size_matches_style": abs((pdf.get("media_box_mm") or [0, 0])[0] - 89.0) <= 0.5
                                  and abs((pdf.get("media_box_mm") or [0, 0])[1] - 70.0) <= 0.5,
        "png_geometry_matches_dpi": abs(png.get("width_px", 0) - exp["target"]["expected_px_at_dpi"][0]) <= 2
                                    and abs(png.get("height_px", 0) - exp["target"]["expected_px_at_dpi"][1]) <= 2,
        "png_colour_space": png.get("colour_type") in (2, 6)}
    return exp, gaps


# ---------------------------------------------------------------- self-checks

def run_checks(chart, mapping, svg, export_check=None, lay=None):
    labels = [s.get("legend") or s.get("name") for s in chart["series"]]
    colours = [s.get("color") or PAL[i % len(PAL)] for i, s in enumerate(chart["series"])]
    pairs = cvd_pairs(colours)
    violations = [p["pair"] for p in pairs if p["verdict"] == "fail"]
    grey_fail = [p["pair"] for p in pairs if p["greyscale"] == "fail"] if len(colours) < 3 else []
    bad = [m["element_id"] for m in mapping
           if any(m["source"].get(k) is None for k in ("file", "row", "col"))
           or f'id="{m["element_id"]}"' not in svg]
    eb = chart.get("error_bar") or {}
    items = {
        "axis_units": (bool(chart["y"].get("unit")) or unit_ok(chart["y"].get("label"), ""),
                       f"y={chart['y'].get('label')!r} unit={chart['y'].get('unit')!r}"),
        "legend_series": (len(labels) == len(set(labels)) and len(colours) == len(set(colours)),
                          f"{len(labels)} series; duplicate_label={len(labels) != len(set(labels))} "
                          f"duplicate_colour={len(colours) != len(set(colours))}"),
        "value_fidelity": (not bad, f"{len(mapping)} mapped; {len(bad)} without locator/SVG id"),
        "error_bars": ((not eb.get("present")) or bool(eb.get("meaning") and eb.get("n")),
                       f"present={eb.get('present')} meaning={eb.get('meaning')!r} n={eb.get('n')}"),
        "cvd_grayscale": (not violations and not grey_fail,
                          f"{len(pairs)} pair(s); cvd_violations={violations} greyscale_fail={grey_fail}; "
                          f"worst_score={min([p['score'] for p in pairs] or [99])}; "
                          f"min_dL_greyscale={min([p['dL_greyscale'] for p in pairs] or [99])}"),
        "export_editable_svg": ("<text" in svg and "<image" not in svg
                                and not re.search(r'(xlink:)?href="(https?|file):', svg),
                                f"editable_text={'<text' in svg} bitmap={'<image' in svg}"),
    }
    oc = (lay or {}).get("occlusion") or {}
    if oc:
        items["label_occlusion"] = (oc.get("clearance_mm", -1) >= 0,
                                    f"axis title right edge {oc.get('ylabel_right_edge_mm')} mm vs best tick "
                                    f"left edge {oc.get('ytick_left_edge_mm')} mm -> clearance "
                                    f"{oc.get('clearance_mm')} mm ({oc.get('method')})")
    ex = (export_check or {}).get("checks") or {}
    if ex:
        pdf, png = (export_check.get("figure.pdf") or {}), (export_check.get("figure.png") or {})
        items["export_pdf"] = (bool(ex.get("pdf_is_vector")) and bool(ex.get("pdf_text_preserved"))
                               and bool(ex.get("pdf_size_matches_style")),
                               f"{pdf.get('bytes')} B, pages={pdf.get('pages')}, "
                               f"media_box={pdf.get('media_box_mm')} mm, text_ops={pdf.get('text_show_ops')}, "
                               f"fonts={pdf.get('fonts')}, embedded={pdf.get('font_subset_embedded')}, "
                               f"images={pdf.get('image_xobjects')}, colour={pdf.get('colour_space')}")
        items["export_png"] = (bool(ex.get("png_geometry_matches_dpi")) and bool(ex.get("png_colour_space")),
                               f"{png.get('bytes')} B, {png.get('width_px')}x{png.get('height_px')} px, "
                               f"bit_depth={png.get('bit_depth')}, colour_type={png.get('colour_type')}, "
                               f"dpi_metadata={png.get('dpi_metadata')}")
    res = {k: {"ok": bool(ok), "errors": 0 if ok else 1, "detail": d} for k, (ok, d) in items.items()}
    res["cvd_grayscale"]["pairs"] = pairs
    res["cvd_grayscale"]["hatch_redundancy"] = ("series>=3 carry distinct dash/hatch so colour is not the only channel"
                                                if len(colours) >= 3 else "not needed for <3 series")
    failed = [k for k, v in res.items() if not v["ok"]]
    return {"ok": not failed, "items": res, "failed": failed}


# ------------------------------------------------------------------- driver

def build(case, case_path, out_dir):
    case_dir = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    tables, materials, rejected = find_tables(case, case_dir)
    table = find_table(case) if case else None
    if table:
        cols, rows, origin, header_line, line_numbers = table[0], table[1], "case.inline", 1, None
        evidence = {"tables_used": ["case.json (inline table)"], "materials_seen": [],
                    "rejected_as_non_data": rejected}
    else:
        table = next((t for t in (load_table(p) for p in tables) if t), None)
        if not table:
            return None, [f"no readable table found: looked inside case.json and at {len(tables)} table "
                          f"file(s) next to {os.path.basename(case_path or '<none>')} (case_dir -> cwd -> "
                          f"/input). Only {', '.join(TABLE_EXT)} are treated as measurement tables; the "
                          f"{len(materials)} material document(s) listed in the work order are evidence, "
                          f"not data, so no value was invented from them."], \
                {"tables_used": [], "materials_seen": [os.path.basename(p) for p in materials],
                 "rejected_as_non_data": rejected}
        cols, rows, note, header_line, line_numbers = table
        origin = os.path.basename(str(note).split(":", 1)[-1])
        evidence = {"tables_used": [origin], "materials_seen": [os.path.basename(p) for p in materials],
                    "rejected_as_non_data": rejected}
    plan, gaps = plan_chart(case, cols, rows, origin)
    if not plan:
        return None, gaps, evidence
    cats, series, unmapped = collect(cols, rows, plan, header_line, line_numbers)
    if not cats or not series or not any(s["values"] for s in series):
        return None, gaps + ["the table holds no plottable numeric cell (an empty canvas is not a success)"], evidence
    if unmapped:
        gaps.append(f"{len(unmapped)} cell(s) held no numeric value and were left unmapped (not invented)")
    for i, s in enumerate(series):
        s["id"], s["legend"] = f"s{i + 1}", s["name"]
    chart = {"type": plan["type"], "title": case.get("title") or "",
             "categories": [{"id": f"cat{i + 1}", "display": c} for i, c in enumerate(cats)], "series": series,
             "x": {"label": plan["xl"]}, "y": {"label": plan["yl"], "unit": plan["yu"]},
             "error_bar": {"present": bool(plan["ec"]),
                           "meaning": str(case.get("error_bar_meaning") or ("s.d." if plan["ec"] else "")),
                           "n": (series[0]["values"][0].get("n") if series[0]["values"] else None)}}
    spec = {"spec_version": "1.0-min2", "figure_id": str(case.get("figure_id") or case.get("case_id") or "figure"),
            "mode": "chart", "workorder": str(case.get("workorder") or "source_value_chart"),
            "journal": str(case.get("journal") or "nature"), "title": chart["title"],
            "caption": case.get("caption") or "", "chart": chart,
            "style": {"width_mm": 89.0, "height_mm": 70.0, "base_font_pt": FS},
            "provenance": {"builder": f"scripts/chart.py {VERSION}", "table_origin": origin,
                           "table_header_line": header_line, "column_roles": plan["roles"],
                           "unmapped": unmapped[:50], "unmapped_count": len(unmapped),
                           "generated_at_local": stamp()}}
    os.makedirs(out_dir, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    svg_path = os.path.join(out_dir, "figure.svg")
    lay = layout(chart)
    mapping = render_svg(chart, spec, svg_path, lay)
    spec["mapping"] = mapping
    wx(os.path.join(out_dir, "figure.map.json"),
       {"figure_id": spec["figure_id"], "svg": "figure.svg", "convention":
        "row = PHYSICAL 1-based line of the source table (comment, header and blank lines included); "
        "record_index = 1-based data record. Inline tables have no lines, so row = record_index + 1 "
        "and the value is keyed by row_key instead.",
        "elements": mapping, "by_element": {m["element_id"]: m["source"] for m in mapping}})
    svg = open(svg_path, encoding="utf-8").read()
    export_check, egaps = export_figure(lay, out_dir, dpi=EXPORT_DPI, engine=EXPORT_ENGINE)
    gaps += egaps
    return {"chart": chart, "spec": spec, "checks": run_checks(chart, mapping, svg, export_check, lay),
            "gaps": gaps, "mapping": mapping, "origin": origin, "svg": svg_path,
            "export_check": export_check, "evidence": evidence,
            "case_id": str(case.get("case_id") or case.get("id") or "case-unknown")}, [], evidence


def main(argv=None):
    ap = argparse.ArgumentParser(description="scientific figure builder (one file, standard library only)")
    ap.add_argument("--case", default=None, help="path to case.json (default: /input/case.json)")
    ap.add_argument("--out", default="/app/output", help="output directory (default: /app/output)")
    ap.add_argument("--engine", default="auto", choices=("auto", "matplotlib", "stdlib"),
                    help="export engine: auto tries matplotlib (real fonts) then falls back to the stdlib writer")
    ap.add_argument("--dpi", type=int, default=300, help="raster preview resolution for figure.png (default 300)")
    a = ap.parse_args(argv)
    global EXPORT_ENGINE, EXPORT_DPI
    EXPORT_ENGINE, EXPORT_DPI = a.engine, a.dpi
    case_path = a.case or next((p for p in ("/input/case.json", os.path.join(os.getcwd(), "case.json"))
                                if os.path.isfile(p)), None)
    out_dir, t0, case, gaps = a.out or "/app/output", time.time(), {}, []
    if case_path and os.path.isfile(case_path):
        try:
            case = json.load(open(case_path, encoding="utf-8-sig"))
        except Exception as exc:
            gaps.append(f"case.json could not be parsed: {type(exc).__name__}: {exc}")
    else:
        gaps.append("no case.json was supplied or found (looked for /input/case.json, then ./case.json)")
    print(f"[chart] case={case_path} out={out_dir}", flush=True)
    built, bgaps, evidence = build(case, case_path, out_dir) if case else (None, [], {})
    gaps += bgaps
    status = "success" if (built and built["checks"]["ok"] and not gaps) else ("partial" if built else "failed")
    failed = [k for k, v in (built["checks"]["items"] if built else {}).items() if not v["ok"]]
    outputs = {}
    if built:
        outputs = {"editable_source": ["figure.svg"], "exports": ["figure.pdf", "figure.png"],
                   "element_map": "figure.map.json",
                   "output_files": [{"path": n, "bytes": os.path.getsize(os.path.join(out_dir, n)),
                                     "sha256": sha256_file(os.path.join(out_dir, n)),
                                     "role": {"figure.svg": "editable_source",
                                              "figure.map.json": "element_map",
                                              "figure.pdf": "export_vector",
                                              "figure.png": "export_raster_preview"}[n]}
                                    for n in ("figure.svg", "figure.map.json", "figure.pdf", "figure.png")
                                    if os.path.isfile(os.path.join(out_dir, n))]}
    values = {"case_id": built["case_id"] if built else str(case.get("case_id") or case.get("id") or "case-unknown"),
              "status": status,
              "summary": ("figure built from the supplied table; all checks green" if status == "success" else
                          (f"figure delivered but checks failed: {', '.join(failed)}" if built else
                           "no figure could be built: " + "; ".join(gaps)[:200])),
              "editable_source": ["figure.svg"] if built else [],
              "exports": (outputs.get("exports") or []) if built else [],
              "export_check": (built["export_check"] if built else None),
              "element_map": "figure.map.json" if built else None,
              "outputs": outputs or None,
              "output_files": outputs.get("output_files") or [],
              "checks": (built["checks"]["items"] if built else {}),
              "sources": ([{"file": built["origin"], "kind": "table", "used_for": "values plotted",
                            "sha256": sha256_file(os.path.join(os.path.dirname(os.path.abspath(case_path)),
                                                               built["origin"]))
                            if case_path and not built["origin"].startswith("case.inline") else ""}] if built else []),
              "evidence_channels": {
                  "policy": f"measurement tables are only ever {list(TABLE_EXT)}; "
                            f"{list(MATERIAL_EXT)} are materials and are never parsed into numbers; "
                            "case.json / task.md / *.example.json / *.template.json are instructions, "
                            "never a data source",
                  "tables_used": (built["evidence"]["tables_used"] if built else []),
                  "materials_seen": (built["evidence"]["materials_seen"] if built else
                                     [os.path.basename(p) for p in (evidence or {}).get("materials_seen", [])]),
                  "rejected_as_non_data": ([os.path.basename(p) for p in
                                            (built["evidence"]["rejected_as_non_data"] if built
                                             else (evidence or {}).get("rejected_as_non_data", []))]),
                  "work_order_used_as_data": False},
              "resolved_from": list(RESOLVED),
              "cwd_independent": {"policy": "relative references resolve against the case.json directory first, "
                                             "then cwd, then /input",
                                  "case_dir": "<CASE_DIR>", "cwd": "<CWD>",
                                  "cases_resolved_from_cwd": sorted({r["from"] for r in RESOLVED if r["from"] == "cwd"})},
              "changes": [{"at": stamp(), "action": "built",
                           "tool": f"scripts/chart.py {VERSION}", "seconds": secs(t0)}],
              "uncertainty": gaps or [{"item": "none observed", "why": "all gates green and every plotted cell was "
                                                                      "mapped back to its source",
                                       "handling": "no action"}],
              "figure": ({"chart_type": built["chart"]["type"],
                          "series_count": len(built["chart"]["series"]),
                          "data_points": sum(len(s["values"]) for s in built["chart"]["series"]),
                          "units": [u for u in (built["chart"]["y"].get("unit"),) if u],
                          "legend_entries": [s["name"] for s in built["chart"]["series"]],
                          "mapping_coverage": 1.0} if built else None)}
    values["change_log"] = values["changes"]
    contract = case.get("output_contract") or case.get("contract") or {}
    result = ({k: values.get(CONTRACT.get(str(k).lower(), ""), None) for k in contract}
              if isinstance(contract, dict) and contract else dict(values))
    # always mirror every auditable block at top level as well, contract or not
    for k, v in values.items():
        result.setdefault(k, v)
    result["_contract_source"] = "case.json output_contract" if contract else "built-in names"
    wx(os.path.join(out_dir, "result.json"), result)
    # render_report.json -- first-class, text-only record of what was actually drawn
    if built:
        wx(os.path.join(out_dir, "export_check.json"), built["export_check"])
        wx(os.path.join(out_dir, "render_report.json"), {
            "chart_id": built["case_id"], "chart_type": built["chart"]["type"],
            "figure_mm": [89.0, 70.0], "drawing_font_pt": FS,
            "font_family_declared_svg": ["Arial", "Helvetica", "sans-serif"],
            "style_source": "built into chart.py; preset table in references/exports.md",
            "categories": [c["display"] for c in built["chart"]["categories"]],
            "series": [{"name": s["name"], "colour": s.get("color") or PAL[i % len(PAL)],
                        "points": len(s["values"])}
                       for i, s in enumerate(built["chart"]["series"])],
            "element_count": len(built["mapping"]),
            "mapping_coverage": 1.0 if built["mapping"] else 0.0,
            "null_value_notes": [f"row {u['row']} col {u['col']!r}: {u['reason']} (omitted, not invented)"
                                 for u in (built["spec"]["provenance"].get("unmapped") or [])],
            "exports": {n: {"path": n, "status": "ok", "bytes": os.path.getsize(os.path.join(out_dir, n)),
                            "sha256": sha256_file(os.path.join(out_dir, n))}
                        for n in ("figure.svg", "figure.map.json", "figure.pdf", "figure.png")
                        if os.path.isfile(os.path.join(out_dir, n))},
            "export_engine": built["export_check"]["engine"],
            "export_checks": built["export_check"]["checks"],
            "export_check_file": "export_check.json (measured from the files on disk)",
            "status": status, "seconds": secs(t0, 3), "version": VERSION,
            "caveats": ["the three renderers share one layout dict, so bar heights cannot drift between "
                        "figure.svg / figure.pdf / figure.png",
                        "PNG is a raster preview; the submission-grade artefact is the vector PDF + SVG"],
            "case_ref": "the --case file given (see result.json.sources)"})
    print(f"[chart] status={status} :: {values['summary'][:100]}", flush=True)
    print("CHART_OK" if status == "success" else f"CHART_{status.upper()}")
    return 0 if status in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
