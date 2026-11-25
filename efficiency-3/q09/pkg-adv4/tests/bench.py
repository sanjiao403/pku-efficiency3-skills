# -*- coding: utf-8 -*-
"""bench.py — the fair baseline-vs-skill measurement, reproducible by anyone.

    python3 tests/bench.py --report benchmark.json

Both arms are built from the *same* example input (same material, same
slide_count, same machine, one run each) and measured with the *same* functions
from the produced .pptx, so the delta is not a claim, it is arithmetic:

  baseline  minimal honest implementation: split the material into N equal
            character chunks and paste one chunk per page (no ledger, no anchors,
            no footer, no notes, no verification)
  skill     scripts/deck.py on the same case
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
EX = os.path.join(PKG, "examples")
PY = sys.executable


def material_text(p):
    return re.sub(r"\s+", " ", open(p, encoding="utf-8", errors="replace").read()).strip()


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", text) if len(s.strip()) > 20]


def baseline_deck(material, out, n_slides):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = 12192000, 6858000
    txt = material_text(material)
    size = max(1, len(txt) // n_slides)
    for i in range(n_slides):
        sl = prs.slides.add_slide(prs.slide_layouts[5] if len(prs.slide_layouts) > 5
                                  else prs.slide_layouts[0])
        box = sl.shapes.add_textbox(Inches(0.5), Inches(0.8), Inches(12.3),
                                    Inches(4.6))
        box.name = "BodyText"
        for j, chunk in enumerate([txt[i * size:(i + 1) * size]]):
            para = box.text_frame.paragraphs[0] if j == 0 else \
                box.text_frame.add_paragraph()
            para.text = chunk
            for r in para.runs:
                r.font.size = Pt(14)
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, "deck.pptx")
    prs.save(p)
    return p


def measure(pptx, out, source=None, case=None, template=None, render=None):
    sys.path.insert(0, os.path.join(PKG, "scripts"))
    import verify as vm
    from pptx import Presentation
    if isinstance(source, str):
        source = json.load(open(source, encoding="utf-8")) if os.path.isfile(source) \
            else None
    prs = Presentation(pptx)
    notes = {i: (s.notes_slide.notes_text_frame.text if s.has_notes_slide else "")
             for i, s in enumerate(prs.slides, 1)}
    feet = {}
    for i, s in enumerate(prs.slides, 1):
        feet[i] = any("footer" in (sh.name or "").lower() and
                      "来源" in (sh.text_frame.text if sh.has_text_frame else "")
                      for sh in s.shapes)
    mat = vm.material_index(source) if source else {"norm": ""}
    whole = [s for s in sentences(mat.get("norm", ""))]
    content = [i for i in range(2, len(prs.slides) + 1)]
    anchored = [i for i in content if "[来源" in notes.get(i, "")]
    footed = [i for i in content if feet.get(i)]
    integrity = []
    for i in content:
        for b in vm.page_anchors(notes.get(i, ""))["bullets"]:
            t = vm.norm(b["text"])
            integrity.append(bool(t) and (t in mat.get("norm", "") or
                                          any(t and t in s for s in whole)))
    c = vm.check(pptx, case=case, source=source, template=template, render=render,
                 edit=None, template_role="template")
    return {"slides": len(prs.slides),
            "slides_match_instruction": (len(prs.slides) == int(case["slide_count"]))
            if case and case.get("slide_count") else None,
            "evidence_page_coverage": round(len(anchored) / float(len(content)), 3)
            if content else 0.0,
            "citation_footer_coverage": round(len(footed) / float(len(content)), 3)
            if content else 0.0,
            "sentence_integrity": round(sum(integrity) / float(len(integrity)), 3)
            if integrity else 0.0,
            "failed_mechanical_checks": (c.get("summary") or {}).get("failed"),
            "checks_not_applicable": (c.get("summary") or {}).get("not_applicable")}


def run(args):
    p = subprocess.run([PY] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=os.path.join(PKG, "benchmark.json"))
    a = ap.parse_args()
    root = tempfile.mkdtemp(prefix="deck-bench-")
    ind = os.path.join(root, "in")
    os.makedirs(ind, exist_ok=True)
    for n in os.listdir(EX):
        shutil.copy2(os.path.join(EX, n), os.path.join(ind, n))
    case = json.load(open(os.path.join(ind, "case.example.json"), encoding="utf-8"))
    os.remove(os.path.join(ind, "case.example.json"))
    json.dump(case, open(os.path.join(ind, "case.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    material = os.path.join(ind, "paper-material.md")
    n_slides = int(case.get("slide_count") or 8)

    t0 = time.time()
    base_out = os.path.join(root, "baseline")
    bp = baseline_deck(material, base_out, n_slides)
    base_s = round(time.time() - t0, 2)

    skill_out = os.path.join(root, "skill")
    rc, log = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                   os.path.join(ind, "case.json"), "--out", skill_out])
    rf = os.path.join(skill_out, "result.json")
    r = json.load(open(rf, encoding="utf-8")) if os.path.isfile(rf) else {}
    skill_s = r.get("runtime_s")
    src = os.path.join(skill_out, "_work", "source.json")
    src = src if os.path.isfile(src) else None
    render = os.path.join(skill_out, "_work", "render_report.json")
    render = json.load(open(render, encoding="utf-8")) if os.path.isfile(render) else None

    base = measure(bp, base_out, source=src, case=case)
    skill = measure(os.path.join(skill_out, "deck.pptx"), skill_out, source=src,
                    case=case, render=render)
    delta = {k: (round(skill[k] - base[k], 3) if isinstance(skill.get(k), (int, float))
                 and isinstance(base.get(k), (int, float)) else None)
             for k in base if k in skill}
    rep = {"what": "real baseline vs Skill on the shipped example (same material, same "
                   "slide_count, same machine, one run each); both arms are measured "
                   "from their own .pptx with the same functions",
           "reproduce": "python3 tests/bench.py --report benchmark.json",
           "baseline_definition": "minimal direct implementation: split the material "
                                  "into N equal character chunks and paste one chunk "
                                  "per page; no ledger, anchors, footer, notes or "
                                  "verification (tests/bench.py: baseline_deck)",
           "baseline": dict(base, seconds=base_s),
           "skill": dict(skill, seconds=skill_s, status=r.get("status")),
           "delta": delta,
           "limitations": [
               "baseline is one honest minimal implementation, not a tuned competitor",
               "one run per path; wall-clock is host-dependent",
               "the shipped example material is synthetic text (no figures, no scanned "
               "pages)",
               "failed_mechanical_checks reuses scripts/verify.py, an estimator for "
               "overflow and a byte-level re-measurement for the export",
               "sentence_integrity only counts anchored bullets, so a deck with no "
               "anchors scores 0 by construction"],
           "workdir": "temporary (not shipped)"}
    json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:2500])
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
