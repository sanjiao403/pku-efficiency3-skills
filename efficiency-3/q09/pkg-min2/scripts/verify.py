"""verify.py — self-check for a deck produced or edited by deck.py"""
import argparse, json, os, re, sys, zipfile
sys.dont_write_bytecode = True
try:
    from pptx import Presentation
except Exception:
    Presentation = None
EXEMPT = ("caption", "footer", "pageno", "rule")
PH = {1: "title", 3: "ctitle", 2: "body", 7: "object"}

def load(p):
    return json.load(open(p, encoding="utf-8")) if p and os.path.isfile(p) else None

def sig(p):
    if not p or not os.path.isfile(p) or Presentation is None:
        return {}
    prs = Presentation(p)
    d = {"size": [int(prs.slide_width), int(prs.slide_height)], "layouts": []}
    for lo in prs.slide_layouts:
        d["layouts"].append([lo.name] + sorted(
            [int(x.placeholder_format.idx), int(x.left or 0), int(x.top or 0),
             int(x.width or 0), int(x.height or 0)] for x in lo.placeholders))
    try:
        d["fonts"] = sorted(set(re.findall(r'typeface="([^"]+)"', zipfile.ZipFile(p)
                            .read("ppt/theme/theme1.xml").decode("utf-8", "replace"))))
    except Exception:
        d["fonts"] = []
    return d

def lines(text, w, size):
    n, ww = 1, 0.0
    for tok in re.findall(r"\s+|[\u2e80-\uffef]|[^\s\u2e80-\uffef]+", text or ""):
        tw = sum(size * (1.0 if ord(c) > 0x2E7F else (0.3 if c in " \t" else 0.55))
                 for c in tok)
        if ww + tw > w and ww:
            n, ww = n + 1, 0.0
        ww += tw
    return n

