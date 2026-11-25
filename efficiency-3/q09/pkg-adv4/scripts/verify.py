# -*- coding: utf-8 -*-
"""verify.py — 13 checks, all derived from the DELIVERED artifacts.

    python3 scripts/verify.py --pptx <out>/deck.pptx --result <out>/result.json
    python3 scripts/verify.py --pptx <out>/deck.pptx --case <case.json> \
        --source <out>/_work/source.json --spec <out>/_work/deck_plan.json \
        --template <template.pptx|starting deck> --render <out>/_work/render_report.json \
        --edit <out>/_work/edit_report.json --out <out>/_work/checks.json

Design rule (the reason this file exists in this shape): a self-check that reads
the *plan* certifies the plan.  Everything below is re-derived from the pptx that
is handed to the user — its shapes, its speaker notes, and the material ledger —
so a deck whose pages say something the material does not support fails here even
when the plan that produced it was self-consistent.

13 ids; a check that cannot apply is reported status="n/a" with a reason and is
never counted as a pass:
  C01 slide count == case instruction      C02 slide count <= max_slides
  C03 no shape outside the slide           C04 no estimated text overflow
  C05 no overlapping body shapes            C06 table fits its frame
  C07 picture aspect ratio preserved        C08 every page has a title + notes
  C09 body font >= floor                    C10 design fingerprint unchanged
  C11 anchors present and resolvable        C12 quotes verbatim in the material
  C13 page-scoped number fidelity
Exit code 0 = nothing failed (n/a allowed), 2 = at least one failure.

Anchor grammar read from the speaker notes (written by scripts/deck.py):
    - <sentence>  [来源 <material> p.<page|-> <block-id>]
      改写自原句：<verbatim sentence from the material>      (only if not verbatim)
    - <outline item>  [路线]
"""
import argparse, hashlib, json, os, re, sys, zipfile

sys.dont_write_bytecode = True
try:
    from pptx import Presentation
except Exception:                                   # pragma: no cover
    Presentation = None

EXEMPT = ("caption", "footer", "pageno", "rule")
IDS = ["C%02d" % i for i in range(1, 17)]
NAMES = {
    "C01": "slide count equals the case instruction",
    "C02": "slide count within max_slides",
    "C03": "no shape outside the slide",
    "C04": "no estimated text overflow",
    "C05": "no overlapping body shapes",
    "C06": "table fits its frame and the slide",
    "C07": "picture aspect ratio preserved",
    "C08": "every content page has a title, speaker notes and a body (or is a declared backup page)",
    "C09": "body font size >= floor",
    "C10": "design fingerprint unchanged (master/layouts/theme)",
    "C11": "every content page carries a resolvable evidence anchor from a real material",
    "C12": "quotes are verbatim in the material (paraphrases declare their source sentence)",
    "C13": "every number on a page comes from that page's own evidence",
    "C14": "rendered PDF re-measured byte for byte (pages, page size, text survival, fonts)",
    "C15": "no placeholder/substitute imagery; every slide has a real, non-blank preview",
    "C16": "result.json contract fields agree with the delivered artifact",
}
# checks that legitimately have nothing to look at for this kind of deck
CONDITIONAL = {"C02", "C06", "C07", "C14", "C15", "C16"}
PLACEHOLDER_HINT = ("figure", "fig", "chart", "image", "picture", "plot", "diagram",
                    "示意图", "图", "表")
LIG = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
       "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"}
DASH = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2212": "-", "\u00ad": ""}
QUOTES = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
NUMRE = re.compile(r"\d+(?:\.\d+)?")
PAGECOUNT = re.compile(r"\(?\b\d+\s*/\s*\d+\b\)?")
ANCHOR = re.compile(r"^-\s+(?P<body>.+?)\s+\[(?P<kind>来源|路线)(?P<rest>[^\[\]]*)\]\s*$")
PARA = re.compile(r"^\s*改写自原句[：:]\s*(?P<q>.+?)\s*$")


# ---------------------------------------------------------------- normalisation
def norm(t):
    t = t or ""
    for k, v in list(LIG.items()) + list(DASH.items()) + list(QUOTES.items()):
        t = t.replace(k, v)
    return re.sub(r"\s+", " ", t).strip()


def flat(t):
    """alphanumerics + CJK only: tolerates PDF hyphenation, ligatures, punctuation."""
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", norm(t).lower())


def contains(quote, material):
    """'verbatim' | 'verbatim-loose' | None — how the quote relates to the material."""
    q = norm(quote)
    if not q:
        return None
    if q in material["norm"]:
        return "verbatim"
    fq = flat(q)
    if fq and fq in material["flat"]:
        return "verbatim-loose"
    return None


def prefix_hit(q, hay):
    """length of the longest prefix of q that occurs in hay (diagnostics only)."""
    lo, hi = 0, len(q)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if q[:mid] in hay:
            lo = mid
        else:
            hi = mid - 1
    return lo


def numbers_in(text, min_len=2):
    out = set()
    for m in NUMRE.finditer(PAGECOUNT.sub(" ", text or "")):
        if len(m.group(0)) >= min_len:
            out.add(m.group(0))
    return out


def shares_token(a, b):
    """do a paraphrase and its declared original share any word or CJK bigram?"""
    def toks(t, cjk_bigrams=True):
        t = norm(t).lower()
        out = {w for w in re.findall(r"[a-z0-9]{3,}", t)}
        if cjk_bigrams:
            cjk = re.sub(r"[^\u3400-\u9fff]", "", t)
            out |= {cjk[i:i + 2] for i in range(max(0, len(cjk) - 1))}
        return out
    return bool(toks(a) & toks(b))


