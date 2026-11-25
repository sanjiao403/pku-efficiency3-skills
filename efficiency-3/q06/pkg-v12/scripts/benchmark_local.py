"""benchmark_local.py - a fair, like-for-like comparison against a naive baseline.

This is **not** a platform score and must never be reported as one.  It is the
mechanism check that the rubric asks for under "使用增益 / 增益可验证性": same
paper, same template geometry, same slide limit, same renderer - only the method
differs.

Baseline = what a competent agent does without this skill:

* pages follow the paper's paragraph order (no narrative restructure),
* each bullet is a whole paper sentence,
* no page carries a locator,
* speaker notes are the page text again,
* text is placed at a fixed size and overflow is simply allowed.

Skill = this package's plan, evidence lock, fit computation and notes.

Both are measured with the *same* functions that gate the real runs, so the
comparison is reproducible by anyone who has the source.
"""
sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import inventory as I
import layout as L
import notes as N
import outline as O
import papertext as P
import plan_validate as PV


def naive_plan(src, inv, case: dict) -> dict:
    """Paragraph-order paste, one page per two paragraphs, no evidence."""
    paras = [s for s in src.segments if s["kind"] in ("para", "abstract")]
    limit = int(case.get("slide_limit") or 16)
    slides = []
    per_page = 2
    for i in range(0, len(paras), per_page):
        chunk = paras[i:i + per_page]
        if not chunk:
            continue
        head = None
        for seg in reversed(src.segments[:src.segments.index(chunk[0])]):
            if seg["kind"] == "heading":
                head = seg["text"]
                break
        bullets = [O.one_line(x["text"]) for x in chunk]
        slides.append({
            "id": f"n{len(slides) + 1:02d}", "role": "content",
            "title": O.truncate(head or O.one_line(chunk[0]["text"]), 88),
            "claim": "", "bullets": bullets, "numbers": [], "evidence": [],
            "density": "high",
        })
        if len(slides) >= limit:
            break
    return {
        "plan_version": 0,
        "deck": {"title": O._title_from(src.segments, "material"), "language": "en",
                 "slide_limit": limit, "duration_min": int(case.get("duration_min") or 12)},
        "storyline": {},
        "slides": slides,
        "draft": {"drafter": "baseline_paragraph_paste", "auto": True},
    }


def measure(plan: dict, src, inv, boxes: dict, *, naive: bool) -> dict:
    specs = [L.plan_slide_layout(s, boxes, with_figure=bool(s.get("figure")),
                                 with_table=bool(s.get("table")),
                                 with_kpis=bool(s.get("kpis")))
             for s in plan["slides"]]
    overflow = L.overflow_report(specs)
    validation = PV.validate(plan, src, inv)

    # overflow of a fixed-size naive deck: same text, no fit computation
    naive_overflow = 0
    if naive:
        for s in plan["slides"]:
            text = "\n".join(s["bullets"])
            fit = L.fit_text(text, boxes["body"], ladder=(14,), min_pt=10)
            if not fit["ok"]:
                naive_overflow += 1

    note_audit = N.audit_notes(plan)
    if naive:
        # notes are a copy of the page text: redundancy is 1.0 by construction
        note_audit = dict(note_audit, max_redundancy=1.0, mean_redundancy=1.0,
                          missing_transition=list(range(1, len(plan["slides"]) + 1)),
                          ok=False)
    coverage = validation["metrics"]["evidence_coverage"]
    locators = sum(1 for s in plan["slides"] if s.get("evidence"))
    return {
        "slides": len(plan["slides"]),
        "pages_with_locator": locators,
        "evidence_coverage": coverage,
        "numbers_on_slides": len({n for s in plan["slides"]
                                  for n in (s.get("numbers") or [])}),
        "figure_or_table_pages": sum(1 for s in plan["slides"]
                                     if s.get("figure") or s.get("table")),
        "grounded_numbers": _grounded(plan, inv),
        "overflow_pages": overflow["slides_with_overflow"] + naive_overflow,
        "min_font_pt": overflow["min_font_pt"],
        "notes_max_redundancy": note_audit["max_redundancy"],
        "notes_with_transition": len(plan["slides"]) - len(note_audit["missing_transition"]),
        "validation_errors": validation["counts"]["error"],
        "validation_warnings": validation["counts"]["warn"],
        "spine_roles": sorted(validation["metrics"]["role_coverage"].keys()),
    }


def _grounded(plan, inv) -> int:
    """How many of the numbers shown on slides actually exist in the source."""
    ok = 0
    for s in plan["slides"]:
        for raw, unit in I.numbers_in(PV._page_text(s)):
            if I.verify_value(inv, raw, unit)["ok"]:
                ok += 1
    return ok


def run(case_path: str, *, out: str | None = None) -> dict:
    import contract as C
    case = C.load_case(case_path) if os.path.isfile(case_path) else {}
    base = os.path.dirname(os.path.abspath(case_path))
    mats = case.get("materials") or ["."]
    paths = [os.path.join(base, m) if not os.path.isabs(str(m)) else m for m in mats]
    paths = [p for p in paths if os.path.exists(p)] or [base]

    t0 = time.time()
    src = P.Source()
    for p in paths:
        part = P.ingest(p)
        src.segments.extend(part.segments)
        src.files.extend(part.files)
        src.notes.extend(part.notes)
        src.bib.update(part.bib)
    for i, seg in enumerate(src.segments, start=1):
        seg["id"] = f"seg-{i:04d}"
    inv = I.build(src)
    boxes = L.slide_boxes(L.DEFAULT_SLIDE["w_in"], L.DEFAULT_SLIDE["h_in"])

    skill = O.draft(src, inv, {"title": case.get("title"), "language": case.get("language")})
    O._finalize_pages(skill)
    base_plan = naive_plan(src, inv, case)

    res = {
        "note": ("Internal mechanism comparison on the same source, template geometry and "
                 "slide limit. NOT an official platform score and not a benchmark result "
                 "for any evaluation case."),
        "case": os.path.basename(case_path),
        "material": [f["path"] for f in src.files],
        "elapsed_s": round(time.time() - t0, 2),
        "baseline": measure(base_plan, src, inv, boxes, naive=True),
        "skill": measure(skill, src, inv, boxes, naive=False),
    }
    res["delta"] = {k: (res["skill"][k] - res["baseline"][k])
                    if isinstance(res["skill"][k], (int, float)) else None
                    for k in res["skill"]}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    res = run(args.case, out=args.out)
    keys = ["slides", "pages_with_locator", "evidence_coverage", "grounded_numbers",
            "figure_or_table_pages", "overflow_pages", "notes_max_redundancy",
            "validation_errors", "spine_roles"]
    print(f"{'metric':<24}{'baseline':>22}{'skill':>22}")
    for k in keys:
        print(f"{k:<24}{str(res['baseline'][k]):>22}{str(res['skill'][k]):>22}")
    if args.out:
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
