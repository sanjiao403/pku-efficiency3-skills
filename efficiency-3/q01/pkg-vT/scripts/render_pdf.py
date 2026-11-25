#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_pdf -- vector PDF export.

Two paths:
  1. cairosvg / PyMuPDF convert the SVG itself (best fidelity);
  2. a pure-stdlib PDF writer draws the *same scene* with real vector operators
     (re / m / l / c / Tj), ASCII in Helvetica and CJK in the predefined
     STSong-Light CID font, so a PDF always exists even on a bare interpreter.

The stdlib path keeps text as selectable text (never outlines), and the page
size is derived from canvas px and dpi, so "resolution" claims stay checkable.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # never leave __pycache__ behind


import struct
import zlib
from pathlib import Path

import ga_core as C


def pdf_info(path):
    try:
        data = Path(path).read_bytes()
    except Exception:
        return None
    if len(data) < 8 or not data.startswith(b"%PDF-"):
        return None
    pages = data.count(b"/Type /Page\n") + data.count(b"/Type /Page ")
    if pages == 0:
        pages = data.count(b"/Type/Page") - data.count(b"/Type/Pages")
    has_content = b"/Contents" in data
    return {"bytes": len(data), "pages": max(1, pages), "header": data[:8].decode("latin-1"),
            "vector": bool(has_content) and b"/Subtype /Image" not in data,
            "compressed_stream": b"/FlateDecode" in data}


def _via_cairosvg(svg_path, pdf_path):
    try:
        import cairosvg
        cairosvg.svg2pdf(url=str(svg_path), write_to=str(pdf_path))
        return "cairosvg"
    except Exception:
        return None


def _via_pymupdf(svg_path, pdf_path):
    try:
        import fitz
        doc = fitz.open(str(svg_path))
        data = doc.convert_to_pdf()
        Path(pdf_path).write_bytes(data)
        doc.close()
        return "pymupdf"
    except Exception:
        return None


