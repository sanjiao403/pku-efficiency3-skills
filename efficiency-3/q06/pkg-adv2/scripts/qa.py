"""qa.py - the single audit that decides whether the deck may ship.

Seven gates, one per rubric dimension that can be checked mechanically:

G1 mainline       storyline fields answered or explicitly not-derivable
G2 page_structure one claim per page, bullets within limits
G3 figure_evidence every page traces to a locator; refs and numbers exist
G4 narrative_notes notes carry a transition, a speaker move and a Q/A,
                   and do not echo the slide
G5 template_layout template placeholders kept, geometry inside the page,
                   fonts at or above the floor, no overflow
G6 render_editability a render exists; the .pptx reopens; shapes are editable
G7 rendered_preview the preview was *measured*: PDF page count and page box,
                   one page image per slide, right aspect, not blank, and the
                   fonts the deck asked for are the ones the PDF embedded

The output is what ``result.json.audit`` and the human reviewer read, and the
same object powers ``tests/selftest.py``.  Gates that cannot be evaluated are
reported as ``not_evaluated`` with the reason, never as passed.
"""
from __future__ import annotations

import os
import re
import hashlib
import sys

sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

import layout as L
import notes as N
import plan_validate as PV
from inventory import refs_in, numbers_in
from util import one_line

MIN_FONT_PT = 11.0
MAX_NOTE_REDUNDANCY = 0.34


def _gate(name: str, ok, detail: dict, reasons: list[str] | None = None) -> dict:
    return {"gate": name, "status": "pass" if ok is True else (
        "fail" if ok is False else "not_evaluated"),
        "detail": detail, "reasons": reasons or []}


