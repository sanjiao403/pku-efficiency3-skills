import os, re, zipfile
import xml.etree.ElementTree as ET

V = "1.4-adv1"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
PRL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
XE = lambda s: str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def theme(mj, ea):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme %s name="T"><a:themeElements>'
            '<a:clrScheme name="T"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1>'
            '<a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="12263A"/></a:dk2><a:lt2>'
            '<a:srgbClr val="F5F7FA"/></a:lt2><a:accent1><a:srgbClr val="2F5B8C"/></a:accent1><a:accent2>'
            '<a:srgbClr val="0B4F6C"/></a:accent2><a:accent3><a:srgbClr val="6E8CA0"/></a:accent3><a:accent4>'
            '<a:srgbClr val="B08D57"/></a:accent4><a:accent5><a:srgbClr val="598392"/></a:accent5><a:accent6>'
            '<a:srgbClr val="3B4252"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink>'
            '<a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="T"><a:majorFont>'
            '<a:latin typeface="%s"/><a:ea typeface="%s"/><a:cs typeface=""/></a:majorFont><a:minorFont>'
            '<a:latin typeface="%s"/><a:ea typeface="%s"/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
            '<a:fmtScheme name="T"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill>'
            '<a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
            '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700">'
            '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill>'
            '<a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle>'
            '<a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/>'
            '</a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
            '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
            '</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>'
            % (NS, XE(mj), XE(ea), XE(mj), XE(ea)))

MASTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster %s><p:cSld><p:spTree>'
          '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>'
          '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
          'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
          '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles>'
          '<p:titleStyle><a:lvl1pPr><a:defRPr sz="3000" b="1"/></a:lvl1pPr></p:titleStyle><p:bodyStyle>'
          '<a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr>'
          '<a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>' % NS)
LAYOUT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout %s type="titleOnly" preserve="1">'
          '<p:cSld name="Title and Content"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
          '</p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Title 1"/><p:cNvSpPr><a:spLocks noGrp="1"/>'
          '</p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="457200" y="274638"/>'
          '<a:ext cx="8229600" cy="1143000"/></a:xfrm></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>'
          '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr>'
          '<p:ph idx="1"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="457200" y="1600200"/><a:ext cx="8229600" cy="4114800"/>'
          '</a:xfrm></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp></p:spTree></p:cSld>'
          '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr><p:hfLst/><p:txStyles><p:titleStyle><a:lvl1pPr>'
          '<a:defRPr sz="3000" b="1"/></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr><a:defRPr sz="1800"/>'
          '</a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle>'
          '</p:txStyles></p:sldLayout>' % NS)
NOTES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:notesMaster %s><p:cSld><p:spTree>'
         '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr>'
         '<p:cNvPr id="2" name="Notes 1"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/>'
         '</p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp></p:spTree></p:cSld>'
         '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
         'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:notesStyle>'
         '<a:lvl1pPr><a:defRPr sz="1200"/></a:lvl1pPr></p:notesStyle></p:notesMaster>' % NS)

def rel_ids(n):
    """One rId per relationship of ppt/presentation.xml - allocated once, used everywhere.

    `pkg-adv1` allocated these ad hoc: sldId used rId(i+1) while rId1 was the slide master,
    notesSlide relationships collided with notesMaster/theme/presProps/tableStyles, and the last
    slide ended up unreachable. python-pptx then failed with
    `AttributeError: 'SlideMasterPart' object has no attribute 'slide'` on slide 1.
    """
    return {"slideMaster": 1, "notesMaster": 2, "theme": 3, "presProps": 4, "tableStyles": 5,
            "slides": list(range(6, 6 + n))}


