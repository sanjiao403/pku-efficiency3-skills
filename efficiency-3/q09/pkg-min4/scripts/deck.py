"""deck.py — minimal academic deck kit (one file, one command)"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, time, zipfile
sys.dont_write_bytecode = True
try:
    from pptx import Presentation
    from pptx.util import Emu, Pt
    from pptx.enum.text import PP_ALIGN
except Exception:
    Presentation = None
NUM = re.compile(r"(?<![\d.])[-+]?\d+(?:\.\d+)?\s?(?:%|ms|s|h|GB|M|K|B|F1)?")
PH = {1: "title", 2: "body", 3: "ctitle", 4: "subtitle", 7: "object", 15: "footer",
      13: "slideno", 16: "date"}
TT = {"question": "研究问题与缺口", "method": "方法", "results": "结果",
      "limits": "限制与不确定性", "conclusion": "结论与下一步", "backup": "备用页"}
ROLES = ("question", "method", "results", "results", "limits", "conclusion")

def jd(p, o):
    if os.path.dirname(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def cl(t):
    t = re.sub(r"_x[0-9A-Fa-f]{4}_|[\ue000-\uf8ff\x00-\x08\x0b-\x1f\x7f]", " ", t or "")
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", " ", t)).strip()

def fp(p):
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

def cfields(case):
    for k in ("output_contract", "outputContract", "contract", "outputs"):
        n = case.get(k)
        if isinstance(n, dict) and isinstance(n.get("properties"), dict):
            return list(n["properties"])
        if isinstance(n, dict):
            n = n.get("fields", n)
            if isinstance(n, dict) and n:
                return [x for x in n if not str(x).startswith("_")]
        if isinstance(n, list) and n and isinstance(n[0], dict):
            return [x for x in n[0] if not str(x).startswith("_")]
    for v in case.values():
        if isinstance(v, dict):
            got = cfields(v)
            if got:
                return got
    return []

def cget(case, *names):
    for src in [case] + [v for v in case.values() if isinstance(v, dict)]:
        for k, v in src.items():
            if str(k).lower() in names and isinstance(v, (int, float, str)):
                return v
    return None

def iscase(p):
    try:
        h = open(p, "rb").read(20000).decode("utf-8", "replace").lower()
    except Exception:
        return False
    return "{" in h and ("case_id" in h or "output_contract" in h)

def resolve(v, base, cwd):
    if not isinstance(v, str) or not v:
        return None, "unset"
    if os.path.isabs(v):
        return (v, "absolute") if os.path.isfile(v) else (None, "absolute-missing")
    for tag, root in (("case_dir", base), ("cwd", cwd or "."), ("/input", "/input")):
        p = os.path.join(root, v)
        if os.path.isfile(p):
            return p, tag
    return None, "missing"

def find(d, case, cwd="."):
    f = {"material": None, "template": None, "deck": None, "ops": None, "spec": None,
         "resolved_from": {}, "missing": []}
    mats, tags = [], {}
    for n in sorted(os.listdir(d)):
        p, low = os.path.join(d, n), n.lower()
        if os.path.isdir(p):
            continue
        if low.endswith(".json") and low != "case.json" and not iscase(p):
            f["spec" if "plan" in low or "spec" in low else "ops"] = p
            tags["spec" if "plan" in low or "spec" in low else "ops"] = "case_dir"
        elif low.endswith(".pptx"):
            k = "deck" if "start" in low or "existing" in low else "template"
            f[k], tags[k] = p, "case_dir"
        elif low.endswith((".pdf", ".md", ".markdown", ".txt", ".text")):
            mats.append((p, "case_dir"))
    for k, s in (("template", "template"), ("starting_deck", "deck"), ("deck", "deck"),
                 ("ops", "ops"), ("edits", "ops"), ("deck_plan", "spec")):
        v = case.get(k)
        if isinstance(v, str):
            p, where = resolve(v, d, cwd)
            if p:
                f[s], tags[s] = p, where
            else:
                f["missing"].append({"key": k, "value": v, "where": where})
    m = case.get("materials")
    for x in ([m] if isinstance(m, str) else (m or [])):
        p, where = resolve(str(x), d, cwd)
        if p:
            mats.insert(0, (p, where))
        else:
            f["missing"].append({"key": "materials", "value": str(x), "where": where})
    mats = sorted(set(mats), key=lambda t: (not t[0].endswith(".pdf"),
                                            os.path.getsize(t[0])))
    if mats:
        f["material"], tags["material"] = mats[0][0], mats[0][1]
    f["resolved_from"] = tags
    return f

def ingest(path, work):
    s = {"kind": os.path.splitext(path)[1].lstrip(".").lower(), "parser": "text",
         "pages": 1, "path": os.path.basename(path), "blocks": [], "numbers": [],
         "limits": [], "notes": [],
         "sha256_16": hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]}
    if s["kind"] == "pdf":
        try:
            import fitz
            doc = fitz.open(path)
            s["parser"], s["pages"] = "pymupdf", doc.page_count
            for i in range(doc.page_count):
                ln = [cl("".join(x.get("text", "") for x in l.get("spans", [])))
                      for b in doc[i].get_text("dict").get("blocks", [])
                      if b.get("type") == 0 for l in b.get("lines", [])]
                ln = [x for x in ln if x]
                if ln:
                    s["blocks"].append({"id": "p%d.b%d" % (i + 1, len(s["blocks"])),
                                        "page": i + 1, "text": cl(" ".join(ln))})
            doc.close()
        except Exception as e:
            s["limits"].append("PDF text unavailable (PyMuPDF missing or unreadable): %s"
                               % str(e)[:70])
        if not any(b["text"] for b in s["blocks"]):
            s["limits"].append("no extractable text layer (scanned PDF?): the plan keeps "
                               "only its skeleton and says so")
    else:
        s["kind"] = "markdown" if s["kind"] in ("md", "markdown") else "text"
        for i, para in enumerate(x for x in re.split(
                r"\n\s*\n", open(path, encoding="utf-8", errors="replace").read())
                if x.strip()):
            s["blocks"].append({"id": "p1.b%d" % i, "page": 1, "text": cl(para)})
        s["notes"].append("text material: no page geometry; anchors carry block ids "
                          "instead of page numbers")
    s["numbers"] = [{"value": m.group(0).strip().replace(" ", ""), "page": b["page"],
                     "block_id": b["id"]} for b in s["blocks"]
                    for m in NUM.finditer(b["text"]) if re.search(r"\d", m.group(0))]
    jd(os.path.join(work, "source.json"), s)
    return s

def plan(src, c):
    zh = not str(c.get("lang") or "zh").lower().startswith("en")
    bud, mins = int(c.get("count") or 10), float(c.get("minutes") or 12)
    roles = list(ROLES)
    while len(roles) + 2 > bud and len(roles) > 1:      # honor a small slide_count
        for r in ("results", "limits", "conclusion", "question"):
            if roles.count(r) > 1:
                roles.remove(r)
                break
        else:
            roles.pop()
    for _ in range(max(0, bud - 2 - len(roles))):
        roles.insert(-2, "results") if roles.count("results") < 4 else roles.append("backup")
    title = c.get("title") or os.path.splitext(src["path"])[0]
    sl = [{"index": 1, "role": "title", "title": title, "bullets": [], "claim": "",
           "subtitle": "%s · %g min" % (c.get("audience") or "-", mins),
           "notes": "开场 30 秒：题目 + 一句话结论。"},
          {"index": 2, "role": "outline", "title": "讲解路线" if zh else "Outline",
           "claim": "先问题、再方法、后证据，最后交代边界。", "notes": "",
           "bullets": [{"text": TT[r], "anchor": {"source": "plan"}}
                       for r in dict.fromkeys(roles)]}]
    cands = [{"text": x.strip(), "anchor": {"source": src["path"], "page": b["page"],
                                            "block_id": b["id"], "quote": x.strip()}}
             for b in src["blocks"]
             for x in re.split(r"(?<=[.!?。！？])\s+", b["text"])
             if 30 <= len(x.strip()) <= 260]
    if not cands:
        cands = [{"text": b["text"][:260], "anchor": {"source": src["path"],
                                                      "page": b["page"],
                                                      "block_id": b["id"],
                                                      "quote": b["text"][:260]}}
                 for b in src["blocks"] if len(b["text"].strip()) >= 20]
    cands.sort(key=lambda b: (0 if re.search(r"[.。!?！？)]$", b["text"]) else 1,
                            0 if re.search(r"\d", b["text"]) else 1, -len(b["text"])))
    pool, seen = [], set()
    for b in cands:
        if b["anchor"]["block_id"] + b["text"][:12] not in seen:
            seen.add(b["anchor"]["block_id"] + b["text"][:12])
            pool.append(b)
    i = 0
    for j, role in enumerate(roles):
        k, n, got, chars = roles[:j].count(role), roles.count(role), [], 0
        while i < len(pool) and len(got) < (4 if role in ("method", "results") else 3) \
                and chars < 420:
            got.append(pool[i])
            chars, i = chars + len(pool[i]["text"]), i + 1
        sl.append({"index": len(sl) + 1, "role": role,
                   "title": TT[role] + ("" if n == 1 else " (%d/%d)" % (k + 1, n)),
                   "claim": "", "bullets": got, "notes": ""})
    return {"_comment": "auto plan; text may be rewritten, anchors/numbers must stay "
                        "traceable", "title": title, "audience": c.get("audience"),
            "language": c.get("lang") or "zh", "source": {"path": src["path"]},
            "slide_budget": bud, "plan_warnings": src["limits"][:4], "slides": sl}

def probe(p):
    t = {"source": os.path.basename(p) if p else None, "layouts": [],
         "safe": {"x": 48, "y": 120, "w": 864, "h": 340}}
    if p and os.path.isfile(p) and Presentation is not None:
        prs = Presentation(p)
        for i, lo in enumerate(prs.slide_layouts):
            sl = {}
            for x in lo.placeholders:
                sl.setdefault(PH.get(int(x.placeholder_format.type), "other"),
                              [float(x.left or 0) / 12700, float(x.top or 0) / 12700,
                               float(x.width or 0) / 12700, float(x.height or 0) / 12700])
            t["layouts"].append({"index": i, "name": lo.name or "", "slots": sl})
        for lo in t["layouts"]:
            if "title" in lo["slots"] and ({"body", "object"} & set(lo["slots"])):
                b = lo["slots"].get("body") or lo["slots"].get("object")
                t["safe"] = {"x": lo["slots"]["title"][0], "y": b[1],
                             "w": lo["slots"]["title"][2], "h": max(60.0, 500.0 - b[1])}
                break
    return t

def master(out):
    import pptx
    shutil.copy2(os.path.join(os.path.dirname(pptx.__file__), "templates",
                              "default.pptx"), out)
    prs = Presentation(out)
    prs.slide_width, prs.slide_height = 12192000, 6858000
    prs.save(out)
    return out

def lay(t, role):
    for w in (("title slide", "title") if role == "title"
              else ("title and content", "content")):
        for lo in t["layouts"]:
            if w in lo["name"].lower():
                return lo["index"]
    return 0

def build(spec, tpl, out, work):
    prs, t, safe, total = Presentation(tpl), probe(tpl), None, len(spec["slides"])
    t, safe = t, t["safe"]
    rep = {"slides": [], "warnings": []}
    for s in spec["slides"]:
        role = s.get("role") or "results"
        slide = prs.slides.add_slide(prs.slide_layouts[lay(t, role)])
        p = {}
        for x in slide.placeholders:
            p.setdefault(PH.get(int(x.placeholder_format.type), "other"), x)
        rec = {"index": s["index"], "role": role}
        ti = p.get("title") or p.get("ctitle")
        if ti is not None:
            ti.text_frame.text = s.get("title") or ""
            if role == "title":
                ti.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        if role == "title":
            if p.get("subtitle") is not None:
                p["subtitle"].text_frame.text = s.get("subtitle") or ""
            for k in ("body", "object"):
                if k in p:
                    p[k]._element.getparent().remove(p[k]._element)
        else:
            bl = [b for b in (s.get("bullets") or []) if b.get("text")]
            if bl:
                body = p.get("body") or p.get("object")
                box = body if body is not None else slide.shapes.add_textbox(
                    Emu(int(safe["x"] * 12700)), Emu(int(safe["y"] * 12700)),
                    Emu(int(safe["w"] * 12700)), Emu(int(safe["h"] * 12700)))
                if body is None:
                    box.name = "BodyText"
                h = float(body.height or 0) / 12700 if body is not None else safe["h"]
                need = sum(1 + len(b["text"]) // 22 for b in bl) * 22.0
                size = round(17.0 if need <= h - 10 else max(12.0, 17.0 * (h - 10) / need), 1)
                box.text_frame.word_wrap = True
                for j, b in enumerate(bl):
                    para = box.text_frame.paragraphs[0] if j == 0 else \
                        box.text_frame.add_paragraph()
                    para.text = b["text"]
                    for r in para.runs:
                        r.font.size = Pt(size)
                rec.update({"bullets": len(bl), "font_pt": size, "fits": need <= h - 10})
                if need > h - 10:
                    rep["warnings"].append({"level": "error", "slide": s["index"],
                                            "what": "text overflows at the floor size",
                                            "needed_pt": round(need), "box_pt": round(h)})
            keep = ("title", "ctitle", "subtitle", "date", "footer", "slideno")
            if bl:
                keep += ("body", "object")      # the filled body must survive pruning
            for x in list(slide.placeholders):
                if PH.get(int(x.placeholder_format.type), "other") not in keep:
                    x._element.getparent().remove(x._element)
        foot = slide.shapes.add_textbox(Emu(int(safe["x"] * 12700)), Emu(500 * 12700),
                                        Emu(int(safe["w"] * 12700)), Emu(22 * 12700))
        foot.name = "SourceFooter"
        pgs = [q for q in sorted({(b.get("anchor") or {}).get("page")
                                  for b in (s.get("bullets") or [])} - {None})
               if isinstance(q, int)]
        foot.text_frame.text = "来源 %s%s   %d/%d" % (
            spec["source"]["path"], " · p." + ", ".join(str(q) for q in pgs) if pgs
            else "", s["index"], total)
        for para in foot.text_frame.paragraphs:
            for r in para.runs:
                r.font.size = Pt(9)
        tf = slide.notes_slide.notes_text_frame
        tf.text = "\n".join((["[主张] %s" % s["claim"]] if s.get("claim") else []) + [
            ("- %s  [路线]" % b["text"][:150]) if (b["anchor"].get("source") == "plan")
            else ("- %s  [来源 %s p.%s %s]" % (b["text"][:150], b["anchor"].get("source"),
                                               b["anchor"].get("page"),
                                               b["anchor"].get("block_id") or ""))
            for b in (s.get("bullets") or [])] + ["[讲稿] " + (s.get("notes") or "")])
        for para in tf.paragraphs:
            for r in para.runs:
                r.font.size = Pt(11)
        rep["slides"].append(rec)
    try:
        prs.core_properties.title = spec.get("title") or "Academic slides"
        prs.core_properties.author = ""
        prs.core_properties.comments = "page evidence anchors are in the speaker notes"
    except Exception:
        pass
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    prs.save(out)
    rep.update({"output": out, "bytes": os.path.getsize(out), "slides_written": total})
    jd(os.path.join(work, "build_report.json"), rep)
    return rep

def tgt(slide, name):
    if name in (None, "", "*"):
        return [x for x in slide.shapes if x.has_text_frame and x.text_frame.text.strip()]
    if str(name).startswith("ph:"):
        return [x for x in slide.placeholders
                if PH.get(int(x.placeholder_format.type)) == str(name).split(":")[1]]
    return [x for x in slide.shapes if x.name == name]

def ops_apply(prs, ops):
    log = []
    for op in ops:
        kind, sn, sl = op.get("op"), int(op.get("slide") or 0), list(prs.slides)
        if kind not in ("set_title", "set_text", "replace_text", "compress_bullets",
                        "set_notes", "delete_slide"):
            log.append({"op": kind, "status": "unsupported"})
        elif not 1 <= sn <= len(sl):
            log.append({"op": kind, "slide": sn, "status": "skipped",
                        "why": "slide out of range"})
        elif kind == "delete_slide":
            ids = list(prs.slides._sldIdLst)
            prs.part.drop_rel(ids[sn - 1].rId)
            prs.slides._sldIdLst.remove(ids[sn - 1])
            log.append({"op": kind, "slide": sn, "status": "ok"})
        elif kind == "set_title":
            ti = sl[sn - 1].shapes.title
            if ti is None:
                log.append({"op": kind, "slide": sn, "status": "failed",
                            "why": "no title placeholder"})
            else:
                was = ti.text_frame.text
                ti.text_frame.text = op.get("text", "")
                log.append({"op": kind, "slide": sn, "status": "ok", "before": was,
                            "after": op.get("text", "")})
        elif kind == "set_notes":
            tf = sl[sn - 1].notes_slide.notes_text_frame
            n0 = len(tf.text)
            tf.text = op.get("text", "")
            log.append({"op": kind, "slide": sn, "status": "ok", "before_len": n0,
                        "after_len": len(tf.text)})
        else:
            hits, extra = 0, {}
            for sh in tgt(sl[sn - 1], op.get("shape")):
                tf = sh.text_frame
                if kind == "set_text":
                    for j, text in enumerate(op.get("paragraphs") or []):
                        para = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                        para.text = text
                    hits += 1
                    if not op.get("all"):
                        break
                elif kind == "replace_text":
                    find, repl = op.get("find", ""), op.get("replace", "")
                    for para in tf.paragraphs:
                        if not find or find not in para.text or not para.runs:
                            continue
                        if len(para.runs) > 1 and not any(find in r.text
                                                          for r in para.runs):
                            para.runs[0].text = para.text.replace(find, repl)
                            for r in para.runs[1:]:
                                r._r.getparent().remove(r._r)
                            hits += 1
                        else:
                            for r in para.runs:
                                if find in r.text:
                                    r.text = r.text.replace(find, repl)
                                    hits += 1
                else:
                    lim = int(op.get("max") or 3)
                    ps = [para.text for para in tf.paragraphs if para.text.strip()]
                    if len(ps) <= lim:
                        continue
                    for j, text in enumerate(ps[:lim]):
                        para = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                        para.text = text
                    while len(tf.paragraphs) > max(1, lim):
                        e = tf.paragraphs[-1]._p
                        e.getparent().remove(e)
                    extra = {"kept": lim, "dropped": ps[lim:], "why": op.get("why")}
                    hits += 1
                    break
            log.append({"op": kind, "slide": sn,
                        "status": "ok" if hits else
                        ("no-match" if kind == "replace_text" else "failed"),
                        "hits": hits, **extra})
    return log

def edit(deck_in, ops, out, work, target=None):
    prs = Presentation(deck_in)
    f0, n0 = fp(deck_in), len(prs.slides)
    log = ops_apply(prs, ops)
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    prs.save(out)
    v = os.path.join(work, "versions")
    os.makedirs(v, exist_ok=True)
    b = os.path.splitext(os.path.basename(deck_in))[0]
    shutil.copy2(deck_in, os.path.join(v, b + "-v0-original.pptx"))
    shutil.copy2(out, os.path.join(v, b + "-v1-edited.pptx"))
    f1, n1 = fp(out), len(Presentation(out).slides)
    rep = {"mode": "edit", "input": os.path.basename(deck_in), "ops": log,
           "slides_before": n0, "slides_after": n1, "template_preserved": f0 == f1,
           "fingerprint_differences": [] if f0 == f1 else {"before": f0, "after": f1},
           "changed_slides": [o.get("slide") for o in log
                              if o.get("status") in ("ok", "no-match")],
           "versions": [os.path.join(v, b + "-v0-original.pptx"),
                        os.path.join(v, b + "-v1-edited.pptx")],
           "target_slide_count": target,
           "meets_target": (n1 == int(target)) if target else None,
           "bytes": os.path.getsize(out)}
    jd(os.path.join(work, "edit_report.json"), rep)
    return rep

def render(pptx, out_dir):
    r = {"renderer": None, "render_status": "unavailable", "pdf": None, "png": [],
         "notes": []}
    os.makedirs(out_dir, exist_ok=True)
    pdf = os.path.join(out_dir, "deck.pdf")
    so = shutil.which("soffice") or shutil.which("libreoffice") or next(
        (p for p in ("/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                     r"C:\Program Files\LibreOffice\program\soffice.exe")
         if os.path.isfile(p)), None)
    if so:
        try:
            subprocess.run([so, "--headless", "--norestore", "--convert-to", "pdf",
                            "--outdir", out_dir, pptx], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=180)
            r["renderer"] = "soffice"
        except Exception as e:
            r["notes"].append("soffice failed: %s" % str(e)[:80])
    if not os.path.isfile(pdf) and os.name == "nt":
        import tempfile
        exe = shutil.which("pwsh") or shutil.which("powershell")
        sc = os.path.join(tempfile.mkdtemp(prefix="deckpdf"), "c.ps1")
        open(sc, "w", encoding="utf-8-sig").write(
            "$ErrorActionPreference='Stop';$a=New-Object -ComObject PowerPoint."
            "Application;try{$p=$a.Presentations.Open('%s',$true,$false,$false);"
            "$p.SaveAs('%s',32);$p.Close()}finally{$a.Quit()}"
            % (os.path.abspath(pptx), os.path.abspath(pdf)))
        for i in range(3):
            try:
                subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                sc], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=240)
                if os.path.isfile(pdf) and os.path.getsize(pdf) > 0:
                    r["renderer"] = "powerpoint-com(attempt %d)" % (i + 1)
                    break
            except Exception as e:
                r["notes"].append("COM attempt %d: %s" % (i + 1, str(e)[:60]))
            time.sleep(2)
    if os.path.isfile(pdf) and os.path.getsize(pdf) > 0:
        r.update({"pdf": pdf, "render_status": "ok", "renderer": r["renderer"] or "convert"})
        try:
            import fitz
            doc = fitz.open(pdf)
            for i in range(doc.page_count):
                p = os.path.join(out_dir, "slide-%02d.png" % (i + 1))
                doc[i].get_pixmap(dpi=110).save(p)
                r["png"].append(p)
            doc.close()
        except Exception:
            pass
    else:
        r["notes"].append("no LibreOffice/PowerPoint: PDF preview unavailable (no PNG "
                          "is produced rather than faked)")
    return r

def main(argv=None):
    ap = argparse.ArgumentParser(description="minimal academic deck kit")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="")
    a = ap.parse_args(argv)
    t0, case, indir = time.time(), {}, None
    if os.path.isdir(a.case):
        indir = os.path.abspath(a.case)
        for n in sorted(os.listdir(indir)):
            if n.endswith(".json") and (n == "case.json" or iscase(
                    os.path.join(indir, n))):
                case = json.load(open(os.path.join(indir, n), encoding="utf-8"))
                break
    elif os.path.isfile(a.case):
        indir = os.path.dirname(os.path.abspath(a.case))
        case = json.load(open(a.case, encoding="utf-8"))
    indir = indir or ("/input" if os.path.isdir("/input") else ".")
    os.makedirs(a.out, exist_ok=True)
    work = a.work or os.path.join(a.out, "_work")
    os.makedirs(work, exist_ok=True)
    stages, warns, unc, chlog = [], [], [], []
    st = lambda n, s, d=None: stages.append({"stage": n, "status": s, "detail": d or {}})
    fields = cfields(case)
    cid = case.get("case_id") or case.get("caseId") or case.get("id") or ""
    st("contract", "ok" if fields else "degraded", {"case_id": cid, "fields": fields})
    f = find(indir, case, os.getcwd())
    st("discover", "ok" if (f["material"] or f["deck"]) else "degraded",
       {k: (os.path.basename(v) if isinstance(v, str) else None)
        for k, v in f.items() if k in ("material", "template", "deck", "ops", "spec")}
       | {"resolved_from": f["resolved_from"], "missing": f["missing"]})
    if f["missing"]:
        unc.append("case.json points at files that do not exist: %s"
                   % json.dumps(f["missing"], ensure_ascii=False))
    if not f["material"] and not f["deck"]:
        unc.append("no material and no starting deck in the input directory")
    tpl = f["template"]
    if not tpl:
        try:
            tpl = master(os.path.join(work, "neutral-master.pptx"))
            warns.append("no template supplied: built a neutral 16:9 master")
        except Exception as e:
            unc.append("no template and the neutral master could not be built: %s"
                       % str(e)[:60])
    st("template", "ok" if tpl else "failed",
       {"source": os.path.basename(tpl) if tpl else None})
    jd(os.path.join(work, "template.json"), probe(tpl))
    src = None
    if f["material"]:
        try:
            src = ingest(f["material"], work)
            st("ingest", "ok", {"parser": src["parser"], "blocks": len(src["blocks"]),
                                "numbers": len(src["numbers"]),
                                "limitations": src["limits"]})
            unc += src["limits"]
            warns += src.get("notes") or []
        except Exception as e:
            st("ingest", "failed", {"error": str(e)[:100]})
            unc.append("material could not be read: %s" % str(e)[:80])
    deck = os.path.join(a.out, "deck.pptx")
    spec = build_rep = edit_rep = rrep = checks = None
    g = lambda *n: cget(case, *n)  # noqa: E731
    # Step 2: drop an honest partial result.json NOW (interruption-safe, zero decisions).
    # It is overwritten by the final result.json at the end of this run; if the run is
    # killed during build/render/verify, the platform still finds a valid, truthful file.
    partial = {"case_id": cid, "status": "partial", "_partial": True,
               "_partial_at_stage": "after discovery/ingest, before build",
               "contract_fields_detected": fields,
               "stages": list(stages), "uncertainty": list(unc),
               "deliverable": {"pptx": "deck.pptx", "slides": 0, "editable": None,
                               "note": "placeholder written before build; the final "
                                       "result.json replaces this file"},
               "sources": [{"kind": "material",
                            "path": (src or {}).get("path") or
                            (os.path.basename(f["deck"]) if f["deck"] else None),
                            "sha256_16": (src or {}).get("sha256_16")}],
               "resolved_from": f["resolved_from"]}
    for k in fields:
        partial[k] = ""
    partial["contract_echo"] = {k: "" for k in fields}
    jd(os.path.join(a.out, "result.json"), partial)
    st("partial_result", "ok", {"written": os.path.join(a.out, "result.json"),
                                "status": "partial", "why": "interruption safety"})
    if f["deck"]:
        ops = []
        if f["ops"]:
            data = json.load(open(f["ops"], encoding="utf-8"))
            ops = data.get("ops") if isinstance(data, dict) else data
        elif isinstance(case.get("ops"), list):
            ops = case["ops"]
        if ops:
            edit_rep = edit(f["deck"], ops, deck, work, g("slide_count", "num_slides"))
            st("edit", "ok" if edit_rep["template_preserved"] else "failed",
               {"slides": [edit_rep["slides_before"], edit_rep["slides_after"]],
                "template_preserved": edit_rep["template_preserved"],
                "meets_target": edit_rep["meets_target"]})
            chlog += [{"what": o.get("op"), "slide": o.get("slide"),
                       "why": o.get("why") or "explicit edit op",
                       "status": o.get("status")} for o in edit_rep["ops"]]
            if not edit_rep["template_preserved"]:
                unc.append("design fingerprint changed while editing")
        else:
            shutil.copy2(f["deck"], deck)
            st("edit", "degraded", {"why": "starting deck without ops: copied"})
            warns.append("starting deck copied through (no edit instructions found)")
    elif src and tpl:
        if f["spec"]:
            spec = json.load(open(f["spec"], encoding="utf-8"))
            st("plan", "ok", {"source": os.path.basename(f["spec"]),
                              "slides": len(spec.get("slides") or [])})
        else:
            spec = plan(src, {"lang": g("language", "lang"),
                              "count": g("slide_count", "num_slides", "max_slides"),
                              "minutes": g("minutes", "duration_min"),
                              "audience": g("audience"), "title": g("deck_title")})
            jd(os.path.join(work, "deck_plan.json"), spec)
            st("plan", "ok", {"slides": len(spec["slides"]),
                              "warnings": spec["plan_warnings"]})
            warns += spec["plan_warnings"]
        build_rep = build(spec, tpl, deck, work)
        st("build", "ok", {"slides": build_rep["slides_written"],
                           "bytes": build_rep["bytes"],
                           "warnings": len(build_rep["warnings"])})
        chlog.append({"what": "generate deck from plan",
                      "why": "%s slides" % len(spec["slides"]), "status": "ok"})
        warns += ["slide %s: %s" % (w.get("slide"), w.get("what"))
                  for w in build_rep["warnings"]]
    else:
        st("build", "skipped", {"why": "no material or no template"})
    if os.path.isfile(deck):
        rrep = render(deck, os.path.join(a.out, "preview"))
        jd(os.path.join(work, "render_report.json"), rrep)
        st("render", "ok" if rrep["render_status"] == "ok" else "degraded",
           {"renderer": rrep["renderer"], "png": len(rrep["png"]),
            "notes": rrep["notes"][:2]})
        if rrep["render_status"] != "ok":
            unc.append("no renderer available: PDF preview missing")
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import verify as vm
            checks = vm.check(deck, case=case, source=src, spec=spec, template=tpl,
                              render=rrep)
        except Exception as e:
            checks = {"passed": None, "error": str(e)[:120]}
        jd(os.path.join(work, "checks.json"), checks)
        st("verify", "ok" if checks.get("passed") else "degraded",
           {"passed": checks.get("passed"),
            "failed": (checks.get("summary") or {}).get("failed_ids"),
            "not_applicable": (checks.get("summary") or {}).get("not_applicable")})
    ev = [{"slide": s["index"], "role": s.get("role"), "claim": s.get("claim"),
           "anchor": b["anchor"]} for s in ((spec or {}).get("slides") or [])
          for b in (s.get("bullets") or []) if (b.get("anchor") or {}).get("page")
          or (b.get("anchor") or {}).get("block_id")]
    if not ev and os.path.isfile(deck):
        from pptx import Presentation as _P
        for i, s in enumerate(_P(deck).slides, 1):
            t = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
            for m in re.finditer(r"- (.*?)\s+\[来源 ([^\]]+?)\s+p\.(\d+)\s*(\S*)\]", t):
                ev.append({"slide": i, "role": "edited", "claim": "",
                           "anchor": {"source": m.group(2), "page": int(m.group(3)),
                                      "block_id": m.group(4) or None,
                                      "quote": m.group(1).strip()}})
    with open(os.path.join(a.out, "evidence_map.jsonl"), "w", encoding="utf-8") as fh:
        for row in ev:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if spec:
        jd(os.path.join(a.out, "slide_plan.json"), spec)
    n = len((spec or {}).get("slides") or []) or (edit_rep or {}).get("slides_after") or 0
    real = 0
    if os.path.isfile(deck):
        try:
            real = len(Presentation(deck).slides)
        except Exception as exc:
            unc.append("deck.pptx cannot be opened: %s" % str(exc)[:60])
        if real == 0:
            unc.append("empty-artifact guard: the produced deck has 0 slides "
                       "(input discovery or build produced nothing)")
        n = real or n
    outs = []
    for p in [deck, (rrep or {}).get("pdf")] + list((rrep or {}).get("png") or []) + [
            os.path.join(a.out, "evidence_map.jsonl"),
            os.path.join(a.out, "slide_plan.json") if spec else None]:
        if p and os.path.isfile(p):
            outs.append({"path": os.path.relpath(p, a.out),
                         "bytes": os.path.getsize(p),
                         "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]})
    dv = {"pptx": "deck.pptx",
          "pptx_bytes": os.path.getsize(deck) if os.path.isfile(deck) else 0,
          "slides": n, "editable": True, "pdf_preview": (rrep or {}).get("pdf"),
          "png_previews": (rrep or {}).get("png") or [], "notes_included": True}
    biz = {"deliverable": dv, "deck": dv, "evidence_map": ev,
           "outputs": outs, "changes": chlog,
           "notes": [{"index": s["index"], "notes": s.get("notes") or ""}
                     for s in ((spec or {}).get("slides") or [])],
           "slide_plan": [{"index": s["index"], "role": s.get("role"),
                           "title": s.get("title"), "claim": s.get("claim")}
                          for s in ((spec or {}).get("slides") or [])],
           "render_and_versions": {
               "renderer": (rrep or {}).get("renderer"),
               "render_status": (rrep or {}).get("render_status"),
               "pdf": (rrep or {}).get("pdf"),
               "png_count": len((rrep or {}).get("png") or []),
               "template": os.path.basename(tpl) if tpl else None,
               "template_preserved": (edit_rep or {}).get("template_preserved",
                                                          True if build_rep else None),
               "versions": (edit_rep or {}).get("versions") or []},
           "checks": checks, "change_log": chlog, "stages": stages,
           "summary": "%s slides; preview %s" % (n, os.path.basename(
               dv["pdf_preview"] or "") or "none"),
           "limitations": (unc + warns)[:10], "runtime_s": round(time.time() - t0, 2)}
    status = "failed"
    if os.path.isfile(deck):
        status = "partial" if (unc or (checks or {}).get("passed") is False or
                               (edit_rep and not edit_rep["template_preserved"])) \
            else "success"
    res = {"case_id": cid, "status": status, "contract_fields_detected": fields}
    echo = {}
    for k in fields:
        res[k] = echo[k] = biz.get(k, "")
    for k, v in biz.items():
        res.setdefault(k, v)
    res.update({"contract_echo": echo,
                "resolved_from": f["resolved_from"],
                "sources": [{"kind": "material",
                             "path": (src or {}).get("path") or
                             (os.path.basename(f["deck"]) if f["deck"] else None),
                             "sha256_16": (src or {}).get("sha256_16"),
                             "anchors": "page/block ids in evidence_map"}],
                "uncertainty": unc, "change_log": chlog,
                "contract_missing_fields": [k for k in fields
                                            if res.get(k) in ("", None, [], {})]})
    jd(os.path.join(a.out, "result.json"), res)
    print(json.dumps({"result": os.path.join(a.out, "result.json"), "status": status,
                      "slides": n, "render": (rrep or {}).get("render_status"),
                      "checks_passed": (checks or {}).get("passed"),
                      "stages": [(s["stage"], s["status"]) for s in stages]},
                     ensure_ascii=False))
    return 0 if status != "failed" else 1

if __name__ == "__main__":
    sys.exit(main())