def audit(*, plan: dict, src, inv, validation: dict, deck_report: dict,
          readback: dict | None, render_info: dict | None, template_info: dict | None,
          specs: list[dict], do_render: bool | None = None) -> dict:
    gates = []

    # ---- G1 mainline
    story = plan.get("storyline") or {}
    answered = [k for k, v in story.items() if one_line(v or "")]
    not_derivable = [k for k in ("gap", "limits")
                     if not one_line(story.get(k) or "")
                     and (plan.get("deck") or {}).get(k + "_status") in
                     ("not-derivable", "none-found", "inferred")]
    roles = validation["metrics"]["role_coverage"]
    spine = [r for r in ("question", "gap", "approach", "result", "limits", "takeaway")
             if roles.get(r)]
    g1_ok = len(story) > 0 and (len(spine) >= 4)
    gates.append(_gate("G1_mainline", g1_ok, {
        "storyline_answered": answered,
        "storyline_empty": [k for k in story if k not in answered],
        "declared_not_derivable": not_derivable,
        "spine_roles_present": spine,
    }, [] if g1_ok else ["fewer than four spine roles have a page"]))

    # ---- G2 page structure
    structure_issues = []
    for s in plan.get("slides") or []:
        bl = s.get("bullets") or []
        if s.get("role") in PV.CONTENT_ROLES:
            if not one_line(s.get("claim") or "") and not s.get("evidence_absent_reason"):
                structure_issues.append(f"{s.get('id')}: no claim and no declared absence")
            if len(bl) > 5:
                structure_issues.append(f"{s.get('id')}: {len(bl)} bullets (> 5)")
        for b in bl:
            if len(str(b)) > 130:
                structure_issues.append(f"{s.get('id')}: bullet of {len(str(b))} chars")
    gates.append(_gate("G2_page_structure", not structure_issues,
                       {"issues": structure_issues[:20],
                        "slides": len(plan.get("slides") or [])}))

    # ---- G3 figure & evidence
    cov = validation["metrics"]
    g3_ok = cov["evidence_coverage"] >= 0.8 and validation["counts"]["error"] == 0
    gates.append(_gate("G3_figure_evidence", g3_ok, {
        "evidence_coverage": cov["evidence_coverage"],
        "slides_with_locator": cov["slides_with_locator"],
        "content_slides": cov["content_slides"],
        "errors": validation["counts"]["error"],
        "error_codes": sorted({e["code"] for e in validation["errors"]}),
        "warnings": validation["counts"]["warn"],
    }, [] if g3_ok else [e["message"] for e in validation["errors"][:6]]))

    # ---- G4 notes
    ninfo = N.audit_notes(plan)
    g4_ok = (not ninfo["missing_transition"]) and ninfo["max_redundancy"] <= MAX_NOTE_REDUNDANCY
    gates.append(_gate("G4_narrative_notes", g4_ok, {
        "max_redundancy": ninfo["max_redundancy"],
        "mean_redundancy": ninfo["mean_redundancy"],
        "missing_transition": ninfo["missing_transition"],
        "slides_without_qa": ninfo["slides_without_qa"],
        "total_speaking_seconds": ninfo["total_seconds"],
        "budget_seconds": int((plan.get("deck") or {}).get("duration_min") or 12) * 60,
    }, [] if g4_ok else ["a note repeats the slide text or lacks a transition"]))

    # ---- G5 layout & template
    overflow = L.overflow_report(specs)
    rb = readback or {}
    geo_problems = list(rb.get("geometry_problems") or [])
    min_font = rb.get("min_font_pt")
    font_ok = (min_font is None) or (min_font >= MIN_FONT_PT)
    tinfo = template_info or {}
    kept_placeholders = True
    layouts_known = True
    if tinfo.get("available") and deck_report.get("per_slide"):
        layouts_used = {d["layout"] for d in deck_report["per_slide"]}
        if layouts_used == {"unknown"}:
            layouts_known = False          # re-audit path: layout names not recorded
        else:
            names = [lay["name"] for lay in tinfo.get("layouts") or []]
            kept_placeholders = bool(layouts_used) and all(n in names for n in layouts_used)
    limit = int((plan.get("deck") or {}).get("slide_limit") or 16)
    count_ok = (rb.get("slide_count") or len(plan.get("slides") or [])) <= limit
    g5_ok = (overflow["slides_with_overflow"] == 0 and not geo_problems
             and font_ok and kept_placeholders and count_ok)
    gates.append(_gate("G5_template_layout", g5_ok, {
        "overflow": overflow,
        "geometry_problems": geo_problems[:10],
        "min_font_pt": min_font,
        "font_floor_pt": MIN_FONT_PT,
        "template_available": bool(tinfo.get("available")),
        "template_layouts_ok": kept_placeholders,
        "template_layouts_evaluated": layouts_known,
        "slide_count": rb.get("slide_count"),
        "slide_limit": limit,
    }, [] if g5_ok else [
        f"{overflow['slides_with_overflow']} page(s) overflow",
        f"min font {min_font}pt below floor",
    ] if not font_ok or overflow["slides_with_overflow"] else geo_problems[:3]))

    # ---- G6 render & editability
    # A model preview is a diagnostic, not a deliverable: the rubric asks for a
    # real rendered preview, so a non-real render fails this gate (and the run
    # reports partial) rather than being quietly accepted.
    rinfo = render_info or {}
    real_render = bool(rinfo.get("pdf")) and rinfo.get("preview_mode") == "real"
    editable = bool(rb.get("pages")) and all(p.get("editable_shapes", 0) >= 2
                                             for p in rb.get("pages") or [])
    g6_ok = real_render and editable
    g6_reasons = []
    if not rinfo.get("ok"):
        g6_reasons.append("no rendered preview could be produced on this host")
    elif not real_render:
        g6_reasons.append(f"preview is not a real render "
                          f"(engine={rinfo.get('engine')}, mode={rinfo.get('preview_mode')}); "
                          f"install LibreOffice or PowerPoint to get one")
    if not editable:
        g6_reasons.append("the deck does not reopen as editable shapes")
    gates.append(_gate("G6_render_editability", g6_ok, {
        "render_engine": rinfo.get("engine"),
        "preview_mode": rinfo.get("preview_mode"),
        "pdf": rinfo.get("pdf"),
        "png_pages": len(rinfo.get("pngs") or []),
        "real_render": real_render,
        "editable": editable,
        "notes_present": rb.get("has_notes"),
    }, g6_reasons))

    # ---- G7 rendered preview, measured
    # "A preview exists" and "the preview is the deck" are different claims.  The
    # numbers come from render.verify(): PDF page count/page box, per-page PNG
    # size/aspect/ink, embedded fonts.  A render that cannot be measured, or that
    # measures wrong (missing pages, blank frames, rescaled page), fails here.
    rv = rinfo.get("verification") or {}
    rv_issues = list(rv.get("issues") or [])
    if do_render is False:
        g7_ok = None
    elif not rv:
        g7_ok = False
        rv_issues = rv_issues + ["render verification did not run"]
    elif rv.get("preview_mode") == "model":
        g7_ok = False
        rv_issues = rv_issues + ["the preview is a model drawing, not a rendered deck"]
    else:
        g7_ok = bool(rv.get("checked"))
    gates.append(_gate("G7_rendered_preview", g7_ok, {
        "preview_mode": rv.get("preview_mode"),
        "pdf_pages": (rv.get("pdf") or {}).get("pages"),
        "pdf_page_size_in": (rv.get("pdf") or {}).get("page_size_in"),
        "png_pages": rv.get("png_count"),
        "deck_slides": (rv.get("deck") or {}).get("slides"),
        "page_count_matches_deck": rv.get("page_count_matches_deck"),
        "fonts_embedded": (rv.get("pdf") or {}).get("fonts_embedded"),
        "fonts_requested_not_embedded": rv.get("fonts_requested_not_embedded"),
        "blank_pages": [p.get("file") for p in rv.get("pages") or [] if p.get("blank")],
        "measured_from": "result.json.render.verification (also render.json)",
        "warnings": rv.get("warnings"),
    }, rv_issues))

    dims = {}
    for g in gates:
        key = {"G1_mainline": "mainline", "G2_page_structure": "page_structure",
               "G3_figure_evidence": "figure_evidence", "G4_narrative_notes": "narrative_notes",
               "G5_template_layout": "template_layout",
               "G6_render_editability": "render_editability",
               "G7_rendered_preview": "rendered_preview"}[g["gate"]]
        dims[key] = {"status": g["status"], "label": PV.DIMENSIONS.get(key, key),
                     "reasons": g["reasons"]}

    passed = sum(1 for g in gates if g["status"] == "pass")
    return {
        "gates": gates,
        "dimensions": dims,
        "passed": passed,
        "total": len(gates),
        "ok": passed == len(gates),
        "real_render": real_render,
        "warnings": validation["warnings"],
        "numbers_seen_on_slides": _count_numbers(plan),
        "refs_seen_on_slides": _count_refs(plan),
    }


