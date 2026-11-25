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

def _mk(title, nodes, edges):
    return {"figure_type": "mechanism", "title": title,
            "canvas": {"width_mm": 180, "margin_mm": 7, "font_pt": 7.5, "line_pt": .9},
            "nodes": nodes, "edges": edges}


def _n(i, lab, q, kind="protein"):
    return {"id": i, "label": lab, "kind": kind, "evidence": [{"source": "m01.md", "quote": q}]}


def _e(i, s, t, rel, q):
    return {"id": i, "source": s, "target": t, "relation": rel,
            "evidence": [{"source": "m01.md", "quote": q}]}


GQ = "MDM2 inhibits p53."
AQ = "p53 activates CDKN1A."
MQ = "ATM phosphorylates MDM2."
FQ = "BRCA1 represses MYC in breast tissue."
WQ = "The wind turned north after lunch."
OQ = "ATM activates p53."
GROUNDED_SPEC = _mk("grounded", [_n("n1", "MDM2", GQ), _n("n2", "p53", GQ),
                                 _n("n3", "CDKN1A", AQ, "gene"), _n("n4", "ATM", MQ)],
                    [_e("e1", "n1", "n2", "inhibition", GQ),
                     _e("e2", "n2", "n3", "activation", AQ),
                     _e("e3", "n4", "n1", "modification", MQ)])
FABRICATED_SPEC = _mk("fabricated", [_n("n1", "BRCA1", FQ), _n("n2", "MYC", FQ, "gene")],
                      [_e("e1", "n1", "n2", "activation", GQ)])
OFF_TOPIC_SPEC = _mk("off topic", [_n("n1", "ATM", WQ), _n("n2", "p53", OQ)],
                     [_e("e1", "n1", "n2", "activation", OQ)])

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
