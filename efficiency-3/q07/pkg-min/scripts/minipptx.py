import os, zipfile

V = "1.3-min"
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

def write(pt, slides, mj="Calibri", ea="Calibri"):
    n = len(slides)
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
    ids = "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 1) for i in range(n))
    pres = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation %s><p:sldMasterIdLst>'
            '<p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:notesMasterIdLst>'
            '<p:notesMasterId r:id="rId%d"/></p:notesMasterIdLst><p:sldIdLst>%s</p:sldIdLst>'
            '<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle>'
            '<a:defPPr><a:defRPr lang="en-US"/></a:defPPr></p:defaultTextStyle></p:presentation>' % (NS, n + 3, ids))
    r = ['<Relationship Id="rId1" Type="%sslideMaster" Target="slideMasters/slideMaster1.xml"/>' % REL]
    r += ['<Relationship Id="rId%d" Type="%sslide" Target="slides/slide%d.xml"/>' % (i + 1, REL, i) for i in range(1, n + 1)]
    r += ['<Relationship Id="rId%d" Type="%snotesSlide" Target="notesSlides/notesSlide%d.xml"/>' % (n + 1 + i, REL, i) for i in range(1, n + 1)]
    r += ['<Relationship Id="rId%d" Type="%snotesMaster" Target="notesMasters/notesMaster1.xml"/>' % (n + 3, REL),
          '<Relationship Id="rId%d" Type="%stheme" Target="theme/theme1.xml"/>' % (n + 4, REL),
          '<Relationship Id="rId%d" Type="%spresProps" Target="presProps.xml"/>' % (n + 5, REL),
          '<Relationship Id="rId%d" Type="%stableStyles" Target="tableStyles.xml"/>' % (n + 6, REL)]
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
        P['ppt/slides/slide%d.xml' % i] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld %s><p:cSld><p:spTree>'
          '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr>'
          '<p:cNvPr id="2" name="Title 1"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/>'
          '</p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="2400" b="1">'
          '<a:latin typeface="+mj-lt"/><a:ea typeface="+mj-ea"/></a:rPr><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>'
          '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr>'
          '<p:ph idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp>'
          '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>' % (NS, XE(s["title"]), body))
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
          '<Relationship Id="rId1" Type="%snotesSlide" Target="../slides/slide%d.xml"/></Relationships>' % (PRL, REL, i))
    os.makedirs(os.path.dirname(os.path.abspath(pt)) or ".", exist_ok=True)
    with zipfile.ZipFile(pt, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in P.items():
            z.writestr(k, v.encode("utf-8"))
