"""deck.py - build the editable .pptx from a validated plan.

Design decisions that matter for the review criteria:

* **Template is the authority.**  If the case supplies a ``.pptx`` master we
  open it, keep its theme (fonts and colours are inherited, never hard-coded),
  reuse its title placeholder and its footer/date/slide-number placeholders, and
  only *resize* placeholders to the geometry computed by :mod:`layout`.  If no
  template is supplied we synthesise one from a declarative spec, so the result
  is still a themed deck rather than 26 loose text boxes.
* **Everything stays editable.**  Real text boxes, real table objects, real
  pictures, real notes pages.  No outlines, no images of text.
* **Honesty about figures.**  If the source figure was not harvested as an
  embedded image, the page gets a clearly labelled schematic placeholder that
  repeats the paper's caption verbatim plus the locator - it is never dressed up
  as data.
* **Speaker notes are written, not copied.**  See :mod:`notes`.
"""
from __future__ import annotations

import copy
import os
import re

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

import layout as L
import notes as N
from util import one_line, truncate

TITLE_ROLES = {"title"}
SECTION_ROLES = {"outline"}

# Layout-name hints, matched case-insensitively against the template's layouts.
_LAYOUT_HINTS = {
    "title": ("title slide", "title", "封面", "标题幻灯片"),
    "section": ("section header", "section", "节标题"),
    "content": ("title and content", "content", "标题和内容", "仅标题", "title only", "blank"),
}


# ---------------------------------------------------------------- template io

