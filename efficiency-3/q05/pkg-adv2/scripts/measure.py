#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# measure.py -- 产物字节级重测（SVG / PDF / PNG）+ 渲染回读（字形覆盖与着墨率）
#
# 目的：题面 workorder 要求 `Real editable SVG/PNG/PDF`。只写"已导出"不算证据，
# 这里全部从**写出的字节**重读：
#   * PDF：/MediaBox -> 页盒 mm（必须等于画布 mm）、Tj/TJ 文本算子数、/Subtype /Image 位图数（矢量必须为 0）、
#          /FontFile* 嵌入字体程序数；有 pymupdf 时再回读文本与每个字形的着墨率
#          （未嵌入中文字体时 PDF 里中文会变方框/空白，着墨率会掉下来 —— 这条能真的抓到）
#   * PNG：IHDR 宽高/位深/颜色类型、pHYs 的 DPI，并与 画布 mm × dpi 的期望像素数比对；
#          采样若干 SVG 图元中心点，确认栅格不是空白
#   * SVG：尺寸 mm、文本数、语义图元数、图层数、位图数
import os, re, struct, sys, zlib
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
NS = "{http://www.w3.org/2000/svg}"
PT_MM = 25.4 / 72.0


# ---------------- SVG ----------------
def svg_facts(path):
    o = {"bytes": os.path.getsize(path), "well_formed": False}
    try:
        root = ET.parse(path).getroot()
    except Exception as x:
        o["error"] = str(x)[:80]
        return o
    o["well_formed"] = True
    o["width_mm"] = float(re.sub(r"[^0-9.]", "", root.get("width") or "0") or 0)
    o["height_mm"] = float(re.sub(r"[^0-9.]", "", root.get("height") or "0") or 0)
    vb = (root.get("viewBox") or "").split()
    o["viewbox_px"] = [float(v) for v in vb[2:4]] if len(vb) == 4 else []
    o["texts"] = sum(1 for e in root.iter() if e.tag == NS + "text")
    o["images"] = sum(1 for e in root.iter() if e.tag == NS + "image")
    o["node_shapes"] = sum(1 for e in root.iter() if e.get("data-role") == "node-shape")
    o["connectors"] = sum(1 for e in root.iter() if e.get("data-role") == "connector")
    o["arrowheads"] = sum(1 for e in root.iter() if e.get("data-role") == "arrowhead")
    o["layers"] = sorted(e.get("id") for e in root.iter()
                         if e.tag == NS + "g" and (e.get("id") or "").startswith("layer-"))
    o["text_chars"] = len(re.sub(r"\s", "", "".join(
        "".join(t.itertext()) for t in root.iter() if t.tag == NS + "text")))
    o["cjk_chars"] = len([c for c in "".join("".join(t.itertext()) for t in root.iter()
                                             if t.tag == NS + "text") if "\u4e00" <= c <= "\u9fff"])
    o["node_centers_px"] = _node_centers(root)
    return o


def _node_centers(root, k=6):
    """取前 k 个实体矩形的中心（SVG 用户坐标 = 96 dpi px），供 PNG 采样。"""
    out = []
    for e in root.iter():
        if e.tag == NS + "rect" and e.get("data-role") == "node-shape":
            try:
                out.append((float(e.get("x")) + float(e.get("width")) / 2.,
                            float(e.get("y")) + float(e.get("height")) / 2.))
            except Exception:
                pass
        if len(out) >= k:
            break
    return out


# ---------------- PDF ----------------
def inflate_streams(b):
    """把 PDF 里所有 stream 解压出来（结论口径 D40：算子/文字必须在**解压后**的字节上数）。"""
    out = []
    for m in re.finditer(rb"stream\r?\n", b):
        s = m.end()
        e = b.find(b"endstream", s)
        if e < 0:
            continue
        raw = b[s:e]
        try:
            out.append(zlib.decompress(raw))
        except Exception:
            try:
                out.append(zlib.decompressobj().decompress(raw))
            except Exception:
                out.append(raw)                      # 未压缩内容流
    return out


def pdf_facts(path):
    b = open(path, "rb").read()
    o = {"bytes": len(b)}
    m = re.search(rb"/MediaBox\s*\[([^\]]+)\]", b)
    if m:
        n = [float(x) for x in m.group(1).split()[:4]]
        o["media_box_pt"] = [round(n[2] - n[0], 2), round(n[3] - n[1], 2)]
        o["page_mm"] = [round((n[2] - n[0]) * PT_MM, 2), round((n[3] - n[1]) * PT_MM, 2)]
    st = inflate_streams(b)
    o["content_streams"] = len(st)
    o["tj_arrays"] = sum(len(re.findall(rb"\bTJ\b", s)) for s in st)
    o["tj_literals"] = sum(len(re.findall(rb"\bTj\b", s)) for s in st)
    o["text_ops"] = o["tj_arrays"] + o["tj_literals"]        # 解压后的真实算子数
    o["text_ops_raw_compressed_scan"] = (len(re.findall(rb"\bTj\b", b))
                                        + len(re.findall(rb"\bTJ\b", b)))   # 仅供参考：会少报
    o["images"] = len(re.findall(rb"/Subtype\s*/Image", b))
    o["font_files"] = len(re.findall(rb"/FontFile2?\b", b)) + len(re.findall(rb"/FontFile3\b", b))
    o["fonts"] = sorted({x.decode("latin-1", "replace")
                         for x in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-_,]{2,60})", b)})[:8]
    o["has_to_unicode"] = bool(re.search(rb"/ToUnicode", b))
    o.update(unicode_text(pdb=path))
    return o


