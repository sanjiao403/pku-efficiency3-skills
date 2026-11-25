#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""benchmark.py -- measured naive-vs-skill comparison plus labelled gain-case verdicts.

  python3 scripts/benchmark.py --out benchmark.json
  python3 scripts/benchmark.py --dump-case gain-01 /tmp/case.json

Runs both routes on tests/gain_cases.json (naive = the plain SVG bar writer in this file, skill =
chart.py + verify.py), compares each label's expectation with the verifier rows, and executes the
copy_probe (package copied into .../stage/outputs) and cwd_probe (unrelated cwd with a decoy table).
No score is claimed: the numbers are measured differences on this example corpus.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import chart as C        # noqa: E402
import verify as V       # noqa: E402

GAIN_FILE = os.path.join(ROOT, "tests", "gain_cases.json")
NAIVE_CASES = ("grounded", "unit_missing")


def load_gain_cases() -> list[dict]:
    data = V.rd(GAIN_FILE, {}) or {}
    return data.get("cases") or []


def write_case(obj: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj["case"], fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# --------------------------------------------------------------- naive route

def naive_render(case_path: str, out_dir: str) -> dict:
    """The unassisted route: read the table, draw bars, stop. No map, no unit, no gates."""
    case = json.load(open(case_path, encoding="utf-8-sig"))
    table = C.find_table(case)
    if table:
        cols, rows, header_line, origin = table[0], table[1], 1, "case.inline"
    else:
        t = next((x for x in (C.load_table(p) for p in C.table_files(case, os.path.dirname(case_path))) if x), None)
        if not t:
            return {"error": "no table"}
        cols, rows, _note, header_line = t
        origin = os.path.basename(_note.split(":", 1)[-1])
    plan, _gaps = C.plan_chart(case, cols, rows, origin)
    if not plan:
        return {"error": "no numeric column"}
    cats, series, _unmapped = C.collect(cols, rows, plan, header_line)
    os.makedirs(out_dir, exist_ok=True)
    W, H = 300.0, 240.0
    vals = [v["value"] for s in series for v in s["values"]]
    top = max(vals + [1.0])
    bars, n = [], len(cats)
    for si, s in enumerate(series):
        for ci, cid in enumerate([f"cat{i + 1}" for i in range(n)]):
            p = next((v for v in s["values"] if v["cat"] == cid), None)
            if not p:
                continue
            w = W / max(n, 1) * 0.6 / max(len(series), 1)
            x = 40 + (W - 60) / max(n, 1) * (ci + 0.5) - w * len(series) / 2 + si * w
            h = (p["value"] / top) * (H - 60)
            fill = "#1f77b4" if si == 0 else "#ff7f0e"          # the classic non-CVD-safe pair
            bars.append(f'<rect x="{x:.1f}" y="{H - 30 - h:.1f}" width="{w * 0.9:.1f}" height="{h:.1f}" fill="{fill}"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}">' +
           f'<text x="{W / 2:.0f}" y="18" text-anchor="middle">{C.esc(plan["yl"])}</text>' +
           "".join(bars) + "</svg>")
    open(os.path.join(out_dir, "figure.svg"), "w", encoding="utf-8", newline="\n").write(svg)
    return {"elements": sum(1 for s in series for _ in s["values"]), "series": len(series)}


def skill_render(case_path: str, out_dir: str) -> dict:
    """The skill route runs the real entry point, so result.json is part of the measurement."""
    C.RESOLVED.clear()
    rc = C.main(["--case", case_path, "--out", out_dir])
    res = V.rd(os.path.join(out_dir, "result.json"), {}) or {}
    emap = V.rd(os.path.join(out_dir, "figure.map.json"), {}) or {}
    return {"elements": len(emap.get("elements") or []),
            "series": (res.get("figure") or {}).get("series_count"),
            "status": res.get("status"), "exit_code": rc,
            "resolved_from": sorted({r.get("from") for r in (res.get("resolved_from") or [])})}


# ---------------------------------------------------------------- measuring

def measure(out_dir: str, case_path: str) -> dict:
    rows = V.collect_rows(out_dir, case_path)
    failed = [r["check"] for r in rows if not r["ok"]]
    svg_p = os.path.join(out_dir, "figure.svg")
    svg = open(svg_p, encoding="utf-8").read() if os.path.isfile(svg_p) else ""
    emap = V.rd(os.path.join(out_dir, "figure.map.json"), {}) or {}
    marks = emap.get("forward") or emap.get("elements") or []
    data_marks = [r for r in re.findall(r"<rect [^>]*>", svg) if 'id="legend-swatch' not in r]
    drawn = len(data_marks)
    traceable = sum(1 for m in marks if (m.get("source") or {}).get("row") and (m.get("source") or {}).get("col"))
    m = re.search(r'id="ylabel"[^>]*>(.*?)</text>', svg, re.S)
    ylab = m.group(1) if m else ""
    unit = re.search(r"\(([^)]+)\)\s*$", ylab)
    return {"checks_total": len(rows), "violations": len(failed), "violation_names": failed[:3],
            "drawn_marks": drawn, "traceable_marks": traceable,
            "traceability_rate": round(traceable / drawn, 3) if drawn else 0.0,
                        "unit_on_axis": bool(unit) or (bool(ylab.strip()) and C.is_dimless(ylab)),
            "value_fidelity": "ok" if "values_match_source" not in failed else "fail"}


def tamper_map(out_dir: str, element_id: str, value: float) -> bool:
    """Make the artefact claim a number that is not in the source table (fabricated-number probe)."""
    p = os.path.join(out_dir, "figure.map.json")
    emap = V.rd(p, None)
    if not emap:
        return False
    for e in (emap.get("elements") or []):
        if e.get("element_id") == element_id:
            e["value"] = value
            e["_tampered"] = "value changed after rendering: this is the fabricated-number probe"
            json.dump(emap, open(p, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
            return True
    return False


def gain_verdicts(work: str) -> list[dict]:
    """Run each labelled case and compare expectation with verifier rows."""
    out_rows = []
    for gc in load_gain_cases():
        cid, label = gc.get("id"), gc.get("label")
        case_dir = os.path.join(work, "gain", cid)
        os.makedirs(case_dir, exist_ok=True)
        case_path = os.path.join(case_dir, "case.json")
        write_case(gc, case_path)
        out = os.path.join(case_dir, "out")
        t = time.time()
        info = skill_render(case_path, out)
        tampered = False
        if label == "fabricated_number":
            exp = gc.get("expect") or {}
            tampered = tamper_map(out, exp.get("tampered_element") or "el-s1-cat1",
                                  float(exp.get("tampered_to") or 7.77))
        metrics = measure(out, case_path)
        res = V.rd(os.path.join(out, "result.json"), {}) or {}
        exp = gc.get("expect") or {}
        got = {"status": res.get("status"), "values_drawn": metrics["drawn_marks"],
               "traceability_rate": metrics["traceability_rate"], "unit_on_axis": metrics["unit_on_axis"],
               "value_fidelity": metrics["value_fidelity"]}
        hits = []
        if "status" in exp:
            hits.append(("status", exp["status"], got["status"]))
        if "value_fidelity" in exp:
            hits.append(("value_fidelity", exp["value_fidelity"], got["value_fidelity"]))
        if "traceability_rate" in exp:
            hits.append(("traceability_rate", exp["traceability_rate"], got["traceability_rate"]))
        if "unit_on_axis" in exp:
            hits.append(("unit_on_axis", exp["unit_on_axis"], got["unit_on_axis"]))
        if "values_drawn" in exp:
            hits.append(("values_drawn", exp["values_drawn"], got["values_drawn"]))
        if exp.get("axis_units") == "fail":
            hits.append(("axis_units", "fail",
                         "fail" if (res.get("checks") or {}).get("axis_units", {}).get("ok") is False else "ok"))
        verdict = all(a == b for _k, a, b in hits)
        out_rows.append({"id": cid, "label": label, "why": (gc.get("why") or "")[:90],
                         "artifact": f"tests/gain_cases.json#cases[{cid}].case -> figure.svg + figure.map.json + result.json + verification_report.json",
                         "tampered": tampered,
                         "expected_vs_actual": [{"field": k, "expected": a, "actual": b} for k, a, b in hits],
                         "verdict": "pass" if verdict else "fail",
                         "seconds": round(time.time() - t, 3),
                         "verify_violations": metrics["violation_names"][:4]})
    return out_rows


# ------------------------------------------------------------- self-sufficiency

def copy_probe(case_id: str = "gain-01") -> dict:
    """Copy the whole package into .../stage/outputs (the staging layout) and run it there."""
    work = tempfile.mkdtemp(prefix="min4-bench-")
    try:
        staged = os.path.join(work, "runs", "q03-fire", "stage", "outputs")
        shutil.copytree(ROOT, staged)
        gc = next((g for g in load_gain_cases() if g.get("id") == case_id), None)
        rel = os.path.join("examples", "case-01.example.json")
        if gc:                                    # materialise the labelled case INSIDE the copy
            write_case(gc, os.path.join(staged, rel))
        out = os.path.join(work, "out")
        t = time.time()
        proc = subprocess.run([sys.executable, os.path.join(staged, "scripts", "chart.py"),
                               "--case", rel, "--out", out], cwd=staged, capture_output=True, text=True)
        res = V.rd(os.path.join(out, "result.json"), {}) or {}
        emap = V.rd(os.path.join(out, "figure.map.json"), {}) or {}
        rows = V.collect_rows(out, os.path.join(staged, rel))
        failed = [r["check"] for r in rows if not r["ok"]]
        return {"staged_path": "<TEMP>/runs/q03-fire/stage/outputs", "case": rel, "status": res.get("status"),
                "elements": len(emap.get("elements") or []), "verify": f"{len(rows) - len(failed)}/{len(rows)}",
                "seconds": round(time.time() - t, 3),
                "stdout_tail": (proc.stdout or "").strip().splitlines()[-1:],
                "ok": res.get("status") == "success" and len(emap.get("elements") or []) > 0 and not failed}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cwd_probe(case_id: str = "gain-01") -> dict:
    """Run from an unrelated cwd that contains a same-named decoy table."""
    work = tempfile.mkdtemp(prefix="min4-cwd-")
    try:
        gc = next((g for g in load_gain_cases() if g.get("id") == case_id), None)
        case_path = os.path.join(work, "case.json")
        if gc:
            write_case(gc, case_path)
        with open(os.path.join(work, "expression.csv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("gene,condition,mean,sd,n\nIl6,Vehicle,1.0,0.1,3\nIl6,LPS,999.0,0.2,3\n")
        out = os.path.join(work, "out")
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "chart.py"),
                               "--case", case_path, "--out", out], cwd=work, capture_output=True, text=True)
        res = V.rd(os.path.join(out, "result.json"), {}) or {}
        emap = V.rd(os.path.join(out, "figure.map.json"), {}) or {}
        values = [v.get("value") for v in (emap.get("elements") or [])]
        return {"cwd": "<TEMP dir containing a decoy expression.csv>", "status": res.get("status"),
                "decoy_used": 999.0 in values,
                "resolved_from": sorted({r.get("from") for r in (res.get("resolved_from") or [])}),
                "ok": res.get("status") == "success" and 999.0 not in values}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="labelled gain cases + naive vs skill routes")
    ap.add_argument("--out", default=os.path.join(ROOT, "benchmark.json"))
    ap.add_argument("--dump-case", nargs=2, metavar=("GAIN_ID", "PATH"),
                    help="write one labelled case out as a runnable case.json, then exit "
                         "(e.g. --dump-case gain-01 /tmp/case.json)")
    a = ap.parse_args(argv)
    if a.dump_case:
        gid, path = a.dump_case
        gc = next((g for g in load_gain_cases() if g.get("id") == gid or g.get("label") == gid), None)
        if not gc:
            print(f"[benchmark] unknown case id/label: {gid}; known: "
                  f"{[g.get('id') for g in load_gain_cases()]}")
            return 2
        write_case(gc, path)
        print(f"[benchmark] wrote {path} (label={gc.get('label')}); run it with "
              f"scripts/chart.py --case {path} --out <OUT>")
        return 0
    work = tempfile.mkdtemp(prefix="min3-bench-run-")
    rows, tot = [], {"naive": {}, "skill": {}}
    try:
        for gc in load_gain_cases():
            label = gc.get("label")
            case_dir = os.path.join(work, "route", gc["id"])
            os.makedirs(case_dir, exist_ok=True)
            case_path = os.path.join(case_dir, "case.json")
            write_case(gc, case_path)
            rec = {"case": gc["id"], "label": label}
            routes = ("naive", "skill") if label in NAIVE_CASES else ("skill",)
            for route in routes:
                out = os.path.join(case_dir, route)
                t = time.time()
                info = naive_render(case_path, out) if route == "naive" else skill_render(case_path, out)
                secs = round(time.time() - t, 3)
                metrics = measure(out, case_path)
                rec[route] = {**info, **metrics, "seconds": secs}
                for k in ("violations", "checks_total", "drawn_marks", "traceable_marks"):
                    tot[route][k] = tot[route].get(k, 0) + metrics.get(k, 0)
                tot[route]["cases"] = tot[route].get("cases", 0) + 1
                tot[route]["unit_ok_cases"] = tot[route].get("unit_ok_cases", 0) + (1 if metrics["unit_on_axis"] else 0)
                tot[route]["traceable_sum"] = tot[route].get("traceable_sum", 0) + metrics["traceable_marks"]
                tot[route]["drawn_sum"] = tot[route].get("drawn_sum", 0) + metrics["drawn_marks"]
                tot[route]["seconds"] = tot[route].get("seconds", 0.0) + secs
            rows.append(rec)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    agg = {}
    for route in ("naive", "skill"):
        t = tot[route]
        agg[route] = {"cases": t.get("cases", 0),
                      "traceability_rate": round(t.get("traceable_sum", 0) / max(t.get("drawn_sum", 1), 1), 3),
                      "unit_correct_rate": round(t.get("unit_ok_cases", 0) / max(t.get("cases", 1), 1), 3),
                      "violations": t.get("violations", 0), "checks_total": t.get("checks_total", 0),
                      "total_seconds": round(t.get("seconds", 0.0), 3)}
    gained = gain_verdicts(work)
    cp, cw = copy_probe(), cwd_probe()
    report = {"_comment": "示例（非正式答案）——由 scripts/benchmark.py 真实运行后写出：带标签案例的判定 + 两条路线在同样工单上的实测差异。",
              "corpus": "tests/gain_cases.json",
              "routes": {"naive": "plain SVG bar writer inside scripts/benchmark.py (no map, no unit, no gates)",
                         "skill": "scripts/chart.py + scripts/verify.py"},
              "aggregate": agg,
              "gain_cases": gained,
              "routes_detail": rows,
              "copy_probe": cp, "cwd_probe": cw,
              "environment": {"python": sys.version.split()[0]},
              "caveats": ["naive route = scripted unassisted plot (a lower bound, not a captured LLM trajectory)",
                          "same verifier rows count violations on both routes",
                          "fabricated_number tampers the element map after rendering (the machine-readable claim)",
                          "no score claimed: measurable differences on this example corpus only"]}
    json.dump(report, open(a.out, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
    print(f"[benchmark] naive: {agg['naive']}")
    print(f"[benchmark] skill: {agg['skill']}")
    for g in gained:
        print(f"[benchmark] gain {g['id']:<8} label={g['label']:<17} verdict={g['verdict']} "
              f"expected_vs_actual={g['expected_vs_actual']}")
    print(f"[benchmark] copy_probe ok={cp['ok']} status={cp['status']} elements={cp['elements']} verify={cp['verify']} | "
          f"cwd_probe ok={cw['ok']} decoy_used={cw['decoy_used']}")
    print(f"[benchmark] wrote {a.out}")
    return 0 if cp["ok"] and cw["ok"] and all(g["verdict"] == "pass" for g in gained) else 1


if __name__ == "__main__":
    raise SystemExit(main())