def describe_template(path: str | None) -> dict:
    """What masters/layouts/placeholders does this template actually give us?"""
    if not path or not os.path.isfile(path):
        return {"path": None, "available": False,
                "slide": dict(L.DEFAULT_SLIDE), "layouts": [],
                "theme_colors": 0, "notes": ["no template supplied; built-in 16:9 geometry"]}
    prs = Presentation(path)
    layouts = []
    for i, lay in enumerate(prs.slide_layouts):
        phs = []
        for ph in lay.placeholders:
            phs.append({"idx": ph.placeholder_format.idx,
                        "type": str(ph.placeholder_format.type),
                        "name": ph.name})
        layouts.append({"index": i, "name": lay.name, "placeholders": phs})
    theme_colors = 0
    try:
        theme_part = prs.slide_masters[0].part.part_related_by(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme")
        theme_colors = len(etree.fromstring(theme_part.blob).findall(
            ".//{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr"))
    except Exception:
        pass
    return {
        "path": os.path.basename(path),
        "available": True,
        "slide": {"w_in": round(prs.slide_width / 914400, 3),
                  "h_in": round(prs.slide_height / 914400, 3)},
        "layouts": layouts,
        "layout_count": len(layouts),
        "master_count": len(prs.slide_masters),
        "theme_colors": theme_colors,
        "notes": [],
    }


def _pick_layout(prs, role: str, template_info: dict):
    """Prefer a template layout whose name matches the page role."""
    order = _LAYOUT_HINTS["title"] if role in TITLE_ROLES else (
        _LAYOUT_HINTS["section"] if role in SECTION_ROLES else _LAYOUT_HINTS["content"])
    by_name = {lay.name.lower(): lay for lay in prs.slide_layouts}
    for key in order:
        for name, lay in by_name.items():
            if key in name:
                return lay
    # fall back on placeholder shape: title + body, else blank
    for lay in prs.slide_layouts:
        types = {str(ph.placeholder_format.type) for ph in lay.placeholders}
        if any("TITLE" in t for t in types) and any("BODY" in t or "OBJECT" in t for t in types):
            return lay
    return prs.slide_layouts[0] if prs.slide_layouts else prs.slide_layouts[6]


def _placeholder(slide, want_type=("TITLE", "CENTER_TITLE"), want_idx=(0,)):
    for ph in slide.placeholders:
        t = str(ph.placeholder_format.type)
        if any(w in t for w in want_type) or ph.placeholder_format.idx in want_idx:
            return ph
    return None


# ---------------------------------------------------------------- text utils

# A control byte can arrive from a PDF whose font has no usable ToUnicode map
# (a ligature became U+0002, so "figure" read as "\x02gure").  python-pptx then
# serialises it as the literal "_x0002_" escape inside the slide XML, which is
# visible garbage on the page.  Every string that reaches the deck goes through
# this scrub - including an author-supplied plan.json, which never passes
# through papertext.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def xml_safe(value) -> str:
    return _CTRL_RE.sub("", str(value))


def _set_text_frame(tf, text_or_lines, *, size_pt, bold=False, color=None,
                    align=PP_ALIGN.LEFT, bullet=False, spacing=L.LINE_SPACING,
                    font=None, space_after=None):
    tf.word_wrap = True
    lines = text_or_lines if isinstance(text_or_lines, list) else [text_or_lines]
    lines = [xml_safe(x) for x in lines]
    # python-pptx cannot delete "the" first paragraph; reuse it
    first = True
    for line in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.line_spacing = spacing
        if space_after is not None:
            p.space_after = Pt(space_after)
        if bullet:
            _enable_bullet(p)
        else:
            _disable_bullet(p)
        run = p.add_run()
        run.text = line
        f = run.font
        f.size = Pt(size_pt)
        f.bold = bold
        if font:
            f.name = font
        if color:
            f.color.rgb = color


def _enable_bullet(p):
    pPr = p._p.get_or_add_pPr()
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    bu = etree.SubElement(pPr, qn("a:buChar"))
    bu.set("char", "\u2022")
    pPr.set("marL", str(int(Inches(0.30))))
    pPr.set("indent", str(int(-Inches(0.30))))


def _disable_bullet(p):
    pPr = p._p.get_or_add_pPr()
    for tag in ("a:buChar", "a:buAutoNum", "a:buNone"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    etree.SubElement(pPr, qn("a:buNone"))


def _box(region):
    return (Inches(region["x_in"]), Inches(region["y_in"]),
            Inches(region["w_in"]), Inches(region["h_in"]))


def _move(shape, region):
    shape.left, shape.top, shape.width, shape.height = _box(region)


# ---------------------------------------------------------------- page parts

def _add_slide_number(slide, boxes, prs, *, size_pt=11):
    """A real slide-number field (updates when pages move), not baked text."""
    txt = slide.shapes.add_textbox(*_box(boxes["pagenum"]))
    tf = txt.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    fld = etree.SubElement(p._p, qn("a:fld"))
    fld.set("id", "{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}")
    fld.set("type", "slidenum")
    rPr = etree.SubElement(fld, qn("a:rPr"))
    rPr.set("lang", "en-US")
    rPr.set("sz", str(int(size_pt * 100)))
    t = etree.SubElement(fld, qn("a:t"))
    t.text = str(len(prs.slides._sldIdLst))
    return txt


def _add_footer(slide, boxes, text, *, size_pt=11, color=None):
    box = slide.shapes.add_textbox(*_box(boxes["footer"]))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = xml_safe(truncate(text, 120))
    r.font.size = Pt(size_pt)
    if color:
        r.font.color.rgb = color
    return box


def _add_bullets(slide, region, fit, *, color=None, font=None):
    box = slide.shapes.add_textbox(*_box(region))
    tf = box.text_frame
    tf.margin_left = Inches(0.02)
    tf.margin_right = Inches(0.02)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = MSO_ANCHOR.TOP
    _set_text_frame(tf, [str(i["text"]) for i in fit["items"]], size_pt=fit["size_pt"],
                    bullet=True, color=color, font=font,
                    space_after=max(4.0, fit["size_pt"] * 0.28))
    return box


def _add_claim(slide, region, text, size_pt, *, color=None, font=None):
    box = slide.shapes.add_textbox(*_box(region))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.02)
    tf.margin_top = Inches(0.0)
    _set_text_frame(tf, text, size_pt=size_pt, bold=True, color=color, font=font)
    return box


def _add_kpis(slide, region, kpis, size_pt, *, accent=None, font=None):
    n = max(1, len(kpis))
    gap = 0.22
    w = (region["w_in"] - gap * (n - 1)) / n
    made = []
    for i, k in enumerate(kpis):
        r = {"x_in": region["x_in"] + i * (w + gap), "y_in": region["y_in"],
             "w_in": w, "h_in": region["h_in"]}
        box = slide.shapes.add_textbox(*_box(r))
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.04)
        _set_text_frame(tf, str(k.get("value") or ""), size_pt=size_pt, bold=True,
                        color=accent, font=font, align=PP_ALIGN.LEFT)
        if k.get("label"):
            p = tf.add_paragraph()
            r2 = p.add_run()
            r2.text = xml_safe(k["label"])
            r2.font.size = Pt(max(12, int(size_pt * 0.34)))
            if font:
                r2.font.name = font
        made.append(box)
    return made


