#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_png -- raster export with a verified result.

The export is not "done" when a file exists: the file is re-opened and its IHDR
header decoded, so a renamed text file or an empty canvas can never be reported
as a successful export.  Five engines are tried in descending fidelity order and
the one that actually worked is recorded in result.json.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # never leave __pycache__ behind


import os
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import fonts

ENGINES = ["cairosvg", "pymupdf", "pillow", "matplotlib", "cli", "browser", "stdlib"]


# --------------------------------------------------------------------------
# PNG header helpers
# --------------------------------------------------------------------------
def png_info(path):
    """Decode width/height/bitdepth/colour from a PNG. Returns None if invalid."""
    try:
        data = Path(path).read_bytes()
    except Exception:
        return None
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if data[12:16] != b"IHDR":
        return None
    try:
        w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", data[16:29])
    except Exception:
        return None
    if w <= 0 or h <= 0 or w > 20000 or h > 20000:
        return None
    return {"width": w, "height": h, "bit_depth": depth, "color_type": ctype,
            "interlace": inter, "bytes": len(data)}


def _nonwhite_ratio(path, sample=420):
    """Rough ink coverage: guards against an all-white 'successful' export."""
    try:
        from PIL import Image
        im = Image.open(str(path)).convert("L")
        im.thumbnail((sample, sample))
        px = list(im.getdata())
        dark = sum(1 for v in px if v < 245)
        return round(dark / float(len(px) or 1), 4)
    except Exception:
        return None


# --------------------------------------------------------------------------
# engines
# --------------------------------------------------------------------------
def _via_cairosvg(svg_path, png_path, width):
    try:
        import cairosvg
    except Exception:
        return None
    try:
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path),
                         output_width=int(width))
        return "cairosvg"
    except Exception:
        return None


def _via_pymupdf(svg_path, png_path, width):
    try:
        import fitz
    except Exception:
        return None
    try:
        doc = fitz.open(str(svg_path))
        page = doc[0]
        zoom = float(width) / max(1.0, page.rect.width)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.save(str(png_path))
        doc.close()
        return "pymupdf"
    except Exception:
        return None


PIL_SANS, PIL_BOLD, PIL_ITALIC = None, None, None


def _pil_font(size, bold=False, italic=False):
    global PIL_SANS, PIL_BOLD, PIL_ITALIC
    from PIL import ImageFont
    rep = fonts.discover(needs_cjk=True)
    path = rep["bold"] if bold else (rep["italic"] if italic else rep["sans"])
    for cand in (path, rep["sans"], rep["bold"]):
        if cand:
            try:
                return ImageFont.truetype(cand, max(6, int(round(size))))
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _dash(draw, x1, y1, x2, y2, pat, fill, w):
    if not pat:
        draw.line([(x1, y1), (x2, y2)], fill=fill, width=w)
        return
    try:
        on, off = [float(v) for v in pat.replace(",", " ").split()][:2]
    except Exception:
        on, off = 4.0, 2.0
    import math
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    pos = 0.0
    while pos < dist:
        e = min(pos + on, dist)
        draw.line([(x1 + ux * pos, y1 + uy * pos), (x1 + ux * e, y1 + uy * e)],
                  fill=fill, width=w)
        pos = e + off


