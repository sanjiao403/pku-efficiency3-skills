#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# svgkit.py -- 极简矢量场景 + SVG 序列化 + PDF/PNG 导出（真实 <text>、语义图层、data-* 溯源）
#
# 三条不变量（由 scripts/verify.py 只读产出的 SVG 独立复核）：
#   I1 语义属性一律序列化为 data-*：内部 API 用 role=，落地必须是 data-role=。
#      裸 role= 会让复核读到 0 个图元/0 条连线 —— 复核会"全绿但什么都没查"（假绿）。
#   I2 每段 <text> 都带 font-family 回退链（含 CJK 族），否则导出端中文可能变方框。
#   I3 画布以 mm 声明且 viewBox 与之一致（1 mm = 96/25.4 px，打印 1:1）。
# 另：本模块不写任何时间戳/随机量，同一输入同一布局 ⇒ 同一字节。
import math, os, re, sys

sys.dont_write_bytecode = True

K = 96.0 / 25.4
FS = 9.0
# CJK 优先、逐级回退：前几项覆盖 Linux/容器常见 Noto/Source Han，随后是本机常见族
FONT = ("Noto Sans CJK SC,Source Han Sans SC,Noto Sans SC,Microsoft YaHei,PingFang SC,"
        "Hiragino Sans GB,WenQuanYi Zen Hei,WenQuanYi Micro Hei,SimHei,DejaVu Sans,Arial,"
        "Liberation Sans,sans-serif")
WIDE = ((0x1100, 0x115F), (0x2E80, 0xA4CF), (0xAC00, 0xD7A3), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6))


def tw(s, z):
    """文本估宽（中文/全角按 1 em，拉丁按 0.545 em）。"""
    return sum(z * (1.0 if any(a <= ord(c) <= b for a, b in WIDE) else 0.545) for c in (s or ""))


def wrap(s, mw, z, ml=3):
    s = (s or "").strip()
    if not s:
        return []
    o, cur = [], ""
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/._°%+]*\s*|.", s):
        if tw(cur + t, z) <= max(mw, z) or not cur:
            cur += t
        else:
            o.append(cur.rstrip()); cur = t.lstrip()
    if cur.strip():
        o.append(cur.rstrip())
    if len(o) > ml:
        t = o[ml - 1]
        while t and tw(t + "…", z) > mw:
            t = t[:-1]
        o = o[:ml - 1] + [t.rstrip() + "…"]
    return o


