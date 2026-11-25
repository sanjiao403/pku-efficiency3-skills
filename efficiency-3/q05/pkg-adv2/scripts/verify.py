#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# verify.py -- 独立复核：只读写出的 SVG 与 result.json，不信作者的数据结构。
#   python3 scripts/verify.py --svg figures/figure.svg --result result.json \
#           [--materials /input] [--case /input/case.json]
# 退出码 0 通过 / 2 有硬失败。
#
# 硬检查（hard=True，任一不过即 exit 2）：
#   svg.well_formed / svg.no_raster_or_foreign / svg.text_is_real_text / svg.layers_present
#   svg.mm_scale_consistent / svg.font_family_declared
#   arrow.one_head_per_connector / arrow.head_sits_on_endpoint
#   layout.content_within_canvas / scale.bar_length_true
#   provenance.blocks_have_quote / provenance.every_element_drawn
#   result.required_keys / result.no_nulls / result.status_honest
#   provenance.no_invented_numbers（给了 --materials 时）
#   contract.declared_fields_present（给了 --case 时）
# 说明：本文件**不打分也不信任作者内存状态**——所有结论都从写出的文件重算，
#       包括自己重算内容包围盒（不读 result.json 里同名结论作证据，只做交叉比对）。
import argparse, json, math, os, re, struct, sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

K = 96.0 / 25.4
NS = "{http://www.w3.org/2000/svg}"
NUM = re.compile(r"(?<![\w.\-])(\d+(?:[.,]\d+)?)(?![\w.\-])")
WIDE = ((0x1100, 0x115F), (0x2E80, 0xA4CF), (0xAC00, 0xD7A3), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6))


def tw(s, z):
    return sum(z * (1.0 if any(a <= ord(c) <= b for a, b in WIDE) else 0.545) for c in (s or ""))


def doc_text(e):
    return "".join(e.itertext()) if e is not None else ""