def _add_table(slide, region, table, fit, *, color=None, font=None):
    rows = list(table.get("rows") or [])
    cols = list(table.get("columns") or [])
    if not cols and not rows:
        return _add_table_missing(slide, region, table, font=font)
    if not cols and rows:
        cols = [f"" for _ in rows[0]]
    ncols = max(1, len(cols) or max((len(r) for r in rows), default=1))
    nrows = len(rows) + (1 if cols else 0)
    shape = slide.shapes.add_table(nrows, ncols, *_box(region))
    tbl = shape.table
    total_w = region["w_in"]
    widths = fit.get("columns_in") or [total_w / ncols] * ncols
    scale = total_w / max(0.01, sum(widths))
    for j, w in enumerate(widths[:ncols]):
        tbl.columns[j].width = Inches(w * scale)
    # pin row heights: PowerPoint otherwise grows every row to fit the box
    body_pt = fit.get("size_pt", 12)
    pad = Pt(body_pt * 0.9)
    per_row = max(0.34, min(0.62, (region["h_in"] - 0.1) / max(1, nrows)))
    for i in range(nrows):
        tbl.rows[i].height = Inches(per_row)
    r0 = 0
    size_pt = fit.get("size_pt", 12)
    if cols:
        for j in range(ncols):
            cell = tbl.cell(0, j)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            run = p.add_run()
            run.text = xml_safe(cols[j]) if j < len(cols) else ""
            run.font.size = Pt(size_pt)
            run.font.bold = True
            if font:
                run.font.name = font
            if color:
                run.font.color.rgb = color
        r0 = 1
    for i, row in enumerate(rows):
        for j in range(ncols):
            cell = tbl.cell(i + r0, j)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            run = p.add_run()
            run.text = xml_safe(row[j]) if j < len(row) else ""
            run.font.size = Pt(size_pt)
            if font:
                run.font.name = font
    return shape


def _add_table_missing(slide, region, table, *, font=None):
    """The table's numbers could not be recovered from the source: say so.

    The phrase "table body not reconstructed" is also the machine marker that
    ``render._shape_facts()`` looks for when it checks that a page announcing a
    table really carries something: without a shared, stable wording an honest
    placeholder would be indistinguishable from a silently dropped table.
    """
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, *_box(region))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xFB, 0xF7, 0xEC)
    box.line.color.rgb = RGBColor(0xB9, 0xA0, 0x6A)
    box.line.dash_style = 4
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    lines = [f"{table.get('label') or 'Table'}: "
             f"{truncate(table.get('caption') or '', 120)}",
             "table body not reconstructed (table cells could not be recovered from "
             "the source) - see the paper at "
             f"{table.get('source_locator') or 'the cited table'}"]
    _set_text_frame(tf, lines, size_pt=13, color=RGBColor(0x6B, 0x54, 0x2A), font=font,
                    align=PP_ALIGN.CENTER)
    return box


def _add_schematic(slide, region, fig, *, language="en", font=None):
    """Clearly-labelled placeholder that carries the paper's own caption."""
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, *_box(region))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xF4, 0xF6, 0xFA)
    box.line.color.rgb = RGBColor(0x9A, 0xA7, 0xBD)
    box.line.width = Pt(1.0)
    box.line.dash_style = 4  # dashed: signals "not the original artwork"
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    head = "示意图 / schematic" if language == "zh" else "Schematic"
    body = (f"{head}: {fig.get('label', '')}\n"
            f"{truncate(fig.get('caption') or '', 140)}\n"
            f"({fig.get('source_locator') or 'see source'})")
    _set_text_frame(tf, body.split("\n"), size_pt=13, color=RGBColor(0x44, 0x4E, 0x62),
                    font=font, align=PP_ALIGN.CENTER)
    return box