def _count_numbers(plan) -> int:
    seen = set()
    for s in plan.get("slides") or []:
        for raw, unit in numbers_in(PV._page_text(s)):
            seen.add((raw, unit))
    return len(seen)


def _count_refs(plan) -> int:
    seen = set()
    for s in plan.get("slides") or []:
        seen.update(refs_in(PV._page_text(s)))
    return len(seen)


def summary(audit_result: dict) -> str:
    g = audit_result
    head = f"{g['passed']}/{g['total']} gates passed · render={g['real_render']}"
    bad = [f"{k}: {v['status']}" for k, v in g["dimensions"].items() if v["status"] != "pass"]
    return head + (" · issues: " + ", ".join(bad) if bad else " · all clear")


def re_audit(out_dir: str) -> dict:
    """Re-run the gates on an already-produced output directory.

    Used by ``qa.py --out`` and by an evaluator who wants to check a deck without
    rebuilding it.  Re-renders nothing, but it does **re-open the delivered
    artefacts**: ``deck.pptx`` is read back from disk, and the preview is
    re-measured from the PDF and the page PNGs.  Reading only the run's own
    ledgers (``deck-readback.json`` / ``render.json``) made this a self-check
    that stayed green while the delivered file had been rewritten - so the
    ledger values are still used, but only after they are checked against the
    files they claim to describe (``G0_ledgers_match_artefacts``).

    G1-G4 are plan-layer gates (they judge the page plan that produced the
    deck); G0 and G5-G7 judge the delivered files.  ``README.md`` says which is
    which, so nobody mistakes this for a full independent audit - that is
    ``scripts/audit_deck.py``.
    """
    import json
    import os

    def load(name, default=None):
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            return default
        with open(path, "r", encoding="utf-8-sig") as fh:
            try:
                return json.load(fh)
            except Exception:
                return default

    plan = load("plan.json") or {}
    validation = load("validation.json") or {"counts": {"error": 0, "warn": 0}, "errors": [],
                                             "warnings": [], "metrics": {
                                                 "evidence_coverage": 0.0,
                                                 "slides_with_locator": 0,
                                                 "content_slides": 0,
                                                 "role_coverage": {}}}
    ledger_readback = load("deck-readback.json")
    render_info = load("render.json")
    layout_info = load("layout.json") or {}
    specs = layout_info.get("slides") or []
    if not specs and plan:
        boxes = L.slide_boxes(L.DEFAULT_SLIDE["w_in"], L.DEFAULT_SLIDE["h_in"])
        specs = [L.plan_slide_layout(s, boxes, with_figure=bool(s.get("figure")),
                                     with_table=bool(s.get("table")),
                                     with_kpis=bool(s.get("kpis")))
                 for s in plan.get("slides") or []]
    result = load("result.json") or {}
    template_info = {"available": bool((result.get("template") or {}).get("available")),
                     "path": (result.get("template") or {}).get("path"),
                     "layouts": [{"name": n} for n in
                                 ((result.get("template") or {}).get("layouts") or [])]}

    # ---- read the delivered artefacts, do not trust the ledger --------------
    import deck as D
    pptx = os.path.join(out_dir, ((result.get("deck") or {}).get("pptx")) or "deck.pptx")
    fresh = None
    fresh_error = None
    if os.path.isfile(pptx):
        try:
            fresh = D.read_back(pptx)
        except Exception as exc:
            fresh_error = f"{type(exc).__name__}: {exc}"
    readback = fresh or ledger_readback
    ledger_mismatch = []

    # declared hashes vs the bytes on disk
    for o in (result.get("outputs") or []):
        p = os.path.join(out_dir, o.get("path") or "")
        if not os.path.isfile(p):
            ledger_mismatch.append(f"{o.get('path')}: missing")
        elif o.get("bytes") is not None and os.path.getsize(p) != o["bytes"]:
            ledger_mismatch.append(f"{o.get('path')}: {os.path.getsize(p)} B on disk, "
                                   f"{o['bytes']} B declared")
        elif o.get("sha256") and sha256_file(p) != o["sha256"]:
            ledger_mismatch.append(f"{o.get('path')}: sha256 differs from result.json")

    # ... and nothing in the delivery that the ledger never declared: a file
    # dropped in afterwards (a raster stand-in, a screenshot) is exactly how a
    # tampered delivery looks, and "extra files are ignored" used to hide it.
    declared_paths = {os.path.normpath(o.get("path") or "")
                      for o in (result.get("outputs") or [])}
    # these two are excluded from outputs[] on purpose (they cannot carry their
    # own digest); see _artifacts() in run.py
    self_excluded = {"result.json", "audit-deck.json"}
    for root, dirs, files in os.walk(out_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            rel = os.path.normpath(os.path.relpath(os.path.join(root, name), out_dir))
            if rel in declared_paths or rel in self_excluded:
                continue
            ledger_mismatch.append(f"{rel.replace(os.sep, '/')}: present in the delivery "
                                   f"but not declared in result.json.outputs[]")

    # the ledger's readback vs the file as it is now
    if fresh is not None and ledger_readback:
        if ledger_readback.get("slide_count") != fresh.get("slide_count"):
            ledger_mismatch.append(
                f"deck-readback.json says {ledger_readback.get('slide_count')} slide(s), "
                f"the delivered pptx has {fresh.get('slide_count')}")
        if ledger_readback.get("min_font_pt") != fresh.get("min_font_pt"):
            ledger_mismatch.append(
                f"deck-readback.json says min font {ledger_readback.get('min_font_pt')}pt, "
                f"the delivered pptx gives {fresh.get('min_font_pt')}pt")
    elif fresh is None:
        ledger_mismatch.append(f"deck.pptx could not be re-opened: "
                               f"{fresh_error or 'file missing'}")

    # re-measure the preview from the files, then hand that to G7
    verified = None
    if render_info is not None:
        try:
            import render as R
            verified = R.verify(pptx, out_dir, render_info, plan=plan)
            render_info = dict(render_info, verification=verified)
        except Exception as exc:
            ledger_mismatch.append(f"preview could not be re-measured: "
                                   f"{type(exc).__name__}: {exc}")

    deck_report = {"per_slide": [{"layout": "unknown"} for _ in plan.get("slides") or []]
                   if not (result.get("template") or {}).get("available") else
                   [{"layout": s.get("layout", "unknown")} for s in
                    ((result.get("deck") or {}).get("per_slide") or
                     [{"layout": "unknown"}] * len(plan.get("slides") or []))],
                   "slides": (readback or {}).get("slide_count") or
                             len(plan.get("slides") or []),
                   "template": template_info,
                   "slide_size_in": (readback or {}).get("size_in") or
                                    dict(L.DEFAULT_SLIDE)}
    class _Src:
        def quote_locator(self, quote):
            return None, (None if not quote else "unverified"), (None if not quote else "unknown")
    out = audit(plan=plan, src=_Src(), inv=None, validation=validation,
                deck_report=deck_report, readback=readback, render_info=render_info,
                template_info=template_info, specs=specs,
                do_render=(render_info is not None))
    # G0 is prepended: the delivered files must still be the files the ledger
    # describes.  Without it every other number here is a memory of a run.
    g0 = _gate("G0_ledgers_match_artefacts", not ledger_mismatch, {
        "outputs_checked": len(result.get("outputs") or []),
        "deck_reopened": fresh is not None,
        "preview_remeasured": verified is not None,
        "mismatches": ledger_mismatch[:8],
    }, ledger_mismatch[:8])
    out["gates"] = [g0] + out["gates"]
    out["dimensions"] = dict({"ledger_integrity": {"status": g0["status"],
                                                  "label": "交付件与台账一致",
                                                  "reasons": g0["reasons"]}},
                             **out["dimensions"])
    out["passed"] = sum(1 for g in out["gates"] if g["status"] == "pass")
    out["total"] = len(out["gates"])
    out["ok"] = out["passed"] == out["total"]
    out["scope"] = ("G1-G4 judge the page plan (plan layer); G0 and G5-G7 judge the "
                    "delivered pptx/pdf/png. For a fully independent audit of the "
                    "artefacts, run scripts/audit_deck.py.")
    return out


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="re-run the six gates on an output directory")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    res = re_audit(args.out)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(summary(res))
        for g in res["gates"]:
            print(f"  {g['gate']:<24} {g['status']}")
            for r in g["reasons"][:3]:
                print(f"      - {r}")
    return 0 if res["passed"] == res["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