def main(a=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--result", default="")
    ap.add_argument("--materials", default="")
    ap.add_argument("--case", default="")
    ap.add_argument("--edited", default="", help="可选：源文件保留式编辑后的 SVG，逐项比对")
    x = ap.parse_args(a)
    if not x.case and x.materials:
        cand = os.path.join(x.materials, "case.json")
        x.case = cand if os.path.exists(cand) else ""
    if not x.materials and x.case:                     # 只给 --case 时也去核真实文件（堵"不给 --materials 就不查"的缝）
        x.materials = os.path.dirname(os.path.abspath(x.case))
    it, fails = [], []

    def ck(name, ok, detail, hard=True):
        it.append({"check": name, "ok": bool(ok), "hard": bool(hard), "detail": str(detail)[:300]})
        if hard and not ok:
            fails.append(name)

    # ---- SVG 结构 ------------------------------------------------------
    try:
        root = ET.parse(x.svg).getroot()
        ck("svg.well_formed", True, "%d bytes" % os.path.getsize(x.svg))
    except Exception as e:
        print("[verify] FAIL svg.well_formed %s" % e)
        return 2
    tags = {}
    for el in root.iter():
        t = el.tag.split("}")[-1]
        tags[t] = tags.get(t, 0) + 1
    ck("svg.no_raster_or_foreign", tags.get("image", 0) == 0 and tags.get("foreignObject", 0) == 0,
       "image=%d foreignObject=%d" % (tags.get("image", 0), tags.get("foreignObject", 0)))
    texts = [el for el in root.iter() if el.tag == NS + "text"]
    ck("svg.text_is_real_text", len(texts) >= 4, "%d <text>" % len(texts))
    layers = [el.get("id") for el in root.iter() if el.tag == NS + "g" and (el.get("id") or "").startswith("layer-")]
    ck("svg.layers_present", len(layers) >= 2, "%s" % layers)
    w = float(re.sub(r"[^0-9.]", "", root.get("width") or "0") or 0)
    vb = (root.get("width") or "").endswith("mm") and (root.get("viewBox") or "").split()
    ok = bool(vb) and len(vb) == 4 and abs(float(vb[2]) - w * K) < 0.05
    ck("svg.mm_scale_consistent", ok, "width=%s viewBox=%s (1mm=%.4fpx)" % (root.get("width"),
                                                                           root.get("viewBox"), K))
    # 字体回退链：每段文字都要有 font-family（且带通用族），否则导出端可能是方框
    nf = [el for el in texts if not (el.get("font-family") or root.get("font-family"))]
    stacks = {el.get("font-family") for el in texts if el.get("font-family")}
    ck("svg.font_family_declared", (not nf) and bool(stacks) and all("sans-serif" in s for s in stacks),
       "texts=%d without family=%d stacks=%s" % (len(texts), len(nf),
                                                 sorted(s.split(",")[0] for s in stacks)[:3]))

    # 箭头：每条 connector 恰好一个箭头，且端点重合
    conns = [el for el in root.iter() if el.get("data-role") == "connector"]
    heads = [el for el in root.iter() if el.get("data-role") == "arrowhead"]
    cf, hf = {}, {}
    for c in conns:
        cf.setdefault(c.get("data-fid") or "", []).append(c)
    for h in heads:
        hf.setdefault(h.get("data-fid") or "", []).append(h)
    bad = [f for f in cf if f and len(hf.get(f, [])) != 1]
    ck("arrow.one_head_per_connector", bool(cf) and not bad,
       "connectors=%d heads=%d offenders=%s" % (len(conns), len(heads), bad[:5]))
    skew = []
    for f, cs in cf.items():
        if not f or f not in hf:
            continue
        pts = [tuple(float(v) for v in p.split(",")) for p in (cs[0].get("points") or "").split()]
        tip = max((tuple(float(v) for v in p.split(",")) for p in (hf[f][0].get("points") or "").split()),
                  key=lambda p: math.dist(p, pts[-2] if len(pts) > 1 else pts[0]))
        if len(pts) > 1 and math.dist(tip, pts[-1]) > 1.5:
            skew.append({"fid": f, "gap_px": round(math.dist(tip, pts[-1]), 2)})
    ck("arrow.head_sits_on_endpoint", not skew, "%s" % skew[:4])

    # 内容包围盒：自己重算（不读 result.json 的同名结论）
    xs, ys = [], []
    for el in root.iter():
        tg, attrs = el.tag.split("}")[-1], el.attrib
        if tg == "rect" and attrs.get("id") != "page":
            xs += [float(attrs.get("x", 0)), float(attrs.get("x", 0)) + float(attrs.get("width", 0))]
            ys += [float(attrs.get("y", 0)), float(attrs.get("y", 0)) + float(attrs.get("height", 0))]
        elif tg in ("polyline", "polygon"):
            p = [tuple(float(v) for v in q.split(",")) for q in (attrs.get("points") or "").split()]
            xs += [q[0] for q in p]; ys += [q[1] for q in p]
        elif tg == "text":
            z = float(attrs.get("font-size", 9))
            wid = tw(doc_text(el), z)
            an, ax = attrs.get("text-anchor", "start"), float(attrs.get("x", 0))
            x0 = ax if an == "start" else (ax - wid if an == "end" else ax - wid / 2.)
            xs += [x0, x0 + wid]; ys += [float(attrs.get("y", 0)) - z * .8, float(attrs.get("y", 0)) + z * .3]
    H = float(re.sub(r"[^0-9.]", "", root.get("height") or "0") or 0) * K
    oob = []
    if xs:
        if min(xs) < -1.5 or max(xs) > w * K + 1.5:
            oob.append("x %.1f..%.1f vs 0..%.1f" % (min(xs), max(xs), w * K))
        if min(ys) < -1.5 or max(ys) > H + 1.5:
            oob.append("y %.1f..%.1f vs 0..%.1f" % (min(ys), max(ys), H))
    ck("layout.content_within_canvas", bool(xs) and not oob,
       "bbox=(%.1f,%.1f,%.1f,%.1f) canvas=%.1fx%.1f %s" % (min(xs), min(ys), max(xs), max(ys), w * K, H,
                                                           "; ".join(oob)))

    # 比例尺
    bars = [el for el in root.iter() if el.get("data-role") == "scale-bar" and el.tag == NS + "polyline"]
    claims = [doc_text(el) for el in root.iter() if el.get("data-role") == "scale-bar-text"]
    mm = next((float(m.group(1)) for t in claims for m in [re.match(r"\s*([\d.]+)\s*mm", t)] if m), None)
    if bars and mm:
        pts = [tuple(float(v) for v in p.split(",")) for p in (bars[0].get("points") or "").split()]
        got = max(math.dist(p, q) for p in pts for q in pts) / K
        ck("scale.bar_length_true", abs(got - mm) <= max(.3, mm * .01), "drawn %.2f mm vs label %s" % (got, mm))
    else:
        ck("scale.bar_present", False, "no scale bar")

    # 来源可追：每个块带 data-quote（现在 data-role 真的存在了，这条不再空转）
    shapes = [el for el in root.iter() if el.get("data-role") == "node-shape"]
    ids = {el.get("data-node") for el in shapes if el.get("data-node")}
    quo = {el.get("data-node") for el in shapes if el.get("data-node") and (el.get("data-quote") or "").strip()}
    ck("provenance.blocks_have_quote", bool(ids) and len(quo) == len(ids),
       "%d/%d blocks carry data-quote" % (len(quo), len(ids)))
    srcs = {el.get("data-src") for el in shapes if el.get("data-src")}
    ck("provenance.locators_present", bool(srcs), "%d distinct locators" % len(srcs))
    for c in conns:
        if not (c.get("data-quote") or "").strip():
            ck("provenance.connectors_have_quote", False, "connector %s without data-quote" % c.get("data-fid"))
            break
    else:
        ck("provenance.connectors_have_quote", bool(conns), "%d connectors all carry data-quote" % len(conns))

    # ---- result.json ---------------------------------------------------
    R = {}
    if x.result and os.path.exists(x.result):
        R = json.load(open(x.result, encoding="utf-8"))
        need = ("case_id", "status", "elements", "relations", "provenance", "uncertainty", "gaps",
                "deliverable", "data_mapping", "contract_echo", "output_contract", "change_log",
                "checks", "source_files", "review")
        miss = [k for k in need if k not in R]
        ck("result.required_keys", not miss, "missing=%s" % miss)
        ck("result.no_nulls", not [k for k, v in R.items() if v is None],
           "nulls=%s" % [k for k, v in R.items() if v is None])
        ck("result.status_honest", (R.get("status") == "partial") or (not fails),
           "status=%s prior_hard_failures=%s" % (R.get("status"), fails[:3]))
        ck("result.change_log_present", bool(R.get("change_log")) and
           all(k in (R.get("change_log") or [{}])[0] for k in ("action", "by", "reason")),
           "entries=%d" % len(R.get("change_log") or []))
        oc = R.get("output_contract") or {}
        ck("result.output_contract_sections",
           all(k in oc for k in ("editable_sources", "exports", "data_mapping", "element_traceability")),
           "sections=%s" % sorted(oc.keys()))
        # 声称画了的实体必须真的画在 SVG 上（抓"结果里列了、图上没有"）
        drawn = {e.get("data-node") for e in shapes if e.get("data-node")}
        claimed = {e.get("id") for e in (R.get("elements") or [])}
        missing = sorted(claimed - drawn)
        ck("provenance.every_element_drawn", bool(claimed) and not missing,
           "claimed=%d drawn=%d missing=%s" % (len(claimed), len(drawn), missing[:6]))
        # 独立重算的包围盒与 result.json 自述交叉比对（不一致即为自述失真）
        L = (R.get("checks") or {}).get("layout") or {}
        bb = L.get("content_bbox_px")
        if bb and xs:
            d = max(abs(float(bb[0]) - min(xs)), abs(float(bb[1]) - min(ys)),
                    abs(float(bb[2]) - max(xs)), abs(float(bb[3]) - max(ys)))
            ck("layout.bbox_matches_selfcheck", d <= 2.0, "max delta %.2f px" % d, hard=False)
        outs = R.get("outputs") or (R.get("deliverable") or {}).get("exports") or []
        ck("result.outputs_listed", bool(outs), "outputs=%d" % len(outs), hard=False)
        if x.case and os.path.exists(x.case):
            try:
                case = json.load(open(x.case, encoding="utf-8-sig"))
            except Exception:
                case = {}
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            try:
                from extract import contract as _contract
            except Exception:
                _contract = None
            F = _contract(case) if _contract else {}
            miss_c = [k for k in F if k not in R]
            ck("contract.declared_fields_present", not miss_c,
               "declared=%d missing_at_top_level=%s" % (len(F), miss_c))
        if x.materials:
            # 数字白名单只收 **material 角色** 的文件：工单/示例/模板里的数字不算证据，
            # 否则"图上的数字能在材料里找到"会因为把指令文本也拼进语料而假通过。
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            try:
                from extract import classify as _classify
            except Exception:
                _classify = None
            blob, skipped = [], []
            for root_d, _s, fs in os.walk(x.materials):
                for f in sorted(fs):
                    if os.path.splitext(f)[1].lower() not in (".md", ".txt", ".csv", ".tsv", ".json", ".tex"):
                        continue
                    p = os.path.join(root_d, f)
                    try:
                        t = open(p, "rb").read().decode("utf-8", "replace")
                    except Exception:
                        continue
                    if _classify and _classify(p, t, x.case or None) != "material":
                        skipped.append(os.path.relpath(p, x.materials))
                        continue
                    blob.append(t)
            allowed = {float(v) for v in re.findall(r"\d+(?:\.\d+)?", " ".join(blob))}
            allowed |= {float(e.get("seq") or 0) for e in (R.get("elements") or [])}
            lab = " ".join(doc_text(el) for el in texts_sel(root))
            inv = sorted({m.group(1) for m in NUM.finditer(lab)
                          if float(m.group(1).replace(",", "")) not in allowed})
            ck("provenance.no_invented_numbers", not inv,
               "unexplained=%s (corpus excl. %s)" % (inv[:6], skipped or "none"))
    else:
        ck("result.present", False, "no result.json given")

    # 每条来源定位的文件必须是"材料"：指向未读文件或工单文件即为证据污染
    if R:
        mats = set((R.get("provenance") or {}).get("materials") or [])
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from extract import WO_NAMES, WO_PAT
        except Exception:
            WO_NAMES, WO_PAT = ("case.json", "task.md"), None
        locs = []
        for sec in ("elements", "relations"):
            for e in (R.get(sec) or []):
                L = (e.get("source") or {}).get("locator")
                if L:
                    locs.append((sec, str(L)))
        unresolved = sorted({"{}: {}".format(s, L) for s, L in locs if L.split("#")[0] not in mats})
        ck("provenance.locators_resolve", bool(locs) and not unresolved,
           "locators=%d unresolved=%s (materials=%s)" % (len(locs), unresolved[:4], sorted(mats)[:5]))
        bad_wo = sorted({L.split("#")[0] for _s, L in locs
                         if os.path.basename(L.split("#")[0]).lower() in WO_NAMES
                         or (WO_PAT and WO_PAT.search(os.path.basename(L.split("#")[0]).lower()))})
        bad_wo += sorted(m for m in mats if os.path.basename(m).lower() in WO_NAMES
                         or (WO_PAT and WO_PAT.search(os.path.basename(m).lower())))
        ck("provenance.no_workorder_sources", not bad_wo,
           "workorder-like sources=%s" % (bad_wo[:5] or "none"))
        # 落到**真实文件**上核验（QA 终检 P1）：文件存在 + 行号不越界 + 引文能在文件里找到
        if x.materials:
            idx = material_index(x.materials, x.case or "")
            inline = set((R.get("provenance") or {}).get("inline_materials") or [])
            ghost, oob, notfound = [], [], []
            for sec in ("elements", "relations"):
                for e in (R.get(sec) or []):
                    src = e.get("source") or {}
                    L = str(src.get("locator") or "")
                    if not L:
                        continue
                    fn = L.split("#")[0]
                    if "::" in fn:                       # case.json 内联材料（伪文件名）
                        base = fn.split("::")[0]
                        if fn not in inline and base not in inline:
                            ghost.append("%s:%s(inline not declared)" % (sec, fn))
                        continue
                    hit = idx.get(fn) or idx.get(os.path.basename(fn))
                    if not hit:
                        ghost.append("%s:%s" % (sec, fn)); continue
                    _p, txt, nlines = hit
                    ln = re.findall(r"L(\d+)", L.split("#", 1)[-1])
                    if ln and max(int(v) for v in ln) > nlines + 1:
                        oob.append("%s:%s (max L%s > %d lines)" % (sec, fn, max(ln), nlines))
                    q = _norm(src.get("quote"))
                    if q and q[:40] and q[:40] not in _norm(txt):
                        notfound.append("%s:%s#%s" % (sec, fn, q[:24]))
            ck("provenance.locators_exist_in_input", not ghost,
               "ghost materials=%s (materials=1 real index, e.g. %s)"
               % (ghost[:4] or "none", sorted(idx)[:3]))
            ck("provenance.locator_lines_in_range", not oob, "out-of-range=%s" % (oob[:4] or "none"))
            ck("provenance.quotes_found_in_material", not notfound,
               "quotes not found=%s" % (notfound[:4] or "none"))
    # ---- 导出件的**字节级重测**（不采信 result.json 里的"已导出"说法）------------
    d_dir = os.path.dirname(os.path.abspath(x.svg))
    pdb = os.path.join(d_dir, "figure.pdf")
    png = os.path.join(d_dir, "figure.png")
    R0 = R or {}
    svg_mm = [float(re.sub(r"[^0-9.]", "", root.get("width") or "0") or 0),
              float(re.sub(r"[^0-9.]", "", root.get("height") or "0") or 0)]
    has_pdf = os.path.exists(pdb) and os.path.getsize(pdb) > 200
    has_png = os.path.exists(png) and os.path.getsize(png) > 200
    want = (not R0) or R0.get("status") == "success"
    ck("export.three_formats_present", (not want) or (has_pdf and has_png),
       "svg=True pdf=%s png=%s status=%s" % (has_pdf, has_png, R0.get("status")))
    if has_pdf:
        b = open(pdb, "rb").read()
        m = re.search(rb"/MediaBox\s*\[([^\]]+)\]", b)
        got = None
        if m:
            n = [float(v) for v in m.group(1).split()[:4]]
            got = [(n[2] - n[0]) * 25.4 / 72., (n[3] - n[1]) * 25.4 / 72.]
        okpage = bool(got) and abs(got[0] - svg_mm[0]) <= 0.5 and abs(got[1] - svg_mm[1]) <= 0.5
        ck("export.pdf_page_matches_canvas", okpage,
           "pdf page %.2fx%.2f mm vs svg %.2fx%.2f mm"
           % ((got or [0, 0])[0], (got or [0, 0])[1], svg_mm[0], svg_mm[1]))
        n_img = len(re.findall(rb"/Subtype\s*/Image", b))
        n_ff = len(re.findall(rb"/FontFile2?\b", b)) + len(re.findall(rb"/FontFile3\b", b))
        # 口径 D40：算子在**解压后**的内容流里数；"文字可抽取"按 Unicode 抽取结果判定
        import zlib as _z
        st = []
        for mm_ in re.finditer(rb"stream\r?\n", b):
            s0 = mm_.end(); e0 = b.find(b"endstream", s0)
            if e0 < 0:
                continue
            try:
                st.append(_z.decompress(b[s0:e0]))
            except Exception:
                st.append(b[s0:e0])
        tj_array = sum(len(re.findall(rb"\bTJ\b", s)) for s in st)
        tj_lit = sum(len(re.findall(rb"\bTj\b", s)) for s in st)
        ck("export.pdf_vector_no_raster", n_img == 0, "image xobjects=%d" % n_img)
        ck("export.pdf_has_live_text", (tj_array + tj_lit) > 0 and n_ff > 0,
           "TJ arrays=%d Tj literals=%d (inflated), embedded font files=%d"
           % (tj_array, tj_lit, n_ff))
        svg_txt = _norm("".join("".join(e.itertext()) for e in texts))
        got_u, src_u = "", None
        for nm_, fnn in (("pypdf", _uni_pypdf), ("pymupdf", _uni_fitz)):
            try:
                got_u, src_u = fnn(pdb), nm_
                break
            except Exception:
                continue
        u = _norm(got_u)
        cov = (len(u) / max(1, len(svg_txt))) if u else 0.0
        ck("export.pdf_text_unicode_extractable",
           bool(u) and cov >= 0.85 and got_u.count("\ufffd") <= max(1, len(u) * 0.02),
           "unicode chars=%d (source=%s) vs svg text=%d, coverage=%.3f, U+FFFD=%d"
           % (len(u), src_u, len(svg_txt), cov, got_u.count("\ufffd")))
        try:
            import fitz as _fz
            doc = _fz.open(pdb)
            raw = doc[0].get_text("rawdict")
            pix = doc[0].get_pixmap(matrix=_fz.Matrix(2, 2), alpha=False)
            W, H, smp, nch = pix.width, pix.height, pix.samples, pix.n
            hit = miss = 0
            for blk in raw.get("blocks", []):
                for ln_ in blk.get("lines", []):
                    for sp in ln_.get("spans", []):
                        for ch in sp.get("chars", []):
                            if not (ch.get("c") or "").strip():
                                continue
                            x0, y0, x1, y1 = [int(v * 2) for v in ch["bbox"]]
                            ink = 0
                            for yy in range(max(0, y0), min(H, y1 + 1)):
                                row = yy * nch * W
                                for xx in range(max(0, x0), min(W, x1 + 1)):
                                    i2 = row + xx * nch
                                    if smp[i2] < 200 or smp[i2 + 1] < 200 or smp[i2 + 2] < 200:
                                        ink = 1; break
                                if ink:
                                    break
                            hit += ink
                            miss += 1 - ink
            rate = hit / max(1, hit + miss)
            ck("export.pdf_glyphs_inked", hit > 0 and rate >= 0.98,
               "glyph ink hit=%d miss=%d rate=%.4f" % (hit, miss, rate))
        except Exception as e:
            ck("export.pdf_glyphs_inked", True, "skipped: %s" % str(e)[:80], hard=False)
    if has_png:
        b = open(png, "rb").read()
        if b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR":
            w, h = struct.unpack(">II", b[16:24])
            ph = re.search(rb"pHYs(.{9})", b, re.S)
            dpi = None
            if ph:
                ppx, _ppy, unit = struct.unpack(">IIB", ph.group(1))
                dpi = round(ppx * 0.0254, 1) if unit == 1 else None
            cl = (R0.get("checks") or {}).get("exports") or {}
            target = float(cl.get("target_dpi") or 300)
            exp = (svg_mm[0] / 25.4 * target, svg_mm[1] / 25.4 * target)
            okpx = abs(w - exp[0]) <= 2 and abs(h - exp[1]) <= 2
            ck("export.png_px_matches_dpi", okpx,
               "%dx%d px vs %.0fx%.0f expected @ %g dpi" % (w, h, exp[0], exp[1], target))
            ck("export.png_dpi_tag", dpi is not None and abs(dpi - target) <= 1,
               "pHYs dpi=%s target=%g" % (dpi, target))
        else:
            ck("export.png_is_png", False, "not a PNG (IHDR missing)")
    # ---- 源文件保留式编辑：给出 --edited 时逐项比对（只允许一处文字变化）----
    if x.edited and os.path.exists(x.edited):
        try:
            e2 = ET.parse(x.edited).getroot()
            t1 = ["".join(el.itertext()) for el in root.iter() if el.tag == NS + "text"]
            t2 = ["".join(el.itertext()) for el in e2.iter() if el.tag == NS + "text"]
            n1 = [el.get("data-node") for el in root.iter() if el.get("data-role") == "node-shape"]
            n2 = [el.get("data-node") for el in e2.iter() if el.get("data-role") == "node-shape"]
            q1 = [el.get("data-quote") for el in root.iter() if el.get("data-quote")]
            q2 = [el.get("data-quote") for el in e2.iter() if el.get("data-quote")]
            diff = [i for i in range(min(len(t1), len(t2))) if t1[i] != t2[i]]
            ck("edit.one_text_touched", len(t1) == len(t2) and len(diff) == 1,
               "texts %d->%d changed=%s" % (len(t1), len(t2), diff[:4]))
            ck("edit.structure_preserved", n1 == n2 and q1 == q2,
               "node ids equal=%s quotes equal=%s" % (n1 == n2, q1 == q2))
        except Exception as e:
            ck("edit.parseable", False, "%s" % str(e)[:100])

    # 空图 + partial 是诚实结果（材料里没有可画的东西）：与内容相关的检查标 not_applicable
    if R and not (R.get("elements") or []) and R.get("status") == "partial":
        soft = {"arrow.one_head_per_connector", "provenance.blocks_have_quote",
                "provenance.locators_present", "provenance.connectors_have_quote",
                "provenance.every_element_drawn", "provenance.locators_resolve"}
        for i in it:
            if i["check"] in soft:
                i["hard"] = False
                i["detail"] = "[not_applicable: empty figure] " + i["detail"]
        fails = [f for f in fails if f not in soft]

    for i in it:
        print("[%s] %-38s %s" % ("ok  " if i["ok"] else ("FAIL" if i["hard"] else "warn"),
                                 i["check"], i["detail"]))
    print("[verify] ok=%s hard_failures=%d checks=%d" % (not fails, len(fails), len(it)))
    return 0 if not fails else 2


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def _uni_pypdf(p):
    from pypdf import PdfReader
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(p).pages)


