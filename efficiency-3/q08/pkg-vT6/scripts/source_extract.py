# -*- coding: utf-8 -*-
"""source_extract.py —— 把论文/研究材料拆成可定位的单元（页级证据映射的原料）。

产出 source_map.json：
  blocks[]    段落级单元，每块带 locator（PDF 行 → "p.4 §2.1 ¶2"；md → "§2.1 ¶2"）
  sections[]  按标题切出的章节，带 locator
  figures[]   图/表：caption + locator + 可嵌入的图片文件（PDF 抽图/裁图；md 直接引用）
  stats       字符数、标题数、图表数、数值断言数

原则：**不臆测**。抽不到的东西（扫描件无文本层、矢量图无法抽位图）写进
`extraction_limits`，由 audit 转成 uncertainty，绝不用"看起来像"的内容补齐。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）
import unicodedata

import units

CAPTION_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(Figure|Fig\.?|Table|Scheme|图|表|圖)\s*([0-9]+(?:\s*[.．]\s*[0-9]+)?)"
    r"\s*[:：.、]?\s*(.*)$", re.I)
NUMERIC_HINT = re.compile(
    r"(\d+(?:\.\d+)?\s*%|\b\d+\.\d+\b|\bp\s*[<=>]\s*0\.\d+|\bAUC\b|\bGDT|"
    r"\bBLEU\b|\bRMSD\b|\baccuracy\b|\bn\s*=\s*\d+|\b95%\s*CI|±)")
HEADISH = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?\s+|第[一二三四五六七八九十]+[章节])")


def _clean(s: str) -> str:
    s = unicodedata.normalize("NFKC", s) if False else s  # 保留原字形（不改变引文）
    s = s.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def split_sentences(text: str) -> list:
    """中英混排断句；对常见缩写（et al./e.g./Fig.）做保护。"""
    text = _clean(text)
    if not text:
        return []
    protected = text
    for ab in ("et al.", "e.g.", "i.e.", "Fig.", "Figs.", "Tab.", "vs.", "cf.", "approx."):
        protected = protected.replace(ab, ab.replace(".", "\u0001"))
    parts = re.split(r"(?<=[。！？；!?;])\s*|(?<=[.])\s+(?=[A-Z0-9(\[])", protected)
    out = []
    for p in parts:
        p = p.replace("\u0001", ".").strip()
        if len(p) >= 4:
            out.append(p)
    return out


# ------------------------------------------------------------------ markdown / txt

def extract_text(text: str, base_dir: str = ".", name: str = "source") -> dict:
    blocks, sections, figures, tables = [], [], [], []
    heads = []          # 当前标题栈 [(level, title)]
    sec_no = 0
    para_in_sec = 0
    lines = text.splitlines()
    buf = []

    def locator(extra: str = "") -> str:
        path = "/".join(h[1] for h in heads) or name
        return "§%s ¶%d%s" % (path, para_in_sec, extra)

    def new_section(title: str, level: int, line_no: int):
        nonlocal sec_no, para_in_sec
        while heads and heads[-1][0] >= level:
            heads.pop()
        heads.append((level, title))
        sec_no += 1
        para_in_sec = 0
        sections.append({"id": "s%02d" % sec_no, "title": title, "level": level,
                         "locator": "§%s" % "/".join(h[1] for h in heads),
                         "line": line_no + 1, "blocks": []})

    def flush():
        nonlocal para_in_sec
        if not buf:
            return
        txt = _clean(" ".join(buf))
        buf.clear()
        if not txt:
            return
        para_in_sec += 1
        cap = CAPTION_RE.match(txt)
        bid = "b%03d" % (len(blocks) + 1)
        blk = {"id": bid, "kind": "caption" if cap else "para", "text": txt,
               "locator": locator(), "line": None,
               "numeric_hint": bool(NUMERIC_HINT.search(txt)),
               "chars": len(txt)}
        if cap:
            label = "%s %s" % ("Figure" if cap.group(1).lower().startswith(("fig", "图")) else "Table",
                               cap.group(2).replace(" ", ""))
            figures.append({"id": "fig%d" % (len(figures) + 1), "label": label,
                            "caption": _clean(cap.group(3)) or txt,
                            "locator": blk["locator"], "image": None,
                            "kind": "caption-only", "block_id": bid})
        blocks.append(blk)
        if sections:
            sections[-1]["blocks"].append(bid)

    i = 0
    while i < len(lines):
        line = lines[i]
        raw = line.rstrip()
        s = raw.strip()
        m = re.match(r"^(#{1,6})\s+(.+)$", s)
        if m:
            flush()
            new_section(_clean(m.group(2)), len(m.group(1)), i)
            blocks.append({"id": "b%03d" % (len(blocks) + 1), "kind": "heading",
                           "text": _clean(m.group(2)), "locator": "§%s" % "/".join(
                               h[1] for h in heads), "line": i + 1,
                           "numeric_hint": False, "chars": len(m.group(2))})
            if sections:
                sections[-1]["blocks"].append(blocks[-1]["id"])
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        if re.match(r"^(\||\+[-=]+\+|[-*_]{3,})$", s):  # 表格行/分隔线
            flush()
            row = [c.strip() for c in s.strip("|").split("|")]
            tables.append({"locator": locator(), "cells": row, "line": i + 1})
            blocks.append({"id": "b%03d" % (len(blocks) + 1), "kind": "table",
                           "text": " | ".join(row), "locator": locator(), "line": i + 1,
                           "numeric_hint": True, "chars": len(s)})
            if sections:
                sections[-1]["blocks"].append(blocks[-1]["id"])
            i += 1
            continue
        im = re.search(r"!\[([^\]]*)\]\(([^)\s]+)", s)
        if im:
            flush()
            path = im.group(2)
            full = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
            fig = {"id": "fig%d" % (len(figures) + 1), "label": "Figure",
                   "caption": _clean(im.group(1)) or os.path.basename(path),
                   "locator": locator(), "image": full if os.path.isfile(full) else None,
                   "kind": "embedded" if os.path.isfile(full) else "missing",
                   "block_id": None}
            cm = CAPTION_RE.match(_clean(im.group(1)))
            if cm:
                fig["label"] = "%s %s" % ("Figure" if cm.group(1).lower().startswith(("fig", "图")) else "Table",
                                          cm.group(2))
                fig["caption"] = _clean(cm.group(3)) or fig["caption"]
            figures.append(fig)
            blocks.append({"id": "b%03d" % (len(blocks) + 1), "kind": "image",
                           "text": _clean(im.group(1)), "locator": locator(),
                           "line": i + 1, "chars": 0, "image": fig["image"]})
            fig["block_id"] = blocks[-1]["id"]
            if sections:
                sections[-1]["blocks"].append(blocks[-1]["id"])
            i += 1
            continue
        if s.startswith(("```", "~~~")):
            flush()
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(("```", "~~~")):
                i += 1
            i += 1
            continue
        buf.append(s)
        i += 1
    flush()

    title = sections[0]["title"] if sections else name
    for sec in sections:
        if sec["level"] == 1:
            title = sec["title"]
            break
    return _finish(blocks, sections, figures, tables, title, "text")


def _finish(blocks, sections, figures, tables, title, kind) -> dict:
    chars = sum(b["chars"] for b in blocks)
    numeric = [b["id"] for b in blocks if b.get("numeric_hint")]
    for sec in sections:
        sec["chars"] = sum(b["chars"] for b in blocks if b["id"] in sec["blocks"])
        sec["numeric_blocks"] = [b["id"] for b in blocks
                                 if b["id"] in sec["blocks"] and b.get("numeric_hint")]
    return {
        "title": title,
        "kind": kind,
        "blocks": blocks,
        "sections": sections,
        "figures": figures,
        "tables": tables,
        "stats": {
            "chars": chars, "blocks": len(blocks), "sections": len(sections),
            "figures": len(figures), "tables": len(tables),
            "numeric_blocks": len(numeric),
            "numeric_ratio": round(len(numeric) / max(1, len(blocks)), 3),
        },
    }


# ------------------------------------------------------------------ markdown 文件

def extract_markdown(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    out = extract_text(text, os.path.dirname(os.path.abspath(path)), os.path.basename(path))
    out["source"] = {"file": os.path.basename(path), "kind": "md",
                     "sha256": units.sha256_file(path), "bytes": os.path.getsize(path),
                     "chars": len(text), "method": "markdown 结构解析（标题/段落/图/表）"}
    return out


# ------------------------------------------------------------------ pdf

def extract_pdf(path: str, work_dir: str, dpi: int = 200) -> dict:
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    blocks, sections, figures, tables = [], [], [], []
    limits = []
    heads = []
    sec_no = 0
    para_in_sec = 0
    body_sizes = []
    page_texts = []
    for pno in range(len(doc)):
        page = doc[pno]
        d = page.get_text("dict")
        for blk in d.get("blocks", []):
            if blk.get("type") != 0:
                continue
            for line in blk.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        body_sizes.append(round(span.get("size", 0), 1))
    from collections import Counter
    body_size = Counter(body_sizes).most_common(1)[0][0] if body_sizes else 10.0

    figdir = os.path.join(work_dir, "figures")
    os.makedirs(figdir, exist_ok=True)

    for pno in range(len(doc)):
        page = doc[pno]
        raw_lines = []
        for blk in page.get_text("blocks"):
            x0, y0, x1, y1, txt, bno, btype = blk[:7]
            if btype != 0:
                continue
            for ln in txt.splitlines():
                ln = _clean(ln)
                if ln:
                    raw_lines.append({"text": ln, "bbox": (x0, y0, x1, y1)})
        page_texts.append("\n".join(l["text"] for l in raw_lines))

        # 逐行判断标题（字号显著大于正文且短，或以 1/2/3 编号开头）
        for ln in raw_lines:
            txt = ln["text"]
            is_head = False
            level = 0
            if HEADISH.match(txt) and len(txt) < 110:
                is_head = True
                level = 1 + len(re.match(r"^(\d+(?:\.\d+)*)", txt).group(1).split(".")) - 1 \
                    if re.match(r"^\d", txt) else 1
            elif 5 < len(txt) < 70 and not txt.endswith((".", "。", ";", "；", ",")) \
                    and txt[0].isupper() and len(txt.split()) <= 12:
                is_head = False  # 保守：不把普通句首当标题
            if is_head:
                para_in_sec = 0
                while heads and heads[-1][0] >= level:
                    heads.pop()
                heads.append((level, txt))
                sec_no += 1
                sections.append({"id": "s%02d" % sec_no, "title": txt, "level": level,
                                 "locator": "p.%d §%s" % (pno + 1, "/".join(h[1] for h in heads)),
                                 "page": pno + 1, "blocks": []})
                bid = "b%03d" % (len(blocks) + 1)
                blocks.append({"id": bid, "kind": "heading", "text": txt,
                               "locator": sections[-1]["locator"], "page": pno + 1,
                               "chars": len(txt)})
                sections[-1]["blocks"].append(bid)
                continue
            para_in_sec += 1
            loc = "p.%d §%s ¶%d" % (pno + 1, "/".join(h[1] for h in heads) or "(正文)", para_in_sec)
            bid = "b%03d" % (len(blocks) + 1)
            cap = CAPTION_RE.match(txt)
            blk = {"id": bid, "kind": "caption" if cap else "para", "text": txt,
                   "locator": loc, "page": pno + 1, "chars": len(txt),
                   "numeric_hint": bool(NUMERIC_HINT.search(txt))}
            blocks.append(blk)
            if sections:
                sections[-1]["blocks"].append(bid)
            if cap:
                figures.append({"id": "fig%d" % (len(figures) + 1),
                                "label": "%s %s" % ("Figure" if cap.group(1).lower().startswith(("fig", "图")) else "Table",
                                                    cap.group(2).replace(" ", "")),
                                "caption": _clean(cap.group(3)) or txt,
                                "locator": loc, "page": pno + 1,
                                "image": None, "kind": "caption-only", "block_id": bid,
                                "bbox": ln["bbox"]})
            # 表格：连续多行含 | 或制表符分隔的数字列
            if txt.count("  ") >= 2 and re.search(r"\d", txt):
                tables.append({"locator": loc, "cells": re.split(r"\s{2,}", txt), "page": pno + 1})

    # 图：优先抽位图，其次按 caption 上方区域裁矢量图
    for fig in figures:
        if fig.get("page") is None:
            continue
        page = doc[fig["page"] - 1]
        cap_bbox = fig.get("bbox") or (0, 0, page.rect.width, page.rect.height)
        best = None
        for img in page.get_images(full=True):
            try:
                rects = page.get_image_rects(img[0])
            except Exception:
                rects = []
            for r in rects:
                if r.width < 120 or r.height < 80:
                    continue
                if abs(r.y1 - cap_bbox[1]) < 160 or abs(r.y0 - cap_bbox[3]) < 160:
                    area = r.width * r.height
                    if best is None or area > best[0]:
                        best = (area, img[0], r)
        if best:
            try:
                pix = doc.extract_image(best[1])
                ext = pix.get("ext", "png")
                fn = os.path.join(figdir, "%s.%s" % (fig["id"], ext))
                with open(fn, "wb") as fh:
                    fh.write(pix["image"])
                fig["image"] = fn
                fig["kind"] = "extracted-raster"
                fig["image_px"] = [pix.get("width"), pix.get("height")]
            except Exception as e:
                fig["note"] = "extract failed: %s" % e
        if not fig.get("image"):
            # 矢量图：裁 caption 上方区域（论文里图在 caption 之上）
            top = max(0, cap_bbox[1] - 260)
            clip = fitz.Rect(cap_bbox[0] - 8, top, cap_bbox[2] + 8, cap_bbox[1] - 2)
            if clip.height > 40 and clip.width > 60:
                fn = os.path.join(figdir, "%s.png" % fig["id"])
                pix = page.get_pixmap(clip=clip, dpi=dpi)
                pix.save(fn)
                fig["image"] = fn
                fig["kind"] = "cropped-region"
                fig["image_px"] = [pix.width, pix.height]
                fig["note"] = "矢量/版面图不可直接抽取，按 caption 上方区域按 %d dpi 裁切" % dpi
    if any(f.get("kind") == "caption-only" for f in figures):
        limits.append("部分图/表只有 caption，未抽到可嵌入位图（可能为矢量图或跨页）")
    if not any(b["kind"] != "heading" for b in blocks):
        limits.append("PDF 未抽到正文文本层（疑为扫描件）——需 OCR 或换材料")

    out = _finish(blocks, sections, figures, tables,
                  (sections[0]["title"] if sections else os.path.basename(path)), "pdf")
    out["source"] = {"file": os.path.basename(path), "kind": "pdf",
                     "sha256": units.sha256_file(path), "bytes": os.path.getsize(path),
                     "pages": len(doc), "chars": sum(len(t) for t in page_texts),
                     "body_font_size": body_size,
                     "method": "PyMuPDF get_text('blocks') 逐行 + caption 正则 + 图像抽取"}
    out["extraction_limits"] = limits
    out["_page_texts"] = page_texts
    doc.close()
    return out


# ------------------------------------------------------------------ docx

def extract_docx(path: str) -> dict:
    import docx
    d = docx.Document(path)
    blocks, sections, figures, tables = [], [], [], []
    heads, sec_no, para_in_sec = [], 0, 0
    for p in d.paragraphs:
        txt = _clean(p.text)
        if not txt:
            continue
        style = (p.style.name or "").lower()
        m = re.match(r"^(heading|标题)\s*(\d)", style)
        if m:
            level = int(m.group(2))
            while heads and heads[-1][0] >= level:
                heads.pop()
            heads.append((level, txt))
            sec_no += 1
            para_in_sec = 0
            sections.append({"id": "s%02d" % sec_no, "title": txt, "level": level,
                             "locator": "§%s" % "/".join(h[1] for h in heads), "blocks": []})
            bid = "b%03d" % (len(blocks) + 1)
            blocks.append({"id": bid, "kind": "heading", "text": txt,
                           "locator": sections[-1]["locator"], "chars": len(txt)})
            sections[-1]["blocks"].append(bid)
            continue
        para_in_sec += 1
        loc = "§%s ¶%d" % ("/".join(h[1] for h in heads) or "(正文)", para_in_sec)
        bid = "b%03d" % (len(blocks) + 1)
        cap = CAPTION_RE.match(txt)
        blocks.append({"id": bid, "kind": "caption" if cap else "para", "text": txt,
                       "locator": loc, "chars": len(txt),
                       "numeric_hint": bool(NUMERIC_HINT.search(txt)),
                       "style": p.style.name})
        if sections:
            sections[-1]["blocks"].append(bid)
        if cap:
            figures.append({"id": "fig%d" % (len(figures) + 1),
                           "label": "%s %s" % ("Figure", cap.group(2).replace(" ", "")),
                           "caption": _clean(cap.group(3)) or txt, "locator": loc,
                           "image": None, "kind": "caption-only", "block_id": bid})
    out = _finish(blocks, sections, figures, tables,
                  (sections[0]["title"] if sections else os.path.basename(path)), "docx")
    out["source"] = {"file": os.path.basename(path), "kind": "docx",
                     "sha256": units.sha256_file(path), "bytes": os.path.getsize(path),
                     "chars": sum(b["chars"] for b in blocks),
                     "method": "python-docx 段落+样式（Heading N）+ caption 正则"}
    out["extraction_limits"] = ["docx 里的嵌入图片未抽取（只有 caption 定位）；如需成图请提供图片文件"]
    return out


# ------------------------------------------------------------------ 数据出图
# 图表适配的上游：只负责出等比原图，等比放置交给 pptx_util.fit_picture()，
# 两者分开才能把原图比例与放置偏差分别核对。支持 line/bar/scatter/forest/km/box。

def _read_csv(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    cols = list(rows[0].keys()) if rows else []
    return {"rows": rows, "cols": cols}


def _num(v):
    try:
        return float(str(v).replace("%", "").strip())
    except Exception:
        return None


def make_figure(spec: dict, base_dir: str, out_path: str) -> dict:
    """spec: {csv, kind, x, y, series, title, xlabel, ylabel, label_col, ...}"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _set_cjk_font(matplotlib, plt)
    csv_path = spec["csv"] if os.path.isabs(spec["csv"]) else os.path.join(base_dir, spec["csv"])
    data = _read_csv(csv_path)
    rows, cols = data["rows"], data["cols"]
    kind = (spec.get("kind") or "line").lower()
    xcol, ycol = spec.get("x"), spec.get("y")
    series = spec.get("series")
    xlabel = spec.get("xlabel", xcol or "")
    ylabel = spec.get("ylabel", ycol or "")
    title = spec.get("title", "")

    fig, ax = plt.subplots(figsize=(float(spec.get("width_in", 6.2)),
                                    float(spec.get("height_in", 3.6))), dpi=200)
    groups = {}
    if series and series in cols:
        for r in rows:
            groups.setdefault(r[series], []).append(r)
    else:
        groups[""] = rows

    if kind == "line":
        for name, rs in groups.items():
            xs = [_num(r[xcol]) for r in rs]
            ys = [_num(r[ycol]) for r in rs]
            pts = sorted([(a, b) for a, b in zip(xs, ys) if a is not None and b is not None])
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", ms=3.5,
                    lw=1.6, label=name or ycol)
    elif kind == "bar":
        labels = [r.get(xcol, "") for r in rows]
        vals = [_num(r[ycol]) or 0.0 for r in rows]
        errs = [_num(r[spec["error"]]) if spec.get("error") in cols else 0.0 for r in rows]
        ax.bar(labels, vals, yerr=errs if any(errs) else None, capsize=3,
               color="#4F81BD", width=0.6)
        plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    elif kind == "scatter":
        xs = [_num(r[xcol]) for r in rows]
        ys = [_num(r[ycol]) for r in rows]
        ax.scatter([v for v in xs if v is not None], [v for v in ys if v is not None], s=18)
    elif kind == "forest":
        labels = [r.get(xcol, "") for r in rows]
        est = [_num(r[ycol]) or 0.0 for r in rows]
        lo = [_num(r[spec["lo"]]) if spec.get("lo") in cols else None for r in rows]
        hi = [_num(r[spec["hi"]]) if spec.get("hi") in cols else None for r in rows]
        ypos = list(range(len(labels)))
        ax.errorbar(est, ypos,
                    xerr=[[e - l if l is not None else 0 for e, l in zip(est, lo)],
                          [h - e if h is not None else 0 for e, h in zip(est, hi)]],
                    fmt="s", ms=5, color="#C0504D", capsize=3, lw=1.4)
        ax.axvline(1.0, color="#888888", ls="--", lw=1)
        ax.set_yticks(ypos)
        ax.set_yticklabels(labels)
        ax.invert_yaxis()
    elif kind == "km":
        for name, rs in groups.items():
            ts = [_num(r[xcol]) for r in rs]
            ss = [_num(r[ycol]) for r in rs]
            pts = sorted([(a, b) for a, b in zip(ts, ss) if a is not None and b is not None])
            ax.step([p[0] for p in pts], [p[1] for p in pts], where="post", lw=1.6,
                    label=name or ycol)
        ax.set_ylim(0.5, 1.02)
    elif kind == "box":
        groups_data = [[_num(r[ycol]) for r in rs if _num(r[ycol]) is not None]
                       for rs in groups.values()]
        ax.boxplot(groups_data, labels=list(groups.keys()) or [ycol])
    else:
        raise ValueError("unsupported figure kind: %s" % kind)

    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    if title:
        ax.set_title(title, fontsize=11)
    ax.grid(alpha=0.25, lw=0.6)
    if len(groups) > 1 or (series and series in cols) or kind == "km":
        ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return {"out": out_path, "kind": kind, "csv": os.path.relpath(csv_path).replace("\\", "/"),
            "csv_sha256": units.sha256_file(csv_path),
            "rows": len(rows), "cols": cols,
            "size_bytes": os.path.getsize(out_path),
            "width_in": spec.get("width_in", 6.2), "height_in": spec.get("height_in", 3.6)}


