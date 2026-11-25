#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pdftext.py -- 纯标准库的 PDF 文本层抽取（无 pymupdf 时的兜底，不编造内容）
#
# 为什么需要它：题面说"PDF parsing receives the actual PDF without a pre-extracted
# answer layer"，即真实案例的材料很可能是 PDF。若抽取只能靠第三方 pymupdf，则
# 平台上没装 pymupdf 时整案实体为 0（空图 + partial）——这是"零依赖"声称之外
# 的隐式硬依赖。本模块只用 zlib（标准库）解压内容流，再用 ToUnicode CMap
# （若有）把字符码映射回 Unicode。
#
# 诚实边界（写进 SKILL/README，不夸大）：
#   * 只做文本层：扫描件（无文本层）抽取为空，调用方按 unreadable 处理，绝不猜内容；
#   * 支持 FlateDecode（多数 PDF）与未压缩内容流；其它滤镜（LZW/DCT/JBIG2）跳过；
#   * 字符码 -> Unicode 依赖 ToUnicode CMap；没有 CMap 且不是可解码单字节编码时，
#     该片段留空而不是输出乱码；跨行/分栏顺序按内容流的 y 变化分行（不保证阅读顺序完美）；
#   * 只读文件，不写盘、无网络。
import re, unicodedata, zlib

_W = re.compile(rb"\s+")


def _score(s):
    """候选解码的"像人话"分：可打印字母/数字/标点/空格加分，控制码与未分配码重罚。"""
    good = bad = 0
    for c in s:
        cat = unicodedata.category(c)
        if cat in ("Cc", "Cn", "Co", "Cs"):
            bad += 1
        elif cat[0] in "LNPSZ":
            good += 1
    return good - 3 * bad


def _streams(data):
    """产出每个 stream...endstream 的字节（先试 zlib，失败则原样）。"""
    for m in re.finditer(rb"stream\r?\n", data):
        s = m.end()
        e = data.find(b"endstream", s)
        if e < 0:
            continue
        raw = data[s:e]
        try:
            yield zlib.decompress(raw)
        except Exception:
            try:
                yield zlib.decompressobj().decompress(raw)   # 截断/多段
            except Exception:
                yield raw


def _hex2bytes(h):
    h = re.sub(rb"[^0-9A-Fa-f]", b"", h)
    if len(h) % 2:
        h += b"0"
    return bytes.fromhex(h.decode("ascii"))


def _cmaps(chunks):
    """所有 ToUnicode CMap 的并集：字符码 -> 文本。"""
    cm = {}
    for c in chunks:
        for blk in re.findall(rb"beginbfchar(.*?)endbfchar", c, re.S):
            for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
                t = _hex2bytes(b)
                try:
                    cm[int(a, 16)] = t.decode("utf-16-be") if len(t) % 2 == 0 else t.decode("latin-1")
                except Exception:
                    pass
        for blk in re.findall(rb"beginbfrange(.*?)endbfrange", c, re.S):
            for a, b, d in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
                try:
                    lo, hi, base = int(a, 16), int(b, 16), _hex2bytes(d)
                    for i, code in enumerate(range(lo, min(hi, lo + 4096) + 1)):
                        cm[code] = chr(int.from_bytes(base, "big") + i)
                except Exception:
                    pass
    return cm


def _decode(s, cm):
    """PDF 字符串字节 -> 文本。

    顺序：ToUnicode CMap（有就用）→ 候选编码打分（latin-1 / UTF-16BE / 带 BOM 的 UTF-16BE）。
    打分是必要的：Identity-H 的 CID 字体（如中式内置字体）常没有可用的 ToUnicode，
    此时字符串是 2 字节码 == Unicode 码点，按 latin-1 解会得到一串控制字符。
    """
    cands = []
    if cm:
        two = "".join(cm.get(int.from_bytes(s[i:i + 2], "big"), "")
                      for i in range(0, len(s) - len(s) % 2, 2))
        one = "".join(cm.get(b, "") for b in s)
        cands += [x for x in (two, one) if x and _score(x) > 0]
    if s[:2] == b"\xfe\xff":
        cands.append(s[2:].decode("utf-16-be", "ignore"))
    cands.append(s.decode("latin-1", "ignore"))
    if len(s) % 2 == 0 and len(s) >= 2:
        try:
            cands.append(s.decode("utf-16-be", "ignore"))
        except Exception:
            pass
    return max(cands, key=_score) if cands else ""


