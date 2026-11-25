#!/usr/bin/env python3
"""gain_check.py - prove the skill tells grounded derivation apart from fabrication.

Three labelled cases live inline in this file (so no extra files are needed). Each one is
materialised into a throwaway directory and driven through the single entry point, then
judged against the label that was declared *before* the run:

  grounded    every quoted sentence really occurs in the material, the inhibition is drawn
              as a T-bar  ->  expect: status=success, blocking={0,0}, quotes verified 3/3
  fabricated  the model names entities that do not occur in the material, quotes sentences
              that do not occur, and inverts one inhibition  ->  expect: status=partial, a
              blocking polarity error, 0/N quotes verified, and every element still listed
              (the fabrication is exposed, never silently accepted)
  off_topic   the material is about the weather and supports nothing  ->  expect:
              status=partial, 0/N quotes verified, and every entity flagged as not occurring

    python3 scripts/gain_check.py [--json path]

Exit code 0 when all three behave exactly as labelled, 1 otherwise. Nothing is written
outside the temp directory (optionally the JSON verdict file).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ENTRY = os.path.join(HERE, "schematic.py")
PY = sys.executable or "python3"

GROUNDED_MATERIAL = """# 示例（非正式答案）· synthetic grounded material for the gain check
MDM2 inhibits p53.
p53 activates CDKN1A.
ATM phosphorylates MDM2.
"""

WEATHER_MATERIAL = """# 示例（非正式答案）· synthetic off-topic material for the gain check
The wind turned north after lunch and the sea stayed calm all afternoon.
Rain is expected tomorrow, and the harbour lights came on early.
"""

GROUNDED_SPEC = {
    "figure_type": "mechanism", "title": "grounded",
    "canvas": {"width_mm": 180, "margin_mm": 7, "font_pt": 7.5, "line_pt": .9},
    "nodes": [
        {"id": "n1", "label": "MDM2", "kind": "protein",
         "evidence": [{"source": "m01.md", "quote": "MDM2 inhibits p53."}]},
        {"id": "n2", "label": "p53", "kind": "protein",
         "evidence": [{"source": "m01.md", "quote": "MDM2 inhibits p53."}]},
        {"id": "n3", "label": "CDKN1A", "kind": "gene",
         "evidence": [{"source": "m01.md", "quote": "p53 activates CDKN1A."}]},
        {"id": "n4", "label": "ATM", "kind": "protein",
         "evidence": [{"source": "m01.md", "quote": "ATM phosphorylates MDM2."}]},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2", "relation": "inhibition",
         "evidence": [{"source": "m01.md", "quote": "MDM2 inhibits p53."}]},
        {"id": "e2", "source": "n2", "target": "n3", "relation": "activation",
         "evidence": [{"source": "m01.md", "quote": "p53 activates CDKN1A."}]},
        {"id": "e3", "source": "n4", "target": "n1", "relation": "modification",
         "evidence": [{"source": "m01.md", "quote": "ATM phosphorylates MDM2."}]},
    ],
}

FABRICATED_SPEC = {
    "figure_type": "mechanism", "title": "fabricated",
    "canvas": {"width_mm": 180, "margin_mm": 7, "font_pt": 7.5, "line_pt": .9},
    "nodes": [  # two names that never occur in the material
        {"id": "n1", "label": "BRCA1", "kind": "protein",
         "evidence": [{"source": "m01.md", "quote": "BRCA1 represses MYC in breast tissue."}]},
        {"id": "n2", "label": "MYC", "kind": "gene",
         "evidence": [{"source": "m01.md", "quote": "BRCA1 represses MYC in breast tissue."}]},
    ],
    "edges": [  # a sentence that does not occur, drawn as an activation of an inhibition
        {"id": "e1", "source": "n1", "target": "n2", "relation": "activation",
         "evidence": [{"source": "m01.md", "quote": "MDM2 inhibits p53."}]},
    ],
}

OFF_TOPIC_SPEC = {
    "figure_type": "mechanism", "title": "off topic",
    "canvas": {"width_mm": 180, "margin_mm": 7, "font_pt": 7.5, "line_pt": .9},
    "nodes": [{"id": "n1", "label": "ATM", "kind": "protein",
               "evidence": [{"source": "m01.md", "quote": "The wind turned north after lunch."}]},
              {"id": "n2", "label": "p53", "kind": "protein",
               "evidence": [{"source": "m01.md", "quote": "ATM activates p53."}]}],
    "edges": [{"id": "e1", "source": "n1", "target": "n2", "relation": "activation",
               "evidence": [{"source": "m01.md", "quote": "ATM activates p53."}]}],
}

CASES = [
    {"label": "grounded", "material": GROUNDED_MATERIAL, "spec": GROUNDED_SPEC,
     "expect": {"status": "success", "blocking_zero": True, "verified_rate": 1.0,
                "all_quotes_verified": True, "tee_bar": True},
     "why": "every quote occurs verbatim in the material and the inhibition is drawn as a T-bar"},
    {"label": "fabricated", "material": GROUNDED_MATERIAL, "spec": FABRICATED_SPEC,
     "expect": {"status": "partial", "blocking_check": "polarity_inverted",
                "verified_below_1": True, "elements_listed": True,
                "warn_check": "entity_unverified"},
     "why": "invented entity names + invented quotes + an inhibition drawn as an activation: "
            "the one real quote still verifies while the invented ones do not, and the "
            "inverted edge blocks"},
    {"label": "off_topic", "material": WEATHER_MATERIAL, "spec": OFF_TOPIC_SPEC,
     "expect": {"status": "partial", "blocking_check": "evidence_unverified",
                "verified_rate": 0.0, "warn_check": "entity_unverified"},
     "why": "the material is about the weather and supports none of the claims: 0/N verified "
            "evidence is blocking"},
]


def run(args, cwd):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run([PY, "-B"] + [str(a) for a in args], cwd=cwd, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def judge(case, tmp):
    """Materialise one labelled case, run it, and check it against its own label."""
    cdir = os.path.join(tmp, case["label"])
    mat = os.path.join(cdir, "materials")
    os.makedirs(mat, exist_ok=True)
    open(os.path.join(mat, "m01.md"), "w", encoding="utf-8", newline="\n").write(case["material"])
    json.dump(case["spec"], open(os.path.join(cdir, "figure.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump({"case_id": "gain-" + case["label"], "material_dir": "materials",
               "figure_spec": "figure.json"},
              open(os.path.join(cdir, "case.json"), "w", encoding="utf-8"), ensure_ascii=False)
    out = os.path.join(tmp, "out-" + case["label"])
    rc, log = run([ENTRY, "--case", os.path.join(cdir, "case.json"), "--out", out], cwd=tmp)
    res = {}
    try:
        res = json.load(open(os.path.join(out, "result.json"), encoding="utf-8"))
    except Exception:
        pass
    svg = ""
    try:
        svg = open(os.path.join(out, "figure.svg"), encoding="utf-8").read()
    except Exception:
        pass
    m = res.get("metrics") or {}
    items = (res.get("checks") or {}).get("items") or []
    blocking = (res.get("checks") or {}).get("blocking") or {}
    srcs = res.get("element_sources") or []
    verified = sum(1 for s in srcs if s.get("verified_in_material"))
    rate = (verified / len(srcs)) if srcs else None
    exp = case["expect"]
    got = {
        "status": res.get("status"),
        "blocking": blocking,
        "blocking_zero": all((blocking.get(k) or 0) == 0 for k in ("model_errors", "data_errors")),
        "elements_listed": len(srcs),
        "quotes_total": len(srcs),
        "quotes_verified": verified,
        "verified_rate": (round(rate, 3) if rate is not None else None),
        "eevidence_rate_field": m.get("evidence_verify_rate"),
        "warn_checks": sorted({i.get("check") for i in items if i.get("severity") == "warn"}),
        "error_checks": sorted({i.get("check") for i in items if i.get("severity") == "error"}),
        "tee_bar": svg.count("tee-bar"),
        "svg_text_elements": svg.count("<text "),
        "crash": "Traceback" in log,
        "rc": rc,
    }
    fails = []
    if got["status"] != exp["status"]:
        fails.append(f"status {got['status']} != {exp['status']}")
    if exp.get("blocking_zero") and not got["blocking_zero"]:
        fails.append(f"blocking not zero: {blocking}")
    if exp.get("blocking_check") and exp["blocking_check"] not in got["error_checks"]:
        fails.append(f"missing blocking check {exp['blocking_check']} (got {got['error_checks']})")
    if exp.get("warn_check") and exp["warn_check"] not in got["warn_checks"]:
        fails.append(f"missing warning {exp['warn_check']} (got {got['warn_checks']})")
    if "verified_rate" in exp and got["verified_rate"] != exp["verified_rate"]:
        fails.append(f"verified rate {got['verified_rate']} != {exp['verified_rate']}")
    if exp.get("verified_below_1") and not (got["verified_rate"] is not None
                                            and got["verified_rate"] < 1.0):
        fails.append(f"expected some quotes to stay unverified, got {got['verified_rate']}")
    if exp.get("all_quotes_verified") and got["quotes_verified"] != got["quotes_total"]:
        fails.append(f"only {got['quotes_verified']}/{got['quotes_total']} quotes verified")
    if exp.get("tee_bar") and got["tee_bar"] <= 0:
        fails.append("no T-bar was drawn for the inhibition")
    if exp.get("elements_listed") and not got["elements_listed"]:
        fails.append("the fabricated elements were dropped instead of being listed")
    if got["crash"]:
        fails.append("the run crashed")
    return {"label": case["label"], "why": case["why"], "expected": exp, "actual": got,
            "pass": not fails, "failures": fails}


def main(argv=None):
    ap = argparse.ArgumentParser(description="labelled gain check: grounded vs fabricated")
    ap.add_argument("--json", default=None, help="also write the verdicts to this path")
    a = ap.parse_args(argv)
    tmp = tempfile.mkdtemp(prefix="gain-check-")
    verdicts = [judge(c, tmp) for c in CASES]
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{'case':<11} {'verdict':<7} status     quotes verified   blocking/warn")
    for v in verdicts:
        ac = v["actual"]
        bw = ",".join(ac["error_checks"] or ac["warn_checks"] or ["-"]) or "-"
        print(f"{v['label']:<11} {'PASS' if v['pass'] else 'FAIL':<7} "
              f"{str(ac['status']):<10} {ac['quotes_verified']}/{ac['quotes_total']}"
              f"{'':<9} {bw}")
        if not v["pass"]:
            for f in v["failures"]:
                print(f"    ! {f}")
    ok = all(v["pass"] for v in verdicts)
    print(f"\ngain_check: {sum(1 for v in verdicts if v['pass'])}/{len(verdicts)} labelled cases "
          f"behaved as labelled")
    print("GAIN_OK" if ok else "GAIN_FAIL")
    if a.json:
        json.dump({"verdicts": verdicts, "all_ok": ok}, open(a.json, "w", encoding="utf-8",
                  newline="\n"), ensure_ascii=False, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