def _set_cjk_font(matplotlib, plt):
    """中文字形缺失时 matplotlib 会画成豆腐块；挑一个已装的中文字体并显式声明。"""
    import os as _os
    cands = ["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC",
             "Source Han Sans SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
    try:
        matplotlib.rcParams["font.sans-serif"] = cands
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass


# ------------------------------------------------------------------ 调度

def extract(path: str, work_dir: str = ".", kind: str | None = None) -> dict:
    ext = (kind or os.path.splitext(path)[1]).lower().lstrip(".")
    if ext in ("md", "markdown", "txt"):
        out = extract_markdown(path)
        out["extraction_limits"] = out.get("extraction_limits") or []
    elif ext == "pdf":
        out = extract_pdf(path, work_dir)
    elif ext in ("docx",):
        out = extract_docx(path)
    else:
        raise ValueError("unsupported source type: %s" % ext)
    out["extraction_limits"] = sorted(set(out.get("extraction_limits") or []))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="extract locatable units from paper/material")
    ap.add_argument("--source", help="论文/材料路径（出图模式可省略）")
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="source_map.json")
    ap.add_argument("--csv", help="改为出图模式：数据表")
    ap.add_argument("--spec", help="出图模式：spec.json")
    ap.add_argument("--figure-out", help="出图模式：输出图片")
    ap.add_argument("--outdir", default="figures")
    a = ap.parse_args(argv)
    if a.csv:
        spec = json.load(open(a.spec, encoding="utf-8")) if a.spec else {}
        spec["csv"] = os.path.abspath(a.csv)
        rep = make_figure(spec, os.path.dirname(os.path.abspath(a.csv)) or ".",
                          a.figure_out or os.path.join(a.outdir, "fig1.png"))
        print(json.dumps(rep, ensure_ascii=False))
        return 0
    data = extract(a.source, a.work)
    page_texts = data.pop("_page_texts", None)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    if page_texts:
        with open(os.path.join(a.work, "page_text.json"), "w", encoding="utf-8") as fh:
            json.dump(page_texts, fh, ensure_ascii=False, indent=1)
    s = data["stats"]
    print("source_extract: %s | blocks=%d sections=%d figures=%d numeric=%d chars=%d" % (
        os.path.basename(a.source), s["blocks"], s["sections"], s["figures"],
        s["numeric_blocks"], s["chars"]))
    for lim in data["extraction_limits"]:
        print("  ! %s" % lim)
    return 0


if __name__ == "__main__":
    sys.exit(main())