def _strings_and_ops(content):
    """把内容流切成 (op, payload) 序列：只关心文本算子与定位算子。"""
    i, n = 0, len(content)
    out = []
    while i < n:
        ch = content[i:i + 1]
        if ch == b"%":                                # 注释
            j = content.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch == b"(":                                # 字面字符串（含转义/嵌套）
            j, depth, buf = i + 1, 1, bytearray()
            while j < n and depth:
                c = content[j:j + 1]
                if c == b"\\":
                    nc = content[j + 1:j + 2]
                    mp = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
                          b"(": b"(", b")": b")", b"\\": b"\\"}
                    if nc in mp:
                        buf += mp[nc]; j += 2; continue
                    oct_ = re.match(rb"[0-7]{1,3}", content[j + 1:j + 4])
                    if oct_:
                        buf.append(int(oct_.group(0), 8) & 0xFF); j += 1 + len(oct_.group(0)); continue
                    j += 2; continue
                if c == b"(":
                    depth += 1
                elif c == b")":
                    depth -= 1
                    if not depth:
                        break
                buf += c; j += 1
            out.append(("str", bytes(buf))); i = j + 1; continue
        if ch == b"<" and content[i + 1:i + 2] != b"<":
            j = content.find(b">", i)
            if j < 0:
                break
            out.append(("str", _hex2bytes(content[i + 1:j]))); i = j + 1; continue
        m = re.match(rb"[A-Za-z'\"*][A-Za-z0-9'\"*]*", content[i:])
        if m:
            i += m.end(); out.append(("op", m.group(0))); continue
        m = re.match(rb"[+-]?\d*\.?\d+", content[i:])
        if m:
            out.append(("num", float(m.group(0)))); i += m.end(); continue
        i += 1
    return out


def extract_stream(content, cm):
    """一个内容流 -> 文本行（y 变化即换行；TJ 数组内大负位移补空格）。"""
    toks = _strings_and_ops(content)
    lines, parts, pending = [], [], []
    x = y = 0.0
    size, gap = 10.0, False

    def flush():
        nonlocal parts
        if parts:
            t = "".join(parts).strip()
            if t:
                lines.append(t)
            parts = []

    for k, v in toks:
        if k == "num":
            pending.append(v)
            if v < -100:
                gap = True
            continue
        if k == "str":
            if gap and parts:
                parts.append(" ")
            parts.append(_decode(v, cm))
            gap = False
            continue
        op = v
        if op in (b"Td", b"TD") and len(pending) >= 2:
            nx, ny = x + pending[-2], y + pending[-1]
            if parts and abs(ny - y) > 1.2:
                flush()
            x, y = nx, ny
            if op == b"TD":
                size = abs(pending[-1]) or size
        elif op == b"Tm" and len(pending) >= 6:
            nx, ny = pending[-2], pending[-1]
            if parts and abs(ny - y) > 1.2:
                flush()
            x, y = nx, ny
        elif op == b"T*":
            y -= size or 10.0
            flush()
        elif op == b"TL" and pending:
            size = abs(pending[-1]) or size
        elif op == b"Tf" and pending:
            size = abs(pending[-1]) or size
        elif op == b"BT":
            x = y = 0.0
        elif op in (b"'", b'"'):
            y -= size or 10.0
            flush()
        pending = []
    flush()
    return lines


def pdf_text(path, max_chars=400000):
    """PDF -> 文本（可能不完整；调用方用 extract._signal 判定是否可用）。"""
    data = open(path, "rb").read()
    ch = list(_streams(data))
    cm = _cmaps(ch)
    out = []
    for c in ch:
        if b"BT" not in c or not (b"Tj" in c or b"TJ" in c):
            continue
        out += extract_stream(c, cm)
        if sum(len(x) for x in out) > max_chars:
            break
    txt = "\n".join(out)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


if __name__ == "__main__":
    import sys
    print(pdf_text(sys.argv[1]))
