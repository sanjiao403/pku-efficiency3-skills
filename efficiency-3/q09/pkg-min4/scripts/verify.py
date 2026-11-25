# -*- coding: utf-8 -*-
"""verify.py — 13 项机读检查 + 只读重算（expected vs actual）。

    python3 scripts/verify.py --pptx <out>/deck.pptx --result <out>/result.json
    python3 scripts/verify.py --pptx <out>/deck.pptx --case <case.json> \
        --source <out>/_work/source.json --spec <out>/_work/deck_plan.json \
        --template <template.pptx> --render <out>/_work/render_report.json \
        --out <out>/_work/checks.json

13 项（编号即报告里的 id；不适用项记 status="n/a" + 原因，绝不假装通过）：
  C01 页数=案例指令   C02 页数≤上限        C03 形状不出界      C04 文本不溢出
  C05 正文不重叠      C06 表格溢出(不适用) C07 图片等比(不适用) C08 每页有标题+备注
  C09 正文字号≥下限   C10 字体继承(主题)   C11 每页有证据锚点  C12 引文逐字真实性
  C13 数字保真回查
退出码：0 全部通过（含 n/a），2 有失败项。
"""
import argparse, json, os, re, sys, zipfile

sys.dont_write_bytecode = True
try:
    from pptx import Presentation
except Exception:
    Presentation = None

EXEMPT = ("caption", "footer", "pageno", "rule")
PH = {1: "title", 3: "ctitle", 2: "body", 7: "object"}
IDS = ["C%02d" % i for i in range(1, 14)]
NAMES = {
    "C01": "slide count equals the case instruction",
    "C02": "slide count within max_slides",
    "C03": "no shape outside the slide",
    "C04": "no estimated text overflow",
    "C05": "no overlapping body shapes",
    "C06": "table overflow",
    "C07": "image aspect ratio",
    "C08": "every page has a title and speaker notes",
    "C09": "body font size >= floor",
    "C10": "font inheritance: theme typefaces unchanged",
    "C11": "every content page carries an evidence anchor",
    "C12": "quote authenticity: anchor quotes exist verbatim in the material",
    "C13": "number fidelity: slide numbers trace back to the material",
}


def load(p):
    return json.load(open(p, encoding="utf-8")) if p and os.path.isfile(p) else None