def _uni_fitz(p):
    import fitz
    return "\n".join(pg.get_text("text") for pg in fitz.open(p))


def material_index(materials, case=""):
    """真实材料索引：rel 路径 / basename -> (绝对路径, 文本, 行数)。

    QA 终检（P1）指出：只跟产物**自己声明**的 provenance.materials 比对等于自证 ——
    改两处（locator + materials）就能让一个从未读过的材料当证据。所以这里改成
    落到 `--materials` 下的**真实文件**上核验。
    """
    idx = {}
    if not materials:
        return idx
    for root, _s, fs in os.walk(materials):
        for f in sorted(fs):
            p = os.path.join(root, f)
            if os.path.splitext(f)[1].lower() not in (".md", ".txt", ".csv", ".tsv", ".json",
                                                      ".tex", ".yaml", ".yml", ".log", ".pdf"):
                continue
            rel = os.path.relpath(p, materials).replace("\\", "/")
            try:
                if os.path.splitext(f)[1].lower() == ".pdf":
                    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                    from measure import unicode_text
                    t = unicode_text(p).get("unicode_sample") or ""
                    idx[rel] = (p, t, 1)
                else:
                    t = open(p, "rb").read().decode("utf-8", "replace")
                    idx[rel] = (p, t, len(t.splitlines()))
            except Exception:
                idx[rel] = (p, "", 0)
    for rel, (p, t, n) in list(idx.items()):
        idx.setdefault(os.path.basename(rel), (p, t, n))
    return idx


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def texts_sel(root):
    out = []
    for el in root.iter():
        if el.tag == NS + "text" and el.get("data-role") in ("node-label", "label", "phase-title"):
            out.append(el)
    return out


if __name__ == "__main__":
    sys.exit(main())