def _clip_seg(x1, y1, x2, y2, x, y, w, h):
    """Liang-Barsky clip of a segment to a rectangle; None when fully outside."""
    t0, t1 = 0.0, 1.0
    dx, dy = x2 - x1, y2 - y1
    for p, q in ((-dx, x1 - x), (dx, x + w - x1), (-dy, y1 - y), (dy, y + h - y1)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    return (x1 + t0 * dx, y1 + t0 * dy, x1 + t1 * dx, y1 + t1 * dy)


def _pattern_lines(bbox, pattern, color="#1A1A1E", step=9.5):
    x, y, w, h = bbox
    segs = []
    if pattern in ("hatch45", "hatch135", "hatch90", "cross", "grid"):
        if pattern in ("hatch90", "cross", "grid"):
            xx = x
            while xx <= x + w:
                segs.append((xx, y, xx, y + h))
                xx += step
        if pattern in ("cross", "grid"):
            yy = y
            while yy <= y + h:
                segs.append((x, yy, x + w, yy))
                yy += step
        else:
            sign = -1.0 if pattern == "hatch45" else 1.0
            if pattern in ("hatch45", "hatch135"):
                d = -h
                while d <= w:
                    got = _clip_seg(x + d, y, x + d + sign * h, y + h, x, y, w, h)
                    if got:
                        segs.append(got)
                    d += step
        return segs
    if pattern == "dots":
        yy = y + step * 0.5
        while yy < y + h:
            xx = x + step * 0.5
            while xx < x + w:
                segs.append((xx, yy, xx, yy))
                xx += step
            yy += step
        return segs
    return segs


def _via_pillow(scene, png_path, scale, supersample=2.0):
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    try:
        draw_scale = scale * supersample
        W = int(scene["canvas"]["width_px"] * draw_scale)
        H = int(scene["canvas"]["height_px"] * draw_scale)
        out_w = int(scene["canvas"]["width_px"] * scale)
        out_h = int(scene["canvas"]["height_px"] * scale)
        scale = draw_scale
        bg = scene["canvas"]["background"]
        img = Image.new("RGB", (W, H), bg)
        dr = ImageDraw.Draw(img, "RGBA")
        fonts_cache = {}

        def F(size, bold=False, italic=False):
            k = (round(size, 1), bold, italic)
            if k not in fonts_cache:
                fonts_cache[k] = _pil_font(size * scale, bold, italic)
            return fonts_cache[k]

        for p in scene["prims"]:
            t = p["t"]
            if t == "rect":
                x0, y0 = p["x"] * scale, p["y"] * scale
                x1, y1 = (p["x"] + p["w"]) * scale, (p["y"] + p["h"]) * scale
                fill = None if p["fill"] in ("none", "") else p["fill"]
                if p.get("pattern") and fill:
                    dr.rounded_rectangle([x0, y0, x1, y1],
                                         radius=p["rx"] * scale, fill=fill)
                    for (a, b, c, d) in _pattern_lines(
                            (p["x"], p["y"], p["w"], p["h"]), p["pattern"]):
                        if c == a and d == b:
                            dr.ellipse([a * scale - 1.2, b * scale - 1.2,
                                        a * scale + 1.2, b * scale + 1.2],
                                       fill=(26, 26, 30, 80))
                        else:
                            dr.line([(a * scale, b * scale), (c * scale, d * scale)],
                                    fill=(26, 26, 30, 64), width=max(1, int(scale)))
                elif fill:
                    dr.rounded_rectangle([x0, y0, x1, y1], radius=max(0, p["rx"] * scale),
                                         fill=fill)
                if p["stroke"] not in ("none", "") and p["sw"] > 0:
                    dr.rounded_rectangle([x0, y0, x1, y1], radius=max(0, p["rx"] * scale),
                                         outline=p["stroke"],
                                         width=max(1, int(round(p["sw"] * scale))))
            elif t == "line":
                _dash(dr, p["x1"] * scale, p["y1"] * scale, p["x2"] * scale,
                      p["y2"] * scale, p["dash"], p["stroke"],
                      max(1, int(round(p["sw"] * scale))))
            elif t == "poly":
                pts = [(a * scale, b * scale) for a, b in p["pts"]]
                if p["fill"] not in ("none", "") and len(pts) >= 3:
                    dr.polygon(pts, fill=p["fill"])
                if p["stroke"] not in ("none", "") and len(pts) >= 2:
                    dr.line(pts + [pts[0]], fill=p["stroke"],
                            width=max(1, int(round(p["sw"] * scale))))
            elif t == "circle":
                box = [(p["cx"] - p["r"]) * scale, (p["cy"] - p["r"]) * scale,
                       (p["cx"] + p["r"]) * scale, (p["cy"] + p["r"]) * scale]
                dr.ellipse(box,
                           fill=None if p["fill"] in ("none", "") else p["fill"],
                           outline=None if p["stroke"] in ("none", "") else p["stroke"],
                           width=max(1, int(round(max(0.6, p["sw"]) * scale))))
            elif t == "text":
                f = F(p["size"], p["bold"], p["italic"])
                if f is None:
                    continue
                anchor = {"start": "ls", "middle": "ms", "end": "rs"}[p["anchor"]]
                dr.text((p["x"] * scale, p["y"] * scale), p["s"], font=f,
                        fill=p["fill"], anchor=anchor)
        if (out_w, out_h) != (W, H):
            img = img.resize((out_w, out_h), Image.LANCZOS)
        img.save(str(png_path), format="PNG")
        return "pillow"
    except Exception:
        return None


def _via_matplotlib(scene, png_path, scale):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Polygon, Rectangle
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except Exception:
        return None
    try:
        W = scene["canvas"]["width_px"]
        H = scene["canvas"]["height_px"]
        dpi = 100.0 * scale
        fig = plt.figure(figsize=(W / 100.0, H / 100.0), dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, W)
        ax.set_ylim(H, 0)
        ax.axis("off")
        fig.patch.set_facecolor(scene["canvas"]["background"])
        for p in scene["prims"]:
            t = p["t"]
            if t == "rect":
                fc = "none" if p["fill"] in ("none", "") else p["fill"]
                ec = "none" if p["stroke"] in ("none", "") else p["stroke"]
                ax.add_patch(Rectangle((p["x"], p["y"]), p["w"], p["h"],
                                       facecolor=fc, edgecolor=ec,
                                       linewidth=p["sw"], zorder=2))
                if p.get("pattern") and fc != "none":
                    for (a, b, c, d) in _pattern_lines(
                            (p["x"], p["y"], p["w"], p["h"]), p["pattern"]):
                        ax.plot([a, c], [b, d], color="#1A1A1E", lw=0.9,
                                alpha=0.24, zorder=3)
            elif t == "line":
                ax.plot([p["x1"], p["x2"]], [p["y1"], p["y2"]], color=p["stroke"],
                        lw=max(0.4, p["sw"]),
                        linestyle=(0, (4, 2)) if p["dash"] else "-", zorder=3,
                        solid_capstyle="round")
            elif t == "poly":
                ax.add_patch(Polygon(p["pts"], closed=True,
                                     facecolor="none" if p["fill"] in ("none", "") else p["fill"],
                                     edgecolor="none" if p["stroke"] in ("none", "") else p["stroke"],
                                     linewidth=p["sw"], zorder=4))
            elif t == "circle":
                ax.add_patch(Circle((p["cx"], p["cy"]), p["r"],
                                    facecolor="none" if p["fill"] in ("none", "") else p["fill"],
                                    edgecolor="none" if p["stroke"] in ("none", "") else p["stroke"],
                                    linewidth=max(0.4, p["sw"]), zorder=4))
            elif t == "text":
                ax.text(p["x"], p["y"], p["s"], fontsize=p["size"] * 72.0 / 100.0,
                        ha={"start": "left", "middle": "center", "end": "right"}[p["anchor"]],
                        va="baseline", color=p["fill"],
                        fontweight="bold" if p["bold"] else "normal",
                        fontstyle="italic" if p["italic"] else "normal", zorder=6)
        FigureCanvasAgg(fig).print_png(str(png_path))
        plt.close(fig)
        return "matplotlib"
    except Exception:
        return None


def _via_cli(svg_path, png_path, width):
    tools = [
        (["rsvg-convert", "-w", str(int(width)), "-o", str(png_path), str(svg_path)],
         "rsvg-convert"),
        (["inkscape", str(svg_path), "--export-type=png",
          "--export-filename=%s" % png_path, "-w", str(int(width))], "inkscape"),
        (["convert", "-background", "white", "-density", "150", str(svg_path),
          str(png_path)], "imagemagick"),
    ]
    for cmd, name in tools:
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=90)
            if res.returncode == 0 and Path(png_path).is_file() and \
                    Path(png_path).stat().st_size > 1000:
                return name
        except Exception:
            continue
    return None


