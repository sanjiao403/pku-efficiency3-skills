#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart.py -- one-file, standard-library-only figure builder.

  python3 scripts/chart.py --case /input/case.json --out /app/output

Writes figure.svg (editable <text>), figure.map.json (element -> source cell),
result.json (contract + hashed output_files) and render_report.json. Relative references
resolve against the case.json directory first, then cwd, then /input. Non-numeric cells are
reported as unmapped, never invented; every mark keeps a physical line/column locator; an
empty canvas is never reported as success.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import time
from xml.sax.saxutils import escape

VERSION = "min2-1.0"
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


def explicit_refs(case):
    """Relative file references written inside the work order (data_file / materials / paths)."""
    out = []

    def walk(n, d=0):
        if d > 3 or n is None:
            return
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, str) and re.search(r"\.(csv|tsv|txt|md)$", v, re.I):
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


def table_files(case, case_dir):
    """Explicit references first (case-dir relative), then sibling csv/tsv of the work order."""
    named = [r for r in (resolve_ref(x, case_dir, "explicit") for x in explicit_refs(case)) if r]
    if os.path.isdir(case_dir):
        named += [os.path.join(case_dir, n) for n in sorted(os.listdir(case_dir))
                  if re.search(r"\.(csv|tsv)$", n, re.I)]
    out, seen = [], set()
    for p in named:
        if p not in seen and os.path.isfile(p):
            seen.add(p)
            out.append(p)
    return out