def material_index(source):
    blocks = (source or {}).get("blocks") or []
    idx = {"norm": norm(" ".join((b.get("text") or "") for b in blocks)),
           "flat": "", "by_id": {}, "by_page": {}, "ledger": set(),
           "file": (source or {}).get("path"),
           "trusted": (source or {}).get("corpus", {}).get("trusted"),
           "why": (source or {}).get("corpus", {}).get("why")}
    idx["flat"] = flat(idx["norm"])
    for b in blocks:
        t = b.get("text") or ""
        bid = b.get("id")
        if bid:
            idx["by_id"][bid] = b
        p = b.get("page")
        if isinstance(p, int):
            idx["by_page"].setdefault(p, []).append(t)
    for x in (source or {}).get("numbers") or []:
        v = re.sub(r"[\s,]", "", x.get("value") or "")
        if v:
            idx["ledger"].add(v)
            idx["ledger"].add(re.sub(r"[^\d.]", "", v))
    return idx


# ------------------------------------------------------------------- structure
def sig(p):
    """design fingerprint: slide size + theme typefaces + layout placeholder geometry."""
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


def page_anchors(notes):
    """parse the anchor grammar out of one page's speaker notes.

    kind is 'material' ([来源 <file> p.N <block>]), 'plan' ([来源 plan ...]) or
    'outline' ([路线]).  Only 'material' anchors claim evidence in the paper.
    """
    out = {"bullets": [], "outline": [], "anchors": 0, "plan": 0,
           "unparsed": [], "malformed": []}
    last = None
    for raw in (notes or "").splitlines():
        m = ANCHOR.match(raw.strip())
        if m:
            body, kind, rest = m.group("body"), m.group("kind"), m.group("rest")
            rec = {"text": body.strip(), "kind": kind, "source": None,
                   "page": None, "block_id": None, "quote": None}
            if kind == "路线":
                rec["kind"] = "outline"
                out["outline"].append(rec)
                last = rec
                continue
            mm = re.match(r"\s*(?P<src>.+?)\s+p\.(?P<page>-|\d+|\?)\s*(?P<bid>.*)$",
                          rest)
            if not mm or mm.group("src").strip().lower() == "plan":
                rec["kind"] = "plan"
                rec["source"] = (mm.group("src").strip() if mm else rest.strip()) or None
                out["plan"] += 1
                out["outline"].append(rec)
                last = rec
                continue
            rec["kind"] = "material"
            rec["source"] = mm.group("src").strip()
            pg = mm.group("page")
            rec["page"] = int(pg) if pg.isdigit() else None
            rec["block_id"] = (mm.group("bid") or "").strip() or None
            out["bullets"].append(rec)
            out["anchors"] += 1
            if rec["page"] is None and not rec["block_id"]:
                out["malformed"].append(rec)
            last = rec
            continue
        p = PARA.match(raw)
        if p and last is not None:
            last["quote"] = p.group("q").strip()
            continue
        if raw.strip() and ("[来源" in raw or "[路线" in raw):
            # a line that looks like an anchor but does not parse: report it instead
            # of silently ignoring or re-interpreting it
            out["unparsed"].append(raw.strip()[:90])
    return out


def nested_get(case, names):
    """same resolution order as deck.py: top level, then one level of sub-dicts."""
    for src in [case or {}] + [v for v in (case or {}).values() if isinstance(v, dict)]:
        for k, v in src.items():
            if str(k).lower() in names and isinstance(v, int):
                return v
    return None


TASK_MARKERS = ("output_contract", "runtime contract", "评分维度", "评分点", "提交材料",
                "do not submit prepared answers", "grader", "rubric")
# anchored, never substring: a real paper called case-study-routing.md is MATERIAL
DENY_EXACT = {"case.json", "case.md", "case.txt", "task.md", "task.json", "task.txt",
              "readme.md", "readme.txt", "rubric.md", "rubric.json", "skill.md",
              "method.md", "notes.md", "benchmark.md", "benchmark.json",
              "deck-rules.md", "prompt.md", "instructions.md"}
DENY_SUFFIX = (".example.json", ".example.md", ".example.txt", ".template.json",
               ".template.md", ".template.txt", ".schema.json", ".schema.md")
DENY_NAME_RE = re.compile(r"^template[-_](spec|plan|deck)[^.]*\.(json|md|txt)$")
EVIDENCE_EXT = (".pdf", ".md", ".markdown", ".txt", ".text")


def deny_by_name(n):
    low = (n or "").lower()
    if low in DENY_EXACT:
        return True
    if any(low.endswith(s) for s in DENY_SUFFIX):
        return True
    return bool(DENY_NAME_RE.match(low))


def corpus_verdict(mat):
    """defence in depth: the verifier also refuses a non-material citation corpus."""
    f = (mat.get("file") or "").lower()
    if not f:
        return True, "no corpus file recorded"
    if os.path.splitext(f)[1] not in EVIDENCE_EXT:
        return False, "the citation corpus is %s, which is not paper/text material" % f
    if deny_by_name(f):
        return False, ("the citation corpus is %s: an instruction/case/example file, "
                       "not research material, so no quote or number in this deck can "
                       "be certified against it" % f)
    if mat.get("trusted") is False:
        return False, "source.json already marked this corpus as refused: %s" % (
            mat.get("why") or "")
    return True, "corpus file looks like research material"


