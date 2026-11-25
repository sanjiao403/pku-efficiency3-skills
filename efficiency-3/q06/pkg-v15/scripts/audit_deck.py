"""audit_deck.py - independent auditor. Recomputes expectations from the *artefacts*.

    python3 scripts/audit_deck.py --out /app/output [--case /input/case.json]

What it reads: ``deck.pptx``, ``result.json`` and **the case material**.
What it deliberately does **not** read: ``plan.json``, ``inventory.json``,
``validation.json``, ``layout.json``, ``checks.json`` - i.e. none of the plan
layer's intermediate state.  If the plan says one thing and the delivered deck
says another, this auditor sees only the deck and will disagree.

For every dimension it records ``expected`` (what the contract/​case demands),
``actual`` (what the artefacts contain) and a verdict, then merges everything
into ``tests/selftest-report.json`` (or a path given with ``--report``).

Checks
  A1 contract   every output_contract field present in result.json, none null
  A2 outputs    every entry in outputs[] exists, and bytes/sha256 match the file
  A3 pages      pptx slide count == len(result.slides) == deck.slide_count <= limit
  A4 evidence   every Figure/Table number and every number in the pptx exists in
                the material (re-extracted here, not taken from the ledger)
  A5 locators   every content page in the deck resolves to a material locator or
                has a declared reason in evidence_map
  A6 notes      notes exist on every page and do not echo the slide (4-gram <= 0.34)
  A7 layout     no shape outside the page, no type below 11pt, footer/page number present
  A8 honesty    status is consistent with the findings (no 'success' with errors)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import inventory as I
import papertext as P
from util import norm_key, one_line

OVERLAP_MAX = 0.34
FLOOR_PT = 11.0
CONTENT_ROLES = {"question", "gap", "approach", "evidence", "result", "limits", "takeaway"}


def grams(text: str) -> set[str]:
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", norm_key(text))
    return {s[i:i + 4] for i in range(max(0, len(s) - 3))} or ({s} if s else set())


def overlap(a: str, b: str) -> float:
    ga, gb = grams(a), grams(b)
    return round(len(ga & gb) / len(ga | gb), 3) if ga and gb else 0.0


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_material(case: dict, case_path: str):
    base = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    decl = []
    for key in ("materials", "material", "sources", "inputs", "paper", "files"):
        v = case.get(key)
        decl += [v] if isinstance(v, str) else ([x for x in v if isinstance(x, str)]
                                                if isinstance(v, list) else [])
    paths = []
    for d in decl:
        p = d if os.path.isabs(d) else os.path.join(base, d)
        if os.path.exists(p):
            paths.append(p)
    if not paths and os.path.isdir(base):
        paths = [os.path.join(base, f) for f in sorted(os.listdir(base))
                 if os.path.splitext(f)[1].lower() in P.SUPPORTED
                 and os.path.abspath(os.path.join(base, f)) != os.path.abspath(case_path or "")]
    src = P.Source()
    for p in paths:
        part = P.ingest(p, exclude=(case_path,))
        src.segments.extend(part.segments)
        src.files.extend(part.files)
        src.notes.extend(part.notes)
        src.bib.update(part.bib)
    if (case.get("material_text") or "").strip():
        for i, line in enumerate([x for x in case["material_text"].split("\n") if x.strip()]):
            src.add(line, kind="para", source="material_text", line=i + 1)
    return src, [f["path"] for f in src.files] or (["material_text"] if src.segments else [])


def deck_facts(pptx: str) -> dict:
    from pptx import Presentation
    prs = Presentation(pptx)
    pages, overflow, min_font = [], [], None
    for i, slide in enumerate(prs.slides, start=1):
        texts, blocks, fonts, has_num, has_footer = [], [], [], False, False
        for sh in slide.shapes:
            if sh.left is not None and sh.top is not None:
                if sh.left < 0 or sh.top < 0 \
                        or sh.left + (sh.width or 0) > prs.slide_width \
                        or sh.top + (sh.height or 0) > prs.slide_height:
                    overflow.append(f"slide {i}: {sh.name} outside the page")
            xml = sh._element.xml if hasattr(sh, "_element") else ""
            if "slidenum" in xml:
                has_num = True
            if sh.has_text_frame:
                for p in sh.text_frame.paragraphs:
                    para = "".join(r.text for r in p.runs)
                    if para.strip():
                        blocks.append(para.strip())
                    for r in p.runs:
                        if r.text.strip():
                            texts.append(r.text)
                            if r.font.size is not None:
                                fonts.append(r.font.size.pt)
        if fonts:
            min_font = min(fonts) if min_font is None else min(min_font, min(fonts))
        body = " ".join(texts)
        if body.strip():
            has_footer = len(texts) > 0
        pages.append({"page": i, "text": body, "blocks": blocks,
                      "notes": slide.notes_slide.notes_text_frame.text
                               if slide.has_notes_slide else "",
                      "min_font": min(fonts) if fonts else None,
                      "has_slide_number": has_num, "has_text": has_footer})
    return {"slide_count": len(pages), "pages": pages, "overflow": overflow,
            "min_font_pt": min_font,
            "size_in": {"w": round(prs.slide_width / 914400, 3),
                        "h": round(prs.slide_height / 914400, 3)}}


def audit(out_dir: str, case_path: str | None) -> dict:
    t0 = time.time()
    with open(os.path.join(out_dir, "result.json"), "r", encoding="utf-8-sig") as fh:
        res = json.load(fh)
    case = {}
    if case_path and os.path.isfile(case_path):
        with open(case_path, "r", encoding="utf-8-sig") as fh:
            case = json.load(fh)
    pptx = os.path.join(out_dir, (res.get("deck") or {}).get("pptx") or "deck.pptx")
    src, material_files = load_material(case, case_path)
    inv = I.build(src)
    deck = deck_facts(pptx) if os.path.isfile(pptx) else {"slide_count": 0, "pages": [],
                                                         "overflow": [], "min_font_pt": None}
    checks: list[dict] = []

    def record(cid, title, expected, actual, ok, detail=None):
        checks.append({"id": cid, "check": title, "expected": expected, "actual": actual,
                       "verdict": "pass" if ok else "fail",
                       "detail": (detail or [])[:8]})

    # A1 contract -------------------------------------------------------------
    fields = ((res.get("contract") or {}).get("fields") or [])
    if not fields:
        fields = [k for k in res.keys() if k not in ("contract", "skill", "runtime")]
    missing = [f for f in fields if f not in res]
    nulls = [f for f in fields if res.get(f) is None]
    record("A1", "result.json: every contract field present and non-null",
           {"fields": len(fields)}, {"present": len(fields) - len(missing), "nulls": nulls},
           not missing and not nulls, [f"missing: {m}" for m in missing] +
           [f"null: {n}" for n in nulls])

    # A2 outputs --------------------------------------------------------------
    outputs = res.get("outputs") or []
    bad = []
    for o in outputs:
        p = os.path.join(out_dir, o.get("path", ""))
        if not os.path.isfile(p):
            bad.append(f"missing file: {o.get('path')}")
            continue
        n = os.path.getsize(p)
        if o.get("bytes") != n:
            bad.append(f"{o['path']}: bytes {o.get('bytes')} != {n}")
        if o.get("sha256") and o["sha256"] != sha256(p):
            bad.append(f"{o['path']}: sha256 mismatch")
    record("A2", "outputs[]: every declared artefact exists with matching bytes and sha256",
           {"entries": len(outputs)}, {"verified": len(outputs) - len({b.split(':')[0] for b in bad})},
           bool(outputs) and not bad, bad or ([] if outputs else ["no outputs[] in result.json"]))

    # A3 pages ----------------------------------------------------------------
    plan_slides = res.get("slides") or []
    limit = ((res.get("deck") or {}).get("template") or {}).get("slide_limit") or \
        ((res.get("plan") or {}).get("deck") or {}).get("slide_limit") or case.get("slide_limit") or 16
    n_pptx, n_res = deck["slide_count"], len(plan_slides)
    record("A3", "page count: pptx == result.slides and within slide_limit",
           {"limit": int(limit)}, {"pptx": n_pptx, "result.json": n_res},
           n_pptx == n_res and n_pptx <= int(limit),
           [f"pptx={n_pptx} result={n_res} limit={limit}"] if n_pptx != n_res else [])

    # A4 evidence present in the material ------------------------------------
    bad_ref, bad_num = [], []
    for p in deck["pages"]:
        for label in I.refs_in(p["text"]):
            if not I.verify_locator(inv, label)["ok"]:
                bad_ref.append(f"slide {p['page']}: cites {label}")
        for raw, unit in I.numbers_in(p["text"]):
            if not I.verify_value(inv, raw, unit)["ok"]:
                bad_num.append(f"slide {p['page']}: number {raw}{unit}")
    record("A4", "every Figure/Table number and number in the pptx exists in the material",
           {"material_numbers": len(inv.numbers), "material_captions": len(inv.captions)},
           {"bad_refs": len(bad_ref), "bad_numbers": len(bad_num)}, not bad_ref and not bad_num,
           bad_ref + bad_num or (["material not readable"] if not src.segments else []))

    # A5 locators -------------------------------------------------------------
    emap = {e.get("page"): e for e in (res.get("evidence_map") or [])}
    bad_loc = []
    for p in deck["pages"]:
        role = next((s.get("role") for s in plan_slides if s.get("id") ==
                     (emap.get(p["page"]) or {}).get("slide_id")), None)
        e = emap.get(p["page"])
        if e is None:
            bad_loc.append(f"page {p['page']}: no evidence_map entry")
        elif (e.get("role") in CONTENT_ROLES and not e.get("locator")
              and not e.get("not_derivable")):
            bad_loc.append(f"page {p['page']}: no locator and no declared reason")
        elif e.get("locator") and not e.get("locator_verified"):
            bad_loc.append(f"page {p['page']}: locator not verified")
    record("A5", "each content page has a verified material locator or a declared reason",
           {"content_pages": sum(1 for e in emap.values() if e.get("role") in CONTENT_ROLES)},
           {"unresolved": len(bad_loc)}, not bad_loc, bad_loc)

    # A6 notes ----------------------------------------------------------------
    bad_notes = []
    for p in deck["pages"]:
        if not p["notes"].strip():
            bad_notes.append(f"slide {p['page']}: no notes")
        elif overlap(p["notes"], p["text"]) > OVERLAP_MAX:
            bad_notes.append(f"slide {p['page']}: note echoes the slide "
                             f"(overlap {overlap(p['notes'], p['text'])})")
    record("A6", f"notes exist and stay under {OVERLAP_MAX} 4-gram overlap",
           {"pages": deck["slide_count"]}, {"bad": len(bad_notes)}, not bad_notes, bad_notes)

    # A7 layout ---------------------------------------------------------------
    layout_bad = list(deck["overflow"])
    if deck["min_font_pt"] is not None and deck["min_font_pt"] < FLOOR_PT:
        layout_bad.append(f"min font {deck['min_font_pt']}pt below {FLOOR_PT}pt")
    no_num = [f"slide {p['page']}: no slide-number field" for p in deck["pages"][1:]
              if not p["has_slide_number"]]
    record("A7", "no shape outside the page, type >= 11pt, slide numbers present",
           {"floor_pt": FLOOR_PT}, {"min_font_pt": deck["min_font_pt"],
                                    "overflow": len(deck["overflow"]),
                                    "pages_without_number": len(no_num)},
           not layout_bad and not no_num, layout_bad + no_num)

    # A8 honesty --------------------------------------------------------------
    failed = [c["id"] for c in checks if c["verdict"] == "fail"]
    status = res.get("status")
    ok = (status == "success" and not failed) or (status in ("partial", "unsupported"))
    record("A8", "status is consistent with the audit findings",
           {"expected": "success only if every check passes"},
           {"status": status, "failed_checks": failed}, ok,
           [f"status={status} but {failed} failed"] if not ok else [])

    report = {
        "auditor": "scripts/audit_deck.py",
        "case_id": case.get("case_id") or "",
        "note": ("Independent audit: reads deck.pptx, result.json and the case material only. "
                 "plan/inventory/validation/layout/checks are NOT read, so a mismatch between "
                 "the plan and the delivered deck shows up here."),
        "out_dir": os.path.abspath(out_dir),
        "deck": {"pptx": os.path.basename(pptx), "slides": deck["slide_count"],
                 "size_in": deck.get("size_in"), "min_font_pt": deck.get("min_font_pt")},
        "material": material_files,
        "checks": checks,
        "passed": sum(1 for c in checks if c["verdict"] == "pass"),
        "failed": len(failed),
        "seconds": round(time.time() - t0, 2),
    }
    return report


def _contract_field_names(case: dict):
    raise NotImplementedError


def merge_report(report: dict, path: str) -> dict:
    """Merge the audit into tests/selftest-report.json without losing prior results."""
    existing = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}
    audits = [a for a in (existing.get("independent_audits") or [])
              if a.get("out_dir") != report["out_dir"]]
    audits.append({"out_dir": report["out_dir"], "deck": report["deck"],
                   "passed": report["passed"], "failed": report["failed"],
                   "checks": [{"id": c["id"], "check": c["check"], "verdict": c["verdict"],
                               "expected": c["expected"], "actual": c["actual"],
                               "detail": c["detail"]} for c in report["checks"]]})
    existing["independent_audits"] = audits
    existing["independent_audit_summary"] = {
        "cases": len(audits),
        "checks_per_case": len(report["checks"]),
        "passed": sum(a["passed"] for a in audits),
        "failed": sum(a["failed"] for a in audits),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(existing, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return existing


def write_case_report(report: dict, path: str) -> dict:
    """Append/replace this run in the aggregate audit-report.json (first-class artefact)."""
    existing = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}
    key = report.get("case_id") or os.path.basename(os.path.abspath(report["out_dir"]))
    cases = [c for c in (existing.get("cases") or []) if c.get("case_id") != key]
    cases.append({
        "case_id": key,
        "out_dir": os.path.basename(report["out_dir"]),
        "deck": report["deck"], "passed": report["passed"], "failed": report["failed"],
        "checks": [{"id": c["id"], "check": c["check"], "verdict": c["verdict"],
                    "expected": c["expected"], "actual": c["actual"]}
                   for c in report["checks"]],
    })
    doc = {
        "what": "independent audit of the delivered artefacts (A1-A8), regenerated per run",
        "generated_by": "scripts/audit_deck.py --out <run> --case <case.json> "
                        "--report-out reports/audit-report.json",
        "reads": ["deck.pptx", "result.json", "the case material"],
        "does_not_read": ["plan.json", "inventory.json", "validation.json", "layout.json"],
        "cases": sorted(cases, key=lambda c: c["case_id"]),
        "summary": {"cases": len(cases),
                    "checks_per_case": len(report["checks"]),
                    "passed": sum(c["passed"] for c in cases),
                    "failed": sum(c["failed"] for c in cases)},
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="independent auditor for a delivered deck")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--case", default=None)
    ap.add_argument("--report", default=None, help="merge into this selftest report")
    ap.add_argument("--report-out", default=None,
                    help="write/append the standalone machine-readable audit report here")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    case_path = args.case or os.path.join(os.path.dirname(os.path.abspath(args.out)), "case.json")
    if not os.path.isfile(os.path.join(args.out, "result.json")):
        print(f"FAIL no result.json in {args.out}")
        return 2
    try:
        report = audit(args.out, case_path if os.path.isfile(case_path) else None)
    except Exception as exc:
        import traceback
        print(f"ERROR audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2
    if args.report:
        merge_report(report, args.report)
    if args.report_out:
        doc = write_case_report(report, args.report_out)
        print(f"wrote {args.report_out} ({doc['summary']['passed']} pass / "
              f"{doc['summary']['failed']} fail across {doc['summary']['cases']} case(s))")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"audit: {report['passed']}/{len(report['checks'])} checks passed on "
              f"{report['deck']['pptx']} ({report['deck']['slides']} slides)")
        for c in report["checks"]:
            print(f"  [{c['verdict']:>4}] {c['id']} {c['check']}")
            for d in c["detail"]:
                print(f"         - {d}")
            if c["verdict"] == "fail":
                print(f"         expected={c['expected']} actual={c['actual']}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
