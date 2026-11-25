# -*- coding: utf-8 -*-
"""minipdf - a tiny, dependency-free PDF writer for the rendered-deck preview.

Why this file exists: `outputs[]` used to advertise a render that was never produced
(`render: {"engine": ..., "preview": None}`), so "editable + rendered" could not be checked.
This module writes a real PDF *from the page plan* (title / claim / bullets / page number),
with a text layer that can be extracted again, so `verify.py` can measure the file instead of
trusting a note.

Deliberate limits, recorded in render-record.json:
  * page geometry is the deck's own 16:9 size (960x540 pt), not PowerPoint's layout engine;
  * Latin text uses the PDF base-14 Helvetica, CJK text uses the standard CID font
    STSong-Light with the UniGB-UCS2-H CMap (viewer-supplied, NOT embedded) - no font
    binary is ever shipped in the package;
  * when LibreOffice is available the caller prefers it and this module is not used.
"""
import hashlib
import io
import re
import zlib

PAGE_W, PAGE_H = 960.0, 540.0
MARGIN = 56.0
BULLET = "\u2022"


def _esc_lit(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


# characters that exist in WinAnsi (Helvetica): keep them OUT of the CJK font, or the CMap has no
# glyph for them and the preview shows garbage where a bullet / ± / × / … should be.
WINANSI = {0x2013: 0x96, 0x2014: 0x97, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93, 0x201D: 0x94,
           0x2022: 0x95, 0x2026: 0x85, 0x00B0: 0xB0, 0x00B1: 0xB1, 0x00B7: 0xB7, 0x00D7: 0xD7,
           0x00F7: 0xF7, 0x2212: 0x2D}


def _win_ok(ch):
    return ord(ch) < 128 or ord(ch) in WINANSI


def _esc_win(s):
    """Escape a WinAnsi string as a PDF literal: parentheses/backslashes and every byte >= 0x7F."""
    out = []
    for ch in s:
        b = WINANSI.get(ord(ch), ord(ch))
        if 32 <= b < 127:
            out.append("\\%s" % chr(b) if chr(b) in "()\\" else chr(b))
        else:
            out.append("\\%03o" % b)
    return "".join(out)


def _is_ascii(s):
    return all(ord(c) < 128 for c in s)


def _runs(text):
    """Split a line into WinAnsi / CJK runs so Latin text is not rendered as full-width CJK."""
    out, cur, mode = [], "", None
    for ch in text:
        m = _win_ok(ch)
        if mode is None or m == mode:
            cur += ch
        else:
            out.append((mode, cur))
            cur = ch
        mode = m
    if cur:
        out.append((mode, cur))
    return out


def _text_ops(x, y, text, font, size, color=(0.10, 0.15, 0.22)):
    """Text run(s) at (x, y): WinAnsi chars with Helvetica (base-14), CJK as UTF-16BE hex with the
    UniGB CMap, each run placed by an estimated advance so mixed lines stay readable. Everything
    lands in a real text layer, which is why verify.py can extract it back out of the bytes."""
    ops = ["BT", "%.3f %.3f %.3f rg" % color, "1 0 0 1 %.2f %.2f Tm" % (x, y)]
    cx = x
    for win, seg in _runs(text):
        use = font if win else "F2"
        ops.append("/%s %.2f Tf" % (use, size))
        ops.append("1 0 0 1 %.2f %.2f Tm" % (cx, y))
        if win:
            ops.append("(%s) Tj" % _esc_win(seg))
            cx += size * 0.52 * len(seg)
        else:
            ops.append("<%s> Tj" % seg.encode("utf-16-be").hex().upper())
            cx += size * 1.0 * len(seg)
    ops.append("ET")
    return "\n".join(ops)


def _wrap(text, size, width, cjk_width_factor=1.0):
    """Very small greedy wrapper: enough to keep text inside the frame, not typesetting."""
    if not text:
        return []
    per = max(8, int(width / (size * (1.0 if _is_ascii(text) else cjk_width_factor * 0.98))))
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= per:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines
def page_stream(page, total, spec):
    aes = (spec or {}).get("theme") or {}
    dark = aes.get("colors") or {}
    body_col = (0.12, 0.16, 0.23)
    ops = []
    # a thin rule so the page is visibly a rendered slide, not a text dump
    ops.append("0.18 0.35 0.55 RG 0.6 w %.1f %.1f m %.1f %.1f l S" % (
        MARGIN, PAGE_H - MARGIN - 8, PAGE_W - MARGIN, PAGE_H - MARGIN - 8))
    y = PAGE_H - MARGIN - 40
    title = str(page.get("title") or "")
    for ln in _wrap(title, 22, PAGE_W - 2 * MARGIN)[:2]:
        ops.append(_text_ops(MARGIN, y, ln, "F1B", 22, (0.05, 0.10, 0.18)))
        y -= 30
    y -= 6
    claim = "[%s] %s" % (page.get("strength") or page.get("claim_strength") or "", page.get("claim") or "")
    for ln in _wrap(claim, 12.5, PAGE_W - 2 * MARGIN)[:3]:
        ops.append(_text_ops(MARGIN, y, ln, "F1", 12.5, (0.30, 0.36, 0.44)))
        y -= 18
    y -= 10
    for b in (page.get("bullets") or [])[:6]:
        for i, ln in enumerate(_wrap(str(b), 12, PAGE_W - 2 * MARGIN - 18)[:3]):
            prefix = BULLET + " " if i == 0 else "   "
            txt = prefix + ln
            ops.append(_text_ops(MARGIN + 12, y, txt, "F1", 12, body_col))
            y -= 17
        y -= 4
    foot = "p.%d / %d  \u00b7  academic-talk-structurer  \u00b7  editable deck, geometric preview" % (
        int(page.get("index") or 0), total)
    ops.append(_text_ops(MARGIN, MARGIN - 12, foot, "F1", 8, (0.45, 0.49, 0.55)))
    return "\n".join(ops).encode("utf-8")


def write(path, slides, spec=None):
    """Write `slides` (same dicts the pptx writer takes) into a real PDF. Returns a record."""
    total = len(slides)
    objs = {}

    def obj(n, body):
        objs[n] = body if isinstance(body, bytes) else body.encode("utf-8")

    font_f1, font_f1b, font_f2, font_f2d = 90, 91, 92, 93
    obj(font_f1, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    obj(font_f1b, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>")
    obj(font_f2d, ("<</Type/Font/Subtype/CIDFontType0/BaseFont/STSong-Light"
                   "/CIDSystemInfo<</Registry(Adobe)/Ordering(GB1)/Supplement 4>>"
                   "/FontDescriptor<</Type/FontDescriptor/FontName/STSong-Light/Flags 6"
                   "/FontBBox[-25 -254 1000 880]/ItalicAngle 0/Ascent 880/Descent -120"
                   "/CapHeight 880/StemV 93>>>>"))
    obj(font_f2, ("<</Type/Font/Subtype/Type0/BaseFont/STSong-Light/Encoding/UniGB-UCS2-H"
                  "/DescendantFonts[%d 0 R]>>" % font_f2d))

    kids, page_objs, content_objs = [], [], []
    n = 10
    for i, s in enumerate(slides, 1):
        cid, pid = n, n + 1
        n += 2
        raw = page_stream(dict(s, index=i), total, spec)
        data = zlib.compress(raw, 9)
        obj(cid, b"<</Length %d/Filter/FlateDecode>>stream\n" % len(data) + data + b"\nendstream")
        obj(pid, ("<</Type/Page/Parent 2 0 R/MediaBox[0 0 %.0f %.0f]/Resources<</Font<</F1 %d 0 R"
                  "/F1B %d 0 R/F2 %d 0 R>>>>/Contents %d 0 R>>" % (
                      PAGE_W, PAGE_H, font_f1, font_f1b, font_f2, cid)))
        kids.append(pid)
        page_objs.append(pid)
        content_objs.append(cid)
    obj(2, "<</Type/Pages/Count %d/Kids[%s]>>" % (total, " ".join("%d 0 R" % k for k in kids)))
    obj(1, "<</Type/Catalog/Pages 2 0 R>>")
    obj(3, "<</Title(academic-talk-structurer deck preview)/Producer(minipdf 1.0)/"
           "Creator(academic-talk-structurer)>>")

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for k in sorted(objs):
        offsets[k] = buf.tell()
        buf.write(("%d 0 obj\n" % k).encode())
        buf.write(objs[k])
        buf.write(b"\nendobj\n")
    xref = buf.tell()
    buf.write(("xref\n0 %d\n" % (max(objs) + 1)).encode())
    buf.write(b"0000000000 65535 f \n")
    for k in range(1, max(objs) + 1):
        if k in offsets:
            buf.write(("%010d 00000 n \n" % offsets[k]).encode())
        else:
            buf.write(b"0000000000 65535 f \n")
    buf.write(("trailer\n<</Size %d/Root 1 0 R/Info 3 0 R>>\nstartxref\n%d\n%%%%EOF\n"
               % (max(objs) + 1, xref)).encode())
    blob = buf.getvalue()
    with open(path, "wb") as fh:
        fh.write(blob)
    return {"engine": "minipdf-geometric", "pages": total, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "page_size_pt": [PAGE_W, PAGE_H],
            "font_embedded": False,
            "fonts": {"F1": "Helvetica (base-14)", "F1B": "Helvetica-Bold (base-14)",
                      "F2": "STSong-Light + UniGB-UCS2-H (viewer-supplied CID font, not embedded)"},
            "fidelity": "geometric layout of this plan (title/claim/bullets/footer); not an Office "
                        "layout-engine render; no font binary is shipped in the package"}


# ------------------------------------------------------------------ reading it back
def _unesc(s):
    """Decode a PDF literal string: \\n \\r \\t \\b \\f \\( \\) \\\\ and octal \\ooo (the WinAnsi
    middle dot / bullet are written as octal escapes, so they must come back as their characters)."""
    out, i = [], 0
    simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "(": "(", ")": ")", "\\": "\\"}
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            m = re.match(r"[0-7]{1,3}", s[i + 1:i + 4])
            if m:
                out.append(chr(int(m.group(0), 8)))
                i += 1 + len(m.group(0))
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_text(path):
    """Extract the text layer back out: literal (...) strings and <hex> UTF-16BE strings."""
    blob = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n", blob):
        e = blob.find(b"endstream", m.end())
        if e < 0:
            continue
        chunk = blob[m.end():e].rstrip(b"\r\n")
        try:
            data = zlib.decompress(chunk)
        except Exception:
            data = chunk
        if b"BT" not in data:
            continue
        for t in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*Tj|<([0-9A-Fa-f]+)>\s*Tj", data):
            seg = t.group(0)
            if seg.startswith(b"("):
                out.append(_unesc(seg[1:seg.rfind(b")")].decode("latin-1")))
            else:
                h = t.group(1).decode()
                try:
                    out.append(bytes.fromhex(h).decode("utf-16-be", "replace"))
                except Exception:
                    pass
    return "\n".join(out)


def page_count(path):
    blob = open(path, "rb").read()
    return len(re.findall(rb"/Type/Page[^s]", blob))


def media_boxes(path):
    blob = open(path, "rb").read()
    return [[float(x) for x in m.groups()] for m in
            re.finditer(rb"/MediaBox\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", blob)]