def _via_browser(svg_path, png_path, width):
    """Last-resort DOM screenshot; requires playwright + a browser install."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        svg_text = Path(svg_path).read_text(encoding="utf-8")
        with sync_playwright() as pw:
            br = pw.chromium.launch(args=["--no-sandbox"])
            pg = br.new_page(viewport={"width": int(width), "height": 600})
            pg.set_content("<html><body style='margin:0;background:#fff'>%s</body></html>"
                           % svg_text)
            el = pg.query_selector("svg")
            el.screenshot(path=str(png_path))
            br.close()
        return "browser"
    except Exception:
        return None


# --------------------------------------------------------------------------
# stdlib fallback rasteriser: geometry only, text via a stroke font
# --------------------------------------------------------------------------
_STROKE = {
    "A": [(0, 1), (0.5, 0), (1, 1)], "V": [(0, 0), (0.5, 1), (1, 0)],
    "0": [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9), (0.1, 0.1)],
    "1": [(0.4, 0.05), (0.5, 0.0), (0.5, 1.0)], "2": [(0.05, 0.2), (0.5, 0.0),
    (0.95, 0.2), (0.05, 1.0), (0.95, 1.0)], "3": [(0.05, 0.05), (0.95, 0.05),
    (0.55, 0.45), (0.95, 0.7), (0.5, 1.0), (0.05, 0.9)],
    "4": [(0.75, 1.0), (0.75, 0.0), (0.05, 0.7), (0.95, 0.7)],
    "5": [(0.95, 0.0), (0.15, 0.0), (0.1, 0.45), (0.6, 0.4), (0.95, 0.7),
          (0.5, 1.0), (0.05, 0.9)],
    "6": [(0.9, 0.05), (0.3, 0.2), (0.05, 0.65), (0.5, 1.0), (0.95, 0.7),
          (0.5, 0.45), (0.05, 0.65)],
    "7": [(0.05, 0.0), (0.95, 0.0), (0.35, 1.0)],
    "8": [(0.5, 0.45), (0.1, 0.25), (0.5, 0.0), (0.9, 0.25), (0.5, 0.45),
          (0.05, 0.7), (0.5, 1.0), (0.95, 0.7), (0.5, 0.45)],
    "9": [(0.95, 0.35), (0.5, 0.0), (0.05, 0.3), (0.5, 0.55), (0.95, 0.35),
          (0.7, 0.85), (0.2, 1.0)],
    "-": [(0.15, 0.55), (0.85, 0.55)], "/": [(0.9, 0.0), (0.1, 1.0)],
    ".": [(0.45, 0.9), (0.55, 0.9)], "%": [(0.85, 0.05), (0.15, 0.95), 
    (0.15, 0.1), (0.35, 0.1), (0.15, 0.3), (0.85, 0.7), (0.7, 1.0), (0.85, 0.9)],
    "+": [(0.5, 0.35), (0.5, 0.75)], "=": [(0.2, 0.45), (0.8, 0.45)],
    "(": [(0.7, 0.0), (0.4, 0.5), (0.7, 1.0)], ")": [(0.3, 0.0), (0.6, 0.5), (0.3, 1.0)],
}


def _via_stdlib(scene, png_path, scale):
    """Pure-Python raster fallback. Faithful geometry, ASCII stroke glyphs."""
    try:
        # a per-pixel Python rasteriser must stay inside the time budget
        px = scene["canvas"]["width_px"] * scene["canvas"]["height_px"] * scale * scale
        if px > 8_000_000:
            scale = scale * ((8_000_000.0 / px) ** 0.5)
        W = max(1, int(round(scene["canvas"]["width_px"] * scale)))
        H = max(1, int(round(scene["canvas"]["height_px"] * scale)))
        bg = scene["canvas"]["background"].lstrip("#")
        bg = tuple(int(bg[i:i + 2], 16) for i in (0, 2, 4)) if len(bg) == 6 else (255, 255, 255)
        buf = bytearray()
        row = bytes(bg) * W
        for _ in range(H):
            buf += b"\x00" + row

        def put(x, y, color):
            xi, yi = int(x), int(y)
            if 0 <= xi < W and 0 <= yi < H:
                off = yi * (W * 3 + 1) + 1 + xi * 3
                buf[off] = color[0]
                buf[off + 1] = color[1]
                buf[off + 2] = color[2]

        def hexc(c, alpha=1.0):
            c = (c or "#000000").lstrip("#")
            if len(c) != 6:
                return (0, 0, 0)
            r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
            return (int(r * alpha + bg[0] * (1 - alpha)),
                    int(g * alpha + bg[1] * (1 - alpha)),
                    int(b * alpha + bg[2] * (1 - alpha)))

        def line(x1, y1, x2, y2, col, w=1.0, dash=""):
            import math
            dist = math.hypot(x2 - x1, y2 - y1)
            steps = int(dist * 2) + 1
            r = max(0.6, w / 2.0)
            on, off = 1e9, 0.0
            if dash:
                try:
                    p = [float(v) for v in dash.replace(",", " ").split()]
                    on, off = p[0], p[1] if len(p) > 1 else 2.0
                except Exception:
                    pass
            for i in range(steps + 1):
                t = i / float(steps)
                dpos = t * dist
                if off and (dpos % (on + off)) > on:
                    continue
                cx, cy = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                for dy in range(-int(r), int(r) + 1):
                    for dx in range(-int(r), int(r) + 1):
                        if dx * dx + dy * dy <= r * r + 0.3:
                            put(cx + dx, cy + dy, col)

        def fill_rect(x, y, w, h, col, alpha=1.0):
            c = hexc(col, alpha)
            for yy in range(int(y * scale), int((y + h) * scale)):
                for xx in range(int(x * scale), int((x + w) * scale)):
                    put(xx, yy, c)

        for p in scene["prims"]:
            t = p["t"]
            if t == "rect":
                if p.get("pattern"):
                    fill_rect(p["x"], p["y"], p["w"], p["h"], p["fill"])
                    for (a, b, c, d) in _pattern_lines(
                            (p["x"], p["y"], p["w"], p["h"]), p["pattern"]):
                        if a == c and b == d:
                            fill_rect(a - 1, b - 1, 2, 2, "#1A1A1E", 0.5)
                        else:
                            line(a * scale, b * scale, c * scale, d * scale,
                                 hexc("#1A1A1E", 0.35), 1.0)
                elif p["fill"] not in ("none", ""):
                    fill_rect(p["x"], p["y"], p["w"], p["h"], p["fill"])
                if p["stroke"] not in ("none", "") and p["sw"] > 0:
                    col = hexc(p["stroke"])
                    w = max(1, int(round(p["sw"] * scale)))
                    line(p["x"] * scale, p["y"] * scale, (p["x"] + p["w"]) * scale,
                         p["y"] * scale, col, w)
                    line(p["x"] * scale, (p["y"] + p["h"]) * scale,
                         (p["x"] + p["w"]) * scale, (p["y"] + p["h"]) * scale, col, w)
                    line(p["x"] * scale, p["y"] * scale, p["x"] * scale,
                         (p["y"] + p["h"]) * scale, col, w)
                    line((p["x"] + p["w"]) * scale, p["y"] * scale,
                         (p["x"] + p["w"]) * scale, (p["y"] + p["h"]) * scale, col, w)
            elif t == "line":
                line(p["x1"] * scale, p["y1"] * scale, p["x2"] * scale, p["y2"] * scale,
                     hexc(p["stroke"]), max(1, int(round(p["sw"] * scale))), p["dash"])
            elif t == "poly":
                pts = [(a * scale, b * scale) for a, b in p["pts"]]
                if p["fill"] not in ("none", "") and len(pts) >= 3:
                    ymin = min(b for _a, b in pts)
                    ymax = max(b for _a, b in pts)
                    for yy in range(int(ymin), int(ymax) + 1):
                        xs = []
                        for i in range(len(pts)):
                            a, b = pts[i]
                            c, d = pts[(i + 1) % len(pts)]
                            if (b <= yy < d) or (d <= yy < b):
                                xs.append(a + (c - a) * ((yy - b) / ((d - b) or 1)))
                        xs.sort()
                        for i in range(0, len(xs) - 1, 2):
                            for xx in range(int(xs[i]), int(xs[i + 1]) + 1):
                                put(xx, yy, hexc(p["fill"]))
            elif t == "circle":
                import math
                r = p["r"] * scale
                for yy in range(int((p["cy"] - p["r"]) * scale),
                                int((p["cy"] + p["r"]) * scale) + 1):
                    for xx in range(int((p["cx"] - p["r"]) * scale),
                                    int((p["cx"] + p["r"]) * scale) + 1):
                        dd = math.hypot(xx - p["cx"] * scale, yy - p["cy"] * scale)
                        if dd <= r and p["fill"] not in ("none", ""):
                            put(xx, yy, hexc(p["fill"]))
                        if abs(dd - r) <= max(0.7, p["sw"] * scale / 2.0) and \
                                p["stroke"] not in ("none", ""):
                            put(xx, yy, hexc(p["stroke"]))
            elif t == "text":
                s = p["s"]
                size = p["size"] * scale
                wide = sum(1 for ch in s if ord(ch) > 0x2E80)
                if wide:
                    # CJK cannot be drawn without a font file: draw a labelled
                    # placeholder block so the geometry stays truthful, and
                    # record the degradation (never silently drop the text).
                    tw = sum(1 for _ in s) * size * 0.5
                    x0 = p["x"] * scale - (tw if p["anchor"] == "end" else
                                           (tw / 2.0 if p["anchor"] == "middle" else 0))
                    fill_rect(x0 / scale, (p["y"] - size * 0.75) / scale,
                              tw / scale, size * 0.85 / scale, "#E8EAED")
                    continue
                adv = 0.0
                for ch in s:
                    g = _STROKE.get(ch.upper())
                    if g:
                        gx = p["x"] * scale + adv
                        gy = (p["y"] - size * 0.78) * scale
                        gw = size * 0.6
                        for i in range(len(g) - 1):
                            line(gx + g[i][0] * gw, gy + g[i][1] * size,
                                 gx + g[i + 1][0] * gw, gy + g[i + 1][1] * size,
                                 hexc(p["fill"]), max(1, int(size / 9.0)))
                    adv += size * 0.62
        raw = b"".join([b"", bytes(buf)])
        comp = zlib.compress(bytes(buf), 6)

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data +
                    struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
        png = (b"\x89PNG\r\n\x1a\n" +
               chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)) +
               chunk(b"IDAT", comp) + chunk(b"IEND", b""))
        Path(png_path).write_bytes(png)
        return "stdlib"
    except Exception:
        return None


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def export_png(scene, svg_path, png_path, scale=1.0, allow_browser=True):
    """Try engines in order; return a record that result.json can quote."""
    svg_path = Path(svg_path)
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    width_px = int(scene["canvas"]["width_px"] * scale)
    record = {"path": str(png_path.name), "requested_width": width_px, "engine": "",
              "verified": False, "attempts": [], "degraded": [], "text_complete": True}
    tries = [
        ("cairosvg", lambda: _via_cairosvg(svg_path, png_path, width_px)),
        ("pymupdf", lambda: _via_pymupdf(svg_path, png_path, width_px)),
        ("pillow", lambda: _via_pillow(scene, png_path, scale)),
        ("matplotlib", lambda: _via_matplotlib(scene, png_path, scale)),
        ("cli", lambda: _via_cli(svg_path, png_path, width_px)),
    ]
    if allow_browser:
        tries.append(("browser", lambda: _via_browser(svg_path, png_path, width_px)))
    tries.append(("stdlib", lambda: _via_stdlib(scene, png_path, scale)))
    for name, fn in tries:
        try:
            got = fn()
        except Exception as exc:  # keep the ladder going, record why
            record["attempts"].append({"engine": name, "result": "exception",
                                       "detail": str(exc)[:160]})
            continue
        if not got:
            record["attempts"].append({"engine": name, "result": "unavailable"})
            continue
        info = png_info(png_path)
        if not info:
            record["attempts"].append({"engine": name, "result": "invalid_png"})
            continue
        ink = _nonwhite_ratio(png_path)
        if ink is not None and ink < 0.004:
            record["attempts"].append({"engine": name, "result": "blank_canvas",
                                       "ink": ink})
            continue
        record["attempts"].append({"engine": name, "result": "ok"})
        record["engine"] = got
        record["verified"] = True
        record["width"] = info["width"]
        record["height"] = info["height"]
        record["bit_depth"] = info["bit_depth"]
        record["bytes"] = info["bytes"]
        record["dpi"] = int(scene["canvas"]["dpi"] * scale)
        record["ink_ratio"] = ink
        record["text_complete"] = got != "stdlib"
        if got == "stdlib":
            record["degraded"].append(
                "PNG 由纯标准库光栅器生成：几何与 ASCII 文本完整，CJK 文本以占位块表示；"
                "可编辑 SVG 不受影响")
        return record
    record["attempts"].append({"engine": "all", "result": "failed"})
    record["degraded"].append("所有 PNG 引擎均不可用；仅交付 SVG+PDF，并在 exceptions 说明")
    return record