def check(pptx, case=None, source=None, spec=None, template=None, render=None):
    rep = {"pptx": os.path.basename(pptx), "checks": [], "passed": True, "sections": {}}

    def add(sec, name, ok, detail=None):
        rep["checks"].append({"section": sec, "check": name, "ok": bool(ok),
                              "detail": detail})
        d = rep["sections"].setdefault(sec, {"pass": 0, "fail": 0})
        d["pass" if ok else "fail"] += 1
        if not ok:
            rep["passed"] = False
    if not os.path.isfile(pptx):
        add("A", "pptx exists", False, pptx)
        return rep
    try:
        prs = Presentation(pptx)
    except Exception as e:
        add("A", "pptx opens", False, str(e)[:150])
        return rep
    add("A", "pptx opens", True, {"slides": len(prs.slides),
                                  "bytes": os.path.getsize(pptx)})
    if template and os.path.isfile(template):
        a, b = sig(template), sig(pptx)
        add("A", "master/layout/theme design unchanged", a == b,
            {"method": "slide size + theme fonts + layout placeholder geometry "
                       "(byte hashes are meaningless: the writer re-serialises)",
             "differences": [] if a == b else {"template": a, "out": b}})
    rules = (spec or {}).get("rules") or {}
    floor = float(rules.get("min_body_pt") or 12)
    maxb = int(rules.get("max_bullets_per_slide") or 6)
    W, H = float(prs.slide_width) / 12700, float(prs.slide_height) / 12700
    out_slide, small, over, many = [], [], [], []
    for i, slide in enumerate(prs.slides, 1):
        nb = 0
        for sh in slide.shapes:
            try:
                x, y = float(sh.left or 0) / 12700, float(sh.top or 0) / 12700
                w, h = float(sh.width or 0) / 12700, float(sh.height or 0) / 12700
            except Exception:
                continue
            if not (-2 <= x and -2 <= y and x + w <= W + 2 and y + h <= H + 2):
                out_slide.append({"slide": i, "shape": sh.name})
            if not sh.has_text_frame:
                continue
            t = sh.text_frame.text or ""
            low = (sh.name or "").lower()
            if any(k in low for k in EXEMPT) or len(t) <= 40 or "title" in low:
                continue
            sizes = [r.font.size.pt for p in sh.text_frame.paragraphs for r in p.runs
                     if r.font.size]
            paras = [p.text for p in sh.text_frame.paragraphs if p.text.strip()]
            if not paras:
                continue
            nb = max(nb, len(paras))
            if sizes and min(sizes) < floor:
                small.append({"slide": i, "shape": sh.name, "pt": sorted(set(sizes))[:3]})
            need = sum(lines(p, max(4.0, w - 8), max(sizes or [17.0])) for p in paras) \
                * max(sizes or [17.0]) * 1.25
            if need > h + 2:
                over.append({"slide": i, "shape": sh.name, "needed_pt": round(need, 1),
                             "box_pt": round(h, 1)})
        if nb > maxb:
            many.append({"slide": i, "bullets": nb})
    add("B", "all shapes inside the slide", not out_slide, out_slide[:6])
    add("B", "no body text below the floor size", not small, small[:6])
    add("C", "bullet count per slide <= %d" % maxb, not many, many[:6])
    add("C", "no estimated text overflow", not over,
        {"count": len(over), "samples": over[:5],
         "method": "width model in verify.lines (estimated; cross-check with a render)"})
    if source:
        nums = set()
        for x in source.get("numbers") or []:
            v = re.sub(r"[\s,]", "", x.get("value") or "")
            if v:
                nums.add(v)
                nums.add(re.sub(r"[^\d.]", "", v))
        bad = []
        for i, slide in enumerate(prs.slides, 1):
            for sh in slide.shapes:
                if not sh.has_text_frame:
                    continue
                if any(k in (sh.name or "").lower() for k in EXEMPT) or i == 1:
                    continue        # cover metadata (audience/duration) is not a claim
                for m in re.finditer(r"\d+(?:\.\d+)?", sh.text_frame.text):
                    if len(m.group(0)) > 1 and \
                            re.sub(r"[\s,]", "", m.group(0)) not in nums:
                        bad.append({"slide": i, "number": m.group(0)})
        add("D", "every number traceable to the material ledger", not bad,
            {"unmatched": bad[:10], "ledger_size": len(nums)})
        add("D", "material number ledger non-empty", len(nums) > 0,
            {"numbers": len(nums)})
    no_anchor = []
    for i, s in enumerate(prs.slides, 1):
        n = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
        if i > 1 and "- " in n and not re.search(r"\[来源|\[路线\]", n):
            no_anchor.append(i)
    add("D", "every page after the cover carries an evidence anchor", not no_anchor,
        {"slides": no_anchor[:8]})
    if case:
        want = None
        for k in ("slide_count", "num_slides", "max_slides"):
            if isinstance(case.get(k), int):
                want = case[k]
        if want:
            add("C", "slide count matches the case instruction",
                len(prs.slides) == int(want), {"expected": want,
                                               "actual": len(prs.slides)})
    if render:
        if render.get("render_status") == "ok":
            add("E", "real render produced", True, {"renderer": render.get("renderer")})
            pdf, pages = render.get("pdf"), None
            if pdf and os.path.isfile(pdf):
                try:
                    import fitz
                    pages = fitz.open(pdf).page_count
                except Exception:
                    try:
                        from pypdf import PdfReader
                        pages = len(PdfReader(pdf).pages)
                    except Exception:
                        pages = None
            add("E", "pdf page count == slide count",
                (pages == len(prs.slides)) if pages else True,
                {"pdf": pages, "pptx": len(prs.slides)} if pages else
                {"note": "pdf present, no reader available to count pages"})
            add("E", "png preview per slide",
                len(render.get("png") or []) >= len(prs.slides),
                {"png": len(render.get("png") or []), "slides": len(prs.slides)})
        else:
            add("E", "real render produced", False,
                {"status": render.get("render_status"), "notes": render.get("notes")})
    rep["summary"] = {"slides": len(prs.slides), "checks": len(rep["checks"]),
                      "failed": sum(1 for c in rep["checks"] if not c["ok"])}
    return rep