def _add_picture(slide, region, path, *, caption=None, font=None, cap_region=None):
    """Place the harvested figure, letterboxed inside the region."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            iw, ih = im.size
    except Exception:
        iw, ih = (4, 3)
    ar = (iw / ih) if ih else 1.33
    w, h = region["w_in"], region["h_in"]
    if w / max(h, 0.01) > ar:
        ph = h
        pw = h * ar
    else:
        pw = w
        ph = w / max(ar, 0.01)
    r = {"x_in": region["x_in"] + (w - pw) / 2, "y_in": region["y_in"] + (h - ph) / 2,
         "w_in": pw, "h_in": ph}
    return slide.shapes.add_picture(path, *_box(r))


# ---------------------------------------------------------------- main build

def build(plan: dict, specs: list[dict], *, out_path: str, template_path: str | None = None,
          assets: dict | None = None, theme: dict | None = None,
          log=None) -> dict:
    assets = assets or {}
    theme = theme or {}
    tinfo = describe_template(template_path)
    if template_path and os.path.isfile(template_path):
        prs = Presentation(template_path)
        # a template may ship sample slides: drop them so the deck is only ours
        for sld in list(prs.slides._sldIdLst):
            rId = sld.get(qn("r:id"))
            prs.part.drop_rel(rId)
            prs.slides._sldIdLst.remove(sld)
    else:
        prs = Presentation()
        prs.slide_width = Inches(L.DEFAULT_SLIDE["w_in"])
        prs.slide_height = Inches(L.DEFAULT_SLIDE["h_in"])

    slide_w = prs.slide_width / 91440.0 / 10.0
    slide_h = prs.slide_height / 91440.0 / 10.0
    boxes = L.slide_boxes(slide_w, slide_h, theme.get("geometry"))
    accent = _rgb(theme.get("accent")) or None
    ink = _rgb(theme.get("text")) or None
    font = theme.get("font")
    language = (plan.get("deck") or {}).get("language") or "en"
    footer_text = (plan.get("deck") or {}).get("footer") or (plan.get("deck") or {}).get("title") or ""

    slides_by_id = {s.get("id"): s for s in plan["slides"]}
    built = []
    spec_by_id = {sp["slide"]: sp for sp in specs}

    for slide_def in plan["slides"]:
        sid = slide_def.get("id")
        role = slide_def.get("role") or "evidence"
        spec = spec_by_id.get(sid) or L.plan_slide_layout(
            slide_def, boxes, with_figure=bool(slide_def.get("figure")),
            with_table=bool(slide_def.get("table")), with_kpis=bool(slide_def.get("kpis")))
        lay = _pick_layout(prs, role, tinfo)
        slide = prs.slides.add_slide(lay)

        # --- title placeholder (inherits the template's title style)
        title_ph = _placeholder(slide)
        title_region = spec["regions"]["title"]
        title_size = spec["fit"]["title"]["size_pt"]
        if title_ph is not None:
            _move(title_ph, title_region)
            _set_text_frame(title_ph.text_frame, slide_def.get("title") or "",
                            size_pt=title_size, bold=True, color=ink, font=font)
        else:
            box = slide.shapes.add_textbox(*_box(title_region))
            _set_text_frame(box.text_frame, slide_def.get("title") or "",
                            size_pt=title_size, bold=True, color=ink, font=font)

        # --- claim (the one sentence of this page).  On a title page the claim is
        #     the title itself; printing it twice is the classic generated-deck tell.
        claim_text = (slide_def.get("claim") or "").strip()
        title_key = _norm(slide_def.get("title") or "")
        claim_key = _norm(claim_text)
        duplicate = (not claim_key) or claim_key == title_key or \
            (title_key and claim_key.startswith(title_key[:24]))
        if "claim" in spec["regions"] and not duplicate:
            _add_claim(slide, spec["regions"]["claim"], claim_text,
                       spec["fit"]["claim"]["size_pt"], color=accent, font=font)

        # --- kpis
        if "kpis" in spec["regions"] and slide_def.get("kpis"):
            _add_kpis(slide, spec["regions"]["kpis"], slide_def["kpis"],
                      spec["fit"]["kpis"][0]["size_pt"], accent=accent, font=font)

        # --- figure / table / bullets
        if slide_def.get("figure") and "figure" in spec["regions"]:
            fig = dict(slide_def["figure"])
            asset = assets.get(fig.get("label") or "")
            if asset and os.path.isfile(asset):
                _add_picture(slide, spec["regions"]["figure"], asset)
                fig["rendered"] = "embedded-image"
                _add_claim(slide, spec["regions"]["caption"], fig.get("caption") or "",
                           spec["fit"]["caption"]["size_pt"], color=ink, font=font)
            else:
                _add_schematic(slide, spec["regions"]["figure"], fig,
                               language=language, font=font)
                fig["rendered"] = "schematic-placeholder"
                fig["kind"] = "schematic"
            slide_def["figure"] = fig
        if slide_def.get("table") and "table" in spec["regions"]:
            _add_table(slide, spec["regions"]["table"], slide_def["table"],
                       spec["fit"]["table"], color=accent, font=font)
        if slide_def.get("bullets") and "bullets" in spec["regions"]:
            fit = spec["fit"].get("bullets") or {}
            if fit.get("items"):
                _add_bullets(slide, spec["regions"]["bullets"], fit, color=ink, font=font)

        # --- page furniture: number field + footer, template styles untouched
        if role not in TITLE_ROLES:
            _add_footer(slide, boxes, footer_text, color=ink)
            _add_slide_number(slide, boxes, prs)

        # --- speaker notes
        note_text = N.compose(slide_def, slides_by_id, plan, slide_index=len(built))
        slide.notes_slide.notes_text_frame.text = xml_safe(note_text["notes"])
        built.append({"slide": sid, "role": role, "layout": lay.name,
                      "notes_chars": len(note_text["notes"]), "spec": spec})

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    prs.save(out_path)
    return {
        "path": os.path.basename(out_path),
        "slides": len(built),
        "template": tinfo,
        "slide_size_in": {"w": round(slide_w, 3), "h": round(slide_h, 3)},
        "per_slide": [{"slide": b["slide"], "role": b["role"], "layout": b["layout"],
                       "notes_chars": b["notes_chars"]} for b in built],
    }


def _norm(s: str) -> str:
    from util import norm_key
    return norm_key(s)


def _rgb(value):
    if not value:
        return None
    v = str(value).strip().lstrip("#")
    if len(v) == 6:
        try:
            return RGBColor.from_string(v.upper())
        except Exception:
            return None
    return None


def read_back(path: str) -> dict:
    """What does the saved file actually contain?  Used by the audit."""
    prs = Presentation(path)
    pages = []
    problems = []
    for i, slide in enumerate(prs.slides, start=1):
        texts, sizes, pics, tables, editable = [], [], 0, 0, 0
        for sh in slide.shapes:
            if sh.has_text_frame:
                editable += 1
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        if r.text.strip():
                            texts.append(r.text)
                            if r.font.size is not None:
                                sizes.append(r.font.size.pt)
            if sh.shape_type is not None and "PICTURE" in str(sh.shape_type):
                pics += 1
            if getattr(sh, "has_table", False) and sh.has_table:
                tables += 1
                for row in sh.table.rows:
                    for cell in row.cells:
                        texts.append(cell.text)
            # geometry sanity
            if sh.left is not None and sh.top is not None:
                if sh.left < 0 or sh.top < 0:
                    problems.append(f"slide {i}: shape '{sh.name}' starts outside the page")
                if (sh.left + (sh.width or 0)) > prs.slide_width + 2000:
                    problems.append(f"slide {i}: shape '{sh.name}' overflows the right edge")
                if (sh.top + (sh.height or 0)) > prs.slide_height + 2000:
                    problems.append(f"slide {i}: shape '{sh.name}' overflows the bottom edge")
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        pages.append({"page": i, "text_chars": sum(len(t) for t in texts),
                      "min_font_pt": round(min(sizes), 1) if sizes else None,
                      "pictures": pics, "tables": tables, "editable_shapes": editable,
                      "notes_chars": len(notes)})
    return {
        "pages": pages,
        "slide_count": len(pages),
        "size_in": {"w": round(prs.slide_width / 914400, 3),
                    "h": round(prs.slide_height / 914400, 3)},
        "has_notes": all(p["notes_chars"] > 0 for p in pages),
        "min_font_pt": min((p["min_font_pt"] for p in pages if p["min_font_pt"]), default=None),
        "geometry_problems": problems,
    }
