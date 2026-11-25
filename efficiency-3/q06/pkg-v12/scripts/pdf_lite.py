"""pdf_lite.py - dependency-free PDF writer + text-layer reader.

Two jobs, both without third-party wheels:

``write_pdf_paper()``
    Emit a small, valid, *text-layer* PDF that looks like a one-column paper:
    title block, section headings, body paragraphs, a vector figure with a
    caption, and a ruled table.  Used by ``scripts/make_case_pdf.py`` to build
    example fixtures, so the package stays pure text (no binary blobs shipped).

``extract_pages()``
    Read a real PDF and recover ``[(page_no, text), ...]`` so that every
    locator the deck claims can be traced back to a page number.  Handles
    FlateDecode content streams, ``Tj``/``TJ``/``'``/``"`` operators and the
    usual text-matrix operators.  If the text layer is missing (scanned PDF)
    it says so instead of inventing text.
"""
from __future__ import annotations

import re
import zlib

# --------------------------------------------------------------------------
# Reader
# --------------------------------------------------------------------------

_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", re.S)
_STREAM_RE = re.compile(rb"stream\r?\n?(.*?)\r?\n?endstream", re.S)

_ESC = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
        "(": "(", ")": ")", "\\": "\\"}


def _unescape_lit(b: bytes) -> str:
    out = []
    i, n = 0, len(b)
    while i < n:
        c = b[i:i + 1]
        if c != b"\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        c = b[i:i + 1]
        if c in (b"n", b"r", b"t", b"b", b"f", b"(", b")", b"\\"):
            out.append(_ESC[c.decode()].encode())
            i += 1
        elif c.isdigit():
            oct_digits = b""
            while i < n and len(oct_digits) < 3 and b[i:i + 1].isdigit():
                oct_digits += b[i:i + 1]
                i += 1
            out.append(bytes([int(oct_digits, 8) & 0xFF]))
        elif c == b"\n":
            i += 1
        elif c == b"\r":
            i += 1
            if i < n and b[i:i + 1] == b"\n":
                i += 1
        else:
            out.append(c)
            i += 1
    return b"".join(out).decode("utf-8", "replace")


def _decode_pdf_string(tok: bytes) -> str:
    tok = tok.strip()
    if tok.startswith(b"<") and not tok.startswith(b"<<"):
        hexs = re.sub(rb"[^0-9A-Fa-f]", b"", tok)
        if len(hexs) % 2:
            hexs += b"0"
        raw = bytes.fromhex(hexs.decode())
        if raw[:2] in (b"\xfe\xff",):
            return raw[2:].decode("utf-16-be", "replace")
        # UTF-16BE without BOM is common for CID text; try it when NULs appear
        if b"\x00" in raw[:8]:
            return raw.decode("utf-16-be", "replace")
        return raw.decode("latin-1", "replace")
    if tok.startswith(b"("):
        inner = tok[1:-1] if tok.endswith(b")") else tok[1:]
        return _unescape_lit(inner)
    return ""


_SHOW_RE = re.compile(rb"(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>)", re.S)
_TJ_RE = re.compile(rb"\[\s*((?:\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>|[-\d.\s])*?)\s*\]\s*TJ", re.S)
_TJ_TOK_RE = re.compile(rb"(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>)|(-?\d+\.?\d*)", re.S)


class _TextState:
    __slots__ = ("x", "y", "leading", "size")

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.leading = 12.0
        self.size = 10.0