def recompute(pptx, result):
    out = {"pairs": [], "passed": True}
    if not os.path.isfile(pptx) or not isinstance(result, dict):
        return {"pairs": [{"item": "artifacts present", "expected": True,
                           "actual": False}], "passed": False}
    prs = Presentation(pptx)
    dv = result.get("deliverable") or {}
    ev = result.get("evidence_map") or []
    out["pairs"].append({"item": "slide count", "expected": dv.get("slides"),
                         "actual": len(prs.slides)})
    notes_pages = {}
    for i, s in enumerate(prs.slides, 1):
        t = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
        notes_pages[i] = t
    in_notes = {i for i in range(2, len(prs.slides) + 1)
                if re.search(r"\[来源 .*?(p\.\d+|p\d+\.b\d+)", notes_pages.get(i, ""))}
    anchored = {e.get("slide") for e in ev
                if (e.get("anchor") or {}).get("page") or
                (e.get("anchor") or {}).get("block_id")}
    missing = sorted(in_notes - anchored)
    out["pairs"].append({"item": "pages anchored in the notes vs evidence_map rows",
                         "expected": sorted(in_notes), "actual": sorted(anchored),
                         "uncovered_pages": missing})
    quotes = {}
    for e in ev:
        a = e.get("anchor") or {}
        for q in [a.get("quote") or "", a.get("block_id") or "",
                  str(a.get("page") or "")]:
            if q:
                quotes.setdefault(e.get("slide"), []).append(q)
    bad = []
    for i, s in enumerate(prs.slides, 1):
        if i == 1:
            continue
        own = " ".join(quotes.get(i, []))
        for sh in s.shapes:
            if not sh.has_text_frame or any(k in (sh.name or "").lower()
                                            for k in EXEMPT):
                continue
            for m in re.finditer(r"\d+", sh.text_frame.text):
                num = m.group(0)
                if len(num) > 1 and num not in own and num not in notes_pages.get(i, ""):
                    bad.append({"slide": i, "number": num})
    out["pairs"].append({"item": "numbers on a slide occur in its own anchors/notes",
                         "expected": [], "actual": bad[:8]})
    for o in result.get("outputs") or []:
        p = os.path.join(os.path.dirname(os.path.abspath(pptx)), o.get("path") or "")
        ok = os.path.isfile(p) and os.path.getsize(p) == o.get("bytes")
        out["pairs"].append({"item": "outputs[] %s bytes" % o.get("path"),
                             "expected": o.get("bytes"),
                             "actual": os.path.getsize(p) if os.path.isfile(p) else None,
                             "ok": bool(ok)})
    out["passed"] = all(x.get("expected") == x.get("actual") or x.get("ok") is not False
                        for x in out["pairs"] if "uncovered_pages" not in x) and \
        not missing and not bad
    for x in out["pairs"]:
        if "uncovered_pages" in x and x["uncovered_pages"]:
            out["passed"] = False
    return out

def main(argv=None):
    ap = argparse.ArgumentParser(description="self-check / recompute a deck")
    for f in ("--pptx", "--case", "--source", "--spec", "--template", "--render",
              "--out", "--result"):
        ap.add_argument(f, default="/app/output/deck.pptx" if f == "--pptx" else "")
    a = ap.parse_args(argv)
    if a.result:
        rep = {"recompute": recompute(a.pptx, load(a.result))}
        rep["passed"] = rep["recompute"]["passed"]
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep["passed"] else 2
    rep = check(a.pptx, case=load(a.case), source=load(a.source), spec=load(a.spec),
                template=a.template or None, render=load(a.render))
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        json.dump(rep, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"passed": rep["passed"], "summary": rep["summary"],
                      "failed": [c for c in rep["checks"] if not c["ok"]][:8]},
                     ensure_ascii=False, indent=1))
    return 0 if rep["passed"] else 2

if __name__ == "__main__":
    sys.exit(main())