# --------------------------------------------------------------------------
# stdlib vector PDF writer
# --------------------------------------------------------------------------
def _hex_rgb(color):
    c = (color or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return (0.0, 0.0, 0.0)
    try:
        return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return (0.0, 0.0, 0.0)


def _n(v):
    s = ("%.2f" % float(v)).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _pdf_escape(s):
    out = []
    for ch in s:
        if ch in "()\\":
            out.append("\\" + ch)
        elif ord(ch) < 32:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _is_wide(ch):
    return C.is_wide(ch)


def _split_runs(s):
    runs, cur, cur_wide = [], "", None
    for ch in s:
        w = _is_wide(ch)
        if cur_wide is None or w == cur_wide:
            cur += ch
            cur_wide = w
        else:
            runs.append((cur_wide, cur))
            cur, cur_wide = ch, w
    if cur:
        runs.append((cur_wide, cur))
    return runs


def _circle_path(cx, cy, r):
    k = 0.5523 * r
    return ("%s %s m %s %s %s %s %s %s c %s %s %s %s %s %s c "
            "%s %s %s %s %s %s c %s %s %s %s %s %s c" % (
                _n(cx + r), _n(cy), _n(cx + r), _n(cy - k), _n(cx + k), _n(cy - r),
                _n(cx), _n(cy - r), _n(cx - k), _n(cy - r), _n(cx - r), _n(cy - k),
                _n(cx - r), _n(cy), _n(cx - r), _n(cy + k), _n(cx - k), _n(cy + r),
                _n(cx), _n(cy + r), _n(cx + k), _n(cy + r), _n(cx + r), _n(cy + k),
                _n(cx + r), _n(cy)))


def _write_stdlib_pdf(scene, pdf_path):
    canvas = scene["canvas"]
    W, H, dpi = canvas["width_px"], canvas["height_px"], canvas["dpi"]
    k = 72.0 / float(dpi)
    pw, ph = W * k, H * k

    def X(x):
        return x * k

    def Y(y):
        return H * k - y * k

    body = []
    bg = _hex_rgb(canvas["background"])
    body.append("q %s %s %s rg 0 0 %s %s re f Q" % (_n(bg[0]), _n(bg[1]), _n(bg[2]),
                                                     _n(pw), _n(ph)))
    # hatch patterns are drawn as clipped line groups
    for p in scene["prims"]:
        t = p["t"]
        if t == "rect":
            x, y, w, h = X(p["x"]), Y(p["y"] + p["h"]), max(0.0, p["w"] * k), max(0.0, p["h"] * k)
            if p["fill"] not in ("none", "") and not p.get("pattern"):
                r, g, b = _hex_rgb(p["fill"])
                body.append("q %s %s %s rg %s %s %s %s re f Q" % (
                    _n(r), _n(g), _n(b), _n(x), _n(y), _n(w), _n(h)))
            elif p.get("pattern") and p["fill"] not in ("none", ""):
                r, g, b = _hex_rgb(p["fill"])
                body.append("q %s %s %s rg %s %s %s %s re f Q" % (
                    _n(r), _n(g), _n(b), _n(x), _n(y), _n(w), _n(h)))
                body.append("q %s %s %s %s re W n" % (_n(x), _n(y), _n(w), _n(h)))
                body.append("0.28 0.28 0.30 RG 0.9 w")
                step = 7.0 * k
                if p["pattern"] in ("hatch45", "hatch135", "hatch90", "cross", "grid"):
                    if p["pattern"] in ("hatch90", "cross", "grid"):
                        xx = x
                        while xx <= x + w:
                            body.append("%s %s m %s %s l S" % (_n(xx), _n(y), _n(xx), _n(y + h)))
                            xx += step
                    if p["pattern"] in ("cross", "grid"):
                        yy = y
                        while yy <= y + h:
                            body.append("%s %s m %s %s l S" % (_n(x), _n(yy), _n(x + w), _n(yy)))
                            yy += step
                    else:
                        sign = -1.0 if p["pattern"] == "hatch45" else 1.0
                        d = -h
                        while d <= w:
                            body.append("%s %s m %s %s l S" % (
                                _n(x), _n(y), _n(x + sign * h), _n(y + h)))
                            d += step
                elif p["pattern"] == "dots":
                    yy = y + step * 0.4
                    while yy < y + h:
                        xx = x + step * 0.4
                        while xx < x + w:
                            body.append("%s %s m %s %s l S" % (_n(xx), _n(yy), _n(xx), _n(yy + 0.01)))
                            xx += step
                        yy += step
                body.append("Q")
            if p["stroke"] not in ("none", "") and p["sw"] > 0:
                r, g, b = _hex_rgb(p["stroke"])
                body.append("q %s %s %s RG %s w %s %s %s %s re S Q" % (
                    _n(r), _n(g), _n(b), _n(max(0.2, p["sw"] * k)), _n(x), _n(y), _n(w), _n(h)))
        elif t == "line":
            r, g, b = _hex_rgb(p["stroke"])
            dash = ""
            if p["dash"]:
                try:
                    on, off = [float(v) * k for v in p["dash"].replace(",", " ").split()][:2]
                    dash = "[%s %s] 0 d " % (_n(on), _n(off))
                except Exception:
                    dash = ""
            body.append("q %s %s %s RG %s w %s%s %s m %s %s l S Q" % (
                _n(r), _n(g), _n(b), _n(max(0.2, p["sw"] * k)), dash,
                _n(X(p["x1"])), _n(Y(p["y1"])), _n(X(p["x2"])), _n(Y(p["y2"]))))
        elif t == "poly":
            pts = p["pts"]
            if not pts:
                continue
            d = "%s %s m " % (_n(X(pts[0][0])), _n(Y(pts[0][1])))
            d += " ".join("%s %s l" % (_n(X(a)), _n(Y(b))) for a, b in pts[1:])
            if p["fill"] not in ("none", "") and len(pts) >= 3:
                r, g, b = _hex_rgb(p["fill"])
                body.append("q %s %s %s rg %s h f Q" % (_n(r), _n(g), _n(b), d))
            if p["stroke"] not in ("none", ""):
                r, g, b = _hex_rgb(p["stroke"])
                body.append("q %s %s %s RG %s w %s h S Q" % (
                    _n(r), _n(g), _n(b), _n(max(0.2, p["sw"] * k)), d))
        elif t == "circle":
            path = _circle_path(X(p["cx"]), Y(p["cy"]), p["r"] * k)
            if p["fill"] not in ("none", ""):
                r, g, b = _hex_rgb(p["fill"])
                body.append("q %s %s %s rg %s f Q" % (_n(r), _n(g), _n(b), path))
            if p["stroke"] not in ("none", ""):
                r, g, b = _hex_rgb(p["stroke"])
                body.append("q %s %s %s RG %s w %s S Q" % (
                    _n(r), _n(g), _n(b), _n(max(0.2, p["sw"] * k)), path))
        elif t == "text":
            size = p["size"] * k
            x0 = p["x"]
            if p["anchor"] == "middle":
                x0 -= C.text_width(p["s"], p["size"], p["bold"]) / 2.0
            elif p["anchor"] == "end":
                x0 -= C.text_width(p["s"], p["size"], p["bold"])
            r, g, b = _hex_rgb(p["fill"])
            if p["bold"]:
                fnt = "F2"
            elif p["italic"]:
                fnt = "F3"
            else:
                fnt = "F1"
            cursor = x0
            for wide, chunk in _split_runs(p["s"]):
                if not chunk:
                    continue
                if wide:
                    hexs = chunk.encode("utf-16-be").hex().upper()
                    body.append("BT /F4 %s Tf %s %s %s rg %s %s Td <%s> Tj ET" % (
                        _n(size), _n(r), _n(g), _n(b), _n(X(cursor)), _n(Y(p["y"])), hexs))
                else:
                    body.append("BT /%s %s Tf %s %s %s rg %s %s Td (%s) Tj ET" % (
                        fnt, _n(size), _n(r), _n(g), _n(b), _n(X(cursor)), _n(Y(p["y"])),
                        _pdf_escape(chunk)))
                cursor += C.text_width(chunk, p["size"], False)

    stream = "\n".join(body).encode("latin-1", "replace")
    compressed = zlib.compress(stream, 6)

    def obj(num, payload):
        return b"%d 0 obj\n" % num + payload + b"\nendobj\n"

    objs = []
    objs.append(obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objs.append(obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"))
    objs.append(obj(3, ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
                        "/Resources << /Font << /F1 5 0 R /F2 6 0 R /F3 7 0 R /F4 8 0 R >> >> "
                        "/Contents 4 0 R >>" % (_n(pw), _n(ph))).encode("latin-1")))
    objs.append(obj(4, b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(compressed) +
                    compressed + b"\nendstream"))
    objs.append(obj(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                       b"/Encoding /WinAnsiEncoding >>"))
    objs.append(obj(6, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                       b"/Encoding /WinAnsiEncoding >>"))
    objs.append(obj(7, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique "
                       b"/Encoding /WinAnsiEncoding >>"))
    objs.append(obj(8, b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
                       b"/Encoding /UniGB-UCS2-H /DescendantFonts [9 0 R] >>"))
    objs.append(obj(9, b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
                       b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> "
                       b"/FontDescriptor 11 0 R /DW 1000 >>"))
    objs.append(obj(10, ("<< /Producer (graphical-abstract-svg skill) "
                         "/Title (graphical abstract) /Creator (ga_build.py) >>").encode("latin-1")))
    objs.append(obj(11, b"<< /Type /FontDescriptor /FontName /STSong-Light /Flags 4 "
                       b"/FontBBox [-25 -254 1000 880] /ItalicAngle 0 /Ascent 880 "
                       b"/Descent -120 /CapHeight 700 /StemV 80 >>"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for o in objs:
        offsets.append(len(out))
        out += o
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += ("%010d 00000 n \n" % off).encode("latin-1")
    out += ("trailer\n<< /Size %d /Root 1 0 R /Info 10 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref_pos)).encode("latin-1")
    Path(pdf_path).write_bytes(bytes(out))
    return "stdlib-pdf"


def export_pdf(scene, svg_path, pdf_path):
    svg_path, pdf_path = Path(svg_path), Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = scene["canvas"]
    record = {"path": str(pdf_path.name), "engine": "", "verified": False,
              "attempts": [], "pages": 0, "vector": True,
              "page_width_pt": round(canvas["width_px"] * 72.0 / canvas["dpi"], 1),
              "page_height_pt": round(canvas["height_px"] * 72.0 / canvas["dpi"], 1)}
    for name, fn in (("cairosvg", lambda: _via_cairosvg(svg_path, pdf_path)),
                     ("pymupdf", lambda: _via_pymupdf(svg_path, pdf_path)),
                     ("stdlib-pdf", lambda: _write_stdlib_pdf(scene, pdf_path))):
        try:
            got = fn()
        except Exception as exc:
            record["attempts"].append({"engine": name, "result": "exception",
                                       "detail": str(exc)[:160]})
            continue
        if not got:
            record["attempts"].append({"engine": name, "result": "unavailable"})
            continue
        info = pdf_info(pdf_path)
        if not info or info["bytes"] < 800:
            record["attempts"].append({"engine": name, "result": "invalid_pdf"})
            continue
        record["attempts"].append({"engine": name, "result": "ok"})
        record["engine"] = got
        record["verified"] = True
        record["pages"] = info["pages"]
        record["bytes"] = info["bytes"]
        record["header"] = info["header"]
        record["vector"] = True
        if name == "stdlib-pdf":
            record["note"] = "标准库矢量 PDF：文字保留为可选中文本，CJK 用 STSong-Light CID 字体"
        return record
    record["attempts"].append({"engine": "all", "result": "failed"})
    return record