def _run_content(data: bytes, page_no: int) -> list[tuple[int, float, float, str]]:
    """Mini content-stream interpreter -> [(page, x, y, fragment), ...]."""
    frags: list[tuple[int, float, float, str]] = []
    ts = _TextState()
    stack: list[tuple[float, float]] = []
    num_buf: list[float] = []

    # tokenise on whitespace but keep strings/arrays intact
    pos, n = 0, len(data)
    tokens: list[bytes] = []
    while pos < n:
        ch = data[pos:pos + 1]
        if ch in b" \t\r\n\f\x00":
            pos += 1
            continue
        if ch == b"%":
            nl = data.find(b"\n", pos)
            pos = n if nl < 0 else nl + 1
            continue
        if ch == b"(":
            depth, i = 1, pos + 1
            while i < n and depth:
                c = data[i:i + 1]
                if c == b"\\":
                    i += 2
                    continue
                if c == b"(":
                    depth += 1
                elif c == b")":
                    depth -= 1
                i += 1
            tokens.append(data[pos:i])
            pos = i
            continue
        if ch == b"<":
            if data[pos:pos + 2] == b"<<":
                depth, i = 1, pos + 2
                while i < n and depth:
                    if data[i:i + 2] == b"<<":
                        depth += 1
                        i += 2
                        continue
                    if data[i:i + 2] == b">>":
                        depth -= 1
                        i += 2
                        continue
                    i += 1
                tokens.append(data[pos:i])
                pos = i
                continue
            i = data.find(b">", pos)
            i = n if i < 0 else i + 1
            tokens.append(data[pos:i])
            pos = i
            continue
        if ch == b"[":
            i = data.find(b"]", pos)
            i = n if i < 0 else i + 1
            tokens.append(data[pos:i])
            pos = i
            continue
        if ch == b"/":
            i = pos + 1
            while i < n and data[i:i + 1] not in b" \t\r\n\f/[]<>()":
                i += 1
            tokens.append(data[pos:i])
            pos = i
            continue
        i = pos
        while i < n and data[i:i + 1] not in b" \t\r\n\f/[]<>()":
            i += 1
        tokens.append(data[pos:i])
        pos = i

    def flush_show(text: str):
        if text:
            frags.append((page_no, round(ts.x, 1), round(ts.y, 1), text))

    def is_num(t: bytes) -> bool:
        try:
            float(t)
            return True
        except ValueError:
            return False

    for i, tok in enumerate(tokens):
        if is_num(tok):
            num_buf.append(float(tok))
            continue
        op = tok
        if op == b"BT":
            ts.x = ts.y = 0.0
        elif op == b"Tm" and len(num_buf) >= 6:
            ts.x, ts.y = num_buf[-2], num_buf[-1]
        elif op == b"Td" and len(num_buf) >= 2:
            ts.x += num_buf[-2]
            ts.y += num_buf[-1]
        elif op == b"TD" and len(num_buf) >= 2:
            ts.leading = -num_buf[-1]
            ts.x += num_buf[-2]
            ts.y += num_buf[-1]
        elif op == b"TL" and num_buf:
            ts.leading = num_buf[-1]
        elif op == b"T*":
            ts.y -= ts.leading
        elif op == b"Tf" and num_buf:
            ts.size = num_buf[-1]
        elif op == b"Tj":
            if i >= 1 and tokens[i - 1].startswith((b"(", b"<")):
                flush_show(_decode_pdf_string(tokens[i - 1]))
        elif op == b"TJ":
            if i >= 1 and tokens[i - 1].startswith(b"["):
                buf = []
                for m in _TJ_TOK_RE.finditer(tokens[i - 1]):
                    if m.group(1) is not None:
                        buf.append(_decode_pdf_string(m.group(1)))
                    elif m.group(2) is not None:
                        try:
                            adj = float(m.group(2))
                        except ValueError:
                            continue
                        if adj < -120 and buf and not buf[-1].endswith(" "):
                            buf.append(" ")
                flush_show("".join(buf))
        elif op in (b"'", b'"'):
            ts.y -= ts.leading
            if op == b"'" and i >= 1 and tokens[i - 1].startswith((b"(", b"<")):
                flush_show(_decode_pdf_string(tokens[i - 1]))
        num_buf = []
    return frags


def _inflate(raw: bytes) -> bytes:
    for fn in (zlib.decompress, lambda b: zlib.decompressobj().decompress(b)):
        try:
            return fn(raw)
        except Exception:
            continue
    return b""


