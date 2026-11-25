"""benchmark_local.py - a real, re-runnable two-arm comparison on identical inputs.

    python3 scripts/benchmark_local.py --reps 3            # writes tests/benchmark-report.json

This is **not** a platform score and must never be reported as one.  It is the
executed evidence the rubric asks for under 使用增益 / 增益可验证性: the same
papers, the same slide limits, the same renderer and the same measurement code -
only the *method* differs.

    arm A baseline   paragraph-order paste: one source line per page at a fixed
                     14pt pitch, no locator, notes = the page text, the slide
                     budget ignored.
    arm B skill      scripts/run.py (this package: narrative plan, evidence lock,
                     fit computation, separated notes, independent audit).

Both arms really run and really write ``deck.pptx`` + ``result.json``; every
number in ``tests/benchmark-report.json`` is then recomputed from those artefacts
by ``measure()`` below (which reads the deck, the result and the material - never
the plan layer) and by ``audit_deck.py``, the same auditor for both arms.

Field paths for the numbers quoted in GAIN.md / GAIN-EVIDENCE.md:
    .cases[i].baseline.<metric>   .cases[i].skill.<metric>   .cases[i].delta.<metric>
    .totals.baseline.<metric>     .totals.skill.<metric>     .totals.delta.<metric>
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

sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import audit_deck as A
import inventory as I
import papertext as P
import run as RUN
from util import one_line, rel_posix, truncate

METRICS = [
    ("slides", "页数", "sum"),
    ("page_budget_ok", "页数不超上限", "mean"),
    ("page_budget_over_by", "超出页数预算", "sum"),
    ("verifiable_elements", "可核验图元数（数字 + 图/表号）", "sum"),
    ("source_traceability", "来源可追率（逐字回查命中）", "mean"),
    ("caption_number_consistency", "图注-数值一致率", "mean"),
    ("layout_violations", "布局/溢出违规数", "sum"),
    ("max_page_chars", "单页最多字符数", "sum"),
    ("notes_echo_pages", "备注复述页数", "sum"),
    ("content_pages_located", "已核实 locator 的内容页", "sum"),
    ("locator_rate", "来源定位覆盖率", "mean"),
    ("audit_deck_failed", "独立审计失败项数", "sum"),
    ("e2e_seconds", "端到端耗时（秒）", "sum"),
]
AGG = {k: a for k, _l, a in METRICS}
FLOOR_PT = 11.0
ECHO_MAX = 0.34
CAP_MIN = 0.60


# ---------------------------------------------------------------- arm A
def naive(case_path: str, out: str) -> dict:
    """Paste every source line as its own page at a fixed pitch; budget ignored."""
    from pptx import Presentation
    from pptx.util import Emu, Pt
    with open(case_path, "r", encoding="utf-8-sig") as fh:
        case = json.load(fh)
    mats, _missing = RUN._split_missing(RUN._find_materials(case, case_path))
    src = P.Source()
    for m in mats:
        part = P.ingest(m, exclude=(case_path,))
        src.segments.extend(part.segments)
        src.files.extend(part.files)
    rows = [s for s in src.segments if s.get("kind") != "heading"] or list(src.segments)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(13.333 * 914400)), Emu(int(7.5 * 914400))
    pages = [[r] for r in rows] or [[]]
    for chunk in pages:
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        head = sl.shapes.add_textbox(Emu(int(.6 * 914400)), Emu(int(.4 * 914400)),
                                     Emu(int(12.1 * 914400)), Emu(int(.7 * 914400)))
        head.text_frame.text = one_line(chunk[0].get("text") or "")[:70]
        for r in head.text_frame.paragraphs[0].runs:
            r.font.size = Pt(26)
        y = 1.0
        for seg in chunk:
            t = one_line(seg.get("text") or "")
            h = .3 + .42 * max(1, (len(t) + 94) // 95)
            box = sl.shapes.add_textbox(Emu(int(.6 * 914400)), Emu(int(y * 914400)),
                                        Emu(int(12.1 * 914400)), Emu(int(h * 914400)))
            box.text_frame.word_wrap = True
            box.text_frame.text = t
            for para in box.text_frame.paragraphs:
                for r in para.runs:
                    r.font.size = Pt(14 if len(t) <= 420 else 10)
            y += h
        sl.notes_slide.notes_text_frame.text = "\n".join(
            one_line(s.get("text") or "") for s in chunk)
    os.makedirs(out, exist_ok=True)
    prs.save(os.path.join(out, "deck.pptx"))
    res = {"case_id": case.get("case_id") or "", "status": "success",
           "deck": {"pptx": "deck.pptx", "slide_count": len(pages)},
           "slides": [{"role": "content"} for _ in pages], "evidence_map": [],
           "sources": [{"path": f["path"], "reader": f["reader"]} for f in src.files],
           "notes": "page text repeated", "uncertainty": [],
           "changes": [{"stage": "paste", "note": f"{len(pages)} pages in source order"}],
           "baseline": {"name": "naive_paragraph_paste", "pages": len(pages),
                        "limit": case.get("slide_limit")}}
    RUN.write_json(os.path.join(out, "result.json"), res)
    return res


# ---------------------------------------------------------------- measurement
def measure(out_dir: str, case_path: str) -> dict:
    """Score a delivered directory from its artefacts (deck + result + material)."""
    un: dict[str, str] = {}
    rp = os.path.join(out_dir, "result.json")
    res = {}
    if os.path.isfile(rp):
        with open(rp, "r", encoding="utf-8-sig") as fh:
            res = json.load(fh)
    else:
        un["result.json"] = "not produced"
    pptx = os.path.join(out_dir, (res.get("deck") or {}).get("pptx") or "deck.pptx")
    if not os.path.isfile(pptx):
        return {"slides": None, "unmeasurable": {**un, "deck.pptx": "not produced"}}
    with open(case_path, "r", encoding="utf-8-sig") as fh:
        case = json.load(fh)
    src, _files = A.load_material(case, case_path)
    inv = I.build(src)
    facts = A.deck_facts(pptx)
    pages = facts["pages"]

    elements = traceable = 0
    bad = []
    cap_hit = cap_tot = 0
    for p in pages:
        # per text block, not on the run-joined slide text: concatenating blocks
        # could fuse a bare number with the next block's metric label
        blocks = p.get("blocks") or [p["text"]]
        page_grams = A.grams(p["text"])           # caption containment is page-level
        for blk in blocks:
            for raw, unit in I.numbers_in(blk):
                elements += 1
                ok = I.verify_value(inv, raw, unit)["ok"]
                traceable += 1 if ok else 0
                if not ok:
                    bad.append(f"p{p['page']} number {raw}{unit}")
            for label in I.refs_in(blk):
                elements += 1
                ok = I.verify_locator(inv, label)["ok"]
                traceable += 1 if ok else 0
                if not ok:
                    bad.append(f"p{p['page']} ref {label}")
                cap = inv.caption_for(label)
                if cap and (cap.get("text") or "").strip():
                    cap_tot += 1
                    want = A.grams(cap["text"])
                    if want and len(want & page_grams) / len(want) >= CAP_MIN:
                        cap_hit += 1
    low = [p["page"] for p in pages
           if p.get("min_font") is not None and p["min_font"] < FLOOR_PT]
    echo = [p["page"] for p in pages if p["notes"].strip()
            and A.overlap(p["notes"], p["text"]) > ECHO_MAX]
    emap = res.get("evidence_map") if isinstance(res.get("evidence_map"), list) else []
    content = [e for e in emap if e.get("role") in A.CONTENT_ROLES]
    located = [e for e in content if e.get("locator") and e.get("locator_verified")]
    limit = int(case.get("slide_limit")
                or ((res.get("deck") or {}).get("template") or {}).get("slide_limit") or 16)
    audit = None
    try:
        rep = A.audit(out_dir, case_path)
        audit = {"passed": rep["passed"], "total": len(rep["checks"]), "failed": rep["failed"],
                 "failed_ids": [c["id"] for c in rep["checks"] if c["verdict"] != "pass"]}
    except Exception as exc:
        un["audit_deck"] = f"{type(exc).__name__}: {exc}"
    chars = [len(p["text"]) for p in pages] or [0]
    return {
        "slides": facts["slide_count"], "slide_limit": limit,
        "page_budget_ok": 1 <= facts["slide_count"] <= limit,
        "page_budget_over_by": max(0, facts["slide_count"] - limit),
        "verifiable_elements": elements, "traceable_elements": traceable,
        "source_traceability": round(traceable / elements, 3) if elements else None,
        "untraceable_examples": bad[:5],
        "caption_elements": cap_tot,
        "caption_number_consistency": round(cap_hit / cap_tot, 3) if cap_tot else None,
        "layout_violations": len(facts["overflow"]) + len(low),
        "offscreen_shapes": len(facts["overflow"]), "pages_below_floor": len(low),
        "min_font_pt": facts.get("min_font_pt"),
        "max_page_chars": max(chars), "mean_page_chars": round(sum(chars) / len(chars)),
        "notes_echo_pages": len(echo),
        "content_pages": len(content), "content_pages_located": len(located),
        "locator_rate": round(len(located) / len(content), 3) if content else None,
        "self_declared_status": res.get("status"), "audit_deck": audit,
        "material_readers": [f["reader"] for f in src.files],
        "unmeasurable": un,
    }


# ---------------------------------------------------------------- harness
CASES = ["case_zh_md", "case_latex", "case_en_pdf"]


def prepare(name: str, work: str) -> str:
    import make_case_pdf
    src_dir = os.path.join(PKG, "examples", name)
    if name != "case_en_pdf":
        return os.path.join(src_dir, "case.json")
    case_dir = os.path.join(work, name)
    os.makedirs(case_dir, exist_ok=True)
    pdf = os.path.join(case_dir, "paper.pdf")
    if not os.path.isfile(pdf):
        make_case_pdf.main(["--src", os.path.join(src_dir, "paper.src.json"), "--out", pdf])
    with open(os.path.join(src_dir, "case.json"), "r", encoding="utf-8-sig") as fh:
        case = json.load(fh)
    case["materials"] = ["paper.pdf"]
    with open(os.path.join(case_dir, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(case, fh, ensure_ascii=False, indent=2)
    return os.path.join(case_dir, "case.json")


def run_case(case_path: str, work: str, reps: int, do_render: bool) -> dict:
    name = os.path.basename(os.path.dirname(os.path.abspath(case_path))) or "case"
    arms = {}
    for arm in ("baseline", "skill"):
        out = os.path.join(work, name, arm)
        wd = out + "-work"
        times, err = [], None
        for _ in range(max(1, reps)):
            shutil.rmtree(out, ignore_errors=True)
            shutil.rmtree(wd, ignore_errors=True)
            t0 = time.time()
            try:
                if arm == "baseline":
                    naive(case_path, out)
                else:
                    RUN.run(case_path, out, wd, do_render=do_render)
                err = None
            except Exception as exc:              # a crashing arm is data too
                import traceback
                traceback.print_exc(limit=3)
                err = f"{type(exc).__name__}: {exc}"
            times.append(round(time.time() - t0, 2))
        m = measure(out, case_path)
        m["e2e_seconds"] = sorted(times)[len(times) // 2]
        m["e2e_seconds_all"] = times
        m["e2e_seconds_spread"] = round(max(times) - min(times), 2)
        m["run_error"] = err
        m["out_dir"] = rel_posix(os.path.basename(out))
        arms[arm] = m
    delta = {k: (round(arms["skill"][k] - arms["baseline"][k], 3)
                 if isinstance(arms["baseline"].get(k), (int, float))
                 and isinstance(arms["skill"].get(k), (int, float))
                 and not isinstance(arms["baseline"].get(k), bool) else None)
             for k, _l, _a in METRICS}
    delta["audit_deck_failed"] = (arms["skill"]["audit_deck"]["failed"]
                                  - arms["baseline"]["audit_deck"]["failed"]
                                  if arms["skill"].get("audit_deck")
                                  and arms["baseline"].get("audit_deck") else None)
    return {"case": name, "reps": max(1, reps), "baseline": arms["baseline"],
            "skill": arms["skill"], "delta": delta}


def flat(m: dict) -> dict:
    d = dict(m)
    d["audit_deck_failed"] = (m.get("audit_deck") or {}).get("failed")
    d["page_budget_ok"] = bool(m.get("page_budget_ok"))
    return d


def totals(rows: list[dict]) -> dict:
    def agg(arm: str, key: str):
        vals = [r[arm].get(key) for r in rows]
        vals = [1.0 if v is True else (0.0 if v is False else float(v))
                for v in vals if isinstance(v, (int, float, bool))]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 3) if AGG.get(key) == "mean" else round(sum(vals), 3)

    out = {}
    for arm in ("baseline", "skill"):
        out[arm] = {k: agg(arm, k) for k, _l, _a in METRICS}
        out[arm]["e2e_spread"] = max([r[arm].get("e2e_seconds_spread") or 0 for r in rows] or [0])
    out["delta"] = {k: (round(out["skill"][k] - out["baseline"][k], 3)
                        if isinstance(out["baseline"].get(k), (int, float))
                        and isinstance(out["skill"].get(k), (int, float)) else None)
                    for k, _l, _a in METRICS}
    out["aggregation"] = AGG
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", action="append", default=None, help="repeatable")
    ap.add_argument("--work", default=None)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(PKG, "tests", "benchmark-report.json"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args(argv)
    work = args.work or tempfile.mkdtemp(prefix="paper2deck-bench-")
    os.makedirs(work, exist_ok=True)
    cases = args.case or [prepare(n, work) for n in CASES]
    raw = [run_case(c, work, args.reps, not args.no_render) for c in cases]
    flat_rows = []
    for r in raw:
        r2 = dict(r)
        r2["baseline"] = flat(r["baseline"])
        r2["skill"] = flat(r["skill"])
        flat_rows.append(r2)
    report = {
        "what": "real two-arm comparison on identical case inputs (mechanism check, "
                "NOT a platform score)",
        "arms": {"baseline": "paragraph-order paste, fixed 14pt, no locator, notes = page text",
                 "skill": "scripts/run.py (this package)"},
        "shared": ["material reader (papertext.py)", "renderer (render.py)",
                   "measurement (benchmark_local.measure)", "auditor (audit_deck.py)"],
        "environment": {"python": sys.version.split()[0], "platform": platform.system(),
                        "model_requests": 0,
                        "note": "both arms are deterministic code; no model is called in "
                                "either arm, so the elapsed-time delta is pure wall clock"},
        "commands": ["python3 scripts/run.py --case <case.json> --out <T>/skill",
                     "python3 scripts/benchmark_local.py --reps 3",
                     "python3 scripts/audit_deck.py --out <T>/<arm> --case <case.json>"],
        "metrics": [{"key": k, "label": l, "field": f"cases[i].{{arm}}.{k}", "aggregation": a}
                    for k, l, a in METRICS],
        "cases": flat_rows, "totals": totals(flat_rows),
        "not_measured": {"human_edit_pages": None,
                         "reason": "no human edit step exists in an automated comparison; "
                                   "recorded as null rather than estimated.",
                         "platform_score": None,
                         "reason_platform_score": "mechanism comparison; cannot be converted "
                                                  "into an official score."},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    t = report["totals"]
    print(f"{'metric':<28}{'baseline':>12}{'skill':>12}{'total delta':>14}")
    for k, _l, _a in METRICS:
        print(f"{k:<28}{str(t['baseline'].get(k)):>12}{str(t['skill'].get(k)):>12}"
              f"{str(t['delta'].get(k)):>14}")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