def unicode_text(pdb):
    """Unicode 抽取口径（D40）：优先 pypdf，其次 pymupdf，最后包内纯标准库 pdftext。

    "文字可抽取"必须按 Unicode 抽取结果判定；按 `Tj` 字面量数会少报（本包实测 0 个字面量、
    真实文字全在 `TJ` 数组里）。
    """
    for name, fn in (("pypdf", _unicode_pypdf), ("pymupdf", _unicode_fitz),
                     ("pdftext-stdlib", _unicode_pdftext)):
        try:
            t = fn(pdb)
            if t is None:
                continue
            chars = len(re.findall(r"[^\W_]", t, re.UNICODE))
            return {"text_source": name, "unicode_chars": chars,
                    "unicode_cjk": len([c for c in t if "\u4e00" <= c <= "\u9fff"]),
                    "unicode_replacement": t.count("\ufffd"),
                    "unicode_sample": re.sub(r"\s+", " ", t)[:70]}
        except Exception:
            continue
    return {"text_source": None, "unicode_chars": -1, "unicode_error": "no extractor available"}


def _unicode_pypdf(p):
    from pypdf import PdfReader
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(p).pages)


def _unicode_fitz(p):
    import fitz
    try:
        fitz.TOOLS.mupdf_display_errors(False); fitz.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass
    dn, sd = os.open(os.devnull, os.O_WRONLY), os.dup(2)
    try:
        os.dup2(dn, 2)
        return "\n".join(pg.get_text("text") for pg in fitz.open(p))
    finally:
        os.dup2(sd, 2); os.close(dn); os.close(sd)


def _unicode_pdftext(p):
    from pdftext import pdf_text
    return pdf_text(p)


# ---------------- PNG ----------------
def _png_chunks(b):
    i = 8
    while i + 8 <= len(b):
        ln = struct.unpack(">I", b[i:i + 4])[0]
        typ = b[i + 4:i + 8]
        data = b[i + 8:i + 8 + ln]
        yield typ, data
        i += 12 + ln


def png_facts(path):
    b = open(path, "rb").read()
    o = {"bytes": len(b), "signature_ok": b[:8] == b"\x89PNG\r\n\x1a\n"}
    chunks = dict(_png_chunks(b)) if o["signature_ok"] else {}
    if b"IHDR" in chunks:
        w, h, bd, ct, comp, filt, inter = struct.unpack(">IIBBBBB", chunks[b"IHDR"][:13])
        o.update(width_px=w, height_px=h, bit_depth=bd, color_type=ct, interlaced=inter)
    if b"pHYs" in chunks and len(chunks[b"pHYs"]) >= 9:
        ppx, ppy, unit = struct.unpack(">IIB", chunks[b"pHYs"][:9])
        if unit == 1:
            o["dpi"] = [round(ppx * 0.0254, 1), round(ppy * 0.0254, 1)]
    o["has_phys"] = b"pHYs" in chunks
    return o


def set_png_dpi(path, dpi):
    """把 pHYs 改成真实 DPI（MuPDF 写 96 dpi，会让查看器/排版软件按错误尺寸摆图）。纯标准库。"""
    b = open(path, "rb").read()
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    ppx = int(round(dpi / 0.0254))
    new = struct.pack(">IIB", ppx, ppx, 1)
    out, i, done = bytearray(b[:8]), 8, False
    while i + 8 <= len(b):
        ln = struct.unpack(">I", b[i:i + 4])[0]
        typ = b[i + 4:i + 8]
        data = b[i + 8:i + 8 + ln]
        if typ == b"pHYs":
            out += struct.pack(">I", len(new)) + typ + new
            out += struct.pack(">I", zlib.crc32(typ + new) & 0xFFFFFFFF)
            done = True
        else:
            out += b[i:i + 12 + ln]
        i += 12 + ln
    if not done:                                    # 没有 pHYs：插到 IHDR 之后
        return False
    open(path, "wb").write(bytes(out))
    return True