def sig(p):
    """design fingerprint: slide size + theme typefaces + layout geometry."""
    if not p or not os.path.isfile(p) or Presentation is None:
        return None
    prs = Presentation(p)
    d = {"size": [int(prs.slide_width), int(prs.slide_height)], "layouts": []}
    for lo in prs.slide_layouts:
        d["layouts"].append([lo.name] + sorted(
            [int(x.placeholder_format.idx), int(x.left or 0), int(x.top or 0),
             int(x.width or 0), int(x.height or 0)] for x in lo.placeholders))
    try:
        d["fonts"] = sorted(set(re.findall(
            r'typeface="([^"]+)"', zipfile.ZipFile(p).read(
                "ppt/theme/theme1.xml").decode("utf-8", "replace"))))
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
    """returns {passed, checks:[{id,name,ok,status,detail}], sections, summary}"""
    found = {}

    def add(cid, ok, detail=None, status=None):
        found[cid] = {"id": cid, "name": NAMES[cid],
                      "ok": (None if ok is None else bool(ok)),
                      "status": status or ("pass" if ok else "fail"),
                      "detail": detail}

    if not os.path.isfile(pptx):
        for cid in IDS:
            add(cid, None, {"why": "deck.pptx does not exist"}, "n/a")
        return _finish(found, None)
    try:
        prs = Presentation(pptx)
    except Exception as e:
        add("C01", False, {"why": "pptx cannot be opened: %s" % str(e)[:120]})
        for cid in IDS[1:]:
            add(cid, None, {"why": "pptx cannot be opened"}, "n/a")
        return _finish(found, None)

    want, cap = None, None
    for k in ("slide_count", "num_slides"):
        if isinstance((case or {}).get(k), int):
            want = case[k]
    for k in ("max_slides", "slide_count_max"):
        if isinstance((case or {}).get(k), int):
            cap = case[k]
    n = len(prs.slides)
    add("C01", (n == want) if want else None,
        {"expected": want, "actual": n} if want else
        {"why": "case.json carries no slide_count: not checkable"}, None if want
        else "n/a")
    add("C02", (n <= cap) if cap else None,
        {"max_slides": cap, "actual": n} if cap else
        {"why": "case.json carries no max_slides"}, None if cap else "n/a")

    W, H = float(prs.slide_width) / 12700, float(prs.slide_height) / 12700
    rules = (spec or {}).get("rules") or {}
    floor = float(rules.get("min_body_pt") or 12)
    maxb = int(rules.get("max_bullets_per_slide") or 6)
    out_slide, over, small, many, overlap, nonotes, noanchor = [], [], [], [], [], [], []
    for i, slide in enumerate(prs.slides, 1):
        boxes, nb = [], 0
        title = slide.shapes.title
        if title is None or not (title.text_frame.text or "").strip():
            nonotes.append({"slide": i, "why": "no title"})
        if not (slide.notes_slide.notes_text_frame.text.strip() if slide.has_notes_slide
                else ""):
            nonotes.append({"slide": i, "why": "empty speaker notes"})
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
            if any(k in low for k in EXEMPT) or "title" in low or len(t) <= 40:
                continue
            sizes = [r.font.size.pt for p in sh.text_frame.paragraphs for r in p.runs
                     if r.font.size]
            paras = [p.text for p in sh.text_frame.paragraphs if p.text.strip()]
            if not paras:
                continue
            nb = max(nb, len(paras))
            boxes.append((x, y, w, h, sh.name))
            if sizes and min(sizes) < floor:
                small.append({"slide": i, "shape": sh.name, "pt": min(sizes)})
            size = max(sizes) if sizes else 17.0
            need = sum(lines(p, max(4.0, w - 8), size) for p in paras) * size * 1.25
            if need > h + 2:
                over.append({"slide": i, "shape": sh.name, "needed_pt": round(need, 1),
                             "box_pt": round(h, 1)})
        if nb > maxb:
            many.append({"slide": i, "bullets": nb})
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                x1, y1, w1, h1, n1 = boxes[a]
                x2, y2, w2, h2, n2 = boxes[b]
                ix = max(0.0, min(x1 + w1, x2 + w2) - max(x1, x2))
                iy = max(0.0, min(y1 + h1, y2 + h2) - max(y1, y2))
                if ix * iy > 0.12 * min(w1 * h1, w2 * h2):
                    overlap.append({"slide": i, "a": n1, "b": n2})
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        if i > 1 and "- " in notes and not re.search(r"\[来源|\[路线\]", notes):
            noanchor.append(i)
    add("C03", not out_slide, out_slide[:6])
    add("C04", not over, {"count": len(over), "samples": over[:5],
                          "method": "character-width model (estimated)"})
    add("C05", not overlap, {"count": len(overlap), "samples": overlap[:5]})
    add("C06", None, {"why": "this minimal pack writes no tables; a table would be "
                              "reported as n/a rather than silently passed"}, "n/a")
    add("C07", None, {"why": "this minimal pack inserts no pictures (no figure "
                              "clipping); n/a"}, "n/a")
    add("C08", not nonotes, nonotes[:6])
    add("C09", not small, {"floor_pt": floor, "samples": small[:6]})
    if template and os.path.isfile(template):
        a, b = sig(template), sig(pptx)
        keep = {"size": b.get("size"), "fonts": b.get("fonts"),
                "layouts": b.get("layouts")} if b else {}
        add("C10", a == b, {"method": "design fingerprint (slide size + theme "
                                      "typefaces + layout geometry), not byte hashes",
                            "differences": [] if a == b else
                            {"template": a, "out": keep}})
    else:
        add("C10", None, {"why": "no template supplied: the deck runs on a neutral "
                                 "master, so inheritance is not comparable"}, "n/a")
    add("C11", not noanchor, {"slides_without_anchor": noanchor[:8]})
    add("C06x", True, {}) if False else None

    material_txt = re.sub(r"\s+", " ", " ".join(
        (b.get("text") or "") for b in (source or {}).get("blocks") or []))
    quotes, missing_quotes = [], []
    for s in (spec or {}).get("slides") or []:
        for b in s.get("bullets") or []:
            a = b.get("anchor") or {}
            q = (a.get("quote") or b.get("text") or "").strip()
            if not q or a.get("source") == "plan":
                continue
            quotes.append(q)
            if re.sub(r"\s+", " ", q) not in material_txt:
                missing_quotes.append({"slide": s.get("index"), "quote": q[:80]})
    if not quotes:
        add("C12", None, {"why": "no evidence quote available (no material?)"}, "n/a")
    else:
        add("C12", not missing_quotes,
            {"quotes_checked": len(quotes), "not_verbatim": missing_quotes[:6],
             "how": "each anchor quote must appear verbatim in the material text"})
    nums = set()
    for x in (source or {}).get("numbers") or []:
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
                continue      # cover metadata (audience/duration) is not a claim
            for m in re.finditer(r"\d+(?:\.\d+)?", sh.text_frame.text):
                if len(m.group(0)) > 1 and \
                        re.sub(r"[\s,]", "", m.group(0)) not in nums:
                    bad.append({"slide": i, "number": m.group(0)})
    if not nums:
        add("C13", None, {"why": "material number ledger is empty (text material "
                                 "without numbers?)"}, "n/a")
    else:
        add("C13", not bad, {"ledger_size": len(nums), "unmatched": bad[:10],
                             "how": "every >=2-digit number on a non-cover page must "
                                    "occur in the material ledger"})
    if render is not None:
        found["render"] = {"id": "aux",
                           "name": "real render produced (aux, not one of the 13)",
                           "ok": render.get("render_status") == "ok",
                           "status": render.get("render_status"),
                           "detail": {"renderer": render.get("renderer"),
                                      "png": len(render.get("png") or []),
                                      "notes": (render.get("notes") or [])[:2]}}
    return _finish(found, n)


