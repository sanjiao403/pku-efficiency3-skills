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
    """(columns, rows, header_line) when the work order carries its table inline."""
    def pair(d):
        c, r = d.get("columns"), d.get("rows")
        return ([str(x) for x in c], r) if isinstance(c, list) and isinstance(r, list) and r else None
    if isinstance(case, dict):
        if pair(case):
            return pair(case)[0], pair(case)[1], 1
        for v in case.values():
            if isinstance(v, list) and v and all(isinstance(r, dict) for r in v) \
                    and any(num(x) is not None for r in v for x in r.values()):
                return list(dict.fromkeys(k for r in v for k in r)), v, 1
            if isinstance(v, dict) and pair(v):
                return pair(v)[0], pair(v)[1], 1
    return None


def load_tables(case, case_dir):
    """{basename: (columns, rows, header_line)}; comment lines are skipped but counted."""
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
        rows = list(csv.DictReader(body, delimiter=delim))
        if rows:
            out[os.path.basename(p)] = (list(rows[0].keys()), rows, head + 1)
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
        cols, tbl, header_line = tables.get(f) or (None, None, 1)
        if not tbl and tables:
            cols, tbl, header_line = next(iter(tables.values()))
        if not tbl or not isinstance(r, int) or not c:
            unverifiable += 1
            continue
        checked += 1
        idx = r - header_line - 1
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

    contract = case.get("output_contract") or case.get("contract") or {}
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
               "artefacts": {n: {"bytes": os.path.getsize(os.path.join(a.out, n)), "sha256": sha256_file(os.path.join(a.out, n))[:16]} for n in ("figure.svg", "figure.map.json", "result.json") if os.path.isfile(os.path.join(a.out, n))},
               "checks": rows, "checks_total": len(rows), "checks_passed": len(rows) - len(failed_rows),
               "failed": [r["check"] for r in failed_rows],
               "verdict": "pass" if not failed_rows else "fail",
               "calibration": "values re-read from source cells (physical line numbers); colours re-simulated",
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