def png_sample(path, pts_px, view_px):
    """按 SVG 用户坐标采样 PNG 像素；返回 [(x,y,(r,g,b))]（PNG 不支持则返回 []）。"""
    b = open(path, "rb").read()
    chunks = dict(_png_chunks(b)) if b[:8] == b"\x89PNG\r\n\x1a\n" else {}
    if b"IHDR" not in chunks:
        return []
    w, h, bd, ct, comp, filt, inter = struct.unpack(">IIBBBBB", chunks[b"IHDR"][:13])
    if bd != 8 or ct not in (2, 6) or inter != 0:
        return []
    nch = 3 if ct == 2 else 4
    raw = zlib.decompress(b"".join(d for t, d in _png_chunks(b) if t == b"IDAT"))
    stride = w * nch
    rows, prev, p = [], bytearray(stride), 0
    for _y in range(h):
        ft = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        if ft == 1:
            for i in range(nch, stride):
                line[i] = (line[i] + line[i - nch]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                bb = prev[i]
                c = prev[i - nch] if i >= nch else 0
                pp = a + bb - c
                pa, pb, pc = abs(pp - a), abs(pp - bb), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (bb if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        rows.append(bytes(line))
        prev = line
    sx = (w / view_px[0]) if view_px and view_px[0] else 1.
    sy = (h / view_px[1]) if view_px and view_px[1] else 1.
    out = []
    for x, y in pts_px:
        px, py = int(x * sx), int(y * sy)
        if 0 <= px < w and 0 <= py < h:
            i = px * nch
            out.append((px, py, tuple(rows[py][i:i + 3])))
    return out


# ---------------- 渲染回读（可选：仅当 pymupdf 可用）----------------
def render_facts(pdf, svg, extra_dpi=2.0):
    """PDF 回读：Unicode 文字覆盖率（口径 D40）+ 每字形着墨率（字体没被真用上会掉下来）。

    覆盖率 = Unicode 抽取到的字符数 / SVG 里应出现的字符数（去空白后比较）。
    """
    uni = unicode_text(pdf)
    exp = svg_facts(svg).get("text_chars", 0)
    base = {"available": uni.get("text_source") is not None, "expected_chars": exp,
            "decoded_chars": uni.get("unicode_chars"), "text_source": uni.get("text_source"),
            "cjk_chars": uni.get("unicode_cjk"), "junk_chars": uni.get("unicode_replacement"),
            "coverage": round(min(1.0, max(0, uni.get("unicode_chars") or 0) / max(1, exp)), 4)}
    if not base["available"]:
        base["why"] = uni.get("unicode_error", "no text extractor")
        return base
    try:
        import fitz
    except Exception as x:
        base["why"] = "pymupdf missing for ink check: %s" % str(x)[:60]
        return base
    try:
        d = fitz.open(pdf)
        raw = d[0].get_text("rawdict")
        pix = d[0].get_pixmap(matrix=fitz.Matrix(extra_dpi, extra_dpi), alpha=False)
        W, H, smp, n = pix.width, pix.height, pix.samples, pix.n
        hit = miss = 0
        for blk in raw.get("blocks", []):
            for ln in blk.get("lines", []):
                for sp in ln.get("spans", []):
                    for ch in sp.get("chars", []):
                        if not (ch.get("c") or "").strip():
                            continue
                        x0, y0, x1, y1 = [int(v * extra_dpi) for v in ch["bbox"]]
                        ink = 0
                        for yy in range(max(0, y0), min(H, y1 + 1)):
                            row = yy * n * W
                            for xx in range(max(0, x0), min(W, x1 + 1)):
                                i = row + xx * n
                                if smp[i] < 200 or smp[i + 1] < 200 or smp[i + 2] < 200:
                                    ink = 1
                                    break
                            if ink:
                                break
                        hit += ink
                        miss += 1 - ink
        base.update(glyph_ink_hit=hit, glyph_ink_miss=miss,
                    glyph_ink_rate=round(hit / max(1, hit + miss), 4))
    except Exception as x:
        base["why"] = "ink check failed: %s" % str(x)[:70]
    return base


def all_facts(sv, pdb, png, canvas_mm, dpi):
    o = {"expected_png_px": [int(round(canvas_mm[0] / 25.4 * dpi)), int(round(canvas_mm[1] / 25.4 * dpi))],
         "target_dpi": dpi, "svg": svg_facts(sv)}
    o["pdf"] = pdf_facts(pdb) if pdb and os.path.exists(pdb) else {"missing": True}
    o["png"] = png_facts(png) if png and os.path.exists(png) else {"missing": True}
    if o["pdf"].get("page_mm"):
        o["pdf"]["page_matches_canvas"] = (abs(o["pdf"]["page_mm"][0] - canvas_mm[0]) <= 0.5
                                           and abs(o["pdf"]["page_mm"][1] - canvas_mm[1]) <= 0.5)
    if o["png"].get("width_px"):
        o["png"]["px_matches_dpi"] = (abs(o["png"]["width_px"] - o["expected_png_px"][0]) <= 2
                                      and abs(o["png"]["height_px"] - o["expected_png_px"][1]) <= 2)
    if o["pdf"].get("bytes") and os.path.exists(sv):
        o["render"] = render_facts(pdb, sv)
        o["sample"] = png_sample(png, o["svg"].get("node_centers_px", []),
                                 o["svg"].get("viewbox_px", [])) if not o["png"].get("missing") else []
        ink = [s for s in o["sample"] if sum(s[2]) < 720]          # 非纯白
        o["png"]["node_centers_inked"] = "%d/%d" % (len(ink), len(o["sample"]))
    return o
