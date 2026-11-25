"""gain_check.py - judge the labeled cases in tests/gain_cases.json, item by item.

    python3 scripts/gain_check.py                    # writes tests/gain-report.json
    python3 scripts/gain_check.py --json             # also print the full report

Each case is a small material + a page-level plan with a label saying what it is
(``grounded``, ``fabricated_number``, ``fabricated_figure_ref``, ...).  The judge
does not trust the generator's own verdicts:

* ``plan_validate.validate()``  - the four hard gates (G1 numbers, G2 Figure/Table
  labels, G3 verbatim quotes, G4 locators) produce error codes;
* ``rigor.check()``             - re-extracts the material and re-proves each
  declared item from scratch, so an error in the plan layer cannot hide it.

A case passes when the observed error codes match ``expect.error_codes`` and every
item in ``expect.rigor_missing`` really is missing.  Exit 0 = every case judged as
labeled, 1 = a case disagreed with its label, 2 = the case file is unreadable.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import sys

sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import inventory as I
import papertext as P
import plan_validate as PV
import rigor as RG
from util import one_line


def source_of(material_text: str) -> P.Source:
    src = P.Source()
    for i, line in enumerate([x for x in material_text.split("\n") if x.strip()], start=1):
        src.add(line, kind="para", source="material_text", line=i)
    for i, seg in enumerate(src.segments, start=1):
        seg["id"] = f"seg-{i:04d}"
    return src


def declared_items(slides: list[dict]) -> list[str]:
    """Every item a page claims, as rigor items the judge must re-prove."""
    out = []
    for s in slides:
        for ftxt in PV._page_fields(s):
            for raw, unit in I.numbers_in(ftxt):
                out.append(f"number:{I.norm_number(raw)}:{unit}" if unit
                           else f"number:{I.norm_number(raw)}")
            for label in I.refs_in(ftxt):
                num = re.findall(r"\d+(?:[.\-]\d+)?", label)
                out.append(f"{I._kind_of(label)}:{num[-1] if num else label}")
        for e in s.get("evidence") or []:
            if e.get("quote"):
                out.append("quote:" + one_line(e["quote"])[:60])
    seen, uniq = set(), []
    for it in out:
        if it not in seen:
            seen.add(it)
            uniq.append(it)
    return uniq


def judge(case: dict, material: str) -> dict:
    src = source_of(material)
    inv = I.build(src)
    plan = {"plan_version": 1, "slides": case.get("slides") or [],
            "deck": {"slide_limit": int(case.get("slide_limit") or 16),
                     "language": "en", "title": "gain case"},
            "storyline": {}}
    val = PV.validate(plan, src, inv)
    codes = sorted({f["code"] for f in val["errors"]})
    items = declared_items(plan["slides"])
    rows = [RG.check(src, inv, it) for it in items]
    missing = [r["item"] for r in rows if not r["found"]]
    expect = case.get("expect") or {}
    want_codes = sorted(expect.get("error_codes") or [])
    want_missing = list(expect.get("rigor_missing") or [])
    codes_ok = [c for c in want_codes if c in codes] == want_codes and \
        (not want_codes or len(codes) == len(want_codes))
    missing_ok = all(any(m.startswith(w.split(":")[0]) and w.split(":")[-1] in m
                         for m in missing) for w in want_missing) if want_missing else True
    return {
        "id": case.get("id"), "label": case.get("label"), "note": case.get("note"),
        "expect": {"error_codes": want_codes, "rigor_missing": want_missing},
        "observed": {"error_codes": codes, "validation_status": val["status"],
                     "errors": len(val["errors"]), "warnings": len(val["warnings"]),
                     "rigor_items": len(items), "rigor_missing": missing,
                     "rigor_found": sum(1 for r in rows if r["found"])},
        "verdict": "pass" if (codes_ok and missing_ok) else "fail",
        "rigor_rows": [{"item": r["item"], "found": r["found"],
                        "locator": (r["evidence"] or {}).get("locator"),
                        "reason": r["reason"]} for r in rows],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", default=os.path.join(PKG, "tests", "gain_cases.json"))
    ap.add_argument("--out", default=os.path.join(PKG, "tests", "gain-report.json"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.cases):
        print(f"FAIL case file not found: {args.cases}")
        return 2
    with open(args.cases, "r", encoding="utf-8-sig") as fh:
        doc = json.load(fh)
    default = doc.get("material_default") or ""
    rows = []
    for case in doc.get("cases") or []:
        material = default if case.get("material_text") == "@material_default" \
            else (case.get("material_text") or default)
        rows.append(judge(case, material))
    report = {
        "what": "labeled gain cases judged by plan_validate.py (hard gates) + rigor.py "
                "(independent re-proof from the material)",
        "cases_file": "tests/gain_cases.json",
        "judge": ["scripts/plan_validate.py", "scripts/rigor.py"],
        "cases": rows,
        "summary": {"passed": sum(1 for r in rows if r["verdict"] == "pass"),
                    "total": len(rows),
                    "failed": [r["id"] for r in rows if r["verdict"] != "pass"]},
        "labels_covered": sorted({r["label"] for r in rows if r.get("label")}),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    for r in rows:
        print(f"[{r['verdict']:>4}] {r['id']:<22} label={r['label']:<22} "
              f"codes={r['observed']['error_codes']} rigor_missing={r['observed']['rigor_missing']}")
    print(f"{report['summary']['passed']}/{report['summary']['total']} cases judged as labeled "
          f"-> {args.out}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if not report["summary"]["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