def esc(s):
    return (str("" if s is None else s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _sem(a):
    """role -> data-role；显式 data-role 优先，避免同一元素出现两个语义属性。"""
    b = dict(a)
    if "data-role" in b and "role" in b:
        b.pop("role")
    return b


def _attrs(a):
    out, seen = [], set()
    for k, v in a.items():
        k = "data-role" if k == "role" else k
        if not (k.startswith("data-") or k == "font-family") or k in seen:
            continue
        seen.add(k)
        out.append('%s="%s"' % (k, esc(v)))
    return " ".join(out)


class Fig:
    def __init__(self, wm, hm, t=""):
        self.wm, self.hm, self.t, self.w, self.h, self.e = wm, hm, t, wm * K, hm * K, []

    # ---- 图元 API（语义属性放 **d，落地为 data-*）------------------------
    def rect(self, x, y, w, h, f, s, rx=4, L="units", role="node-shape", **d):
        self.e.append(("rect", dict(role=role, x=x, y=y, w=w, h=h, fill=f, stroke=s, rx=rx, L=L, **d)))

    def poly(self, p, f, L="units", role="arrowhead", **d):
        self.e.append(("poly", dict(role=role, pts=p, fill=f, L=L, **d)))

    def line(self, p, c, sw=1.5, dash=None, L="connectors", role="connector", **d):
        self.e.append(("line", dict(role=role, pts=p, stroke=c, sw=sw, dash=dash, L=L, **d)))

    def text(self, x, y, t, z=FS, c="#1A1A1A", an="middle", L="labels", role="text", wt="normal", **d):
        self.e.append(("text", dict(role=role, x=x, y=y, s=str(t or ""), size=round(z * 2) / 2.,
                                    fill=c, anchor=an, wt=wt, L=L, **d)))

    def arw(self, p0, p1, c, sz=7.5, L="connectors", role="arrowhead", **d):
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        dd = math.hypot(dx, dy) or 1.
        ux, uy, n = dx / dd, dy / dd, max(5.5, sz)
        bx, by, W = p1[0] - ux * n, p1[1] - uy * n, n * .46
        self.poly([p1, (bx - uy * W, by + ux * W), (bx + uy * W, by - ux * W)], c, L, role, **d)

    # ---- 几何自查（verify.py 会独立重算同一件事）-------------------------
    def bbox(self):
        """全部图元的坐标包围盒 (x0,y0,x1,y1)，用于"内容是否在画布内"的硬检查。"""
        xs, ys = [], []
        for tg, a in self.e:
            if tg == "rect":
                xs += [a["x"], a["x"] + a["w"]]; ys += [a["y"], a["y"] + a["h"]]
            elif tg in ("line", "poly"):
                xs += [p[0] for p in a["pts"]]; ys += [p[1] for p in a["pts"]]
            else:
                an, w = a["anchor"], tw(a["s"], a["size"])
                x0 = a["x"] if an == "start" else (a["x"] - w if an == "end" else a["x"] - w / 2.)
                xs += [x0, x0 + w]
                ys += [a["y"] - a["size"] * .8, a["y"] + a["size"] * .3]
        if not xs:
            return (0., 0., 0., 0.)
        return (min(xs), min(ys), max(xs), max(ys))

    def overflow(self, pad=1.5):
        x0, y0, x1, y1 = self.bbox()
        bad = []
        if x0 < -pad or x1 > self.w + pad:
            bad.append("x: %.2f..%.2f vs 0..%.2f" % (x0, x1, self.w))
        if y0 < -pad or y1 > self.h + pad:
            bad.append("y: %.2f..%.2f vs 0..%.2f" % (y0, y1, self.h))
        return bad

    # ---- 序列化 --------------------------------------------------------
    def svg(self, meta=None):
        m = _attrs({k: v for k, v in (meta or {}).items() if k.startswith("data-")})
        o = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %.2f %.2f" '
             'data-generator="apparatus.py" data-font-stack="%s" font-family="%s"%s>'
             % (self.wm, self.hm, self.w, self.h, esc(FONT), esc(FONT), " " + m if m else ""),
             "<title>%s</title>" % esc(self.t),
             '<desc>可编辑矢量图：真实 &lt;text&gt; 未转曲；每个图元带 data-* 语义与原文溯源；'
             '画布 %g×%g mm，1 mm = 96/25.4 px。</desc>' % (self.wm, self.hm),
             '<rect id="page" x="0" y="0" width="%.2f" height="%.2f" fill="#FFFFFF"/>' % (self.w, self.h)]
        for L in ("rulers", "units", "connectors", "labels", "legend", "annotations"):
            es = [x for x in self.e if x[1]["L"] == L]
            if not es:
                continue
            o.append('<g id="layer-%s">' % L)
            for tg, a0 in es:
                a = _sem(a0)
                d = _attrs(a)
                if tg == "rect":
                    o.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f"%s fill="%s" stroke="%s" '
                             'stroke-width="1.3" %s/>' % (a["x"], a["y"], a["w"], a["h"],
                                                          ' rx="%g"' % a["rx"] if a["rx"] else "", a["fill"],
                                                          a["stroke"], d))
                elif tg == "poly":
                    o.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="1" %s/>'
                             % (" ".join("%.2f,%.2f" % p for p in a["pts"]), a["fill"], a["fill"], d))
                elif tg == "line":
                    o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.2f"%s %s/>'
                             % (" ".join("%.2f,%.2f" % p for p in a["pts"]), a["stroke"], a["sw"],
                                ' stroke-dasharray="%s"' % a["dash"] if a["dash"] else "", d))
                else:
                    o.append('<text x="%.2f" y="%.2f" font-family="%s" font-size="%.2f" fill="%s" '
                             'text-anchor="%s"%s xml:space="preserve" %s>%s</text>'
                             % (a["x"], a["y"], esc(FONT), a["size"], a["fill"], a["anchor"],
                                ' font-weight="%s"' % a["wt"] if a["wt"] != "normal" else "", d, esc(a["s"])))
            o.append("</g>")
        return "\n".join(o) + "\n</svg>\n"


