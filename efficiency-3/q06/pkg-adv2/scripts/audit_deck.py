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
  A9 preview    the exported PDF and the page PNGs are re-counted here, from the
                files, without reading render.json - so "a real preview was
                rendered" is checked by someone other than the renderer
  A10 sources   nothing from task.md / case.json / *.example.json / *.template.json
                was promoted into sources[], and every cited locator names a
                declared source: the deck is derived from the paper, not the
                work order
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

# Every extension the delivery legitimately contains, and the subset that is a
# raster image.  A9 walks the whole output tree against these two sets.
BINARY_EXTS = {".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
               ".tif", ".tiff", ".emf", ".wmf", ".ttf", ".otf"}
RASTER_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


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


def load_material(case: dict, case_path: str, exclude_dirs=()):
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
        skip_dirs = {os.path.abspath(x) for x in exclude_dirs if x}
        paths = [os.path.join(base, f) for f in sorted(os.listdir(base))
                 if os.path.splitext(f)[1].lower() in P.SUPPORTED
                 and os.path.abspath(os.path.join(base, f)) != os.path.abspath(case_path or "")
                 and os.path.abspath(os.path.join(base, f)) not in skip_dirs]
    src = P.Source()
    for p in paths:
        part = P.ingest(p, exclude=(case_path,), exclude_dirs=exclude_dirs)
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
        texts, fonts, has_num, has_footer = [], [], False, False
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
        pages.append({"page": i, "text": body,
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
    src, material_files = load_material(case, case_path, exclude_dirs=(out_dir,))
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
    # A locator printed on the page ("(paper.pdf · §3.8 Model Analysis · p6 ·
    # para24)") is a citation, not a claim: its section and page coordinates are
    # not measured data, so they are removed before numbers are checked.  A
    # citation that does not resolve is still caught, by A5.
    bad_ref, bad_num = [], []
    for p in deck["pages"]:
        body = strip_locators(p["text"])
        for label in I.refs_in(body):
            if not I.verify_locator(inv, label)["ok"]:
                bad_ref.append(f"slide {p['page']}: cites {label}")
        for raw, unit in I.numbers_in(body):
            if not I.verify_value(inv, raw, unit)["ok"]:
                bad_num.append(f"slide {p['page']}: number {raw}{unit}")
    record("A4", "every Figure/Table number and number in the pptx exists in the material",
           {"material_numbers": len(inv.numbers), "material_captions": len(inv.captions)},
           {"bad_refs": len(bad_ref), "bad_numbers": len(bad_num)}, not bad_ref and not bad_num,
           bad_ref + bad_num or (["material not readable"] if not src.segments else []))

    # the declared source list, used by A5 and A10
    src_paths = [s.get("path") or "" for s in (res.get("sources") or [])]

    # A5 locators -------------------------------------------------------------
    # The quote is re-located in the material *here*, instead of trusting the
    # ``locator_verified`` flag the plan layer wrote about itself: a flag that
    # only repeats the producer's own conclusion cannot catch a quote that was
    # edited after the fact.
    emap = {e.get("page"): e for e in (res.get("evidence_map") or [])}
    declared = {os.path.basename(p.replace("\\", "/")) for p in src_paths}
    bad_loc = []
    for p in deck["pages"]:
        e = emap.get(p["page"])
        if e is None:
            bad_loc.append(f"page {p['page']}: no evidence_map entry")
            continue
        if e.get("not_derivable"):
            continue
        if e.get("role") in CONTENT_ROLES and not e.get("locator"):
            bad_loc.append(f"page {p['page']}: no locator and no declared reason")
            continue
        quote = (e.get("quote") or "").rstrip("\u2026 ").strip()
        if quote:
            _seg, found, _kind = src.quote_locator(quote)
            if not found:
                bad_loc.append(f"page {p['page']}: the quoted passage is not in the "
                               f"material as delivered")
                continue
        elif e.get("locator"):
            bad_loc.append(f"page {p['page']}: locator with no quotable passage, so the "
                           f"page cannot be re-verified from the material")
            continue
        loc = (e.get("locator") or e.get("verified_locator") or "")
        loc_src = os.path.basename(loc.split(" \u00b7 ")[0].strip().replace("\\", "/"))
        if loc and declared and loc_src and loc_src not in declared:
            bad_loc.append(f"page {p['page']}: cites {loc_src}, which is not a declared source")
    record("A5", "each content page has a verified material locator or a declared reason, "
                 "re-derived from the material",
           {"content_pages": sum(1 for e in emap.values() if e.get("role") in CONTENT_ROLES)},
           {"unresolved": len(bad_loc), "declared_sources": sorted(declared)},
           not bad_loc, bad_loc)

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

    # A9 rendered preview, re-measured here -----------------------------------
    # Deliberately does NOT read render.json: the run's own verification record
    # could agree with itself.  This walks the delivered *files* - the exported
    # PDF and the page PNGs - and counts them again with independent code.
    pv = preview_facts(out_dir, res)
    a9_bad = list(pv["issues"])
    n_slides = deck["slide_count"] or 0
    if n_slides and pv["pdf_pages"] and pv["pdf_pages"] != n_slides:
        a9_bad.append(f"exported PDF has {pv['pdf_pages']} page(s) for {n_slides} slide(s)")
    if n_slides and pv["png_count"] and pv["png_count"] != n_slides:
        a9_bad.append(f"{pv['png_count']} page image(s) for {n_slides} slide(s)")
    geo = deck.get("size_in") or {}
    px = pv.get("first_png_px") or {}
    if geo.get("w") and geo.get("h") and px.get("w") and px.get("h"):
        want = geo["w"] / float(geo["h"])
        got = px["w"] / float(px["h"])
        if abs(got - want) / want > 0.02:
            a9_bad.append(f"page image aspect {got:.3f} != deck aspect {want:.3f}")
    record("A9", "the delivered preview is a real render of this deck "
                 "(pdf pages, page images, aspect, not blank, no undeclared raster)",
           {"deck_slides": n_slides, "deck_size_in": deck.get("size_in")},
           {"pdf": pv["pdf"], "pdf_pages": pv["pdf_pages"],
            "pdf_page_in": pv["pdf_page_in"], "png_pages": pv["png_count"],
            "first_png_px": pv["first_png_px"], "blank_pages": pv["blank_pages"],
            "unexpected_raster": pv.get("unexpected_raster"),
            "binaries": len(pv.get("binaries") or []),
            "measured_by": "audit_deck.preview_facts (reads the artefacts, not render.json)"},
           not a9_bad, a9_bad)

    # A10 sources are scientific material, not task/case/example inputs --------
    # The run is handed a whole folder: task.md, case.json, example and template
    # JSON all sit next to the paper.  If any of them is promoted into
    # ``sources[]`` the deck is no longer derived from the paper - it is quoting
    # the exam paper back.  This check reads the declared list and re-decides
    # material-or-not with the same rule the reader uses.
    src_paths = [s.get("path") or "" for s in (res.get("sources") or [])]
    promoted, absent = [], []
    for p in src_paths:
        base = os.path.basename(p.replace("\\", "/"))
        reason = P.non_material_reason(base)
        if reason:
            promoted.append(f"{p}: {reason}")
        elif not os.path.isfile(os.path.join(out_dir, "..", p)) and \
                not os.path.isfile(p) and not os.path.isabs(p):
            # not an error by itself (materials live outside the output tree);
            # reported so a reviewer can see what could not be re-opened here
            absent.append(p)
    emap_sources = set()
    for e in (res.get("evidence_map") or []):
        loc = (e.get("locator") or e.get("verified_locator") or "").split(" \u00b7 ")[0].strip()
        if loc:
            emap_sources.add(os.path.basename(loc.replace("\\", "/")))
    undeclared = sorted(s for s in emap_sources
                        if src_paths and s and s not in
                        {os.path.basename(p.replace("\\", "/")) for p in src_paths})
    record("A10", "sources[] holds scientific material only, and every cited "
                  "locator belongs to a declared source",
           {"declared_sources": len(src_paths)},
           {"non_material_promoted": promoted, "locators_from_undeclared": undeclared,
            "not_reopenable_here": absent[:4]},
           bool(src_paths) and not promoted and not undeclared,
           promoted + [f"locator from undeclared source: {u}" for u in undeclared] +
           ([] if src_paths else ["result.json declares no sources[]"]))

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


_LOCATOR_RE = re.compile(r"\([^()]{0,400}?[·\u00b7][^()]{0,400}?\)")


def strip_locators(text: str) -> str:
    """Drop parenthesised source locators from a page's text.

    Locators are parenthesised and use ``·`` between coordinates, so this only
    removes citation spans - never a sentence, and never a data value.
    """
    return _LOCATOR_RE.sub(" ", text or "")


def preview_facts(out_dir: str, res: dict) -> dict:
    """Re-count the rendered preview from the delivered files only.

    Independent of ``render.json`` and of ``render.verify``: the PDF is located
    on disk, its page boxes are parsed here, and every page image is measured
    from its own IHDR (and pixels, when Pillow happens to be installed).
    """
    import glob
    out = {"pdf": None, "pdf_pages": None, "pdf_page_in": None, "png_count": 0,
           "first_png_px": None, "blank_pages": [], "issues": []}
    announced = ((res.get("render") or {}).get("pdf")) or ""
    pdfs = [announced] if announced else []
    pdfs += [os.path.basename(p) for p in sorted(glob.glob(os.path.join(out_dir, "*.pdf")))]
    pdf_path = next((os.path.join(out_dir, p) for p in pdfs
                     if p and os.path.isfile(os.path.join(out_dir, p))), None)
    if not pdf_path:
        out["issues"].append("no exported PDF in the output directory")
    else:
        with open(pdf_path, "rb") as fh:
            blob = fh.read()
        out["pdf"] = os.path.basename(pdf_path)
        boxes = re.findall(rb"/MediaBox\s*\[([^\]]{0,120})\]", blob)
        sizes = []
        for b in boxes:
            parts = b.split()
            if len(parts) >= 4:
                try:
                    x0, y0, x1, y1 = (float(v) for v in parts[-4:])
                except ValueError:
                    continue
                sizes.append((abs(x1 - x0), abs(y1 - y0)))
        pages = len(sizes) or len(re.findall(rb"/Type\s*/Page(?![s])", blob))
        out["pdf_pages"] = pages
        if sizes:
            out["pdf_page_in"] = {"w": round(sizes[0][0] / 72.0, 3),
                                  "h": round(sizes[0][1] / 72.0, 3)}
        if pages <= 0:
            out["issues"].append("the exported PDF reports no pages")

    pngs = sorted(glob.glob(os.path.join(out_dir, "slides", "*.png"))) or \
        sorted(glob.glob(os.path.join(out_dir, "**", "slide-*.png"), recursive=True))
    out["png_count"] = len(pngs)
    for p in pngs:
        ok_struct, why = png_intact(p)
        if not ok_struct:
            out["issues"].append(f"{os.path.basename(p)}: {why}")
            continue
        try:
            with open(p, "rb") as fh:
                head = fh.read(33)
        except OSError:
            out["issues"].append(f"cannot read {os.path.basename(p)}")
            continue
        if not head.startswith(b"\x89PNG\r\n\x1a\n") or head[12:16] != b"IHDR":
            out["issues"].append(f"{os.path.basename(p)} is not a PNG")
            continue
        w = int.from_bytes(head[16:20], "big")
        h = int.from_bytes(head[20:24], "big")
        if out["first_png_px"] is None:
            out["first_png_px"] = {"w": w, "h": h}
        try:
            from PIL import Image
            with Image.open(p) as img:
                g = img.convert("L")
                data = list(g.getdata())
                dark = sum(1 for v in data if v < 240)
                if dark / float(len(data) or 1) < 0.002:
                    out["blank_pages"].append(os.path.basename(p))
        except Exception:
            pass
    if not pngs:
        out["issues"].append("no page PNGs in the output directory")
    if out["blank_pages"]:
        out["issues"].append("blank page image(s): " + ", ".join(out["blank_pages"][:4]))

    # The whole output root, not just slides/: a delivery that smuggles a raster
    # ("baseline_reference.png", a screenshot, a traced bitmap) next to the deck
    # is not a vector/editable artefact set, and it used to pass A9 silently
    # because only *.pdf and slides/*.png were ever opened.
    declared = {os.path.basename(x or "") for x in (res.get("render") or {}).get("pngs") or []}
    declared |= {os.path.basename(((res.get("deck") or {}).get("pptx")) or "deck.pptx"),
                 os.path.basename(out["pdf"] or "deck.pdf")}
    unexpected, binaries = [], []
    for root, dirs, files in os.walk(out_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            rel = os.path.relpath(os.path.join(root, name), out_dir).replace("\\", "/")
            if ext in BINARY_EXTS:
                binaries.append(rel)
            if ext in RASTER_EXTS:
                if name in declared and rel.startswith("slides/"):
                    continue
                if name in declared:
                    continue
                unexpected.append(rel)
    out["binaries"] = binaries
    out["unexpected_raster"] = unexpected
    if unexpected:
        out["issues"].append("raster image(s) in the delivery that are not declared page "
                             "previews (an editable deck must not carry a bitmap "
                             "stand-in): " + ", ".join(unexpected[:6]))
    return out


def png_intact(path: str) -> tuple[bool, str]:
    """Walk the PNG chunk chain to the end of the file.

    Pillow tolerates trailing junk and truncated tails; a delivery that claims a
    page preview should end exactly on its ``IEND`` chunk.  This is the byte
    level re-measurement behind "the preview file is really there".
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError as exc:
        return False, f"cannot read ({exc})"
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return False, "missing PNG signature"
    pos, seen_iend = 8, False
    while pos + 8 <= len(blob):
        length = int.from_bytes(blob[pos:pos + 4], "big")
        ctype = blob[pos + 4:pos + 8]
        nxt = pos + 12 + length
        if nxt > len(blob):
            return False, f"chunk {ctype.decode('ascii', 'replace')} runs past EOF"
        if ctype == b"IEND":
            seen_iend = True
            pos = nxt
            break
        pos = nxt
    if not seen_iend:
        return False, "no IEND chunk"
    if pos != size:
        return False, f"{size - pos} trailing byte(s) after IEND"
    return True, "ok"


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="independent auditor for a delivered deck")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--case", default=None)
    ap.add_argument("--report", default=None, help="merge into this selftest report")
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
    # always leave the report next to the artefacts: a reviewer who re-runs this
    # by hand gets the same machine-readable verdict as the automated run, and a
    # tampered delivery cannot hide behind the run's own earlier report.
    try:
        with open(os.path.join(args.out, "audit-deck.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        print(f"WARN could not write audit-deck.json: {exc}", file=sys.stderr)
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
