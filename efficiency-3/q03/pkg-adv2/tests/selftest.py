#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py -- end-to-end self-check of this Skill package, no network and no fixtures required.

  python3 tests/selftest.py [--out <dir>] [--report tests/selftest-report.json]

Every case runs the real entry point in a temporary directory and asserts on the files that land on
disk. The report contains only <PKG>/<TMP> placeholders, never a machine-specific absolute path.
Prints one line per case and ends with SELFTEST_OK (exit 0) or FAILED (exit 1).
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHART, VERIFY = (os.path.join(PKG, "scripts", n) for n in ("chart.py", "verify.py"))
EXAMPLE = os.path.join(PKG, "examples", "case.example.json")
rows, fails = [], []


def run(args, cwd=None, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run([sys.executable] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rd(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def rec(name, ok, detail, kind="positive"):
    rows.append({"case": name, "kind": kind, "ok": bool(ok), "detail": detail[:400]})
    if not ok:
        fails.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name:<38} {detail[:110]}")


def clean(text, tmp):
    return (str(text).replace(PKG, "<PKG>").replace(tmp, "<TMP>")
            .replace(os.path.dirname(tmp), "<TMP>").replace("\\", "/"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="self-check this Skill package end to end")
    ap.add_argument("--out", default=None, help="work directory (default: a fresh temp directory)")
    ap.add_argument("--report", default=os.path.join(PKG, "tests", "selftest-report.json"))
    a = ap.parse_args(argv)
    tmp = os.path.abspath(a.out or tempfile.mkdtemp(prefix="adv2-selftest-"))
    os.makedirs(tmp, exist_ok=True)

    # 1 -------------------------------------------------------- happy path
    out = os.path.join(tmp, "case1")
    code, log = run([CHART, "--case", EXAMPLE, "--out", out])
    res = rd(os.path.join(out, "result.json"), {}) or {}
    exp = rd(os.path.join(out, "export_check.json"), {}) or {}
    want = ("figure.svg", "figure.map.json", "figure.pdf", "figure.png", "result.json",
            "export_check.json", "render_report.json")
    rec("end_to_end_success", code == 0 and res.get("status") == "success"
        and all(os.path.isfile(os.path.join(out, n)) for n in want),
        f"exit={code} status={res.get('status')} files={sum(os.path.isfile(os.path.join(out, n)) for n in want)}/7 "
        f"engine={exp.get('engine')}")
    rec("export_gates_green", all((exp.get("checks") or {}).values()) and len(exp.get("checks") or {}) >= 5,
        f"checks={exp.get('checks')}")
    code_v, log_v = run([VERIFY, "--case", EXAMPLE, "--out", out])
    rec("independent_verify", code_v == 0, f"exit={code_v} :: {log_v.strip().splitlines()[-1][:90]}")

    # 2 ------------------------------------------------- contract never drops case_id
    mini = os.path.join(tmp, "mini")
    os.makedirs(mini, exist_ok=True)
    src = rd(EXAMPLE, {}) or {}
    src["output_contract"] = {"status": "s", "notes": "n"}          # contract that does NOT name case_id
    src["case_id"] = "contract-probe"
    with open(os.path.join(mini, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(src, fh, ensure_ascii=False)
    out2 = os.path.join(tmp, "case2")
    code, _ = run([CHART, "--case", os.path.join(mini, "case.json"), "--out", out2])
    r2 = rd(os.path.join(out2, "result.json"), {}) or {}
    rec("contract_keeps_case_id", code == 0 and r2.get("case_id") == "contract-probe"
        and r2.get("status") == "success" and "notes" in r2,
        f"case_id={r2.get('case_id')!r} keys={sorted(r2)[:6]}… status={r2.get('status')}")

    # 3 ------------------------------------------------- physical lines with comments and blank lines
    tab = os.path.join(tmp, "lines")
    os.makedirs(tab, exist_ok=True)
    with open(os.path.join(tab, "data.csv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# comment line\ngene,mean,sd,n\nA,1.0,0.1,3\n\nB,2.5,0.2,3\nC,3.0,0.3,3\n")
    with open(os.path.join(tab, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"case_id": "line-probe", "data_file": "data.csv", "y_label": "value (a.u.)"}, fh)
    out3 = os.path.join(tmp, "case3")
    code, _ = run([CHART, "--case", os.path.join(tab, "case.json"), "--out", out3])
    m3 = rd(os.path.join(out3, "figure.map.json"), {}) or {}
    got = sorted(e["source"]["row"] for e in (m3.get("elements") or []))
    rec("physical_line_numbers", code == 0 and got == [3, 5, 6],
        f"physical rows of the 3 records = {got} (header on line 2, blank line 4 must not shift them)")

    # 4 ------------------------------------------------- degradation: no case.json at all
    out4 = os.path.join(tmp, "case4")
    code, log = run([CHART, "--case", os.path.join(tmp, "nope", "case.json"), "--out", out4])
    r4 = rd(os.path.join(out4, "result.json"), {}) or {}
    rec("missing_case_writes_result", code == 1 and r4.get("status") == "failed" and r4.get("uncertainty"),
        f"exit={code} status={r4.get('status')} uncertainty={len(r4.get('uncertainty') or [])} item(s)",
        kind="negative")

    # 5 --------------------------------------- degradation: no numeric column -> no invented canvas
    non = os.path.join(tmp, "nonnum")
    os.makedirs(non, exist_ok=True)
    with open(os.path.join(non, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"case_id": "nonnum", "columns": ["gene", "note"],
                   "rows": [["Il6", "n.d."], ["Tnf", "n.d."]]}, fh)
    out5 = os.path.join(tmp, "case5")
    code, _ = run([CHART, "--case", os.path.join(non, "case.json"), "--out", out5])
    r5 = rd(os.path.join(out5, "result.json"), {}) or {}
    rec("no_numeric_column_is_failed", code == 1 and r5.get("status") == "failed"
        and not os.path.isfile(os.path.join(out5, "figure.svg")),
        f"exit={code} status={r5.get('status')} figure_written={os.path.isfile(os.path.join(out5,'figure.svg'))}",
        kind="negative")

    # 6 ------------------------------------- degradation: missing unit -> partial, figure still delivered
    nounit = os.path.join(tmp, "nounit")
    os.makedirs(nounit, exist_ok=True)
    with open(os.path.join(nounit, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"case_id": "nounit", "y_label": "serum cortisol", "columns": ["group", "mean"],
                   "rows": [["ctl", 12.0], ["trt", 9.5]]}, fh)
    out6 = os.path.join(tmp, "case6")
    code, _ = run([CHART, "--case", os.path.join(nounit, "case.json"), "--out", out6])
    r6 = rd(os.path.join(out6, "result.json"), {}) or {}
    rec("missing_unit_is_partial", code == 0 and r6.get("status") == "partial"
        and (r6.get("checks", {}).get("axis_units", {}) or {}).get("ok") is False
        and os.path.isfile(os.path.join(out6, "figure.svg")),
        f"status={r6.get('status')} axis_units_ok={(r6.get('checks',{}).get('axis_units',{}) or {}).get('ok')} "
        f"figure_delivered={os.path.isfile(os.path.join(out6,'figure.svg'))}", kind="negative")

    # 7 -------------------------------------------------- stdlib export engine (no matplotlib)
    out7 = os.path.join(tmp, "case7")
    code, _ = run([CHART, "--case", EXAMPLE, "--out", out7, "--engine", "stdlib"])
    code_v7, _ = run([VERIFY, "--case", EXAMPLE, "--out", out7])
    e7 = rd(os.path.join(out7, "export_check.json"), {}) or {}
    rec("stdlib_engine_delivers", code == 0 and code_v7 == 0 and os.path.isfile(os.path.join(out7, "figure.pdf"))
        and (e7.get("checks") or {}).get("pdf_text_preserved") is True,
        f"engine={e7.get('engine')} png_text_layer={str(e7.get('png_text_layer'))[:60]} verify_exit={code_v7}")

    # 8 --------------------------------------- copy probe: whole package copied under a path with 'outputs'
    stage = os.path.join(tmp, "runs", "q03-fire", "stage", "outputs")
    shutil.copytree(PKG, stage)
    out8 = os.path.join(tmp, "case8")
    code, log = run([os.path.join(stage, "scripts", "chart.py"),
                     "--case", os.path.join(stage, "examples", "case.example.json"), "--out", out8],
                    cwd=os.path.join(tmp, "runs"))
    r8 = rd(os.path.join(out8, "result.json"), {}) or {}
    n8 = len((rd(os.path.join(out8, "figure.map.json"), {}) or {}).get("elements") or [])
    rec("copy_probe", code == 0 and r8.get("status") == "success" and n8 > 0,
        f"copied under .../outputs -> status={r8.get('status')} elements={n8}")

    # 9 ------------------------------ cwd probe: a decoy table next to cwd must never be used
    decoy = os.path.join(tmp, "decoy")
    real = os.path.join(tmp, "real")
    os.makedirs(decoy, exist_ok=True)
    os.makedirs(real, exist_ok=True)
    with open(os.path.join(decoy, "data.csv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("gene,mean\nA,999.0\nB,999.0\n")
    with open(os.path.join(real, "data.csv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("gene,mean\nA,1.0\nB,2.0\n")
    with open(os.path.join(real, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"case_id": "decoy-probe", "data_file": "data.csv"}, fh)
    out9 = os.path.join(tmp, "case9")
    code, _ = run([CHART, "--case", os.path.join(real, "case.json"), "--out", out9], cwd=decoy)
    vals = {e["value"] for e in ((rd(os.path.join(out9, "figure.map.json"), {}) or {}).get("elements") or [])}
    rec("cwd_decoy_not_used", code == 0 and 999.0 not in vals and vals == {1.0, 2.0},
        f"plotted values={sorted(vals)} (decoy in cwd holds 999.0)")

    # 10 ------------------------------------------------------------- non-ASCII labels stay honest
    cjk = os.path.join(tmp, "cjk")
    os.makedirs(cjk, exist_ok=True)
    with open(os.path.join(cjk, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"case_id": "cjk", "x_label": "基因", "y_label": "相对表达量 (fold change)",
                   "columns": ["gene", "mean"], "rows": [["Il6", 1.0], ["Tnf", 8.4]]}, fh)
    out10 = os.path.join(tmp, "case10")
    code, _ = run([CHART, "--case", os.path.join(cjk, "case.json"), "--out", out10])
    r10 = rd(os.path.join(out10, "result.json"), {}) or {}
    e10 = rd(os.path.join(out10, "export_check.json"), {}) or {}
    svg10 = open(os.path.join(out10, "figure.svg"), encoding="utf-8").read() if os.path.isfile(
        os.path.join(out10, "figure.svg")) else ""
    rec("cjk_labels_preserved", code == 0 and "基因" in svg10 and bool(e10.get("non_ascii_in_labels")),
        f"svg_has_cjk={'基因' in svg10} font_basis={str(e10.get('font_basis'))[:64]} status={r10.get('status')}")

    # 11 ------------------------------------------------------------ rows are findable by csv reader
    rec("verify_reads_physical_rows", code_v == 0, "verify.py re-read every bar value from its physical line")

    # 12 ------------------------ NEGATIVE CONTROL: a material document must never become plotted data
    #     The work order here references a .md "material" and no table at all. A builder that treats any
    #     referenced file as data will happily parse the note into columns and draw it (that is the
    #     "notification-as-evidence" failure class); the correct answer is failed + no figure.
    ev = os.path.join(tmp, "evidence")
    os.makedirs(ev, exist_ok=True)
    with open(os.path.join(ev, "alpha_notes.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# material\nIl6 and Tnf were measured by qPCR under Vehicle/LPS.\nNo values are given here.\n")
    with open(os.path.join(ev, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"case_id": "evidence-probe", "materials": ["alpha_notes.md"],
                   "y_label": "Relative mRNA (fold change)"}, fh)
    out12 = os.path.join(tmp, "case12")
    code, _ = run([CHART, "--case", os.path.join(ev, "case.json"), "--out", out12])
    r12 = rd(os.path.join(out12, "result.json"), {}) or {}
    ch12 = r12.get("evidence_channels") or {}
    rec("material_doc_is_not_data", code == 1 and not os.path.isfile(os.path.join(out12, "figure.svg"))
        and r12.get("status") == "failed" and ch12.get("work_order_used_as_data") is False
        and "alpha_notes.md" in (ch12.get("materials_seen") or []) and not ch12.get("tables_used"),
        f"exit={code} status={r12.get('status')} figure_written="
        f"{os.path.isfile(os.path.join(out12,'figure.svg'))} materials_seen={ch12.get('materials_seen')}",
        kind="negative")

    # 13 ------------------------------- NO invented citation: sources[] must name the table, never case.json
    src13 = [str(s.get("file")) for s in (res.get("sources") or [])]
    rec("sources_name_the_table_only", bool(src13) and not any("case.json" in s or s.endswith(".example.json")
                                                               for s in src13),
        f"sources={src13}")

    # 14 ---------------------- a sibling example JSON next to the work order is never read as measurements
    sib = os.path.join(tmp, "sibling")
    os.makedirs(sib, exist_ok=True)
    with open(os.path.join(sib, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"case_id": "sibling-probe", "data_file": "real.csv"}, fh)
    with open(os.path.join(sib, "real.csv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("group,mean\nctl,1.0\ntrt,2.0\n")
    with open(os.path.join(sib, "figure_spec.example.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"columns": ["decoy", "value"], "rows": [["x", 999.0], ["y", 999.0]]}, fh)
    out14 = os.path.join(tmp, "case14")
    code, _ = run([CHART, "--case", os.path.join(sib, "case.json"), "--out", out14])
    vals14 = {e["value"] for e in ((rd(os.path.join(out14, "figure.map.json"), {}) or {}).get("elements") or [])}
    ch14 = (rd(os.path.join(out14, "result.json"), {}) or {}).get("evidence_channels") or {}
    rec("sibling_example_json_not_data", code == 0 and vals14 == {1.0, 2.0}
        and "figure_spec.example.json" in [p for p in (ch14.get("rejected_as_non_data") or [])],
        f"plotted={sorted(vals14)} rejected_as_non_data={ch14.get('rejected_as_non_data')}")

    # 15 ------------------- REGRESSION: pinned SOURCE_DATE_EPOCH => every artefact is byte-identical
    #     (QA round 2026-11-24 found figure.pdf differing by 5 bytes of /CreationDate between two runs)
    det_a, det_b = os.path.join(tmp, "det-a"), os.path.join(tmp, "det-b")
    pinned = {"SOURCE_DATE_EPOCH": "0"}
    run([CHART, "--case", EXAMPLE, "--out", det_a], env=pinned)
    time.sleep(1.1)                      # a wall-clock timestamp would now differ if it still leaked
    run([CHART, "--case", EXAMPLE, "--out", det_b], env=pinned)
    names = sorted(n for n in os.listdir(det_a) if os.path.isfile(os.path.join(det_a, n)))
    diffs = []
    for n in names:
        pa, pb = os.path.join(det_a, n), os.path.join(det_b, n)
        if not os.path.isfile(pb):
            diffs.append(n + ":missing")
        elif sha256_file(pa) != sha256_file(pb):
            diffs.append(f"{n}:{sha256_file(pa)[:8]}!={sha256_file(pb)[:8]}")
    rec("reproducible_byte_identical", names and not diffs,
        f"{len(names)} artefact(s) compared with SOURCE_DATE_EPOCH=0: diff={diffs or 'none'} "
        f"(pdf={sha256_file(os.path.join(det_a, 'figure.pdf'))[:16]})")

    report = {"package": "pkg-adv2", "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "python": sys.version.split()[0], "work_dir": "<TMP>", "package_dir": "<PKG>",
              "determinism": {"policy": "SOURCE_DATE_EPOCH pins every timestamp; two runs of the same case "
                                        "are byte-identical (figure.pdf included)",
                              "files_compared": len(names), "diff": diffs,
                              "figure_pdf_sha256": sha256_file(os.path.join(det_a, "figure.pdf"))},
              "cases_total": len(rows), "cases_passed": len(rows) - len(fails), "failed": fails,
              "cases": rows}
    os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
    with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"\n{len(rows) - len(fails)}/{len(rows)} cases passed"
          + (f"; FAILED: {', '.join(fails)}" if fails else "; SELFTEST_OK"))
    if not a.out:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