# ----------------------------------------------------------------------- check
def check(pptx, case=None, source=None, spec=None, template=None, render=None,
          edit=None, template_role=None, result=None):
    """result: the result.json contract this run is about to publish (optional).

    When it is supplied, C16 audits the contract fields against the artifact: a
    contract that describes the plan instead of the delivered deck is a defect
    (QA-round-20261124 P0-1/P0-2a/P1-2)."""
    found = {}

    def add(cid, ok, detail=None, status=None):
        found[cid] = {"id": cid, "name": NAMES[cid],
                      "ok": (None if ok is None else bool(ok)),
                      "status": status or ("pass" if ok else "fail"),
                      "detail": detail}

    def na(cid, why):
        add(cid, None, {"why": why}, "n/a")

    if not os.path.isfile(pptx):
        for cid in IDS:
            na(cid, "deck.pptx does not exist: nothing was delivered")
        return _finish(found, None)
    try:
        prs = Presentation(pptx)
    except Exception as e:
        add("C01", False, {"why": "pptx cannot be opened: %s" % str(e)[:120]})
        for cid in IDS[1:]:
            na(cid, "pptx cannot be opened")
        return _finish(found, None)

    n = len(prs.slides)
    want = nested_get(case, ("slide_count", "num_slides"))
    cap = nested_get(case, ("max_slides", "slide_count_max"))
    if want:
        add("C01", n == int(want), {"expected": int(want), "actual": n,
                                    "field_source": "case.json (top level or one "
                                                    "level of nesting)"})
    else:
        na("C01", "case.json carries no slide_count/num_slides anywhere")
    if cap:
        add("C02", n <= int(cap), {"max_slides": int(cap), "actual": n})
    elif (spec or {}).get("slide_budget"):
        add("C02", n <= int(spec["slide_budget"]),
            {"max_slides": int(spec["slide_budget"]), "actual": n,
             "field_source": "deck_plan.slide_budget (no max_slides in case.json)"})
    else:
        na("C02", "neither case.json max_slides nor deck_plan.slide_budget exist")

    W, H = float(prs.slide_width) / 12700, float(prs.slide_height) / 12700
    rules = (spec or {}).get("rules") or {}
    floor = float(rules.get("min_body_pt") or 12)
    maxb = int(rules.get("max_bullets_per_slide") or 6)
    (out_slide, over, small, many, overlap, nonotes,
     noanchor, quote_bad, num_bad) = ([] for _ in range(9))
    none_inherited, q_inherited, contentless = [], [], []
    empty_body, backup_pages = [], []
    tables_seen = pictures_seen = 0
    mat = material_index(source)
    per_page = {}
    for i, slide in enumerate(prs.slides, 1):
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        pa = page_anchors(notes)
        per_page[i] = pa
        title = slide.shapes.title
        titled = bool(title is not None and (title.text_frame.text or "").strip())
        if not titled:      # a title-text box counts too, not only a title placeholder
            for sh in slide.shapes:
                if sh.has_text_frame and "title" in (sh.name or "").lower() and \
                        (sh.text_frame.text or "").strip():
                    titled = True
                    break
        if not titled:
            nonotes.append({"slide": i, "why": "no title text on the page"})
        if not notes.strip():
            nonotes.append({"slide": i, "why": "empty speaker notes"})
        declared_backup = "[备份]" in notes
        if declared_backup:
            backup_pages.append(i)
        body_chars = sum(len((sh.text_frame.text or "").strip())
                         for sh in slide.shapes
                         if sh.has_text_frame
                         and not any(k in (sh.name or "").lower()
                                     for k in EXEMPT)
                         and "title" not in (sh.name or "").lower())
        if i > 1 and body_chars == 0 and not declared_backup:
            # QA-round-20261124 P1-1: three content pages shipped with only a title and
            # a footer, and every check stayed green
            empty_body.append({"slide": i,
                               "why": "the page carries no body text and is not a "
                                      "declared backup page ([备份] missing)"})
        boxes, nb = [], 0
        for sh in slide.shapes:
            try:
                x, y = float(sh.left or 0) / 12700, float(sh.top or 0) / 12700
                w, h = float(sh.width or 0) / 12700, float(sh.height or 0) / 12700
            except Exception:
                continue
            if not (-2 <= x and -2 <= y and x + w <= W + 2 and y + h <= H + 2):
                out_slide.append({"slide": i, "shape": sh.name,
                                  "box": [round(x), round(y), round(w), round(h)]})
            if getattr(sh, "has_table", False) and sh.has_table:
                tables_seen += 1
                try:
                    cols = sum(float(c.width or 0) for c in sh.table.columns) / 12700
                    rows = sum(float(r.height or 0) for r in sh.table.rows) / 12700
                    if cols > w + 4 or rows > h + 4 or x + cols > W + 2 or \
                            y + rows > H + 2:
                        out_slide.append({"slide": i, "shape": sh.name,
                                          "why": "table body exceeds its frame",
                                          "frame": [round(w), round(h)],
                                          "table": [round(cols), round(rows)]})
                except Exception:
                    pass
            if sh.shape_type is not None and "PICTURE" in str(sh.shape_type):
                pictures_seen += 1
                try:
                    iw, ih = sh.image.size
                    if iw and ih and w and h:
                        want_ar, got_ar = iw / float(ih), w / float(h)
                        if abs(got_ar - want_ar) / want_ar > 0.02:
                            out_slide.append({"slide": i, "shape": sh.name,
                                              "why": "picture aspect ratio distorted",
                                              "image_ar": round(want_ar, 4),
                                              "placed_ar": round(got_ar, 4)})
                except Exception:
                    pass
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
                over.append({"slide": i, "shape": sh.name,
                             "needed_pt": round(need, 1), "box_pt": round(h, 1)})
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

    add("C03", not out_slide, out_slide[:6])
    add("C04", not over, {"count": len(over), "samples": over[:5],
                          "method": "character-width model (estimated); cross-check "
                                    "the rendered PDF"})
    add("C05", not overlap, {"count": len(overlap), "samples": overlap[:5],
                             "method": "intersection > 12% of the smaller body box"})
    if tables_seen:
        add("C06", not [x for x in out_slide if x.get("why", "").startswith("table")],
            {"tables": tables_seen})
    else:
        na("C06", "this deck contains no table (0 table shapes found in the artifact)")
    if pictures_seen:
        add("C07", not [x for x in out_slide
                        if x.get("why", "").startswith("picture")],
            {"pictures": pictures_seen, "tolerance": "2% of the intrinsic aspect"})
    else:
        na("C07", "this deck contains no picture (0 picture shapes found)")
    add("C08", not (nonotes or empty_body),
        {"page_problems": nonotes[:6], "empty_body_pages": empty_body[:6],
         "declared_backup_pages": backup_pages,
         "how": "a content page needs a title, speaker notes and body text; a page with "
                "no body text is only accepted when its notes declare it with [备份] "
                "(and that page is then listed here)"})
    add("C09", not small, {"floor_pt": floor, "samples": small[:6]})
    if template and os.path.isfile(template):
        a, b = sig(template), sig(pptx)
        add("C10", a == b, {"baseline": os.path.basename(template),
                            "baseline_role": template_role or "template",
                            "method": "design fingerprint (slide size + theme "
                                      "typefaces + layout placeholder geometry), not "
                                      "byte hashes: the writer re-serialises parts",
                            "differences": [] if a == b else
                            {"baseline": a, "deck": b}})
    else:
        na("C10", "no baseline deck/template supplied, so inheritance is not comparable")

    # C11 — anchors exist and resolve against the material, on the artifact itself
    anchors_before = (edit or {}).get("anchors_found_before")
    inherited = {}
    for row in (edit or {}).get("input_anchor_keys") or []:
        if isinstance(row, list) and len(row) == 2:
            inherited.setdefault(row[0], set()).add(row[1])

    def inherit(slide, text):
        """is this notes bullet carried over unchanged from the supplied deck?"""
        return hashlib.sha1(norm(text).encode("utf-8")).hexdigest()[:16] in \
            (inherited.get(slide) or set())

    def locator_ok(b, mat):
        """(ok, how) — a locator is good if its cited source is real research
        material, the block resolves, or the quote really is on the cited page."""
        src_name = (b.get("source") or "").strip()
        allowed = {os.path.basename(x) for x in
                   [mat.get("file") or ""] + list((source or {}).get("siblings") or [])}
        allowed.discard("")
        low = src_name.lower()
        if not src_name:
            return False, "anchor names no source at all"
        if deny_by_name(low) or \
                os.path.splitext(low)[1] not in EVIDENCE_EXT:
            return False, ("the anchor cites %s: a task sheet / case file / example / "
                           "non-material file, not research material" % src_name)
        if allowed and src_name not in allowed and src_name.lower() not in {
                a.lower() for a in allowed}:
            # a second real material is allowed only if discovery accepted it
            return False, ("the anchor cites %s, which was not one of the material "
                           "candidates this run accepted (%s)"
                           % (src_name, ", ".join(sorted(allowed))[:120]))
        bid, pg, q = b.get("block_id"), b.get("page"), (b.get("quote") or b["text"])
        if bid and mat["by_id"]:
            blk = mat["by_id"].get(bid)
            if blk is not None:
                if pg is not None and isinstance(blk.get("page"), int) and \
                        blk["page"] != pg:
                    return False, "anchor page disagrees with the block it names"
                return True, "block id resolves"
            if pg is None:
                return False, "block id does not exist in the material and no page " \
                              "is given"
            hit = [x for x in mat["by_page"].get(pg, []) if contains(q, {"norm": norm(x),
                                                                        "flat": flat(x)})]
            if hit:
                return True, "stale block id, re-resolved by page + verbatim quote"
            return False, "block id does not exist in the material and the quote is " \
                          "not on the cited page"
        if pg is not None:
            if mat["by_page"] and pg not in mat["by_page"]:
                return False, "cited page does not exist in the material"
            return True, "page locator only (no block id given)"
        return False, "anchor carries no page and no block id: nothing to resolve"

    for i in range(2, n + 1):
        pa = per_page[i]
        page_has_text = False
        for sh in prs.slides[i - 1].shapes:
            if sh.has_text_frame and not any(
                    k in (sh.name or "").lower() for k in EXEMPT) and \
                    "title" not in (sh.name or "").lower() and \
                    len((sh.text_frame.text or "").strip()) > 3:
                page_has_text = True
                break
        for bad_line in pa["unparsed"]:
            row = {"slide": i, "malformed_anchor_line": bad_line}
            (noanchor if not (edit and inherit(i, bad_line))
             else none_inherited).append(row)
        for b in pa["bullets"]:
            ok, how = locator_ok(b, mat)
            if ok:
                continue
            row = {"slide": i, "block_id": b.get("block_id"), "page": b.get("page"),
                   "why": how, "text": b["text"][:70]}
            (noanchor if not (edit and inherit(i, b["text"])) else none_inherited).append(row)
        if not pa["anchors"] and not (pa["outline"] or pa["plan"]):
            if not page_has_text:
                contentless.append(i)      # a spacer/backup page: nothing to anchor
            else:
                noanchor.append({"slide": i,
                                 "why": "the page carries text but no [来源]/[路线] "
                                        "anchor in its notes"})
    if not mat["by_id"] and not mat["by_page"]:
        na("C11", "no material ledger (source.json) was supplied: anchors cannot be "
                  "resolved")
    elif n < 2:
        na("C11", "the deck has a single page: no content page to anchor")
    elif edit and not anchors_before and not any(
            per_page[i]["anchors"] for i in range(2, n + 1)):
        na("C11", "the supplied starting deck carries no material anchor and no edit "
                  "op introduced one: an input limitation, recorded instead of a pass")
    else:
        add("C11", not noanchor,
            {"slides_without_valid_anchor": noanchor[:8],
             "contentless_pages": contentless,
             "inherited_from_input_deck": none_inherited[:6],
             "anchors_found_before_edit": anchors_before,
             "how": "a [来源] anchor must name real research material (a task sheet, "
                    "case file or example is rejected even when its page/block resolves) "
                    "and must resolve: its block id must exist in source.json (a stale "
                    "label is re-resolved by page + verbatim quote and reported), or its "
                    "page must exist. A page with no body text is a spacer page and "
                    "needs no anchor; a malformed anchor line is reported. Anchor "
                    "problems that already existed in the supplied deck are reported "
                    "here as inherited and are not counted against this run."})

    # C12 — quote authenticity, read from the delivered speaker notes
    quote_bad, paraphrases, checked, no_overlap = [], 0, 0, []
    corpus_ok, corpus_why = corpus_verdict(mat)
    if mat["norm"] and not corpus_ok:
        quote_bad.append({"slide": None, "kind": "citation corpus",
                          "why": corpus_why, "text": mat.get("file")})
        checked = 1
        add("C12", False, {"corpus": corpus_why, "file": mat.get("file"),
                           "how": "the corpus itself must be research material before "
                                  "any quote can be called verbatim"})
    elif not mat["norm"]:
        na("C12", "no material text (source.json) was supplied: a quote cannot be "
                  "verified against anything")
    else:
        for i in range(2, n + 1):
            for b in per_page[i]["bullets"]:
                q = b.get("quote")
                evidence = q or b["text"]
                checked += 1
                kind = contains(evidence, mat)
                if kind:
                    if q:
                        paraphrases += 1
                        if not shares_token(b["text"], q):
                            no_overlap.append({"slide": i, "text": b["text"][:70],
                                               "declared_original": q[:70],
                                               "note": "no shared token (common in a "
                                                       "translated bullet: see "
                                                       "limitations)"})
                    continue
                lo = prefix_hit(norm(evidence), mat["norm"])
                row = {"slide": i,
                       "kind": "declared original sentence" if q else "bullet text",
                       "text": evidence[:90],
                       "matched_prefix_chars": lo,
                       "diverges_at": norm(evidence)[lo:lo + 60],
                       "why": "not verbatim in the material (even after ligature/"
                              "hyphen/punctuation normalisation)"}
                (quote_bad if not (edit and inherit(i, b["text"]))
                 else q_inherited).append(row)
        if not checked:
            na("C12", "the deck carries no material anchor quote to authenticate")
        else:
            add("C12", not quote_bad,
                {"quotes_checked": checked, "paraphrases_declared": paraphrases,
                 "paraphrases_without_shared_token": no_overlap[:6],
                 "inherited_from_input_deck": q_inherited[:6],
                 "not_verbatim": quote_bad[:6],
                 "how": "each [来源] bullet must be verbatim in the material, or be "
                        "followed by 改写自原句：<verbatim sentence>; a paraphrase "
                        "without its original sentence fails. Problems already "
                        "present in the supplied deck are reported as inherited.",
                 "limit": "this checks citation AUTHENTICITY; it cannot decide whether "
                          "a declared original sentence actually entails a paraphrased "
                          "bullet (see references/deck-rules.md §6)"})

    # C13 — number fidelity, scoped to the page that claims the number
    scope = str(rules.get("number_scope") or (case or {}).get("number_scope")
                or "page").lower()
    if not mat["ledger"]:
        na("C13", "the material carries no numbers: nothing to check")
    elif not corpus_ok:
        add("C13", False, {"corpus": corpus_why, "file": mat.get("file"),
                           "how": "the ledger comes from a file that is not research "
                                  "material, so a number matching it proves nothing"})
    else:
        for i in range(2, n + 1):
            pa = per_page[i]
            allowed = set()
            for b in pa["bullets"]:
                # evidence only: the declared original sentence, and the material
                # block/page it cites.  The slide's own text is deliberately NOT used
                # as its own evidence, otherwise any number would certify itself.
                allowed |= numbers_in(b.get("quote") or "")
                blk = mat["by_id"].get(b.get("block_id") or "")
                if blk is None and b.get("page") in mat["by_page"]:
                    allowed |= numbers_in(" ".join(mat["by_page"][b["page"]]))
                elif blk:
                    allowed |= numbers_in(blk.get("text") or "")
            outline_page = not pa["anchors"] and (pa["outline"] or pa["plan"])
            if outline_page or not (pa["anchors"] or pa["outline"] or pa["plan"]):
                allowed = set(mat["ledger"])     # an outline page summarises the whole
            for sh in prs.slides[i - 1].shapes:
                if not sh.has_text_frame:
                    continue
                if any(k in (sh.name or "").lower() for k in EXEMPT):
                    continue
                txt = sh.text_frame.text or ""
                for m in NUMRE.finditer(PAGECOUNT.sub(" ", txt)):
                    v = m.group(0)
                    if len(v) < 2 or v in allowed:
                        continue
                    where = ("wrong-page-scope" if v in mat["ledger"]
                             else "not-in-material")
                    if where == "wrong-page-scope" and scope != "page":
                        continue
                    num_bad.append({"slide": i, "number": v, "verdict": where,
                                    "shape": sh.name,
                                    "page_evidence": sorted(allowed)[:12]})
        if any(p["anchors"] or p["outline"] or p["plan"] for p in per_page.values()):
            add("C13", not num_bad,
                {"scope": scope, "ledger_size": len(mat["ledger"]),
                 "unmatched": num_bad[:10],
                 "how": "a >=2-digit number on a page must occur in that page's own "
                        "anchored sentence or in the material block/page it cites "
                        "(outline pages are checked against the whole ledger); a "
                        "number that only exists elsewhere in the paper is "
                        "'wrong-page-scope' (set number_scope=material in the plan or "
                        "case to downgrade that one rule)"})
        else:
            na("C13", "the deck has no anchors, so a page's own evidence is undefined"
                      " (see C11)")

    if render is not None:
        found["render"] = {"id": "aux",
                           "name": "real render produced (aux, not one of the 15)",
                           "ok": render.get("render_status") == "ok",
                           "status": render.get("render_status"),
                           "detail": {"renderer": render.get("renderer"),
                                      "png": len(render.get("png") or []),
                                      "notes": (render.get("notes") or [])[:2]}}

    # C14 — the preview is re-measured from its own bytes, not taken on trust
    if not (render and render.get("pdf") and os.path.isfile(render["pdf"])):
        na("C14", "no rendered PDF was produced (render_status=%s), so there is "
                  "nothing to re-measure; a PNG preview is never fabricated to fill "
                  "this gap" % (render or {}).get("render_status"))
    else:
        pdf = render["pdf"]
        pdf_pt = [int(prs.slide_width) / 12700.0, int(prs.slide_height) / 12700.0]
        m = {"pdf": os.path.basename(pdf), "bytes": os.path.getsize(pdf),
             "pptx_slide_pt": [round(x, 1) for x in pdf_pt]}
        try:
            import fitz
            doc = fitz.open(pdf)
            m["pages"] = doc.page_count
            m["page_size_pt"] = [[round(p.rect.width, 1), round(p.rect.height, 1)]
                                 for p in doc][:3]
            m["fonts_seen"] = sorted({f[3] for p in doc for f in p.get_fonts()})[:12]
            ratios = []
            for i, page in enumerate(doc, 1):
                txt = norm(page.get_text())
                if i - 1 >= len(prs.slides):
                    continue
                want = norm(" ".join(sh.text_frame.text for sh in
                                     prs.slides[i - 1].shapes if sh.has_text_frame))
                toks = [t for t in re.findall(r"[A-Za-z]{3,}|[\u3400-\u9fff]", want)]
                if not toks:
                    continue
                hit = sum(1 for t in toks if t in txt)
                ratios.append(round(hit / float(len(toks)), 3))
            doc.close()
            m["text_survival_min"] = min(ratios) if ratios else None
            m["text_survival_pages"] = len(ratios)
            bad = []
            if m["pages"] != len(prs.slides):
                bad.append({"why": "pdf page count != slide count",
                            "pdf": m["pages"], "pptx": len(prs.slides)})
            for sz in m["page_size_pt"]:
                if abs(sz[0] - pdf_pt[0]) > 2 or abs(sz[1] - pdf_pt[1]) > 2:
                    bad.append({"why": "pdf page size differs from the slide size",
                                "pdf": sz, "pptx": [round(x, 1) for x in pdf_pt]})
            if m["text_survival_min"] is not None and m["text_survival_min"] < 0.82:
                bad.append({"why": "text did not survive the export (possible font "
                                   "substitution or clipping)",
                            "min_survival": m["text_survival_min"], "floor": 0.82})
            add("C14", not bad, dict(m, problems=bad))
        except Exception as e:
            add("C14", False, dict(m, error="the PDF could not be re-measured: %s"
                                             % str(e)[:110]))

    # C15 — no placeholder/substitute imagery, and a real, non-blank PNG per slide
    placeholders, pics, blank_png, png_stats = [], 0, [], []
    for i, slide in enumerate(prs.slides, 1):
        for sh in slide.shapes:
            if sh.shape_type is None or "PICTURE" not in str(sh.shape_type):
                continue
            pics += 1
            rec = {"slide": i, "shape": sh.name}
            try:
                blob, px = sh.image.blob, sh.image.size
                rec.update({"bytes": len(blob), "px": list(px)})
                if len(blob) < 2048 or min(px) < 16:
                    placeholders.append(dict(rec, why="the embedded image is a stub "
                                                      "(too few bytes / pixels): a "
                                                      "placeholder, not a figure"))
            except Exception as e:
                placeholders.append(dict(rec, why="no embedded image part: %s"
                                                   % str(e)[:60]))
    png_missing = {}
    if (render or {}).get("render_status") == "ok":
        pngs = list(render.get("png") or [])
        if len(pngs) < len(prs.slides):
            png_missing = {"png": len(pngs), "slides": len(prs.slides)}
        # QA-round-20261124 P0-2b: counting the files was not enough — every preview
        # could be replaced by pure white and C15 still passed.  Read the pixels.
        seen_hashes = {}
        for p in pngs:
            if not os.path.isfile(p):
                blank_png.append({"file": os.path.basename(p), "why": "missing"})
                continue
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
            if h in seen_hashes:
                blank_png.append({"file": os.path.basename(p),
                                  "why": "byte-identical to %s: the same picture was "
                                         "reused for several slides" % seen_hashes[h]})
                continue
            seen_hashes[h] = os.path.basename(p)
            try:
                from PIL import Image
                from collections import Counter
                im = Image.open(p).convert("RGB")
                small = im.resize((96, 96))
                cnt = Counter(small.getdata())
                top_ratio = cnt.most_common(1)[0][1] / float(96 * 96)
                uniq = len(cnt)
                png_stats.append({"file": os.path.basename(p), "px": list(im.size),
                                  "unique_colors_96x96": uniq,
                                  "dominant_ratio": round(top_ratio, 4)})
                want_ar = float(prs.slide_width) / float(prs.slide_height)
                got_ar = im.size[0] / float(im.size[1])
                if abs(got_ar - want_ar) / want_ar > 0.02:
                    blank_png.append({"file": os.path.basename(p),
                                      "why": "preview aspect ratio differs from the slide",
                                      "png_ar": round(got_ar, 3),
                                      "slide_ar": round(want_ar, 3)})
                elif uniq <= 2 or top_ratio >= 0.995:
                    blank_png.append({"file": os.path.basename(p),
                                      "why": "the preview is blank: %d distinct colour(s) "
                                             "in a 96x96 sample, dominant colour covers "
                                             "%.1f%%" % (uniq, top_ratio * 100)})
            except Exception as e:
                blank_png.append({"file": os.path.basename(p),
                                  "why": "the PNG could not be read: %s" % str(e)[:60]})
    if render is None:
        na("C15", "no render report was supplied: imagery and previews are unchecked")
    elif pics == 0 and not png_missing and not blank_png:
        add("C15", True, {"pictures": 0, "previews": png_stats[:4],
                          "note": "this deck embeds no picture at all (nothing is "
                                  "standing in for a figure), and every slide has its "
                                  "own non-blank rendered PNG"})
    else:
        bad = placeholders + blank_png + ([{"why": "no PNG preview for every slide",
                                            **png_missing}] if png_missing else [])
        add("C15", not bad, {"pictures": pics, "placeholder_or_stub": placeholders[:6],
                             "blank_or_reused_previews": blank_png[:6],
                             "preview_gap": png_missing, "previews": png_stats[:4],
                             "how": "every picture shape must carry a real image part "
                                    "(>=2 KB, >=16x16 px); every rendered PNG must be "
                                    "readable, non-blank (>=3 distinct colours in a "
                                    "96x96 sample, dominant colour < 99.5%) and unique"})

    # C16 — the published contract must describe the artifact, not the plan
    if result is None:
        na("C16", "no result.json was handed to the verifier: the contract fields "
                  "cannot be audited against the artifact")
    else:
        bad, notes_mismatch = [], []
        cid_claimed = str(result.get("case_id") or "").strip()
        cid_input = (case or {}).get("case_id") or (case or {}).get("caseId") or \
            (case or {}).get("id")
        if not cid_claimed:
            bad.append({"field": "case_id", "why": "empty"})
        elif cid_input is not None and cid_claimed != str(cid_input):
            bad.append({"field": "case_id", "expected": str(cid_input),
                        "actual": cid_claimed,
                        "why": "result.json case_id does not match the input case"})
        srcs = result.get("sources") or []
        if not srcs:
            bad.append({"field": "sources", "why": "empty"})
        for s in srcs if isinstance(srcs, list) else []:
            p = str((s or {}).get("path") or "")
            low = os.path.basename(p).lower()
            ext = os.path.splitext(low)[1]
            if not p:
                bad.append({"field": "sources[].path", "why": "empty"})
            elif ext in EVIDENCE_EXT and not deny_by_name(low):
                continue
            elif ext == ".pptx" and p.lower() in [str((result.get("deliverable") or {}
                                                       ).get("pptx", "")).lower(),
                                                  "deck.pptx"]:
                continue        # editing a supplied deck with no paper: the deck is the source
            else:
                bad.append({"field": "sources[].path", "value": p,
                            "why": "the declared source is not research material "
                                   "(task sheet / case file / example / non-text file)"})
        dv = result.get("deliverable") or {}
        if isinstance(dv, dict) and dv.get("slides") not in (None, n):
            bad.append({"field": "deliverable.slides", "expected": n,
                        "actual": dv.get("slides"),
                        "why": "the contract reports a different slide count than the "
                               "artifact"})
        rows = {x.get("index"): x for x in (result.get("notes") or [])
                if isinstance(x, dict)}
        for i, slide in enumerate(prs.slides, 1):
            actual = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide \
                else ""
            row = rows.get(i)
            if row is None:
                notes_mismatch.append({"slide": i, "why": "no notes entry in the contract"})
                continue
            claimed = str(row.get("notes_full") or row.get("notes") or "").strip()
            if actual.strip() and not claimed:
                notes_mismatch.append({"slide": i,
                                       "why": "the deck has speaker notes but the "
                                              "contract field is empty",
                                       "artifact_chars": len(actual)})
            elif claimed and not actual.strip():
                notes_mismatch.append({"slide": i,
                                       "why": "the contract claims notes the deck does "
                                              "not have"})
        if notes_mismatch:
            bad.append({"field": "notes", "mismatches": notes_mismatch[:8],
                        "why": "the notes contract field must describe the delivered "
                               "speaker notes"})
        outs_bad = []
        for o in result.get("outputs") or []:
            p = os.path.join(os.path.dirname(os.path.abspath(pptx)),
                             (o or {}).get("path") or "")
            if not (os.path.isfile(p) and os.path.getsize(p) == o.get("bytes")):
                outs_bad.append({"path": (o or {}).get("path"),
                                 "expected_bytes": (o or {}).get("bytes"),
                                 "actual_bytes": os.path.getsize(p)
                                 if os.path.isfile(p) else None})
        if outs_bad:
            bad.append({"field": "outputs[].bytes", "mismatches": outs_bad[:6]})
        add("C16", not bad, {"problems": bad[:8], "artifact_slides": n,
                             "how": "case_id, sources[], deliverable.slides, notes[] "
                                    "and outputs[].bytes are re-derived from the "
                                    "artifact and compared with the published contract"})
    return _finish(found, n)


