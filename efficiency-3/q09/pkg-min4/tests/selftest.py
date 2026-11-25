# -*- coding: utf-8 -*-
"""selftest.py — expected vs actual from real runs (generate / edit / recompute / cwd / copy).

    python3 tests/selftest.py --report tests/selftest-report.json
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
PY = sys.executable
EX = os.path.join(PKG, "examples")


def run(args, cwd):
    p = subprocess.run([PY] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       cwd=cwd)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=os.path.join(HERE, "selftest-report.json"))
    a = ap.parse_args(argv)
    root = tempfile.mkdtemp(prefix="deck-selftest-")
    rep = {"note": "expected vs actual, produced by real runs of the main command",
           "python": sys.version.split()[0], "tests": [], "passed": True}

    def rec(name, expected, actual, ok=None, extra=None):
        ok = (expected == actual) if ok is None else ok
        row = {"test": name, "expected": expected, "actual": actual, "ok": bool(ok)}
        if extra:
            row.update(extra)
        rep["tests"].append(row)
        rep["passed"] = rep["passed"] and bool(ok)

    def case_dir(name, extra_case=None, deck=None):
        d = os.path.join(root, "in", name)
        os.makedirs(d, exist_ok=True)
        for n in os.listdir(EX):
            shutil.copy2(os.path.join(EX, n), os.path.join(d, n))
        cj = json.load(open(os.path.join(d, "case.example.json"), encoding="utf-8"))
        os.remove(os.path.join(d, "case.example.json"))
        cj = {**cj, **(extra_case or {})}
        if deck:
            shutil.copy2(deck, os.path.join(d, "starting-deck.pptx"))
        json.dump(cj, open(os.path.join(d, "case.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)
        return d

    # T1 generate (zero extra parameters)
    d1, o1 = case_dir("case-01"), os.path.join(root, "out-01")
    rc, log = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                   os.path.join(d1, "case.json"), "--out", o1], root)
    r1 = json.load(open(os.path.join(o1, "result.json"), encoding="utf-8"))
    rec("T1 generate: exit code", 0, rc, extra={"tail": log[-200:]})
    rec("T1 generate: result.status", "success", r1.get("status"))
    rec("T1 generate: slides == case slide_count", 8,
        (r1.get("deliverable") or {}).get("slides"))
    rec("T1 generate: contract keys echoed", True,
        all(k in r1 for k in ("deliverable", "slide_plan", "evidence_map", "notes")))
    rec("T1 generate: outputs[] carries sha256", True,
        all(o.get("sha256") for o in (r1.get("outputs") or [])))
    rec("T1 generate: body text is not empty (placeholder kept)", True,
        bool([e for e in (r1.get("evidence_map") or []) if e.get("slide", 0) > 2]) and
        bool([s for s in (r1.get("deliverable", {}).get("png_previews") or [])]) )

    # T2 edit the deck T1 produced (8 -> 6)
    d2 = case_dir("case-03", deck=os.path.join(o1, "deck.pptx"),
                  extra_case={"slide_count": 6, "ops": [
                      {"op": "set_title", "slide": 1, "text": "Fixture deck (edited)"},
                      {"op": "compress_bullets", "slide": 4, "max": 1,
                       "why": "selftest"},
                      {"op": "delete_slide", "slide": 8, "why": "8 -> 7"},
                      {"op": "delete_slide", "slide": 7, "why": "7 -> 6"},
                      {"op": "set_notes", "slide": 1, "text": "[讲稿] selftest"}]})
    o2 = os.path.join(root, "out-03")
    rc2, log2 = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                     os.path.join(d2, "case.json"), "--out", o2], root)
    r2 = json.load(open(os.path.join(o2, "result.json"), encoding="utf-8"))
    er = json.load(open(os.path.join(o2, "_work", "edit_report.json"), encoding="utf-8"))
    rec("T2 edit: exit code", 0, rc2, extra={"tail": log2[-200:]})
    rec("T2 edit: result.status", "success", r2.get("status"),
        extra={"uncertainty": r2.get("uncertainty"),
               "checks": (r2.get("checks") or {}).get("summary"),
               "failed_checks": [c["id"] + " " + c["name"] for c in
                                 ((r2.get("checks") or {}).get("checks") or [])
                                 if c.get("status") == "fail"]})
    rec("T2 edit: slide count trimmed to the case instruction", 6,
        er.get("slides_after"))
    rec("T2 edit: template_preserved", True, er.get("template_preserved"))
    rec("T2 edit: version snapshots written", 2, len(er.get("versions") or []))

    # T3 recompute from the two artifacts only
    for tag, o, expect in (("generated", o1, 0), ("edited", o2, 0)):
        rc3, log3 = run([os.path.join(PKG, "scripts", "verify.py"), "--pptx",
                         os.path.join(o, "deck.pptx"), "--result",
                         os.path.join(o, "result.json")], root)
        rec("T3 recompute (%s deck) exits 0" % tag, expect, rc3,
            extra={"tail": log3[-240:]})

    # T4 cwd independence (R1b): run from an unrelated directory
    ext = tempfile.mkdtemp(prefix="deck-cwd-")
    rc4, log4 = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                     os.path.join(d1, "case.json"), "--out", os.path.join(ext, "out")],
                    ext)
    r4 = json.load(open(os.path.join(ext, "out", "result.json"), encoding="utf-8"))
    rep["cwd_independence"] = {
        "command": "cd <external-cwd> && python3 <pkg>/scripts/deck.py --case "
                   "<pkg>/examples/../in/case.json --out <external-cwd>/out",
        "cwd": "<external temp dir, not the package dir and not /input>",
        "exit_code": rc4, "status": r4.get("status"),
        "slides": (r4.get("deliverable") or {}).get("slides"),
        "resolved_from": r4.get("resolved_from"), "tail": log4[-160:]}
    rec("T4 cwd independence: status success", "success", r4.get("status"))
    rec("T4 cwd independence: material resolved from case_dir", "case_dir",
        (r4.get("resolved_from") or {}).get("material"))

    # T5 copy probe: package copied under a path containing "outputs"
    deep = os.path.join(tempfile.mkdtemp(prefix="copy-probe-"), "runs", "q09-fire",
                        "stage", "outputs", "pkg-copy")
    shutil.copytree(PKG, deep, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    ext2 = tempfile.mkdtemp(prefix="copy-probe-out-")
    rc5, log5 = run([os.path.join(deep, "scripts", "deck.py"), "--case",
                     os.path.join(deep, "examples", "case.example.json"), "--out",
                     os.path.join(ext2, "out")], ext2)
    r5 = json.load(open(os.path.join(ext2, "out", "result.json"), encoding="utf-8"))
    rep["copy_probe"] = {
        "why": "input discovery keys on file names only, never on absolute path "
               "segments: a package placed under a path containing 'outputs' still "
               "sees its inputs",
        "copy_path_shape": "<tmp>/runs/q09-fire/stage/outputs/pkg-copy",
        "command": "cd <external-cwd> && python3 <copy>/scripts/deck.py --case "
                   "<copy>/examples/case.example.json --out <external-cwd>/out",
        "exit_code": rc5, "status": r5.get("status"),
        "slides": (r5.get("deliverable") or {}).get("slides"),
        "discover": next((s.get("status") for s in r5.get("stages", [])
                          if s.get("stage") == "discover"), None),
        "uncertainty": r5.get("uncertainty")}
    rec("T5 copy probe: exit code", 0, rc5)
    rec("T5 copy probe: status success", "success", r5.get("status"))
    rec("T5 copy probe: slides == 8", 8, (r5.get("deliverable") or {}).get("slides"))

    # T6 empty-artifact guard: a case with neither material nor deck must not pass
    d6 = os.path.join(root, "in", "empty")
    os.makedirs(d6, exist_ok=True)
    json.dump({"case_id": "EMPTY", "slide_count": 5,
               "output_contract": {"deliverable": "pptx"}},
              open(os.path.join(d6, "case.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    o6 = os.path.join(root, "out-empty")
    rc6, log6 = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                     os.path.join(d6, "case.json"), "--out", o6], root)
    r6 = (json.load(open(os.path.join(o6, "result.json"), encoding="utf-8"))
          if os.path.isfile(os.path.join(o6, "result.json")) else {})
    rep["empty_artifact_guard"] = {"exit_code": rc6, "status": r6.get("status"),
                                   "slides": (r6.get("deliverable") or {}).get("slides"),
                                   "uncertainty": r6.get("uncertainty")}
    rec("T6 empty input: status is not success", True,
        r6.get("status") in ("partial", "failed"))
    rec("T6 empty input: a reason is recorded", True, bool(r6.get("uncertainty")))

    rep["runtime_workdir"] = "temporary (not shipped)"
    json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"report": a.report, "passed": rep["passed"],
                      "failed": [t["test"] for t in rep["tests"] if not t["ok"]]},
                     ensure_ascii=False, indent=1))
    shutil.rmtree(root, ignore_errors=True)
    return 0 if rep["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