def legend_scale(f, ks, pal, y, inr, colors, dashes, labels, mg=37.795):
    """图例（按用到的语义生成 -> 颜色与图形同源）+ 40 mm 比例尺。返回占用底部 y。"""
    f.text(mg + 2, y + 4, "图例 legend（按用到的语义自动生成，颜色与图形同源）", FS * .86, "#1A1A1A",
           "start", "legend", "legend-title")
    lx, ly = mg + 2, y + 13
    for k in ks:
        if k in colors:
            f.line([(lx, ly + 2), (lx + 18, ly + 2)], colors[k], 2., dashes.get(k), "legend", "legend-line",
                   **{"data-legend": k})
            f.arw((lx, ly + 2), (lx + 18, ly + 2), colors[k], 6, "legend", "legend-arrow", **{"data-legend": k})
        else:
            F0, S0, _ = pal.get(k, pal["unit"])
            f.rect(lx, ly - 2, 17, 8.4, F0, S0, 2, "legend", "legend-swatch", **{"data-legend": k})
        lab = labels.get(k, k)
        f.text(lx + 22, ly + 5, lab, FS * .86, "#1A1A1A", "start", "legend", "legend-text", **{"data-legend": k})
        lx += 24 + tw(lab, FS * .86) + 16
        if lx > mg + inr - 130:
            lx, ly = mg + 2, ly + FS * 1.6
    ly += FS * 2.
    bp = 40 * K
    f.line([(mg, ly), (mg + bp, ly)], "#1A1A1A", 1.6, None, "rulers", "scale-bar")
    for tx in (mg, mg + bp / 2, mg + bp):
        f.line([(tx, ly - 3), (tx, ly + 3)], "#1A1A1A", 1.2, None, "rulers", "scale-bar")
    f.text(mg, ly + 11, "0", FS * .78, "#1A1A1A", **{"data-role": "scale-bar-text"})
    f.text(mg + bp, ly + 11, "40 mm", FS * .78, "#1A1A1A", **{"data-role": "scale-bar-text"})
    f.text(mg, ly + 24, "画布 %g×%g mm · 可编辑 SVG 源（真实文本 + data-* 溯源）" % (f.wm, f.hm), FS * .78,
           "#5A6672", "start", "annotations", "figure-footer")
    return ly + 30


def legend_height(ks, inr, labels=None, mg=37.795):
    """图例+比例尺+页脚的预估高度（用于先算画布高度，避免内容溢出画布）。"""
    labels = labels or {}
    lx, rows = mg + 2, 1
    for k in ks:
        lab = labels.get(k, k)
        lx += 24 + tw(lab, FS * .86) + 16
        if lx > mg + inr - 130:
            lx, rows = mg + 2, rows + 1
    return 13 + rows * FS * 1.6 + FS * 2. + 30


def export(sv, pdb, png, dpi=300):
    """有后端就出 PDF/PNG，没有就如实记录（不伪造）。

    PNG 的 pHYs 由 MuPDF 写成 96 dpi，会让查看器/排版软件按错误物理尺寸摆图；
    这里按真实目标 dpi 重写 pHYs（纯标准库），再由 scripts/measure.py 回读确认。
    """
    o = {"pdf": None, "png": None, "notes": []}
    try:
        import fitz
        try:
            fitz.TOOLS.mupdf_display_errors(False); fitz.TOOLS.mupdf_display_warnings(False)
        except Exception:
            pass
        dn, sd = os.open(os.devnull, os.O_WRONLY), os.dup(2)
        try:
            os.dup2(dn, 2)
            d = fitz.open(sv)
            open(pdb, "wb").write(d.convert_to_pdf())
            d[0].get_pixmap(matrix=fitz.Matrix(dpi / 72., dpi / 72.), alpha=False).save(png)
        finally:
            os.dup2(sd, 2); os.close(dn); os.close(sd)
        o.update(pdf=pdb, png=png, backend="pymupdf")
        try:
            from measure import set_png_dpi
            o["png_dpi_rewritten"] = bool(set_png_dpi(png, dpi))
        except Exception as x:
            o["notes"].append("pHYs patch: %s" % str(x)[:60])
    except Exception as x:
        o["notes"].append("pymupdf: %s" % str(x)[:90])
        try:
            import cairosvg
            cairosvg.svg2pdf(url=sv, write_to=pdb); cairosvg.svg2png(url=sv, write_to=png, dpi=dpi)
            o.update(pdf=pdb, png=png, backend="cairosvg")
        except Exception as z:
            o["notes"] += ["cairosvg: %s" % str(z)[:90], "SVG 源文件完整可交；PDF/PNG 缺失已如实记录"]
    return o