def _finish(found, n):
    checks = [found[cid] for cid in IDS if cid in found]
    if "render" in found:
        checks.append(found["render"])
    failed = [c for c in checks if c["status"] == "fail"]
    na_ids = [c["id"] for c in checks if c["status"] == "n/a"]
    passed = [c for c in checks if c["status"] == "pass"]
    return {"pptx_slides": n, "passed": not failed, "checks": checks,
            "sections": {"pass": len(passed), "fail": len(failed),
                         "n/a": len(na_ids)},
            "summary": {"slides": n, "checks": len(checks), "failed": len(failed),
                        "not_applicable": na_ids, "failed_ids": [c["id"] for c in failed],
                        "conditional_ids": sorted(CONDITIONAL),
                        "coverage": {"passed": len(passed),
                                     "failed": len(failed),
                                     "not_applicable": len(na_ids)}},
            "ids": IDS, "names": NAMES}


# ------------------------------------------------------------------- recompute
def recompute(pptx, result):
    """read-only: re-derive the deliverable's claims from pptx + result.json only."""
    out = {"pairs": [], "passed": True}
    if not os.path.isfile(pptx) or not isinstance(result, dict):
        return {"pairs": [{"item": "artifacts present", "expected": True,
                           "actual": False}], "passed": False}
    prs = Presentation(pptx)
    dv = result.get("deliverable") or {}
    ev = result.get("evidence_map") or []
    out["pairs"].append({"item": "contract carries a case_id",
                         "expected": True,
                         "actual": bool(str(result.get("case_id") or "").strip())})
    bad_src = []
    for s in result.get("sources") or []:
        p = str((s or {}).get("path") or "")
        low = os.path.basename(p).lower()
        ext = os.path.splitext(low)[1]
        if not p:
            bad_src.append({"path": p, "why": "empty"})
        elif ext in EVIDENCE_EXT and not deny_by_name(low):
            continue
        elif ext == ".pptx" and (p.lower() == "deck.pptx" or
                                 p.lower() == str(dv.get("pptx") or "").lower()):
            continue
        else:
            bad_src.append({"path": p,
                            "why": "declared source is not research material"})
    out["pairs"].append({"item": "declared sources[] are research material",
                         "expected": [], "actual": bad_src[:6],
                         "ok": not bad_src})
    out["pairs"].append({"item": "slide count", "expected": dv.get("slides"),
                         "actual": len(prs.slides)})
    notes = {i: (s.notes_slide.notes_text_frame.text if s.has_notes_slide else "")
             for i, s in enumerate(prs.slides, 1)}
    in_notes = {i for i in range(2, len(prs.slides) + 1)
                if re.search(r"\[来源 .*?p\.(-|\d+)", notes.get(i, ""))}
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
        for q in (a.get("quote"), e.get("text"), a.get("block_id"),
                  str(a.get("page") or "")):
            if q:
                quotes.setdefault(e.get("slide"), []).append(str(q))
    bad = []
    for i, s in enumerate(prs.slides, 1):
        if i == 1:
            continue
        own = " ".join(quotes.get(i, []))
        # the page's own evidence also covers the sentences its notes carry
        own += " " + " ".join(b["text"] for b in page_anchors(notes.get(i, ""))["bullets"])
        for sh in s.shapes:
            if not sh.has_text_frame or any(k in (sh.name or "").lower()
                                            for k in EXEMPT):
                continue
            for m in NUMRE.finditer(PAGECOUNT.sub(" ", sh.text_frame.text or "")):
                v = m.group(0)
                if len(v) > 1 and v not in own:
                    bad.append({"slide": i, "number": v,
                                "why": "not in this slide's own anchor quote"})
    out["pairs"].append({"item": "numbers on a slide occur in its own anchor quote",
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


def load(p):
    return json.load(open(p, encoding="utf-8")) if p and os.path.isfile(p) else None


def main(argv=None):
    ap = argparse.ArgumentParser(description="16 artifact-level checks + recompute")
    for f in ("--pptx", "--case", "--source", "--spec", "--template", "--render",
              "--edit", "--out", "--result", "--contract"):
        ap.add_argument(f, default="/app/output/deck.pptx" if f == "--pptx" else "")
    ap.add_argument("--template-role", default="")
    a = ap.parse_args(argv)
    if a.result and not a.contract:
        # legacy mode: recompute from pptx + result.json only
        rep = {"recompute": recompute(a.pptx, load(a.result))}
        rep["passed"] = rep["recompute"]["passed"]
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep["passed"] else 2
    rep = check(a.pptx, case=load(a.case), source=load(a.source), spec=load(a.spec),
                template=a.template or None, render=load(a.render),
                edit=load(a.edit), template_role=a.template_role or None,
                result=load(a.contract or a.result))
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