def extract_pages(path: str, max_pages: int = 400) -> dict:
    """Return {'pages': [{'page': 1, 'text': '...'}, ...], 'text_layer': bool,
    'engine': str, 'notes': [...]}"""
    with open(path, "rb") as fh:
        blob = fh.read()
    notes: list[str] = []
    if not blob.startswith(b"%PDF"):
        return {"pages": [], "text_layer": False, "engine": "pdf_lite",
                "notes": ["not a PDF (missing %PDF header)"]}

    objs: dict[int, bytes] = {}
    for m in _OBJ_RE.finditer(blob):
        try:
            objs[int(m.group(1))] = m.group(3)
        except ValueError:
            continue

    # page order: objects carrying /Type /Page (not /Pages)
    page_objs = []
    for num, body in objs.items():
        head = body[:400]
        if re.search(rb"/Type\s*/Page\b", head) and not re.search(rb"/Type\s*/Pages\b", head):
            page_objs.append(num)
    if not page_objs:
        notes.append("no /Type /Page objects found; falling back to stream order")
        page_objs = sorted(objs)

    pages = []
    for idx, num in enumerate(sorted(page_objs)[:max_pages], start=1):
        body = objs[num]
        content_refs = re.findall(rb"/Contents\s+(\d+)\s+\d+\s+R", body)
        if not content_refs:
            arr = re.search(rb"/Contents\s*\[(.*?)\]", body, re.S)
            if arr:
                content_refs = re.findall(rb"(\d+)\s+\d+\s+R", arr.group(1))
        chunks = []
        for ref in content_refs:
            cbody = objs.get(int(ref), b"")
            m = _STREAM_RE.search(cbody)
            if not m:
                continue
            raw = m.group(1)
            if b"/FlateDecode" in cbody[:m.start()]:
                raw = _inflate(raw)
            elif b"/Filter" in cbody[:m.start()]:
                notes.append(f"page {idx}: unsupported filter, stream skipped")
                continue
            chunks.append(raw)
        if not chunks:
            continue
        data = b"\n".join(chunks)
        frags = _run_content(data, idx)
        text = _frags_to_text(frags)
        if text.strip():
            pages.append({"page": idx, "text": text})

    total = sum(len(p["text"]) for p in pages)
    text_layer = total > 40 * max(1, len(pages))
    if not text_layer:
        notes.append("text layer missing or empty: treat as scanned; run OCR before planning")
    return {"pages": pages, "text_layer": text_layer, "engine": "pdf_lite", "notes": notes}


def _frags_to_text(frags) -> str:
    if not frags:
        return ""
    rows: dict[tuple[int, float], list[tuple[float, str]]] = {}
    for page, x, y, text in frags:
        key = (page, round(y / 3.0))
        rows.setdefault(key, []).append((x, text))
    lines = []
    for key in sorted(rows, key=lambda k: (k[0], -k[1])):
        parts = sorted(rows[key], key=lambda t: t[0])
        buf = []
        prev_end = None
        for x, t in parts:
            if prev_end is not None:
                gap = x - prev_end
                if gap > 14.0 and buf and not buf[-1].endswith((" ", "|")):
                    # a wide horizontal gap is a column separator, not a space:
                    # keeping it lets table rows stay reconstructable
                    buf.append(" | ")
                elif gap > 6.0 and buf and not buf[-1].endswith((" ", "|")):
                    buf.append(" ")
            buf.append(t)
            prev_end = x + 0.46 * len(t)
        lines.append("".join(buf).strip())
    # merge tiny fragments belonging to the same visual line already done;
    # strip speaker/page furniture noise
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank:
                out.append("")
            blank = True
            continue
        blank = False
        out.append(re.sub(r"[ \t]{2,}", " ", ln))
    return "\n".join(out).strip()


# --------------------------------------------------------------------------
# Writer (fixture builder)
# --------------------------------------------------------------------------

_PAGE_W, _PAGE_H = 595.0, 842.0   # A4 portrait, pt
_MARGIN_L, _MARGIN_R = 64.0, 64.0
_BODY_SIZE = 9.6
_LEADING = 13.4
_COL_W = _PAGE_W - _MARGIN_L - _MARGIN_R