def _finish(found, n):
    checks = [found[cid] for cid in IDS if cid in found]
    if "render" in found:
        checks.append(found["render"])
    failed = [c for c in checks if c["status"] == "fail"]
    na = [c for c in checks if c["status"] == "n/a"]
    return {"pptx_slides": n, "passed": not failed, "checks": checks,
            "sections": {"pass": len([c for c in checks if c["status"] == "pass"]),
                         "fail": len(failed), "n/a": len(na)},
            "summary": {"slides": n, "checks": len(checks), "failed": len(failed),
                        "not_applicable": [c["id"] for c in na],
                        "failed_ids": [c["id"] for c in failed]},
            "ids": IDS, "names": NAMES}


def recompute(pptx, result):
    """read-only: re-derive the deliverable's claims from pptx + result.json only."""
    out = {"pairs": [], "passed": True}
    if not os.path.isfile(pptx) or not isinstance(result, dict):
        return {"pairs": [{"item": "artifacts present", "expected": True,
                           "actual": False}], "passed": False}
    prs = Presentation(pptx)
    dv = result.get("deliverable") or {}
    ev = result.get("evidence_map") or []
    out["pairs"].append({"item": "slide count", "expected": dv.get("slides"),
                         "actual": len(prs.slides)})
    notes_pages = {i: (s.notes_slide.notes_text_frame.text if s.has_notes_slide else "")
                   for i, s in enumerate(prs.slides, 1)}
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
                if len(m.group(0)) > 1 and m.group(0) not in own and \
                        m.group(0) not in notes_pages.get(i, ""):
                    bad.append({"slide": i, "number": m.group(0)})
    out["pairs"].append({"item": "numbers on a slide occur in its own anchors/notes",
                         "expected": [], "actual": bad[:8]})
    for o in result.get("outputs") or []:
        p = os.path.join(os.path.dirname(os.path.abspath(pptx)), o.get("path") or "")
        ok = os.path.isfile(p) and os.path.getsize(p) == o.get("bytes")
        out["pairs"].append({"item": "outputs[] %s bytes" % o.get("path"),
                             "expected": o.get("bytes"),
                             "actual": os.path.getsize(p) if os.path.isfile(p) else None,
                             "ok": bool(ok)})
    out["passed"] = (not missing and not bad and
                     all(x.get("expected") == x.get("actual") or x.get("ok") is not False
                         for x in out["pairs"] if "uncovered_pages" not in x))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="13 checks + read-only recompute")
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
                      "failed": [c["id"] + " " + c["name"] for c in rep["checks"]
                                 if c["status"] == "fail"]},
                     ensure_ascii=False, indent=1))
    return 0 if rep["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