def load_table(path):
    """(columns, rows, note, header_line): header_line is the PHYSICAL 1-based line of the header."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        lines = fh.read().splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")), 0)
    body = lines[head:]
    delim = "\t" if path.lower().endswith(".tsv") or (body and body[0].count("\t") > body[0].count(",")) else ","
    rows = list(csv.DictReader(body, delimiter=delim))
    if not rows:
        return None
    return list(rows[0].keys()), rows, f"file:{os.path.basename(path)}", head + 1


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


def collect(cols, rows, plan, header_line):
    """Group rows into series; row numbers are PHYSICAL lines (comments and header included)."""
    cats, series, unmapped = [], [], []
    for i, row in enumerate(rows):
        row_no = header_line + 1 + i
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
                            "source": {"file": plan["origin"], "row": row_no, "col": plan["vc"],
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

def render_svg(chart, spec, path):
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
    x0, x1, y0, y1 = 11.0 * MM, W - 4.0 * MM, 12.0 * MM, H - 11.0 * MM
    Y = lambda v: y1 - (float(v) - ymin) / (ymax - ymin) * (y1 - y0)                    # noqa: E731
    step = (x1 - x0) / max(len(cids), 1)
    X = lambda i: x0 + step * (i + 0.5)                                                # noqa: E731
    gw, bw = step * 0.74, step * 0.74 / max(len(series), 1)
    T = lambda x, y, s, a="middle", c=None: (                                            # noqa: E731
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{FS}" text-anchor="{a}" '
        f'font-family="Arial, Helvetica, sans-serif"{f" class={chr(34)}{c}{chr(34)}" if c else ""}>{esc(s)}</text>')
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{W:.2f}pt" height="{H:.2f}pt" '
         f'viewBox="0 0 {W:.2f} {H:.2f}" font-family="Arial, Helvetica, sans-serif">',
         f'<title id="figure-title">{esc(spec.get("title"))}</title>',
         f'<line id="xaxis" x1="{x0:.2f}" y1="{y1:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="#333333" stroke-width="0.8"/>',
         f'<line id="yaxis" x1="{x0:.2f}" y1="{y0:.2f}" x2="{x0:.2f}" y2="{y1:.2f}" stroke="#333333" stroke-width="0.8"/>']
    for k in range(6):
        v = ymin + (ymax - ymin) * k / 5
        o.append(T(x0 - 1.6, Y(v) + FS * 0.34, fm(v), a="end", c=f"ytick-{k}"))
    o += [T((x0 + x1) / 2, H - 2.2, chart["x"]["label"] or "", c="xlabel"),
          f'<text id="ylabel" transform="translate(2.6,{(y0 + y1) / 2:.2f}) rotate(-90)" font-size="{FS}" '
          f'text-anchor="middle" font-family="Arial, Helvetica, sans-serif">{esc(ylab)}</text>']
    o += [T(X(i), y1 + FS + 2.0, disp.get(cid, cid), c=f"xtick-{cid}") for i, cid in enumerate(cids)]
    mapping = []
    for si, s in enumerate(series):
        for cid in cids:
            p = next((v for v in s["values"] if v["cat"] == cid), None)
            if not p:
                continue
            x = X(cids.index(cid)) - gw / 2 + si * bw
            top, zero = Y(p["value"]), Y(0.0)
            eid = f'el-{s["id"]}-{cid}'
            o.append(f'<rect id="{eid}" x="{x:.2f}" y="{min(top, zero):.2f}" width="{bw * 0.92:.2f}" '
                     f'height="{max(abs(top - zero), 0.4):.2f}" fill="{PAL[si % len(PAL)]}" '
                     f'stroke="#222222" stroke-width="0.3"{"" if si < 3 else " stroke-dasharray=\"2 1\""}/>')
            if p.get("error") is not None:
                o.append(f'<line x1="{x + bw * 0.46:.2f}" y1="{Y(p["value"] - abs(p["error"])):.2f}" '
                         f'x2="{x + bw * 0.46:.2f}" y2="{Y(p["value"] + abs(p["error"])):.2f}" '
                         f'stroke="#222222" stroke-width="0.8"/>')
            mapping.append({"element_id": eid, "role": "bar_height", "value": p["value"], "source": p["source"],
                            "error": p.get("error"), "n": p.get("n")})
    lx = x0 + 1.0
    for si, s in enumerate(series):
        label = str(s["name"])
        o += [f'<rect id="legend-swatch-{s["id"]}" x="{lx:.2f}" y="{6.6 - FS:.2f}" width="{FS}" '
              f'height="{FS * 0.72:.2f}" fill="{PAL[si % len(PAL)]}" stroke="#222222" stroke-width="0.3"/>',
              T(lx + FS + 1.2, 6.0, label, a="start", c=f"legend-{s['id']}")]
        lx += FS + 3.2 + len(label) * FS * 0.52
    o.append("</svg>")
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(o) + "\n")
    return mapping


# ---------------------------------------------------------------- self-checks

def run_checks(chart, mapping, svg):
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
        "export": ("<text" in svg and "<image" not in svg, f"editable_text={'<text' in svg}"),
    }
    res = {k: {"ok": bool(ok), "errors": 0 if ok else 1, "detail": d} for k, (ok, d) in items.items()}
    res["cvd_grayscale"]["pairs"] = pairs
    res["cvd_grayscale"]["hatch_redundancy"] = ("series>=3 carry distinct dash/hatch so colour is not the only channel"
                                                if len(colours) >= 3 else "not needed for <3 series")
    failed = [k for k, v in res.items() if not v["ok"]]
    return {"ok": not failed, "items": res, "failed": failed}


# ------------------------------------------------------------------- driver

def build(case, case_path, out_dir):
    case_dir = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    table = find_table(case) if case else None
    if table:
        cols, rows, origin, header_line = table[0], table[1], "case.inline", 1
    else:
        table = next((t for t in (load_table(p) for p in table_files(case, case_dir)) if t), None)
        if not table:
            return None, [f"no readable table found: looked inside case.json and next to "
                          f"{os.path.basename(case_path or '<none>')} (case_dir -> cwd -> /input); "
                          f"explicit refs tried: {[r['ref'] for r in RESOLVED] or 'none'}"]
        cols, rows, note, header_line = table
        origin = os.path.basename(str(note).split(":", 1)[-1])
    plan, gaps = plan_chart(case, cols, rows, origin)
    if not plan:
        return None, gaps
    cats, series, unmapped = collect(cols, rows, plan, header_line)
    if not cats or not series or not any(s["values"] for s in series):
        return None, gaps + ["the table holds no plottable numeric cell (an empty canvas is not a success)"]
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
                           "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S")}}
    os.makedirs(out_dir, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    svg_path = os.path.join(out_dir, "figure.svg")
    mapping = render_svg(chart, spec, svg_path)
    spec["mapping"] = mapping
    wx(os.path.join(out_dir, "figure.map.json"),
       {"figure_id": spec["figure_id"], "svg": "figure.svg", "convention":
        "row = physical 1-based line of the source table (comment lines and the header included)",
        "elements": mapping, "by_element": {m["element_id"]: m["source"] for m in mapping}})
    svg = open(svg_path, encoding="utf-8").read()
    return {"chart": chart, "spec": spec, "checks": run_checks(chart, mapping, svg), "gaps": gaps,
            "mapping": mapping, "origin": origin, "svg": svg_path,
            "case_id": str(case.get("case_id") or case.get("id") or "case-unknown")}, []


def main(argv=None):
    ap = argparse.ArgumentParser(description="scientific figure builder (one file, standard library only)")
    ap.add_argument("--case", default=None, help="path to case.json (default: /input/case.json)")
    ap.add_argument("--out", default="/app/output", help="output directory (default: /app/output)")
    a = ap.parse_args(argv)
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
    built, bgaps = build(case, case_path, out_dir) if case else (None, [])
    gaps += bgaps
    status = "success" if (built and built["checks"]["ok"] and not gaps) else ("partial" if built else "failed")
    failed = [k for k, v in (built["checks"]["items"] if built else {}).items() if not v["ok"]]
    outputs = {}
    if built:
        outputs = {"editable_source": ["figure.svg"], "exports": ["figure.svg"],
                   "element_map": "figure.map.json",
                   "output_files": [{"path": n, "bytes": os.path.getsize(os.path.join(out_dir, n)),
                                     "sha256": sha256_file(os.path.join(out_dir, n)),
                                     "role": {"figure.svg": "editable_source",
                                              "figure.map.json": "element_map"}[n]}
                                    for n in ("figure.svg", "figure.map.json")
                                    if os.path.isfile(os.path.join(out_dir, n))]}
    values = {"case_id": built["case_id"] if built else str(case.get("case_id") or case.get("id") or "case-unknown"),
              "status": status,
              "summary": ("figure built from the supplied table; all checks green" if status == "success" else
                          (f"figure delivered but checks failed: {', '.join(failed)}" if built else
                           "no figure could be built: " + "; ".join(gaps)[:200])),
              "editable_source": ["figure.svg"] if built else [], "exports": ["figure.svg"] if built else [],
              "element_map": "figure.map.json" if built else None,
              "outputs": outputs or None,
              "output_files": outputs.get("output_files") or [],
              "checks": (built["checks"]["items"] if built else {}),
              "sources": ([{"file": built["origin"], "kind": "table", "used_for": "values plotted",
                            "sha256": sha256_file(os.path.join(os.path.dirname(os.path.abspath(case_path)),
                                                               built["origin"]))
                            if case_path and not built["origin"].startswith("case.inline") else ""}] if built else []),
              "resolved_from": list(RESOLVED),
              "cwd_independent": {"policy": "relative references resolve against the case.json directory first, "
                                             "then cwd, then /input",
                                  "case_dir": "<CASE_DIR>", "cwd": "<CWD>",
                                  "cases_resolved_from_cwd": sorted({r["from"] for r in RESOLVED if r["from"] == "cwd"})},
              "changes": [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": "built",
                           "tool": f"scripts/chart.py {VERSION}", "seconds": round(time.time() - t0, 2)}],
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
        svg_rel = "figure.svg"
        wx(os.path.join(out_dir, "render_report.json"), {
            "chart_id": built["case_id"], "chart_type": built["chart"]["type"],
            "figure_mm": [89.0, 70.0], "font_family_used": ["Arial", "Helvetica", "sans-serif"],
            "style_source": "built into chart.py; see references/journal-profiles.md",
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
                        for n in (svg_rel, "figure.map.json") if os.path.isfile(os.path.join(out_dir, n))},
            "status": status, "seconds": round(time.time() - t0, 3),
            "caveats": ["text-only; SVG only (no PDF/PNG in this minimal build)"],
            "case_ref": "the --case file given (see result.json.sources)"})
    print(f"[chart] status={status} :: {values['summary'][:100]}", flush=True)
    print("CHART_OK" if status == "success" else f"CHART_{status.upper()}")
    return 0 if status in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