def write(pt, slides, mj="Calibri", ea="Calibri"):
    n = len(slides)
    R = rel_ids(n)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
          '<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>'
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>'
          '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>'
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
          + "".join('<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
                    '<Override PartName="/ppt/notesSlides/notesSlide%d.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>' % (i, i)
                    for i in range(1, n + 1)) + "</Types>")
    ids = "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, R["slides"][i - 1]) for i in range(1, n + 1))
    pres = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation %s><p:sldMasterIdLst>'
            '<p:sldMasterId id="2147483648" r:id="rId%d"/></p:sldMasterIdLst><p:notesMasterIdLst>'
            '<p:notesMasterId r:id="rId%d"/></p:notesMasterIdLst><p:sldIdLst>%s</p:sldIdLst>'
            '<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle>'
            '<a:defPPr><a:defRPr lang="en-US"/></a:defPPr></p:defaultTextStyle></p:presentation>'
            % (NS, R["slideMaster"], R["notesMaster"], ids))
    r = ['<Relationship Id="rId%d" Type="%sslideMaster" Target="slideMasters/slideMaster1.xml"/>' % (R["slideMaster"], REL)]
    r += ['<Relationship Id="rId%d" Type="%sslide" Target="slides/slide%d.xml"/>' % (R["slides"][i - 1], REL, i)
          for i in range(1, n + 1)]
    r += ['<Relationship Id="rId%d" Type="%snotesMaster" Target="notesMasters/notesMaster1.xml"/>' % (R["notesMaster"], REL),
          '<Relationship Id="rId%d" Type="%stheme" Target="theme/theme1.xml"/>' % (R["theme"], REL),
          '<Relationship Id="rId%d" Type="%spresProps" Target="presProps.xml"/>' % (R["presProps"], REL),
          '<Relationship Id="rId%d" Type="%stableStyles" Target="tableStyles.xml"/>' % (R["tableStyles"], REL)]
    P = {'[Content_Types].xml': ct, 'ppt/presentation.xml': pres,
         'ppt/_rels/presentation.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s">%s</Relationships>' % (PRL, "".join(r)),
         'ppt/theme/theme1.xml': theme(mj, ea), 'ppt/slideMasters/slideMaster1.xml': MASTER,
         'ppt/slideMasters/_rels/slideMaster1.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s"><Relationship Id="rId1" Type="%sslideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="%stheme" Target="../theme/theme1.xml"/></Relationships>' % (PRL, REL, REL),
         'ppt/slideLayouts/slideLayout1.xml': LAYOUT,
         'ppt/slideLayouts/_rels/slideLayout1.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s"><Relationship Id="rId1" Type="%sslideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>' % (PRL, REL),
         'ppt/notesMasters/notesMaster1.xml': NOTES,
         'ppt/notesMasters/_rels/notesMaster1.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s"><Relationship Id="rId1" Type="%stheme" Target="../theme/theme1.xml"/></Relationships>' % (PRL, REL),
         'ppt/presProps.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentationPr %s/>' % NS,
         'ppt/tableStyles.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>',
         '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s"><Relationship Id="rId1" Type="%sofficeDocument" Target="ppt/presentation.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>' % (PRL, REL),
         'docProps/core.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>talkplan</dc:creator><dc:title>%s</dc:title></cp:coreProperties>' % V}
    for i, s in enumerate(slides, 1):
        body = "".join('<a:p><a:pPr marL="0" indent="0"><a:buChar char="\u2022"/></a:pPr><a:r><a:rPr lang="en-US" sz="1700">'
                       '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/></a:rPr><a:t>%s</a:t></a:r></a:p>' % XE(b)
                       for b in s["bullets"][:7])
        if s.get("claim"):
            body += ('<a:p><a:pPr marL="0" indent="0"><a:buNone/></a:pPr><a:r><a:rPr lang="en-US" sz="1500">'
                     '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/></a:rPr><a:t>%s</a:t></a:r></a:p>'
                     % XE("[%s] %s" % (s.get("strength", ""), s["claim"])))
        P['ppt/slides/slide%d.xml' % i] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld %s%s><p:cSld><p:spTree>'
          '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr>'
          '<p:cNvPr id="2" name="Title 1"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/>'
          '</p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="2400" b="1">'
          '<a:latin typeface="+mj-lt"/><a:ea typeface="+mj-ea"/></a:rPr><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>'
          '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr>'
          '<p:ph idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp>'
          '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
          % (NS, ' show="0"' if s.get("hidden") else '', XE(s["title"]), body))
        P['ppt/slides/_rels/slide%d.xml.rels' % i] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s">'
          '<Relationship Id="rId1" Type="%sslideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
          '<Relationship Id="rId2" Type="%snotesSlide" Target="../notesSlides/notesSlide%d.xml"/></Relationships>' % (PRL, REL, REL, i))
        nt = "".join('<a:p><a:r><a:rPr lang="en-US" sz="1200"/><a:t>%s</a:t></a:r></a:p>' % XE(x)
                     for x in str(s.get("notes", "")).split("\n")[:40])
        P['ppt/notesSlides/notesSlide%d.xml' % i] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:notes %s><p:cSld><p:spTree>'
          '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr>'
          '<p:cNvPr id="2" name="Notes 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/>'
          '</p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp></p:spTree></p:cSld>'
          '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>' % (NS, nt))
        P['ppt/notesSlides/_rels/notesSlide%d.xml.rels' % i] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s">'
          '<Relationship Id="rId1" Type="%sslide" Target="../slides/slide%d.xml"/>'
          '<Relationship Id="rId2" Type="%snotesMaster" Target="../notesMasters/notesMaster1.xml"/></Relationships>'
          % (PRL, REL, i, REL))
    os.makedirs(os.path.dirname(os.path.abspath(pt)) or ".", exist_ok=True)
    with zipfile.ZipFile(pt, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in P.items():
            z.writestr(k, v.encode("utf-8"))


# ---------------------------------------------------------------- reading it back
P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _rels(z, part):
    """rId -> (type, target) of one part, with the target resolved relative to the part."""
    name = os.path.dirname(part) + "/_rels/" + os.path.basename(part) + ".rels"
    if name not in z.namelist():
        return {}, name
    out = {}
    root = ET.fromstring(z.read(name))
    for rel in root.findall(PKG_REL + "Relationship"):
        rid = rel.get("Id")
        tgt = rel.get("Target") or ""
        base = os.path.dirname(part)
        resolved = os.path.normpath(os.path.join(base, tgt)).replace("\\", "/") if not tgt.startswith("/") \
            else tgt.lstrip("/")
        out[rid] = (rel.get("Type") or "", resolved)
    return out, name


def inspect(path):
    """Read the produced pptx the way a consumer does: follow presentation.xml -> presentation
    rels -> slide parts, and report every structural problem instead of trusting the writer.

    `pkg-adv1` shipped a deck whose first sldId resolved to the slide master, whose rIds collided,
    and whose last slide was unreachable; nothing inside the package looked at that, and
    python-pptx failed on slide 1 (`'SlideMasterPart' object has no attribute 'slide'`).
    """
    rec = {"ok": False, "errors": [], "warnings": [], "slides": [], "count": 0,
           "duplicate_rel_ids": [], "unreachable_slide_parts": [], "unresolved_sld_ids": [],
           "missing_targets": [], "notes_master_rid": None}
    try:
        z = zipfile.ZipFile(path)
    except Exception as exc:
        rec["errors"].append("pptx unreadable: %s: %s" % (type(exc).__name__, exc))
        return rec
    names = set(z.namelist())
    if "ppt/presentation.xml" not in names:
        rec["errors"].append("missing ppt/presentation.xml")
        return rec
    pres = ET.fromstring(z.read("ppt/presentation.xml"))
    rels, rels_name = _rels(z, "ppt/presentation.xml")
    for rid, (typ, tgt) in rels.items():
        if tgt not in names:
            rec["missing_targets"].append({"part": rels_name, "rId": rid, "target": tgt})
    rel_ids = re.findall(rb'<Relationship [^>]*Id="([^"]+)"', z.read(rels_name) if rels_name in names else b"")
    dupes = sorted({i.decode() for i in rel_ids if rel_ids.count(i) > 1})
    rec["duplicate_rel_ids"] = dupes
    if dupes:
        rec["errors"].append("duplicate relationship ids in presentation.xml.rels: %s" % dupes)
    sld_ids = pres.find(P_NS + "sldIdLst")
    order, referenced = [], set()
    for sld in (sld_ids.findall(P_NS + "sldId") if sld_ids is not None else []):
        rid = sld.get(R_NS + "id")
        typ, tgt = rels.get(rid, ("", ""))
        if not re.match(r"ppt/slides/slide\d+\.xml$", tgt or ""):
            rec["unresolved_sld_ids"].append({"id": sld.get("id"), "rId": rid, "target": tgt,
                                              "why": "does not resolve to a slide part"})
            continue
        if tgt not in names:
            rec["unresolved_sld_ids"].append({"id": sld.get("id"), "rId": rid, "target": tgt,
                                              "why": "target part missing"})
            continue
        order.append(tgt)
        referenced.add(tgt)
    nmm = pres.find(P_NS + "notesMasterIdLst")
    if nmm is not None:
        nm = nmm.find(P_NS + "notesMasterId")
        if nm is not None:
            rec["notes_master_rid"] = {"rId": nm.get(R_NS + "id"),
                                       "target": (rels.get(nm.get(R_NS + "id")) or ("", ""))[1]}
            if rec["notes_master_rid"]["target"] not in names:
                rec["errors"].append("notesMasterId does not resolve to a part: %s" % rec["notes_master_rid"])
    present = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n))
    rec["unreachable_slide_parts"] = sorted(set(present) - referenced)
    orphan = sorted(referenced - set(present))
    if rec["unreachable_slide_parts"]:
        rec["errors"].append("slide parts with no sldId reference: %s" % rec["unreachable_slide_parts"])
    if orphan:
        rec["errors"].append("sldIds pointing outside ppt/slides: %s" % orphan)
    if rec["unresolved_sld_ids"]:
        rec["errors"].append("sldIds that do not resolve to a slide part: %s" % rec["unresolved_sld_ids"])
    for part in order:
        try:
            root = ET.fromstring(z.read(part))
        except Exception as exc:
            rec["errors"].append("%s unparsable: %s" % (part, exc))
            continue
        srels, srels_name = _rels(z, part)
        for rid, (typ, tgt) in srels.items():
            if tgt not in names:
                rec["missing_targets"].append({"part": srels_name, "rId": rid, "target": tgt})
        notes = [t for t, (typ, tgt) in srels.items() if typ.endswith("/notesSlide")]
        if not notes:
            rec["warnings"].append("%s has no notesSlide relationship" % part)
        texts, title = [], ""
        for sp in root.iter(P_NS + "sp"):
            runs = [t.text or "" for t in sp.iter(A_NS + "t")]
            if not runs:
                continue
            ph = sp.find(".//" + P_NS + "ph")
            if ph is not None and (ph.get("type") == "title"):
                title = " ".join(runs)
            else:
                texts.append(" ".join(runs))
        hidden = (root.get("show") == "0")
        rec["slides"].append({"part": part, "title": title, "texts": texts, "hidden": hidden,
                              "notes_rids": notes})
    rec["count"] = len(order)
    if rec["count"] == 0:
        rec["errors"].append("no slide is reachable from sldIdLst")
    rec["ok"] = not rec["errors"]
    return rec
