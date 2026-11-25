# -*- coding: utf-8 -*-
"""pptx_util.py —— OOXML/python-pptx 底层工具。

这里集中处理 python-pptx 没有直接暴露、但「真实套用模板」必须做的事：
  * 读模板的**主题字体**（major/minor 的 latin/ea/cs + a:font script 表）与**主题色**（12 色）；
  * 解析每个**版式（layout）**的占位符（idx/type/名称/几何，几何缺失时回溯母版）；
  * 清空模板自带示例页 / 从指定版式建页（保留母版-版式-占位符继承链）；
  * 把版式上的 footer/slide-number 占位符**克隆**到页面（否则页脚页眉不显示）；
  * 逐 run 写 latin/ea/cs 字体（中文必须走 a:ea，否则渲染端按 latin 字体回退导致版式错乱）；
  * 项目符号、normAutofit、页码域（a:fld type="slidenum"）、备注页、等比插图。

所有写 XML 的地方都按 schema 顺序插入（python-pptx 的 insert_element_before），
避免 PowerPoint 报"需要修复"。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）
import tempfile
import zipfile

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls

import units

try:  # python-pptx >= 0.6.19
    from pptx.shapes.autoshape import Shape as _Shape  # noqa: F401
except Exception:  # pragma: no cover
    pass


# ------------------------------------------------------------------ 载入

def load(path: str) -> Presentation:
    return Presentation(path)


def strip_slides(prs: Presentation) -> int:
    """删掉模板/起始稿里已有的示例页，只保留母版与版式（继承链不动）。"""
    removed = 0
    sld_id_lst = prs.slides._sldIdLst
    for sld_id in list(sld_id_lst):
        rId = sld_id.get(qn("r:id"))
        try:
            prs.part.drop_rel(rId)
        except Exception:
            pass
        sld_id_lst.remove(sld_id)
        removed += 1
    return removed


def slide_size(prs: Presentation) -> dict:
    return {"width_emu": int(prs.slide_width), "height_emu": int(prs.slide_height),
            "width_in": prs.slide_width / 914400.0,
            "height_in": prs.slide_height / 914400.0,
            "aspect": round(prs.slide_width / float(prs.slide_height), 4),
            "ratio_label": _ratio_label(prs.slide_width, prs.slide_height)}


def _ratio_label(w: int, h: int) -> str:
    a = w / float(h)
    for label, val in (("16:9", 16 / 9.0), ("4:3", 4 / 3.0), ("16:10", 1.6),
                       ("3:2", 1.5), ("A4-portrait", 210 / 297.0),
                       ("A4-landscape", 297 / 210.0)):
        if abs(a - val) < 0.02:
            return label
    return "%.3f:1" % a


# ------------------------------------------------------------------ 主题

_DEFAULT_CLR = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3",
                "accent4", "accent5", "accent6", "hlink", "folHlink"]


def theme_info(pptx_path: str) -> dict:
    """从 pptx 包里直接读 theme1.xml（比走 python-pptx 对象模型更稳，版本无关）。"""
    out = {"themes": [], "fonts": {}, "colors": {}, "font_scripts": {},
           "source": "ppt/theme/theme1.xml"}
    try:
        zf = zipfile.ZipFile(pptx_path)
    except Exception as exc:
        out["error"] = "cannot open pptx zip: %s" % exc
        return out
    with zf:
        names = [n for n in zf.namelist() if n.startswith("ppt/theme/theme") and n.endswith(".xml")]
        names.sort()
        master_theme = None
        try:
            rels = zf.read("ppt/slideMasters/_rels/slideMaster1.xml.rels").decode("utf-8", "replace")
            for part in rels.split("<Relationship"):
                if "theme" in part:
                    import re
                    m = re.search(r'Target="([^"]+)"', part)
                    if m:
                        t = m.group(1).lstrip("/")
                        master_theme = t if t.startswith("ppt/") else "ppt/" + t.replace("../", "")
        except KeyError:
            pass
        if master_theme and master_theme in names:
            names = [master_theme] + [n for n in names if n != master_theme]
        out["themes"] = names
        if not names:
            out["error"] = "no theme part"
            return out
        xml = zf.read(names[0]).decode("utf-8", "replace")
        out["source"] = names[0]
        import re
        fs = re.search(r"<a:fontScheme.*?</a:fontScheme>", xml, re.S)
        if fs:
            blob = fs.group(0)
            for kind in ("majorFont", "minorFont"):
                km = re.search(r"<a:%s>(.*?)</a:%s>" % (kind, kind), blob, re.S)
                if not km:
                    continue
                part = km.group(1)
                fonts = {}
                for tag in ("latin", "ea", "cs"):
                    m = re.search(r"<a:%s typeface=\"([^\"]*)\"" % tag, part)
                    fonts[tag] = m.group(1) if m else ""
                scripts = dict(re.findall(r"<a:font script=\"([^\"]+)\" typeface=\"([^\"]*)\"", part))
                out["fonts"][kind] = fonts
                out["font_scripts"][kind] = scripts
        cs = re.search(r"<a:clrScheme.*?</a:clrScheme>", xml, re.S)
        if cs:
            blob = cs.group(0)
            for name in _DEFAULT_CLR:
                m = re.search(r"<a:%s>(.*?)</a:%s>" % (name, name), blob, re.S)
                if not m:
                    continue
                body = m.group(1)
                sm = re.search(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', body)
                ym = re.search(r'lastClr="([0-9A-Fa-f]{6})"', body)
                val = sm.group(1).upper() if sm else (ym.group(1).upper() if ym else None)
                out["colors"][name] = val
    return out


# ------------------------------------------------------------------ 版式与占位符

_ROLE_BY_PH = {
    PP_PLACEHOLDER.TITLE: "title", PP_PLACEHOLDER.CENTER_TITLE: "title",
    PP_PLACEHOLDER.SUBTITLE: "subtitle", PP_PLACEHOLDER.BODY: "body",
    PP_PLACEHOLDER.OBJECT: "object", PP_PLACEHOLDER.PICTURE: "picture",
    PP_PLACEHOLDER.CHART: "chart", PP_PLACEHOLDER.TABLE: "table",
    PP_PLACEHOLDER.DATE: "date", PP_PLACEHOLDER.FOOTER: "footer",
    PP_PLACEHOLDER.SLIDE_NUMBER: "slide_number", PP_PLACEHOLDER.HEADER: "header",
    PP_PLACEHOLDER.VERTICAL_BODY: "body", PP_PLACEHOLDER.VERTICAL_TITLE: "title",
}


# 占位符**名称**兜底识别（中文模板场景：cNvPr/@name 是「标题 1」「内容占位符 3」这类）。
# 顺序有意义："副标题" 里含 "标题"，必须先判 subtitle。
_PH_NAME_HINTS = (
    ("subtitle", ("副标题", "subtitle", "sub-title")),
    ("title", ("标题", "題", "title")),
    ("slide_number", ("幻灯片编号", "页码", "slide number", "slidenum")),
    ("body", ("内容占位符", "正文", "文本占位符", "内容", "body", "text placeholder",
              "content placeholder", "vertical text")),
    ("picture", ("图片", "圖", "picture", "image")),
    ("table", ("表格", "table")),
    ("chart", ("图表", "chart")),
    ("footer", ("页脚", "頁腳", "footer")),
    ("date", ("日期", "date")),
)


def ph_kind(ph) -> str:
    """占位符角色。先按 OOXML type（语言无关），type 缺失/未收录时按**名称**（中文模板）兜底。"""
    try:
        t = ph.placeholder_format.type
    except Exception:
        t = None
    kind = _ROLE_BY_PH.get(t)
    if kind:
        return kind
    name = ""
    try:
        name = getattr(ph, "name", "") or ""
    except Exception:
        name = ""
    if name:
        low = name.lower()
        for k, hints in _PH_NAME_HINTS:
            if any(h in low or h in name for h in hints):
                return k
    return "other" if t is None else str(t).lower()


def _master_geometry(layout):
    """版式占位符没写几何时，回溯母版里同名/同 idx 的占位符。"""
    try:
        master = layout.slide_master
    except Exception:
        return {}
    out = {}
    for mph in master.placeholders:
        try:
            key = (int(mph.placeholder_format.idx), ph_kind(mph))
        except Exception:
            continue
        out[key] = {"left": mph.left, "top": mph.top, "width": mph.width, "height": mph.height}
    return out


def layout_info(layout, index: int) -> dict:
    master_geo = _master_geometry(layout)
    phs = []
    for ph in layout.placeholders:
        try:
            idx = int(ph.placeholder_format.idx)
        except Exception:
            idx = -1
        kind = ph_kind(ph)
        geo = {"left": ph.left, "top": ph.top, "width": ph.width, "height": ph.height}
        inherited = False
        if geo["width"] is None or geo["height"] is None:
            mg = master_geo.get((idx, kind)) or {}
            for k in geo:
                if geo[k] is None:
                    geo[k] = mg.get(k)
                    inherited = inherited or mg.get(k) is not None
        name = ""
        try:
            name = ph.name
        except Exception:
            name = ""
        phs.append({
            "idx": idx, "kind": kind, "name": name,
            "geometry": {k: (int(v) if v is not None else None) for k, v in geo.items()},
            "geometry_from_master": inherited,
            "has_text_frame": bool(getattr(ph, "has_text_frame", False)),
        })
    return {
        "index": index,
        "name": layout.name,
        "placeholders": phs,
        "placeholder_kinds": [p["kind"] for p in phs],
        "role_guess": classify_layout(phs, layout.name),
    }


def classify_layout(phs: list, name: str = "") -> str:
    """按占位符构成（而非仅版式名）猜角色，模板改过名也能认。

    判定顺序：先看"版式名"里的强信号（section / title only / blank / agenda），
    再看占位符构成；两者都不像时按 content 兜底并让 audit 记录低置信。
    """
    kinds = [p["kind"] for p in phs]
    n_name = (name or "").lower()
    has_title = "title" in kinds or "subtitle" in kinds
    bodies = [k for k in kinds if k in ("body", "object")]
    if not kinds:
        return "blank"
    # 名称强信号（中文模板常见「节标题 / 仅标题 / 空白」）
    if any(w in n_name for w in ("section header", "section", "节标题", "章节标题")):
        return "section"
    if any(w in n_name for w in ("title only", "仅标题")):
        return "title-only"
    if any(w in n_name for w in ("blank", "空白")):
        return "blank"
    if any(w in n_name for w in ("agenda", "outline", "目录", "提纲")):
        return "agenda"
    if "picture" in kinds and has_title:
        return "figure"
    if has_title and "subtitle" in kinds and not bodies:
        return "title"
    if has_title and len(bodies) >= 2:
        return "two-column"
    if has_title and bodies:
        return "content"
    if has_title and not bodies:
        return "title-only"
    return "content" if bodies else "blank"


def all_layouts(prs: Presentation) -> list:
    return [layout_info(l, i) for i, l in enumerate(prs.slide_layouts)]


# 角色 → 版式名/占位符构成 的匹配规则（templates/layout_roles.json 可覆盖）
DEFAULT_ROLE_RULES = {
    "title": {"prefer_names": ["title slide", "标题幻灯片", "标题"], "roles": ["title"]},
    "agenda": {"prefer_names": ["agenda", "outline", "目录", "content"], "roles": ["content"]},
    "section": {"prefer_names": ["section header", "节标题", "章节"], "roles": ["section"]},
    "bullets": {"prefer_names": ["title and content", "内容", "content"], "roles": ["content"]},
    "two-column": {"prefer_names": ["two content", "比较", "两栏", "comparison"],
                   "roles": ["two-column"]},
    "figure": {"prefer_names": ["picture with caption", "图片", "内容", "content", "figure"],
               "roles": ["figure", "content"]},
    "closing": {"prefer_names": ["title slide", "标题幻灯片", "blank", "空白"],
                "roles": ["title", "section", "blank"]},
}


def pick_layout(prs: Presentation, role: str, rules: dict | None = None,
                explicit: str | int | None = None):
    """按角色选版式，返回 (layout, info, rationale)。explicit 支持名称子串或序号。"""
    infos = all_layouts(prs)
    if explicit is not None:
        for info in infos:
            if isinstance(explicit, int) and info["index"] == explicit:
                return prs.slide_layouts[info["index"]], info, "explicit index"
        for info in infos:
            if isinstance(explicit, str) and explicit.lower() in (info["name"] or "").lower():
                return prs.slide_layouts[info["index"]], info, "explicit name"
    rule = (rules or DEFAULT_ROLE_RULES).get(role) or {"roles": ["content"]}
    want_roles = rule.get("roles") or ["content"]
    best, best_score, why = None, -1.0, ""
    for info in infos:
        score = 0.0
        nm = (info["name"] or "").lower()
        for i, pn in enumerate(rule.get("prefer_names") or []):
            if pn.lower() in nm:
                score += 3.0 - 0.25 * i
        if info["role_guess"] == want_roles[0]:
            score += 2.0
        elif info["role_guess"] in want_roles:
            score += 1.0
        elif info["role_guess"] in ("blank",):
            score += 0.1
        else:
            score -= 1.0
        if score > best_score:
            best, best_score, why = info, score, "name/placeholder match (score=%.2f)" % score
    if best is None:
        best = infos[0]
    return prs.slide_layouts[best["index"]], best, why


def content_placeholder(layout_or_slide, prefer=("body", "object")):
    for ph in layout_or_slide.placeholders:
        if ph_kind(ph) in prefer:
            return ph
    return None


# ------------------------------------------------------------------ 页面与占位符写入

def new_slide(prs: Presentation, layout):
    return prs.slides.add_slide(layout)


def clone_placeholder(slide, layout_ph):
    """把版式上的占位符（footer / slide number / date）克隆到页面。

    python-pptx 的 add_slide 不克隆 latent 占位符，导致页脚/页码在 PowerPoint 里
    就是不显示。这里手动 deepcopy，并保证 cNvPr@id 唯一。
    """
    el = copy.deepcopy(layout_ph._element)
    spTree = slide.shapes._spTree
    # 唯一 shape id
    used = set()
    for e in spTree.iter():
        v = e.get("id")
        if v and v.isdigit():
            used.add(int(v))
    nv = el.find(".//" + qn("p:cNvPr"))
    if nv is not None:
        new_id = max(used) + 1 if used else 2
        nv.set("id", str(new_id))
    spTree.append(el)
    try:
        from pptx.shapes.autoshape import Shape
        return Shape(el, None)
    except Exception:
        return None


def slide_by_layout_name(prs, name_sub: str):
    for i, l in enumerate(prs.slide_layouts):
        if name_sub.lower() in (l.name or "").lower():
            return i
    return None


def set_run_fonts(run, latin: str | None = None, ea: str | None = None,
                  cs: str | None = None, size_pt: float | None = None,
                  bold: bool | None = None, italic: bool | None = None,
                  color_rgb: str | None = None, language: str = "zh-CN"):
    """逐 run 写字体。中文必须落在 a:ea —— 只写 a:latin 会让 CJK 走渲染端默认回退。"""
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color_rgb:
        from pptx.dml.color import RGBColor
        rgb = color_rgb.lstrip("#")
        run.font.color.rgb = RGBColor.from_string(rgb.upper())
    if latin:
        run.font.name = latin  # → a:latin
    rPr = run._r.get_or_add_rPr()
    rPr.set("lang", language)
    rPr.set("altLang", "en-US" if language.startswith("zh") else "zh-CN")
    for tag, face in (("a:ea", ea), ("a:cs", cs)):
        if not face:
            continue
        el = rPr.find(qn(tag))
        if el is None:
            el = parse_xml('<%s %s typeface=""/>' % (tag, nsdecls("a")))
            rPr.insert_element_before(el, "a:cs", "a:sym", "a:hlinkClick",
                                      "a:hlinkMouseOver", "a:rtl", "a:extLst")
        el.set("typeface", face)
    return run


def add_paragraph(tf, text: str, size_pt: float, latin: str, ea: str,
                  level: int = 0, bold: bool = False, bullet: bool = True,
                  align: str = "left", space_before_pt: float = 0.0,
                  space_after_pt: float = 0.0, line_spacing: float = 1.0,
                  color_rgb: str | None = None, italic: bool = False):
    p = tf.add_paragraph()
    p.level = level
    run = p.add_run()
    run.text = text
    set_run_fonts(run, latin=latin, ea=ea, size_pt=size_pt, bold=bold,
                  color_rgb=color_rgb, italic=italic)
    pPr = p._p.get_or_add_pPr()
    pPr.set("algn", {"left": "l", "center": "ctr", "right": "r",
                     "justify": "just"}.get(align, "l"))
    if line_spacing and line_spacing != 1.0:
        ln = parse_xml('<a:lnSpc %s><a:spcPct val="%d"/></a:lnSpc>'
                       % (nsdecls("a"), int(line_spacing * 100000)))
        pPr.insert_element_before(ln, "a:spcBef", "a:spcAft", "a:buClrTx", "a:buClr",
                                  "a:buSzTx", "a:buSzPct", "a:buSzPts", "a:buFontTx",
                                  "a:buFont", "a:buNone", "a:buAutoNum", "a:buChar",
                                  "a:tabLst", "a:defRPr", "a:extLst")
    for tag, val in (("a:spcBef", space_before_pt), ("a:spcAft", space_after_pt)):
        if val:
            el = parse_xml('<%s %s><a:spcPts val="%d"/></%s>'
                           % (tag, nsdecls("a"), int(val * 100), tag))
            if tag == "a:spcBef":
                pPr.insert_element_before(el, "a:spcAft", "a:buClrTx", "a:buClr", "a:buSzTx",
                                          "a:buSzPct", "a:buSzPts", "a:buFontTx", "a:buFont",
                                          "a:buNone", "a:buAutoNum", "a:buChar", "a:tabLst",
                                          "a:defRPr", "a:extLst")
            else:
                pPr.insert_element_before(el, "a:buClrTx", "a:buClr", "a:buSzTx", "a:buSzPct",
                                          "a:buSzPts", "a:buFontTx", "a:buFont", "a:buNone",
                                          "a:buAutoNum", "a:buChar", "a:tabLst", "a:defRPr",
                                          "a:extLst")
    if not bullet and level >= 0:
        pPr.insert_element_before(parse_xml('<a:buNone %s/>' % nsdecls("a")),
                                  "a:tabLst", "a:defRPr", "a:extLst")
    elif bullet:
        pPr.set("marL", str(int(Inches(0.28 + 0.24 * level))))
        pPr.set("indent", str(-int(Inches(0.24))))
        bf = parse_xml('<a:buFont %s typeface="Arial"/>' % nsdecls("a"))
        bc = parse_xml('<a:buChar %s char="%s"/>' % (nsdecls("a"), "•" if level == 0 else "–"))
        pPr.insert_element_before(bf, "a:buNone", "a:buAutoNum", "a:buChar", "a:tabLst",
                                  "a:defRPr", "a:extLst")
        pPr.insert_element_before(bc, "a:tabLst", "a:defRPr", "a:extLst")
    return p


def set_text_frame(tf, lines: list, latin: str, ea: str, size_pt: float,
                   line_spacing: float = 1.0, align: str = "left",
                   anchor: str = "top", bullet_levels=None):
    """lines: [{"text":..., "level":0, "bold":False, "size_pt":..}]"""
    tf.clear()
    tf.word_wrap = True
    tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE,
                          "bottom": MSO_ANCHOR.BOTTOM}[anchor]
    first = True
    for item in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        lvl = max(0, min(8, int(item.get("level", 0))))  # OOXML lvl 取值 0..8；-1 表示"无项目符号"
        p.level = lvl
        run = p.add_run()
        run.text = item["text"]
        set_run_fonts(run, latin=latin, ea=ea,
                      size_pt=item.get("size_pt", size_pt),
                      bold=item.get("bold", False),
                      color_rgb=item.get("color_rgb"),
                      italic=item.get("italic", False))
        pPr = p._p.get_or_add_pPr()
        pPr.set("algn", {"left": "l", "center": "ctr", "right": "r"}.get(align, "l"))
        lsp = item.get("line_spacing", line_spacing)
        if lsp and lsp != 1.0:
            ln = parse_xml('<a:lnSpc %s><a:spcPct val="%d"/></a:lnSpc>'
                           % (nsdecls("a"), int(lsp * 100000)))
            pPr.insert_element_before(ln, "a:spcBef", "a:spcAft", "a:buClrTx", "a:buClr",
                                      "a:buSzTx", "a:buSzPct", "a:buSzPts", "a:buFontTx",
                                      "a:buFont", "a:buNone", "a:buAutoNum", "a:buChar",
                                      "a:tabLst", "a:defRPr", "a:extLst")
        sb = item.get("space_before_pt", 4.0 if not first else 0.0)
        if sb:
            el = parse_xml('<a:spcBef %s><a:spcPts val="%d"/></a:spcBef>'
                           % (nsdecls("a"), int(sb * 100)))
            pPr.insert_element_before(el, "a:spcAft", "a:buClrTx", "a:buClr", "a:buSzTx",
                                      "a:buSzPct", "a:buSzPts", "a:buFontTx", "a:buFont",
                                      "a:buNone", "a:buAutoNum", "a:buChar", "a:tabLst",
                                      "a:defRPr", "a:extLst")
        if item.get("bullet", int(item.get("level", 0)) >= 0):
            pPr.set("marL", str(int(Inches(0.28 + 0.24 * int(item.get("level", 0))))))
            pPr.set("indent", str(-int(Inches(0.24))))
            bf = parse_xml('<a:buFont %s typeface="Arial"/>' % nsdecls("a"))
            bc = parse_xml('<a:buChar %s char="%s"/>'
                           % (nsdecls("a"), "•" if int(item.get("level", 0)) == 0 else "–"))
            pPr.insert_element_before(bf, "a:buNone", "a:buAutoNum", "a:buChar", "a:tabLst",
                                      "a:defRPr", "a:extLst")
            pPr.insert_element_before(bc, "a:tabLst", "a:defRPr", "a:extLst")
        else:
            pPr.insert_element_before(parse_xml('<a:buNone %s/>' % nsdecls("a")),
                                      "a:tabLst", "a:defRPr", "a:extLst")


def set_norm_autofit(tf, font_scale: float = 1.0, ln_spc_reduction: float = 0.0):
    """写 normAutofit 并把字号缩放比例落到 XML —— PowerPoint 会照此渲染。"""
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is None:
        return
    el = bodyPr.find(qn("a:normAutofit"))
    if el is None:
        el = parse_xml('<a:normAutofit %s/>' % nsdecls("a"))
        bodyPr.append(el)
    el.set("fontScale", str(int(round(font_scale * 100000))))
    if ln_spc_reduction:
        el.set("lnSpcReduction", str(int(round(ln_spc_reduction * 100000))))


def set_placeholder_text(ph, lines: list, latin: str, ea: str, size_pt: float,
                         line_spacing: float = 1.0, align: str = "left",
                         anchor: str = "top", font_scale: float | None = None):
    if ph is None or not getattr(ph, "has_text_frame", False):
        return False
    set_text_frame(ph.text_frame, lines, latin, ea, size_pt, line_spacing, align, anchor)
    if font_scale is not None:
        set_norm_autofit(ph.text_frame, font_scale)
    return True


def add_textbox(slide, left: int, top: int, width: int, height: int,
                lines: list, latin: str, ea: str, size_pt: float,
                line_spacing: float = 1.0, align: str = "left", anchor: str = "top",
                font_scale: float | None = None, name: str = "SynthTextBox"):
    box = slide.shapes.add_textbox(Emu(int(left)), Emu(int(top)), Emu(int(width)), Emu(int(height)))
    box.name = name
    set_text_frame(box.text_frame, lines, latin, ea, size_pt, line_spacing, align, anchor)
    if font_scale is not None:
        set_norm_autofit(box.text_frame, font_scale)
    return box


def set_slide_number(ph, start_number_text: str | None = None):
    """在页码占位符里写 a:fld type="slidenum"（可编辑域，PowerPoint 自动翻页更新）。"""
    if ph is None or not getattr(ph, "has_text_frame", False):
        return False
    tf = ph.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    pPr = p._p.get_or_add_pPr()
    pPr.set("algn", "r")
    fld = parse_xml(
        '<a:fld %s id="{B4A1B7A0-6E7B-4A6E-9E24-9E1C1F6A0F11}" type="slidenum">'
        '<a:rPr lang="en-US"/><a:t>%s</a:t></a:fld>'
        % (nsdecls("a"), start_number_text or "‹#›"))
    p._p.append(fld)
    return True


def ensure_header_footer_flags(slide, footer=True, slide_number=True, date=False):
    """写 <p:hf>：PowerPoint 只在 hf 标记为真时才渲染页脚/页码占位符。

    python-pptx 既不克隆 latent 占位符也不写 hf，所以"页脚/页码看不见"是常见坑。
    """
    sld = slide._element
    hf = sld.find(qn("p:hf"))
    if hf is None:
        hf = parse_xml('<p:hf %s/>' % nsdecls("p"))
        # p:hf 必须在 p:cSld 之后、p:clrMapOvr 之前
        clr = sld.find(qn("p:clrMapOvr"))
        if clr is not None:
            clr.addprevious(hf)
        else:
            sld.append(hf)
    hf.set("ftr", "1" if footer else "0")
    hf.set("sldNum", "1" if slide_number else "0")
    hf.set("hdr", "0")
    hf.set("dt", "1" if date else "0")
    return hf


def set_notes(slide, text: str):
    if not text:
        return False
    slide.notes_slide.notes_text_frame.text = text
    return True


def fit_picture(slide, image_path: str, container: dict, mode: str = "fit",
                caption: str | None = None, latin: str = "Arial", ea: str = "SimSun",
                caption_pt: float = 12.0, border: bool = False):
    """等比把图片放进容器：mode=fit（完整可见，留白）| cover（裁切填满）。

    返回实测缩放与宽高比偏差，供 fit_check.py 判定"是否拉伸变形"。
    """
    from PIL import Image
    with Image.open(image_path) as im:
        iw, ih = im.size
    cw, ch = int(container["width"]), int(container["height"])
    cl, ct = int(container["left"]), int(container["top"])
    if cw <= 0 or ch <= 0 or iw <= 0 or ih <= 0:
        raise ValueError("bad container/image geometry")
    cap_h = 0
    if caption:
        # 图注高度按实际折行数留（含 1 行保底 + 上下各 2pt），否则图注会溢出小框
        cw_in = cw / 914400.0
        lines = max(1, len(units.wrap_lines(caption, cw_in, caption_pt)))
        cap_h = int(Inches((lines * caption_pt * 1.35 + 4) / 72.0))
    avail_h = max(int(Inches(0.4)), ch - cap_h)
    sx, sy = cw / float(iw), avail_h / float(ih)
    scale = max(sx, sy) if mode == "cover" else min(sx, sy)
    w, h = int(iw * scale), int(ih * scale)
    left = cl + (cw - w) // 2
    top = ct + (avail_h - h) // 2
    pic = slide.shapes.add_picture(image_path, Emu(left), Emu(top), Emu(w), Emu(h))
    pic.name = "Figure"
    src_aspect = iw / float(ih)
    out_aspect = w / float(h)
    dev = abs(out_aspect - src_aspect) / src_aspect
    if caption:
        cl_box = add_textbox(slide, cl, ct + avail_h, cw, cap_h, 
                             [{"text": caption, "bullet": False, "level": -1}],
                             latin=latin, ea=ea, size_pt=caption_pt,
                             align="center", anchor="middle", name="FigureCaption")
        cl_box.name = "FigureCaption"
    return {"image": image_path, "image_px": [iw, ih], "mode": mode,
            "container_emu": [cl, ct, cw, ch], "placed_emu": [left, top, w, h],
            "scale": round(scale, 6), "aspect_deviation": round(dev, 6),
            "letterbox_emu": [cw - w, avail_h - h] if mode == "fit" else [0, 0],
            "caption": caption}


def placeholder_geometry_report(slide) -> list:
    out = []
    for ph in slide.placeholders:
        out.append({
            "idx": int(ph.placeholder_format.idx) if ph.placeholder_format.idx is not None else -1,
            "kind": ph_kind(ph),
            "left_in": round(ph.left / 914400.0, 4) if ph.left is not None else None,
            "top_in": round(ph.top / 914400.0, 4) if ph.top is not None else None,
            "width_in": round(ph.width / 914400.0, 4) if ph.width is not None else None,
            "height_in": round(ph.height / 914400.0, 4) if ph.height is not None else None,
            "inherits_from_layout": True,
        })
    return out


# ==================================================================
# 模板生成 / 改造（主题字体、配色、画幅、版式命名）
# 与“读模板”共用同一套主题 XML 知识，避免两处各改一份。
# ==================================================================

# 学术模板主题：标题 Arial/黑体，正文 Times New Roman/宋体（印刷可读性优先）
THEMES = {
    "academic-cjk": {
        "major": {"latin": "Arial", "ea": "黑体", "cs": "Arial"},
        "minor": {"latin": "Times New Roman", "ea": "宋体", "cs": "Times New Roman"},
        "colors": {"dk1": "000000", "lt1": "FFFFFF", "dk2": "1F3864",
                   "lt2": "F2F2F2", "accent1": "2E74B5", "accent2": "C00000",
                   "accent3": "548235", "accent4": "BF8F00", "accent5": "7030A0",
                   "accent6": "00B0F0", "hlink": "0563C1", "folHlink": "954F72"},
    },
    "academic-en": {
        "major": {"latin": "Arial", "ea": "Arial", "cs": "Arial"},
        "minor": {"latin": "Times New Roman", "ea": "Times New Roman",
                  "cs": "Times New Roman"},
        "colors": {"dk1": "000000", "lt1": "FFFFFF", "dk2": "1F3864",
                   "lt2": "F2F2F2", "accent1": "2E74B5", "accent2": "C00000",
                   "accent3": "548235", "accent4": "BF8F00", "accent5": "7030A0",
                   "accent6": "00B0F0", "hlink": "0563C1", "folHlink": "954F72"},
    },
    # 故意使用"不一定装了"的思源系字体：验证字体缺失→回退→记录 的完整链路
    "academic-sourcehan": {
        "major": {"latin": "Source Sans Pro", "ea": "Source Han Sans SC", "cs": "Arial"},
        "minor": {"latin": "Source Serif Pro", "ea": "Source Han Serif SC",
                  "cs": "Times New Roman"},
        "colors": {"dk1": "1A1A1A", "lt1": "FFFFFF", "dk2": "004B6B",
                   "lt2": "F4F4F4", "accent1": "0072B2", "accent2": "D55E00",
                   "accent3": "009E73", "accent4": "E69F00", "accent5": "CC79A7",
                   "accent6": "56B4E9", "hlink": "0072B2", "folHlink": "CC79A7"},
    },
}

LAYOUT_NAMES_ZH = {
    "Title Slide": "标题幻灯片",
    "Title and Content": "标题和内容",
    "Section Header": "节标题",
    "Two Content": "两栏内容",
    "Comparison": "比较",
    "Title Only": "仅标题",
    "Blank": "空白",
    "Content with Caption": "内容与标题",
    "Picture with Caption": "图片与标题",
    "Title and Vertical Text": "标题和竖排文本",
    "Vertical Title and Text": "竖排标题和文本",
}

# 占位符名称的中文化（模拟中文模板里常见的「标题 1」「内容占位符 3」「图片占位符 4」命名）
PH_NAME_ZH = {
    "title": "标题", "ctrTitle": "标题", "subTitle": "副标题", "body": "内容占位符",
    "obj": "内容占位符", "pic": "图片占位符", "tbl": "表格占位符", "chart": "图表占位符",
    "ftr": "页脚占位符", "sldNum": "幻灯片编号占位符", "dt": "日期占位符",
}

_PH_SP_RE = re.compile(r"<p:sp>.*?</p:sp>", re.S)
_PH_TYPE_RE = re.compile(r'<p:ph[^>]*\btype="([^"]+)"')
_PH_PH_RE = re.compile(r"<p:ph[^>]*/?>")
_PH_NAME_RE = re.compile(r'(<p:cNvPr[^>]*\bname=")([^"]*)(")')


def rename_placeholder_names(xml: str) -> str:
    """把 slideLayout/slideMaster 里每个占位符 sp 的 cNvPr@name 改成中文名。

    只改 name，不动 <p:ph type=.../>：这样模板依旧合法，而我们的
    角色识别必须同时吃「中文名」这条线索（v1.1 新增的断言就测这个）。
    """
    def _one(m):
        block = m.group(0)
        tm = _PH_TYPE_RE.search(block)
        if not tm:
            return block
        zh = PH_NAME_ZH.get(tm.group(1))
        if not zh:
            return block
        n = [0]

        def _nm(mm):
            n[0] += 1
            prefix = mm.group(1)
            # 保留原编号后缀（"Title 1" → "标题 1"），便于人工对照
            tail = re.search(r"(\s*\d+)?$", mm.group(2))
            suffix = tail.group(1) or (" %d" % n[0])
            return prefix + zh + suffix + mm.group(3)
        return _PH_NAME_RE.sub(_nm, block, count=1)
    return _PH_SP_RE.sub(_one, xml)


def strip_body_placeholders(xml: str) -> str:
    """删掉版式里的 body/obj 占位符 —— 用于制造「模板没有你要的版式」的降级场景。

    注意：OOXML 里 `<p:ph idx="1"/>` **不带 type 就是 obj（正文）**，
    只删 type="body"/"obj" 会漏掉这种最常见写法（实测踩过）。
    """
    def _one(m):
        block = m.group(0)
        ph = _PH_PH_RE.search(block)
        if not ph:
            return block
        tm = _PH_TYPE_RE.search(block)
        if tm is None:              # 没有 type 属性 → 默认 obj（正文）
            return ""
        return "" if tm.group(1) in ("body", "obj") else block
    return _PH_SP_RE.sub(_one, xml)


def _theme_xml(xml: str, theme: dict) -> str:
    for kind in ("major", "minor"):
        face = theme[kind]
        m = re.search(r"<a:%sFont>(.*?)</a:%sFont>" % (kind, kind), xml, re.S)
        if not m:
            continue
        blk = m.group(1)
        new = blk
        for tag in ("latin", "ea", "cs"):
            new = re.sub(r'<a:%s typeface="[^"]*"[^>]*/>' % tag,
                         '<a:%s typeface="%s"/>' % (tag, face[tag]), new, count=1)
        new = re.sub(r'<a:font script="Hans" typeface="[^"]*"/>',
                     '<a:font script="Hans" typeface="%s"/>' % face["ea"], new)
        if 'script="Hans"' not in new:
            new = new.replace("</a:%sFont>" % kind,
                              '<a:font script="Hans" typeface="%s"/></a:%sFont>'
                              % (face["ea"], kind))
        xml = xml[:m.start(1)] + new + xml[m.end(1):]
    # 配色：整块替换 <a:NAME>…</a:NAME>（原实现会留下 sysClr 的 "/>" 残片，
    # 生成的 pptx 会被 PowerPoint 判为损坏 —— 这是踩过的坑，保留注释）
    for name, val in theme["colors"].items():
        pat = re.compile(r"(<a:%s>)(.*?)(</a:%s>)" % (name, name), re.S)
        xml = pat.sub(lambda mm: mm.group(1) + '<a:srgbClr val="%s"/>' % val + mm.group(3),
                      xml, count=1)
    return xml


def _rewrite_zip(src: str, dst: str, replacer) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            new = replacer(item.filename, data)
            zout.writestr(item, new if new is not None else data)


SPEC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "templates", "template-spec.json")


def load_template_spec(path: str | None = None) -> dict:
    with open(path or SPEC_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def spec_entry(spec: dict, name: str | None = None) -> dict:
    name = name or spec.get("default")
    for item in spec.get("templates") or []:
        if item.get("name") == name:
            return item
    raise KeyError("template spec has no entry %r" % name)


def build_template_from_spec(spec: dict, name: str | None = None,
                             out_path: str | None = None) -> dict:
    """按文本 spec 在**运行时**合成模板 pptx，并用 spec.expected 复核结构一致性。

    平台只接受 UTF-8 文本资源，所以模板不进包；这个函数保证"合成出来的模板"与
    spec 里记录的版式数/角色/占位符几何/主题字体一致（不一致就报出来，不静默）。
    """
    item = spec_entry(spec, name)
    build = item.get("build") or {}
    # spec 自带 theme：临时并入 THEMES，使 spec 成为唯一真源
    tname = build.get("theme_name") or "academic-cjk"
    if item.get("theme"):
        THEMES[tname] = {"major": item["theme"]["major"], "minor": item["theme"]["minor"],
                         "colors": item["theme"]["colors"]}
    out = out_path or tempfile.mktemp(suffix=".pptx")
    info = build_template(out, build.get("size", "16:9"), tname,
                          bool(build.get("rename_layouts_zh")),
                          name_placeholders_zh=bool(build.get("name_placeholders_zh")))
    exp = item.get("expected") or {}
    check = {"layout_count_match": None, "theme_match": None, "roles_match": None,
             "geometry_max_delta_emu": None}
    if exp:
        m = template_probe_stub(out)
        check["layout_count_match"] = (m["layout_count"] == exp.get("layout_count"))
        check["theme_match"] = (m["theme_fonts"] == exp.get("theme_fonts"))
        check["roles_match"] = (m["roles"] == exp.get("roles"))
        by_idx = {l["index"]: l for l in m["layouts"]}
        delta = 0
        for l in exp.get("layouts") or []:
            cur = by_idx.get(l["index"]) or {}
            cph = {}
            for p in cur.get("placeholders") or []:
                cph[(p["idx"], p["kind"])] = p.get("geometry") or {}
            for p in l.get("placeholders") or []:
                g = cph.get((p["idx"], p["kind"]))
                if not g:
                    continue
                for k in ("left", "top", "width", "height"):
                    a, b = (p.get("geometry") or {}).get(k), g.get(k)
                    if a is None or b is None:
                        continue
                    delta = max(delta, abs(int(a) - int(b)))
        check["geometry_max_delta_emu"] = delta
        check["ok"] = bool(check["layout_count_match"] and check["theme_match"]
                           and check["roles_match"] and delta <= 12700)  # ≤1pt
    info["spec_check"] = check
    info["spec_name"] = item.get("name")
    return info


def template_probe_stub(path: str) -> dict:
    """轻量探针（避免 pptx_util ↔ template_probe 循环 import 时互相拖累）。"""
    import template_probe as _tp
    return _tp.probe(path, with_fonts=False)


def build_template(out_path: str, size: str = "16:9", theme_name: str = "academic-cjk",
                   rename_zh: bool = False, drop_layout: str | None = None,
                   name_placeholders_zh: bool = False, strip_body: bool = False) -> dict:
    from pptx import Presentation as P
    import pptx  # noqa
    default = os.path.join(os.path.dirname(pptx.__file__), "templates", "default.pptx")
    prs = P(default)
    if size == "16:9":
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    elif size == "4:3":
        prs.slide_width, prs.slide_height = Inches(10.0), Inches(7.5)
    else:
        raise ValueError("size must be 16:9 or 4:3")
    # 先落盘（保留母版/版式），再改主题 XML 与版式名
    tmp = tempfile.mktemp(suffix=".pptx")
    prs.save(tmp)
    theme = THEMES[theme_name]
    renames = LAYOUT_NAMES_ZH if rename_zh else {}

    def replacer(name: str, data: bytes):
        if name.endswith(".xml") and "/theme/" in name:
            return _theme_xml(data.decode("utf-8"), theme).encode("utf-8")
        if re.match(r"ppt/(slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$", name):
            xml = data.decode("utf-8")
            if renames and "/slideLayouts/" in name:
                for en, zh in renames.items():
                    xml = xml.replace('name="%s"' % en, 'name="%s"' % zh)
            if name_placeholders_zh:
                xml = rename_placeholder_names(xml)
            if strip_body:
                xml = strip_body_placeholders(xml)
            return xml.encode("utf-8")
        return None

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    _rewrite_zip(tmp, out_path, replacer)
    os.remove(tmp)
    info = {"out": out_path, "size": size, "theme": theme_name,
            "renamed_layouts": bool(rename_zh), "bytes": os.path.getsize(out_path),
            "sha256": units.sha256_file(out_path)}
    # 自检：能被重新打开，且主题已生效
    p2 = P(out_path)
    tm = theme_info(out_path)
    info["verify"] = {"slide_size": slide_size(p2),
                      "layouts": len(p2.slide_layouts),
                      "theme_fonts": tm.get("fonts"),
                      "theme_colors_accent1": (tm.get("colors") or {}).get("accent1")}
    return info


def _template_main(argv=None) -> int:
    import json as _json
    ap = argparse.ArgumentParser(description="build an academic pptx template")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="16:9", choices=["16:9", "4:3"])
    ap.add_argument("--theme", default="academic-cjk", choices=sorted(THEMES))
    ap.add_argument("--spec", help="文本模板规格 JSON（平台只接受文本资源时用它合成模板）")
    ap.add_argument("--name", help="spec 里的模板条目名（默认 spec.default）")
    ap.add_argument("--rename-layouts", default="", choices=["", "zh"])
    ap.add_argument("--name-placeholders", default="", choices=["", "zh"],
                    help="把占位符 cNvPr@name 改成中文（标题 1 / 内容占位符 3 …）")
    ap.add_argument("--strip-body", action="store_true",
                    help="删掉版式里的正文占位符，用于验证缺版式降级")
    a = ap.parse_args(argv)
    if a.spec:
        info = build_template_from_spec(load_template_spec(a.spec), a.name, a.out)
        print(_json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if (info.get("spec_check") or {}).get("ok", True) else 7
    info = build_template(a.out, a.size, a.theme, bool(a.rename_layouts),
                          name_placeholders_zh=bool(a.name_placeholders),
                          strip_body=bool(a.strip_body))
    print(_json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_template_main())
