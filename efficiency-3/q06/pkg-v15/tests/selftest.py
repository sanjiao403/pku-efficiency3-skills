"""selftest.py - unit checks + a real end-to-end run, with a machine-readable report.

    python3 tests/selftest.py                 # full: units + one real case + render
    python3 tests/selftest.py --quick         # units only (no office, no render)
    python3 tests/selftest.py --report PATH    # where to write selftest-report.json

The report records, per check: name, what it asserts, the exact command or call,
pass/fail, and the elapsed time - plus the environment and the evidence that a
real pptx→PDF render happened.  Nothing here is a claim about platform scores.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback

sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SCRIPTS = os.path.join(PKG, "scripts")
for _p in (SCRIPTS, HERE):          # runnable as `python3 tests/selftest.py` from anywhere
    if _p not in sys.path:
        sys.path.insert(0, _p)

RESULTS: list[dict] = []
AUDITS: list[dict] = []


def check(name: str, assertion: str, fn):
    t0 = time.time()
    try:
        detail = fn()
        RESULTS.append({"check": name, "asserts": assertion, "status": "pass",
                        "detail": detail, "seconds": round(time.time() - t0, 3)})
    except Exception as exc:
        RESULTS.append({"check": name, "asserts": assertion, "status": "fail",
                        "detail": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc(limit=4).splitlines()[-3:],
                        "seconds": round(time.time() - t0, 3)})


# ---------------------------------------------------------------- unit checks

def _fixture_pdf(path: str) -> str:
    import pdf_lite
    doc = {
        "title": "Selftest Fixture Paper on Residual Attention",
        "authors": "A. Tester, B. Tester",
        "affiliation": "Selftest Lab",
        "abstract": "We report a mean absolute error of 3.7 degC and R2 = 0.86 on 12 stations.",
        "sections": [
            {"heading": "1. Introduction",
             "paras": ["Prior work reports a mean absolute error of 4.9 degC."],
             "figure": {"label": "Figure 1", "caption": "Schematic of the proposed pipeline.",
                        "kind": "flow", "nodes": ["A", "B", "C"]}},
            {"heading": "2. Results",
             "paras": ["The proposed model reduces the error."],
             "table": {"label": "Table 1", "caption": "Ablation results.",
                       "header": ["Variant", "MAE (degC)", "R2"],
                       "rows": [["Base", "4.9", "0.71"], ["Ours", "3.7", "0.86"]]}},
        ],
        "references": ["[1] Tester, A. (2021). Fixtures. Journal of Selftests."],
        "footer": "selftest fixture",
    }
    pdf_lite.write_pdf_paper(path, doc)
    return path


def unit_checks(tmp: str):
    import inventory as I
    import layout as L
    import notes as N
    import outline as O
    import papertext as P
    import plan_validate as PV

    pdf = _fixture_pdf(os.path.join(tmp, "fixture.pdf"))

    def pdf_roundtrip():
        res = P.ingest(pdf)
        assert res.text_layer, "fixture must expose a text layer"
        txt = res.full_text
        for needle in ("3.7", "0.86", "Figure 1", "Table 1", "24.5" if "24.5" in txt else "12 stations"):
            assert needle in txt, f"{needle} missing from extracted text"
        return {"segments": len(res.segments), "text_layer": True}

    check("pdf_text_layer_roundtrip", "PDF writer -> reader keeps numbers, figure and table labels",
          pdf_roundtrip)

    src = P.ingest(pdf)
    inv = I.build(src)

    check("inventory_units", "numbers carry units, incl. metric names such as R2",
          lambda: _assert_units(inv))

    check("verify_value_rejects_wrong_unit", "3.7 degC accepted, 3.7 kg rejected",
          lambda: _assert_units2(inv))

    check("verify_locator", "Figure 1 exists; Figure 9 does not",
          lambda: _assert_refs(inv))

    def evidence_lock():
        plan = O.draft(src, inv, {"title": "Selftest Deck", "language": "en"})
        good = PV.validate(plan, src, inv)
        assert good["counts"]["error"] == 0, f"clean plan has errors: {good['errors']}"
        tampered = json.loads(json.dumps(plan))
        for s in tampered["slides"]:
            if s["role"] == "question":
                s["claim"] = "Our model reaches an MAE of 9.9 degC on 999 stations"
                s["numbers"] = ["9.9 degC"]
                s["bullets"] = ["See Fig. 9 for the improvement"]
        bad = PV.validate(tampered, src, inv)
        codes = {e["code"] for e in bad["errors"]}
        assert "NUMBER_NOT_IN_SOURCE" in codes, f"invented number not caught: {codes}"
        assert "REF_NOT_IN_SOURCE" in codes, f"invented figure not caught: {codes}"
        return {"clean_errors": 0, "tampered_errors": bad["counts"]["error"],
                "codes": sorted(codes)}

    check("evidence_lock_catches_fabrication",
          "an invented number and an invented figure number both fail the lock",
          evidence_lock)

    def fit_engine():
        box = {"x_in": 0.6, "y_in": 1.6, "w_in": 6.0, "h_in": 4.0}
        short = L.fit_text("A short claim.", box, ladder=(22, 20, 18, 16), min_pt=16)
        assert short["ok"] and short["size_pt"] == 22, short
        long_text = " ".join(["crowded"] * 400)
        over = L.fit_bullets([long_text], box)
        assert not over["ok"], "an overfull box must not report success"
        assert over["size_pt"] >= 16, "must never shrink below the declared floor"
        assert over["action"] in ("split", "trim"), over["action"]
        return {"short_pt": short["size_pt"], "overflow_action": over["action"],
                "floor_pt": over["size_pt"]}

    check("layout_floor_and_overflow_action",
          "fit picks the largest size and reports split/trim instead of shrinking below 16pt",
          fit_engine)

    def notes_guard():
        plan = O.draft(src, inv, {"title": "Selftest Deck", "language": "en"})
        audit = N.audit_notes(plan)
        assert audit["max_redundancy"] <= N.MAX_REDUNDANCY, audit["max_redundancy"]
        assert not audit["missing_transition"], audit["missing_transition"]
        pushed = json.loads(json.dumps(plan))
        for s in pushed["slides"]:
            s["bullets"] = [s.get("claim") or ""] * 3
        forced = N.compose(pushed["slides"][2], {}, pushed, 2)
        assert forced["has_transition"] and forced["qa_count"] >= 1
        return {"max_redundancy": audit["max_redundancy"],
                "total_speaking_seconds": audit["total_seconds"]}

    check("notes_separated_from_slide", "notes carry transitions/Q&A and stay under the echo threshold",
          notes_guard)

    def contract_shapes():
        import contract as C
        shapes = [
            {"output_contract": {"deliverable": "d", "slides": "s"}},
            {"output_contract": {"type": "object", "properties": {"a": {"type": "string"}},
                                 "required": ["a"]}},
            {"output_contract": ["x", "y"]},
            {},
        ]
        got = [C.detect(c) for c in shapes]
        assert got[0]["source"] == "output_contract" and len(got[0]["fields"]) == 2
        assert got[1]["fields"][0]["name"] == "a" and got[1]["fields"][0].get("required")
        assert [f["name"] for f in got[2]["fields"]] == ["x", "y"]
        assert len(got[3]["fields"]) >= 8 and got[3]["source"] == "default"
        filled = C.fill({"case_id": "c1"}, {"status": "partial", "deliverable": "d"},
                        contract=got[0])
        assert filled["case_id"] == "c1" and "deliverable" in filled
        return {"shapes_handled": 4}

    check("contract_four_shapes", "map / JSON Schema / array / absent contracts all resolve",
          contract_shapes)


def _assert_units(inv):
    units = {n["unit_norm"] for n in inv.numbers}
    assert "°c" in units, f"degC unit missing: {units}"
    assert any(u in units for u in ("r²", "r2")), f"metric unit (R2) missing: {units}"
    vals = {n["value"] for n in inv.numbers}
    assert {"3.7", "4.9", "0.86"} <= vals, f"missing values: {sorted(vals)}"
    return {"units": sorted(units)}


def _assert_units2(inv):
    import inventory as I
    ok = I.verify_value(inv, "3.7", "°C")
    bad = I.verify_value(inv, "3.7", "kg")
    assert ok["ok"], ok
    assert not bad["ok"], bad
    return {"accepted": "3.7 °C", "rejected": "3.7 kg"}


def _assert_refs(inv):
    import inventory as I
    assert I.verify_locator(inv, "Figure 1")["ok"]
    assert not I.verify_locator(inv, "Figure 9")["ok"]
    return {"present": "Figure 1", "absent": "Figure 9"}


# ---------------------------------------------------------------- e2e check

def e2e_check(tmp: str, do_render: bool) -> dict:
    import contract as C
    import make_case_pdf
    import run as R

    case_dir = os.path.join(tmp, "e2e")
    os.makedirs(case_dir, exist_ok=True)
    src_spec = os.path.join(PKG, "examples", "case_en_pdf", "paper.src.json")
    pdf = os.path.join(case_dir, "paper.pdf")
    make_case_pdf.main(["--src", src_spec, "--out", pdf])
    case = {
        "case_id": "selftest-e2e",
        "task": "selftest",
        "language": "en",
        "materials": ["paper.pdf"],
        "slide_limit": 12,
        "output_contract": {"deliverable": "d", "slides": "s", "evidence_map": "e",
                             "render": "r", "status": "st"},
    }
    case_path = os.path.join(case_dir, "case.json")
    with open(case_path, "w", encoding="utf-8") as fh:
        json.dump(case, fh, ensure_ascii=False)

    out = os.path.join(tmp, "out")
    work = os.path.join(tmp, "work")
    t0 = time.time()
    res = R.run(case_path, out, work, do_render=do_render)
    elapsed = round(time.time() - t0, 2)

    pptx = os.path.join(out, "deck.pptx")
    assert os.path.isfile(pptx), "no deck.pptx produced"
    assert res.get("case_id") == "selftest-e2e"
    assert (res.get("status") in ("success", "partial")), res.get("status")
    validation = res.get("validation") or {}
    assert validation.get("counts", {}).get("error", 1) == 0, "e2e produced evidence-lock errors"
    audit = res.get("audit") or {}
    assert audit.get("total") == 6, audit

    detail = {
        "seconds": elapsed,
        "status": res.get("status"),
        "slides": len(res.get("slides") or []),
        "gates_passed": f"{audit.get('passed')}/{audit.get('total')}",
        "evidence_coverage": validation.get("metrics", {}).get("evidence_coverage"),
        "pptx_bytes": os.path.getsize(pptx),
        "render_engine": (res.get("render") or {}).get("engine"),
        "preview_mode": (res.get("render") or {}).get("preview_mode"),
        "pdf": (res.get("render") or {}).get("pdf"),
        "png_pages": len((res.get("render") or {}).get("pngs") or []),
        "result_json_fields": sorted(res.keys()),
    }
    if do_render:
        pdf_out = os.path.join(out, (res.get("render") or {}).get("pdf") or "deck.pdf")
        detail["pdf_bytes"] = os.path.getsize(pdf_out) if os.path.isfile(pdf_out) else 0
        detail["real_render"] = bool(detail["preview_mode"] == "real" and detail["pdf_bytes"])

    # ---- independent audit: re-derive everything from the artefacts alone -----
    #      audit_deck reads deck.pptx + result.json + the case material; it does
    #      NOT read plan.json / inventory.json / validation.json, so a plan that
    #      lies about the delivered file cannot hide behind itself here.
    import audit_deck
    rep = audit_deck.audit(out, case_path)
    AUDITS.append({"out_dir": "selftest-e2e", "deck": rep["deck"],
                   "passed": rep["passed"], "failed": rep["failed"],
                   "checks": [{"id": c["id"], "check": c["check"], "verdict": c["verdict"],
                               "expected": c["expected"], "actual": c["actual"],
                               "detail": c["detail"]} for c in rep["checks"]]})
    detail["independent_audit"] = {
        "auditor": rep["auditor"], "passed": rep["passed"], "total": len(rep["checks"]),
        "checks": [{"id": c["id"], "verdict": c["verdict"]} for c in rep["checks"]],
        "declared_outputs": len(res.get("outputs") or []),
        "result_json_in_outputs": any(o.get("path") == "result.json"
                                      for o in (res.get("outputs") or [])),
    }
    assert rep["failed"] == 0, [c for c in rep["checks"] if c["verdict"] != "pass"]
    assert res.get("audit_deck", {}).get("passed") == rep["passed"], \
        "run did not record the same independent audit it embedded"
    return detail


def environment() -> dict:
    import pptx
    try:
        import PIL
        pil = PIL.__version__
    except Exception:
        pil = None
    import render as R
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "python_pptx": pptx.__version__,
        "pillow": pil,
        "soffice": R._soffice_bin(),
        "powerpoint_com_available": os.name == "nt" and bool(shutil.which("pwsh") or
                                                              shutil.which("powershell")),
        "skill_version": "1.0.0",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="paper2deck self-test")
    ap.add_argument("--quick", action="store_true", help="units only")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--report", default=os.path.join(PKG, "tests", "selftest-report.json"))
    args = ap.parse_args(argv)

    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="paper2deck-selftest-")
    try:
        unit_checks(tmp)
        if not args.quick:
            check("end_to_end_run",
                  "one full run on the PDF example: deck.pptx + gates + honest result.json",
                  lambda: e2e_check(tmp, do_render=not args.no_render))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for r in RESULTS if r["status"] == "pass")
    report = {
        "skill": {"name": "paper2deck", "version": "1.0.0"},
        "generated_by": "tests/selftest.py",
        "note": ("Real self-test results from this machine. Checks the mechanism, not a platform "
                 "score. Rendering evidence is recorded under end_to_end_run.detail."),
        "environment": environment(),
        "summary": {"passed": passed, "total": len(RESULTS),
                    "failed": [r["check"] for r in RESULTS if r["status"] != "pass"],
                    "seconds": round(time.time() - t0, 2), "quick": args.quick},
        "checks": RESULTS,
        "independent_audits": AUDITS,
        "independent_audit_summary": {
            "auditor": "scripts/audit_deck.py",
            "note": ("Recomputed from deck.pptx + result.json + the case material only; "
                     "plan.json / inventory.json / validation.json / layout.json are not "
                     "read, so the expected-vs-actual verdicts below are independent of the "
                     "plan layer that produced the deck."),
            "cases": len(AUDITS),
            "checks_per_case": len(AUDITS[0]["checks"]) if AUDITS else 0,
            "passed": sum(a["passed"] for a in AUDITS),
            "failed": sum(a["failed"] for a in AUDITS),
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    with open(args.report, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"{passed}/{len(RESULTS)} checks passed in {report['summary']['seconds']}s "
          f"-> {args.report}")
    for r in RESULTS:
        mark = "ok  " if r["status"] == "pass" else "FAIL"
        print(f"  {mark} {r['check']} ({r['seconds']}s)")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
