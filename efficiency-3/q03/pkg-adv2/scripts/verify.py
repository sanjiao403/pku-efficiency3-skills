#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py -- read-only recomputation of every claim chart.py makes.

  python3 scripts/verify.py --case /input/case.json --out /app/output

Opens ONLY the produced artefacts plus the referenced table and recomputes: bytes/sha256, element
ids in the SVG, every value re-read from its source cell (PHYSICAL line numbers), axis unit, legend
uniqueness, colour-vision/greyscale separation (Machado 2009 + CIE76 dE) and the contract echo.
Prints expected-vs-actual rows, writes verification_report.json, exits non-zero on any failure.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import zlib

NUM = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?%?")
CVD = {"deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413),
                        (-0.011820, 0.042940, 0.968881)),
       "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
                      (-0.003882, -0.048116, 1.051998)),
       "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602),
                      (0.004733, 0.691367, 0.303900))}


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\u2212", "-")
    return float(s.rstrip("%")) if NUM.fullmatch(s) else None


def rd(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f(t):
    return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116


def _lab(h):
    h = str(h).lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (128, 128, 128)
    r, g, b = _lin(r), _lin(g), _lin(b)
    X, Y, Z = 0.4124 * r + 0.3576 * g + 0.1805 * b, 0.2126 * r + 0.7152 * g + 0.0722 * b, \
        0.0193 * r + 0.1192 * g + 0.9505 * b
    fx, fy, fz = _f(X / 0.95047), _f(Y), _f(Z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def simulate(h, kind):
    h = str(h).lstrip("#")
    lin = [_lin(int(h[i:i + 2], 16)) for i in (0, 2, 4)]
    if kind == "achromatopsia":
        g = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        lin = [g, g, g]
    elif kind in CVD:
        m = CVD[kind]
        lin = [sum(m[i][j] * lin[j] for j in range(3)) for i in range(3)]
    return _lab_of_lin([min(max(v, 0.0), 1.0) for v in lin])


def _lab_of_lin(lin):
    r, g, b = lin
    X, Y, Z = 0.4124 * r + 0.3576 * g + 0.1805 * b, 0.2126 * r + 0.7152 * g + 0.0722 * b, \
        0.0193 * r + 0.1192 * g + 0.9505 * b
    fx, fy, fz = _f(X / 0.95047), _f(Y), _f(Z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def de76(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def inline_table(case):
    """(columns, rows, header_line, line_numbers) when the work order carries its table inline.

    Inline JSON has no physical lines, so the chart writes row = record_index + 1 and line_numbers
    stays None: the value is re-read from the record, not from a line that does not exist."""
    def pair(d):
        c, r = d.get("columns"), d.get("rows")
        return ([str(x) for x in c], r) if isinstance(c, list) and isinstance(r, list) and r else None
    if isinstance(case, dict):
        if pair(case):
            return pair(case)[0], pair(case)[1], 1, None
        for v in case.values():
            if isinstance(v, list) and v and all(isinstance(r, dict) for r in v) \
                    and any(num(x) is not None for r in v for x in r.values()):
                return list(dict.fromkeys(k for r in v for k in r)), v, 1, None
            if isinstance(v, dict) and pair(v):
                return pair(v)[0], pair(v)[1], 1, None
    return None


def load_tables(case, case_dir):
    """{basename: (columns, rows, header_line, line_numbers)}; comment and blank lines are counted."""
    out = {}
    inl = inline_table(case)
    if inl:
        out["case.inline"] = inl
    names = re.findall(r'"([^"]{1,200}\.(?:csv|tsv))"', json.dumps(case, ensure_ascii=False), re.I)
    if os.path.isdir(case_dir):
        names += [n for n in sorted(os.listdir(case_dir)) if re.search(r"\.(csv|tsv)$", n, re.I)]
    for n in names:
        p = os.path.normpath(n if os.path.isabs(n) else os.path.join(case_dir, n))
        if not os.path.isfile(p):
            continue
        lines = open(p, encoding="utf-8-sig").read().splitlines()
        head = next((i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")), 0)
        body = lines[head:]
        delim = "\t" if p.lower().endswith(".tsv") or (body and body[0].count("\t") > body[0].count(",")) else ","
        reader = csv.DictReader(body, delimiter=delim)
        rows, lineno = [], []
        for rec in reader:
            rows.append(rec)
            lineno.append(head + reader.line_num)
        if rows:
            out[os.path.basename(p)] = (list(rows[0].keys()), rows, head + 1, lineno)
    return out


def read_material(case_dir):
    lines = {}
    if os.path.isdir(case_dir):
        for n in sorted(os.listdir(case_dir)):
            if re.search(r"\.(txt|md)$", n, re.I):
                try:
                    lines[n] = open(os.path.join(case_dir, n), encoding="utf-8-sig").read().splitlines()
                except Exception:
                    continue
    return lines


def pdf_content(path):
    """Concatenated, inflated content streams of the produced PDF."""
    raw = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n", raw):
        end = raw.find(b"endstream", m.end())
        if end >= 0:
            blob = raw[m.end():end]
            try:
                out.append(zlib.decompress(blob))
            except Exception:
                out.append(blob)
    return b"\n".join(out)


def png_pixels(path):
    """Decoded RGB rows of the produced PNG (all five filter types), or None if it is not readable."""
    raw = open(path, "rb").read()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w = h = None
    depth = ctype = None
    idat, i = b"", 8
    while i + 8 <= len(raw):
        ln = int.from_bytes(raw[i:i + 4], "big")
        typ, data = raw[i + 4:i + 8], raw[i + 8:i + 8 + ln]
        if typ == b"IHDR":
            w, h = int.from_bytes(data[0:4], "big"), int.from_bytes(data[4:8], "big")
            depth, ctype = data[8], data[9]
        elif typ == b"IDAT":
            idat += data
        i += 12 + ln
        if typ == b"IEND":
            break
    bpp = {2: 3, 6: 4, 0: 1}.get(ctype or -1)
    if not w or not h or depth != 8 or bpp is None:
        return None
    buf = zlib.decompress(idat)
    stride = w * bpp + 1
    rows, prev = [], bytearray(w * bpp)
    for y in range(h):
        off = y * stride
        ft, line = buf[off], bytearray(buf[off + 1:off + 1 + w * bpp])
        if ft == 0:
            pass
        elif ft == 2:
            for x in range(len(line)):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ft == 1:
            for x in range(bpp, len(line)):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ft == 3:
            for x in range(len(line)):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ft == 4:
            for x in range(len(line)):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        else:
            return None
        rows.append(line)
        prev = line
    return {"w": w, "h": h, "bpp": bpp, "rows": rows}


def sample_px(rows, w, h, bpp, x_user, y_user, view_w):
    """Sample one pixel given user-space (pt) coordinates of the SVG, scaled to raster pixels."""
    if not view_w:
        return None
    k = w / float(view_w)
    px, py = int(x_user * k), int(y_user * k)
    if not (0 <= px < w and 0 <= py < h):
        return None
    off = px * bpp
    return tuple(rows[py][off:off + 3])


def hex_rgb(value):
    h = str(value).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (0, 0, 0)


def collect_rows(out_dir, case_path):
    rows = []
    case = rd(case_path, {}) if case_path else {}
    case_dir = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    svg_p, map_p, res_p = (os.path.join(out_dir, n) for n in ("figure.svg", "figure.map.json", "result.json"))
    svg = open(svg_p, encoding="utf-8").read() if os.path.isfile(svg_p) else ""
    emap = rd(map_p, {}) or {}
    result = rd(res_p, {}) or {}
    forward = emap.get("forward") or emap.get("elements") or []
    tables, materials = load_tables(case, case_dir), read_material(case_dir)

    def add(name, expected, actual, ok, note=""):
        rows.append({"check": name, "expected": expected, "actual": actual, "ok": bool(ok), "note": note})

    claimed = ((result.get("outputs") or {}).get("output_files") or result.get("output_files") or [])
    bad = []
    for item in claimed:
        p = os.path.join(out_dir, os.path.basename(str(item.get("path"))))
        if not os.path.isfile(p):
            bad.append(f"{item.get('path')}:missing")
        elif os.path.getsize(p) != item.get("bytes") or sha256_file(p) != item.get("sha256"):
            bad.append(f"{item.get('path')}:bytes/sha256")
    add("output_files_hashed", f"{len(claimed)} declared", f"{len(bad)} mismatch", claimed and not bad,
        "bytes/sha256 re-derived from disk")

    ids = [str(e.get("element_id")) for e in forward]
    missing = [i for i in ids if f'id="{i}"' not in svg]
    add("elements_in_svg", f"{len(ids)} mapped", f"{len(missing)} missing", ids and not missing, "")

    checked, mismatch, unverifiable = 0, [], 0
    for e in forward:
        v, src = num(e.get("value")), (e.get("source") or {})
        if v is None:
            q, line = src.get("quote"), src.get("line")
            if q and line:
                checked += 1
                blob = " ".join(lines[line - 1] for lines in materials.values() if 0 < line <= len(lines))
                if q not in blob:
                    mismatch.append(f"{e.get('element_id')}:quote@line{line}")
            continue
        f, r, c = os.path.basename(str(src.get("file") or "")), src.get("row"), src.get("col")
        if f and f not in tables:
            # a locator may only point at a file that really was loaded as a measurement table; an
            # unknown name (a material, the work order, a renamed file) must go red instead of being
            # silently re-pointed at whatever table happens to be lying around
            if f.startswith("case.inline") and tables:
                cols, tbl, header_line, linenos = next(iter(tables.values()))
            else:
                unverifiable += 1
                mismatch.append(f"{e.get('element_id')}:source_file_not_a_table({f})")
                continue
        else:
            cols, tbl, header_line, linenos = tables.get(f) or (None, None, 1, None)
        if not tbl or not isinstance(r, int) or not c:
            unverifiable += 1
            continue
        checked += 1
        # a physical row number is looked up among the physical line numbers, so a blank or comment
        # line inside the table cannot silently shift every value by one record
        if linenos and r in linenos:
            row = tbl[linenos.index(r)]
        else:
            idx = r - (header_line or 1) - 1
            row = tbl[idx] if 0 <= idx < len(tbl) else None
        if isinstance(row, dict):
            cell = row.get(c)
        elif isinstance(row, (list, tuple)) and c in cols:
            cell = row[cols.index(c)] if cols.index(c) < len(row) else None
        else:
            cell = None
        if num(cell) is None or abs(num(cell) - v) > 1e-9:
            mismatch.append(f"{e.get('element_id')}:{v}!={cell}")
    add("values_match_source", f"{checked} re-read", f"{len(mismatch)} mismatch",
        checked > 0 and not mismatch, f"unverifiable={unverifiable}; {mismatch[:2]}")

    fig = result.get("figure") or {}
    units = [u for u in (fig.get("units") or []) if u]
    ylabel = re.search(r'id="ylabel"[^>]*>(.*?)</text>', svg, re.S)
    ytext = ylabel.group(1) if ylabel else ""
    add("axis_unit_on_axis", f"units {units}", f"ylabel={ytext[:36]!r}",
        (not units) or all(u in ytext for u in units), "")
    dimless = ("relative", "fold change", "ratio", "%", "a.u.", "index", "score", "normalis", "normaliz")
    low = " " + re.sub(r"[^a-z0-9.%]+", " ", ytext.lower()).strip() + " "
    declared = bool(re.search(r"\([^)]+\)\s*$", ytext)) or ("%" in ytext) or any(f" {t} " in low for t in dimless)
    add("axis_unit_declared", "unit or dimensionless", f"ylabel={ytext[:36]!r}", declared,
        "a physical quantity without a unit is a defect")

    colours = re.findall(r'<rect id="el-[^"]*"[^>]*fill="(#[0-9A-Fa-f]{6})"', svg)
    colours = list(dict.fromkeys(colours))
    pairs = []
    for i in range(len(colours)):
        for j in range(i + 1, len(colours)):
            score = min([de76(simulate(colours[i], "normal"), simulate(colours[j], "normal"))]
                        + [de76(simulate(colours[i], k), simulate(colours[j], k)) for k in CVD])
            grey = abs(simulate(colours[i], "normal")[0] - simulate(colours[j], "normal")[0])
            pairs.append((min(score, 99), grey))
    worst = min([p[0] for p in pairs] or [99])
    worst_g = min([p[1] for p in pairs] or [99])
    # same rule as chart.run_checks: colour-blind separation <12 fails; greyscale <5 only fails when
    # colour is the sole channel (<3 series), otherwise it is a warning the author is told about
    ok_cvd = worst >= 12 and not (len(colours) < 3 and worst_g < 5)
    add("cvd_grayscale_recomputed", "dE>=12; dL*>=5 if colour is the only channel",
        f"dE={worst:.2f} dL*={worst_g:.2f} ({len(pairs)} pair(s), {len(colours)} colour(s))",
        ok_cvd, "Machado 2009 s1.0 + CIE76, from the SVG fills only")

    labels = [str(x) for x in (fig.get("legend_entries") or [])]
    drawn = [t for t in labels if re.search(r">\s*" + re.escape(t) + r"\s*<", svg)]
    add("legend_unique_present", f"{len(labels)} unique", f"{len(set(labels))} unique/{len(drawn)} drawn",
        len(labels) == len(set(labels)) and len(drawn) == len(labels), ", ".join(labels[:3]))

    # ---------------------------------------------------------------- exports
    # The exports are re-derived from the files on disk and cross-checked against the SVG geometry:
    # the PDF must carry one rectangle per SVG rect and real text operators, and the PNG raster must
    # be painted where the SVG says a bar is (and blank just above it). Nothing is taken on trust.
    pdf_p, png_p = os.path.join(out_dir, "figure.pdf"), os.path.join(out_dir, "figure.png")
    ex = result.get("export_check") or {}
    claims = ((ex.get("figure.pdf") or {}), (ex.get("figure.png") or {}))
    bad = []
    for p, claim in ((pdf_p, claims[0]), (png_p, claims[1])):
        if not os.path.isfile(p):
            bad.append(f"{os.path.basename(p)}:missing")
        elif os.path.getsize(p) != claim.get("bytes") or sha256_file(p) != claim.get("sha256"):
            bad.append(f"{os.path.basename(p)}:bytes/sha256")
    add("export_artefacts_hashed", "figure.pdf + figure.png with matching bytes/sha256",
        f"{len(bad)} mismatch", os.path.isfile(pdf_p) and os.path.isfile(png_p) and not bad, ", ".join(bad[:2]))

    content = pdf_content(pdf_p) if os.path.isfile(pdf_p) else b""
    raw_pdf = open(pdf_p, "rb").read() if os.path.isfile(pdf_p) else b""
    rects_svg = len(re.findall(r"<rect\b", svg))
    rects_pdf = len(re.findall(rb"\bre\b", content))
    text_svg = len(re.findall(r"<text\b", svg))
    text_pdf = len(re.findall(rb"\bT[jJ]\b", content))
    fills_pdf = {tuple(round(float(v) * 255) for v in m)
                 for m in re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) rg", content)}
    fills_svg = {hex_rgb(f) for f in re.findall(r'<rect\b[^>]*fill="(#[0-9A-Fa-f]{6})"', svg)}
    lost = [f for f in sorted(fills_svg)
            if not any(all(abs(a - b) <= 2 for a, b in zip(f, p)) for p in fills_pdf)]
    add("pdf_matches_svg_geometry",
        f"{rects_svg} SVG rect(s), {len(fills_svg)} fill colour(s), {text_svg} SVG text(s)",
        f"{rects_pdf} PDF re-op(s), {len(fills_pdf)} PDF rg colour(s), {text_pdf} PDF Tj-op(s), "
        f"{len(re.findall(rb'/Subtype\\s*/Image', raw_pdf))} image(s), missing_fills={lost}",
        rects_pdf >= rects_svg and text_pdf >= max(1, int(text_svg * 0.8)) and not lost
        and not re.search(rb"/Subtype\s*/Image", raw_pdf),
        "live text operators and every series fill colour, not a rasterised page")

    px = png_pixels(png_p) if os.path.isfile(png_p) else None
    head = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    view_w = float(head.group(1)) if head else None
    bars = re.findall(r'<rect id="el-[^"]*"[^>]*x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" '
                      r'height="([\d.]+)" fill="(#[0-9A-Fa-f]{6})"', svg)
    if isinstance(px, dict) and bars and view_w:
        hit, miss = 0, []
        for x, y, w_, h_, fill in bars[:40]:
            want = hex_rgb(fill)
            got = sample_px(px["rows"], px["w"], px["h"], px["bpp"],
                            float(x) + float(w_) / 2, float(y) + float(h_) / 2, view_w)
            # the blank probe sits off-centre, because the error bar is drawn through the bar centre
            above = sample_px(px["rows"], px["w"], px["h"], px["bpp"],
                              float(x) + float(w_) * 0.15, max(float(y) - 1.2, 0.1), view_w)
            if got and all(abs(a - b) <= 8 for a, b in zip(got, want)) and above and min(above) >= 240:
                hit += 1
            else:
                miss.append(f"({x},{y}):{got} vs {want} above={above}")
        add("png_raster_matches_svg_bars", f"{len(bars)} bar(s) sampled at centre + just above the top",
            f"{hit} matched", hit == min(len(bars), 40), f"mismatch={miss[:2]}")
    else:
        add("png_raster_matches_svg_bars", "readable 8-bit PNG + SVG bars", "unreadable or no bars",
            False, "the raster could not be cross-checked against the SVG geometry")

    contract = case.get("output_contract") or case.get("contract") or {}
    # a declared source may only be a measurement table: the work order, a task text, an example or a
    # template JSON, or a free-text material can never be promoted into sources[] as if it held data
    NON_DATA = ("case.json", "task.md", "readme.md")
    declared = [str(s.get("file")) for s in (result.get("sources") or [])]
    bad_src = []
    for name in declared:
        base = os.path.basename(name).lower()
        if base in NON_DATA or base.endswith((".example.json", ".template.json")) or base.endswith((".txt", ".md")):
            bad_src.append(name)
        elif not base.startswith("case.inline") and base not in tables:
            bad_src.append(name + " (not a loaded table)")
    add("sources_are_measurement_tables", "only the loaded .csv/.tsv (or the inline table)",
        f"declared={declared}", bool(declared) and not bad_src, f"non_data={bad_src}")
    add("svg_pure_vector", "no <image>, no external href, real <text>",
        f"text={'<text' in svg} bitmap={'<image' in svg} external="
        f"{bool(re.search(r'(xlink:)?href=.(https?|file|data):', svg))}",
        "<text" in svg and "<image" not in svg
        and not re.search(r'(xlink:)?href=.(https?|file|data):', svg), "editable, self-contained SVG")
    miss = [k for k in contract if k not in result] if isinstance(contract, dict) else []
    add("contract_keys_echoed", f"{len(contract)} keys", f"missing={miss}", not miss,
        f"resolved_from={len(result.get('resolved_from') or [])}")
    for key in ("status", "sources", "uncertainty", "changes", "output_files"):
        add(f"block_{key}", "present",
            str(type(result.get(key)).__name__) if result.get(key) not in (None, "", [], {}) else "empty/missing",
            result.get(key) not in (None, "", [], {}), "")
    add("status_reported", "success|partial|failed", str(result.get("status")),
        result.get("status") in ("success", "partial", "failed"), "")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="recompute every claim from the produced artefacts")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--case", default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--report-out", default=None,
                    help="where to write verification_report.json (default: <out>/verification_report.json)")
    ap.add_argument("--no-report", action="store_true", help="do not write the report file")
    a = ap.parse_args(argv)
    case_path = a.case if (a.case and os.path.isfile(a.case)) else next(
        (p for p in ("/input/case.json", os.path.join(os.getcwd(), "case.json")) if os.path.isfile(p)), None)
    if not os.path.isdir(a.out):
        print(f"[FAIL] output directory not found: {a.out}")
        return 1
    rows = collect_rows(a.out, case_path)
    for r in rows:
        print(f"[{'PASS' if r['ok'] else 'FAIL'}] {r['check']:<26} expected={r['expected']}  actual={r['actual']}"
              + (f"  ({r['note']})" if r["note"] else ""))
    failed = [r["check"] for r in rows if not r["ok"]]
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"case": os.path.basename(case_path or "") or None, "rows": rows}, fh,
                      ensure_ascii=False, indent=2)
            fh.write("\n")
    # verification_report.json -- first-class, text-only verdict record (written by default)
    if not a.no_report:
        failed_rows = [r for r in rows if not r["ok"]]
        rep = {"case": os.path.basename(case_path or "") or None,
               "artefacts": {n: {"bytes": os.path.getsize(os.path.join(a.out, n)), "sha256": sha256_file(os.path.join(a.out, n))[:16]} for n in ("figure.svg", "figure.map.json", "figure.pdf", "figure.png", "result.json") if os.path.isfile(os.path.join(a.out, n))},
               "checks": rows, "checks_total": len(rows), "checks_passed": len(rows) - len(failed_rows),
               "failed": [r["check"] for r in failed_rows],
               "verdict": "pass" if not failed_rows else "fail",
               "calibration": "values re-read from source cells (physical line numbers, blank lines "
                              "included); colours re-simulated under CVD; the PDF and the PNG are "
                              "cross-checked against the SVG geometry",
               "generated_by": "scripts/verify.py (reads only the artefacts above)"}
        path = a.report_out or os.path.join(a.out, "verification_report.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    print(f"\n{len(rows) - len(failed)}/{len(rows)} recomputed checks passed"
          + (f"; FAILED: {', '.join(failed)}" if failed else "; VERIFY_OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