def _esc(s: str) -> str:
    return (s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
             .replace("\u2014", "-").replace("\u2013", "-")
             .replace("\u2018", "'").replace("\u2019", "'")
             .replace("\u201c", '"').replace("\u201d", '"')
             .replace("\u00b0", "o").replace("\u2264", "<=").replace("\u2265", ">=")
             .replace("\u00d7", "x").replace("\u00b7", ".")
             .replace("\u03b1", "alpha").replace("\u03b2", "beta")
             .replace("\u03c3", "sigma").replace("\u03bc", "mu"))


def _wrap(text: str, width_pt: float, size: float) -> list[str]:
    from util import display_width  # local import: keeps module importable alone
    per_em = size
    limit = width_pt / per_em
    lines, cur, curw = [], [], 0.0
    for word in text.split(" "):
        ww = display_width(word + " ")
        if cur and curw + ww > limit:
            lines.append(" ".join(cur))
            cur, curw = [word], display_width(word + " ")
        else:
            cur.append(word)
            curw += ww
    if cur:
        lines.append(" ".join(cur))
    return lines or [""]


class _Page:
    def __init__(self, page_no: int):
        self.page_no = page_no
        self.ops: list[str] = []
        self.y = _PAGE_H - 86.0

    def text(self, x, y, s, size=_BODY_SIZE, font="F1", gray=0.0):
        self.ops.append(f"BT /{font} {size:.2f} Tf {gray:.2f} g "
                        f"{x:.2f} {y:.2f} Td ({_esc(s)}) Tj ET")

    def rule(self, x1, y1, x2, y2, w=0.7, gray=0.55):
        self.ops.append(f"{gray:.2f} G {w:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x, y, w, h, fill=1.0, stroke=0.35, lw=0.6):
        self.ops.append(f"{stroke:.2f} G {lw:.2f} w {fill:.2f} g "
                        f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re B")

    def content(self) -> bytes:
        return ("\n".join(self.ops) + "\n").encode("latin-1", "replace")


def write_pdf_paper(path: str, doc: dict) -> str:
    """Build a paper-like PDF.

    ``doc`` = {
      'title': str, 'authors': str, 'affiliation': str, 'abstract': str,
      'sections': [{'heading': str, 'paras': [str], 'bullets': [str],
                    'figure': {'label','caption','kind':'bars'|'scatter'|'flow'},
                    'table': {'label','caption','header':[...],'rows':[[...]]}}],
      'references': [str], 'footer': str }
    """
    pages: list[_Page] = []
    pg = _Page(1)
    pages.append(pg)

    def new_page():
        p = _Page(len(pages) + 1)
        pages.append(p)
        return p

    def need(space: float):
        nonlocal pg
        if pg.y - space < 78.0:
            pg = new_page()
        return pg

    def para(text: str, size=_BODY_SIZE, font="F1", indent=0.0, lead=_LEADING, gray=0.0):
        nonlocal pg
        for ln in _wrap(text, _COL_W - indent, size):
            need(lead)
            pg.text(_MARGIN_L + indent, pg.y, ln, size=size, font=font, gray=gray)
            pg.y -= lead

    pg.y = _PAGE_H - 96.0
    for ln in _wrap(doc.get("title", ""), _COL_W, 16.0):
        pg.text(_MARGIN_L, pg.y, ln, size=16.0, font="F3")
        pg.y -= 21.0
    pg.y -= 4
    for ln in _wrap(doc.get("authors", ""), _COL_W, 10.0):
        pg.text(_MARGIN_L, pg.y, ln, size=10.0)
        pg.y -= 13.0
    for ln in _wrap(doc.get("affiliation", ""), _COL_W, 8.6):
        pg.text(_MARGIN_L, pg.y, ln, size=8.6, gray=0.25)
        pg.y -= 11.5
    pg.y -= 10

    if doc.get("abstract"):
        need(40)
        pg.text(_MARGIN_L, pg.y, "Abstract", size=10.4, font="F2")
        pg.y -= 14
        para(doc["abstract"], size=9.2, lead=12.6, indent=0.0)
        pg.y -= 8

    for sec in doc.get("sections", []):
        need(64)
        pg.y -= 6
        pg.text(_MARGIN_L, pg.y, sec.get("heading", ""), size=11.4, font="F2")
        pg.y -= 16
        for t in sec.get("paras", []):
            para(t)
            pg.y -= 3
        for b in sec.get("bullets", []):
            for k, ln in enumerate(_wrap(b, _COL_W - 12, _BODY_SIZE)):
                need(_LEADING)
                pg.text(_MARGIN_L, pg.y, ("- " if k == 0 else "  ") + ln)
                pg.y -= _LEADING
            pg.y -= 1.5
        if sec.get("figure"):
            _emit_figure(sec["figure"], need, para)
        if sec.get("table"):
            _emit_table(sec["table"], need, para)

    if doc.get("references"):
        need(60)
        pg.y -= 6
        pg.text(_MARGIN_L, pg.y, "References", size=10.4, font="F2")
        pg.y -= 15
        for ref in doc["references"]:
            for k, ln in enumerate(_wrap(ref, _COL_W - 14, 8.4)):
                need(11.4)
                pg.text(_MARGIN_L + (0 if k == 0 else 14), pg.y, ln, size=8.4, gray=0.15)
                pg.y -= 11.4

    # page furniture + write
    total = len(pages)
    for p in pages:
        p.rule(_MARGIN_L, 62, _PAGE_W - _MARGIN_R, 62, w=0.5, gray=0.7)
        p.text(_MARGIN_L, 48, doc.get("footer", "preprint"), size=7.6, gray=0.45)
        p.text(_PAGE_W - _MARGIN_R - 40, 48, f"{p.page_no} / {total}", size=7.6, gray=0.45)

    return _assemble(path, pages)


def _emit_figure(fig: dict, need, para):
    h = float(fig.get("height", 132.0))
    pg = need(h + 34)
    x, y, w = _MARGIN_L + 26, pg.y - h, _COL_W - 84
    kind = fig.get("kind", "bars")
    if kind == "bars":
        bars = fig.get("bars") or [0.55, 0.72, 0.61, 0.86]
        bw = w / (len(bars) * 1.7)
        pg.rule(x - 6, y - 4, x + w + 6, y - 4, w=0.6, gray=0.5)
        pg.rule(x - 6, y - 4, x - 6, y + h + 4, w=0.6, gray=0.5)
        for i, v in enumerate(bars):
            bx = x + i * bw * 1.7 + bw * 0.3
            pg.rect(bx, y, bw, h * float(v), fill=0.86, stroke=0.2)
            if fig.get("labels") and i < len(fig["labels"]):
                pg.text(bx - 1, y - 15, str(fig["labels"][i]), size=7.0, gray=0.2)
    elif kind == "flow":
        n = len(fig.get("nodes") or ["A", "B", "C"])
        bw = (w - (n - 1) * 12) / n
        for i in range(n):
            bx = x + i * (bw + 12)
            pg.rect(bx, y + h * 0.30, bw, h * 0.36, fill=0.93, stroke=0.25)
            label = (fig.get("nodes") or ["A", "B", "C"])[i]
            pg.text(bx + 5, y + h * 0.43, str(label), size=7.4, gray=0.1)
            if i < n - 1:
                pg.rule(bx + bw + 1, y + h * 0.48, bx + bw + 11, y + h * 0.48, w=0.8, gray=0.3)
    else:  # scatter
        pg.rule(x - 6, y - 4, x + w + 6, y - 4, w=0.6, gray=0.5)
        pg.rule(x - 6, y - 4, x - 6, y + h + 4, w=0.6, gray=0.5)
        pts = fig.get("points") or [(0.1, 0.2), (0.3, 0.35), (0.5, 0.5), (0.7, 0.66), (0.9, 0.8)]
        for px, py in pts:
            pg.rect(x + w * px - 1.6, y + h * py - 1.6, 3.2, 3.2, fill=0.2, stroke=0.2)
    pg.y = y - 15
    cap = f"{fig.get('label','Figure 1')}. {fig.get('caption','')}"
    for k, ln in enumerate(_wrap(cap, _COL_W - 20, 8.4)):
        pg = need(11.4)
        pg.text(_MARGIN_L + 6, pg.y, ln, size=8.4, gray=0.2)
        pg.y -= 11.4
    pg.y -= 10


def _emit_table(tbl: dict, need, para):
    header = tbl.get("header") or []
    rows = tbl.get("rows") or []
    cols = max(1, len(header) or max(len(r) for r in rows))
    colw = _COL_W / cols
    # wrap cells inside their column instead of truncating the number away
    def cell_lines(cell, width_pt):
        return _wrap(str(cell), width_pt - 6, 8.0)

    grid: list[list[list[str]]] = []
    if header:
        grid.append([cell_lines(h, colw) for h in header])
    for row in rows:
        grid.append([cell_lines(row[j] if j < len(row) else "", colw) for j in range(cols)])
    row_h = [max(len(c) for c in line) * 9.6 + 4.0 for line in grid]
    need(sum(row_h) + 30)
    pg = need(sum(row_h) + 30)
    for ln in _wrap(f"{tbl.get('label','Table 1')}. {tbl.get('caption','')}", _COL_W, 8.4):
        pg.text(_MARGIN_L, pg.y, ln, size=8.4, gray=0.25)
        pg.y -= 11.0
    pg.y -= 3
    for r_i, line in enumerate(grid):
        is_head = header and r_i == 0
        for j, cell in enumerate(line):
            for k, sub in enumerate(cell):
                pg.text(_MARGIN_L + j * colw + 2, pg.y - k * 9.6, sub, size=8.0,
                        font="F2" if is_head else "F1")
        pg.y -= row_h[r_i]
        if is_head:
            pg.rule(_MARGIN_L, pg.y + 14, _MARGIN_L + colw * cols, pg.y + 14, w=0.7, gray=0.3)
    pg.rule(_MARGIN_L, pg.y + 14, _MARGIN_L + colw * cols, pg.y + 14, w=0.5, gray=0.45)
    pg.y -= 8


def _assemble(path: str, pages: list[_Page]) -> str:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold /Encoding /WinAnsiEncoding >>")
    font3 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    res = add(f"<< /Font << /F1 {font1} 0 R /F2 {font2} 0 R /F3 {font3} 0 R >> >>".encode())

    pages_obj_num = len(objects) + 1 + 2 * len(pages)  # placeholder, fixed below
    kids_refs = []
    page_nums = []
    for p in pages:
        data = p.content()
        comp = zlib.compress(data, 9)
        cnum = add(b"<< /Length " + str(len(comp)).encode() + b" /Filter /FlateDecode >>\nstream\n"
                   + comp + b"\nendstream")
        page_nums.append(add(b""))  # placeholder slot for the page object
        kids_refs.append((page_nums[-1], cnum))

    pages_obj_num = add(b"")  # placeholder for /Pages
    for i, (pnum, cnum) in enumerate(kids_refs):
        objects[pnum - 1] = (f"<< /Type /Page /Parent {pages_obj_num} 0 R "
                             f"/MediaBox [0 0 {_PAGE_W:.0f} {_PAGE_H:.0f}] "
                             f"/Resources {res} 0 R /Contents {cnum} 0 R >>").encode()
    kids = " ".join(f"{n} 0 R" for n, _ in kids_refs)
    objects[pages_obj_num - 1] = (f"<< /Type /Pages /Count {len(pages)} /Kids [ {kids} ] >>").encode()
    cat = add(f"<< /Type /Catalog /Pages {pages_obj_num} 0 R >>".encode())

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {cat} 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return path
