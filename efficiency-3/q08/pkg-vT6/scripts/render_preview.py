# -*- coding: utf-8 -*-
"""render_preview.py —— 真渲染：pptx → PDF → PNG，并**从渲染件回测**。

为什么渲染件要回测：pptx 里字号/字体重排、缺字体回退、图片丢失，只有渲染后才看得见。
本模块做四件事：
  1. 多后端渲染：powerpoint（COM，Windows，保真最高）/ soffice（Linux 容器常见）/ none；
  2. 从 PDF 抽每页文本、字体表、图片数、文本包围盒 → 判定"是否越界/是否丢字/字体是否被替换"；
  3. 把 pptx 的文本与 PDF 的文本做**逐页覆盖率**比对（丢字 = 溢出被裁或渲染失败）；
  4. 后端全失败时**不伪造** PDF：写 preview.html + preview.layout.md，状态记 partial 并留报错原文。

用法：
    python render_preview.py --pptx deck.pptx --out out/ --backend auto [--dpi 110]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）
import tempfile
import time

import units

PAGE_MARGIN_PT = 4.0  # 文本允许贴边的容差（pt）


# ------------------------------------------------------------------ 后端探测

def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def detect_backends() -> dict:
    return {
        "powerpoint": os.name == "nt" and (
            os.path.isfile(r"C:\Program Files\Microsoft Office\Root\Office16\POWERPNT.EXE")
            or have("POWERPNT.EXE")),
        "soffice": bool(have("soffice") or have("libreoffice")),
    }


# ------------------------------------------------------------------ PowerPoint COM

_PS_TEMPLATE = r"""
$ErrorActionPreference = "Stop"
$pptx = "{pptx}"
$pdf  = "{pdf}"
$pngdir = "{pngdir}"
$width = {width}
$height = {height}
$ppt = New-Object -ComObject PowerPoint.Application
try {{
  $pres = $ppt.Presentations.Open($pptx, $true, $false, $false)
  try {{
    $pres.SaveAs($pdf, 32)
    $null = New-Item -ItemType Directory -Force -Path $pngdir
    for ($i = 1; $i -le $pres.Slides.Count; $i++) {{
      $n = "{idx_fmt}" -f $i
      $pres.Slides.Item($i).Export((Join-Path $pngdir "slide-$n.png"), "PNG", $width, $height)
    }}
    Write-Output ("OK " + $pres.Slides.Count)
  }} finally {{ $pres.Close() }}
}} finally {{ $ppt.Quit() }}
"""


def render_powerpoint(pptx: str, pdf: str, pngdir: str, width=1600, height=900) -> dict:
    os.makedirs(pngdir, exist_ok=True)
    script = _PS_TEMPLATE.format(pptx=os.path.abspath(pptx).replace('"', ''),
                                 pdf=os.path.abspath(pdf).replace('"', ''),
                                 pngdir=os.path.abspath(pngdir).replace('"', ''),
                                 width=width, height=height, idx_fmt="{0:D2}")
    fd, spath = tempfile.mkstemp(suffix=".ps1")
    os.close(fd)
    with open(spath, "w", encoding="utf-8-sig") as fh:
        fh.write(script)
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-File", spath], capture_output=True, text=True, timeout=300)
    finally:
        try:
            os.remove(spath)
        except OSError:
            pass
    if proc.returncode != 0 or not os.path.isfile(pdf):
        return {"backend": "powerpoint", "ok": False,
                "error": (proc.stderr or proc.stdout or "unknown").strip()[:600]}
    return {"backend": "powerpoint", "ok": True, "pdf": pdf,
            "png": sorted(os.path.join(pngdir, f) for f in os.listdir(pngdir)
                          if f.endswith(".png")),
            "note": "PowerPoint COM 导出（与编辑端同一渲染引擎，字体回退最真实）"}


def render_soffice(pptx: str, pdf: str, pngdir: str, dpi: int = 110) -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(pdf)) or ".", exist_ok=True)
    exe = "soffice" if have("soffice") else "libreoffice"
    prof = tempfile.mkdtemp(prefix="lo-profile-")
    try:
        proc = subprocess.run([exe, "--headless", "--norestore",
                               "-env:UserInstallation=file://" + prof.replace("\\", "/"),
                               "--convert-to", "pdf", "--outdir",
                               os.path.dirname(os.path.abspath(pdf)), pptx],
                              capture_output=True, text=True, timeout=300)
    except Exception as exc:
        return {"backend": "soffice", "ok": False, "error": str(exc)[:400]}
    produced = os.path.join(os.path.dirname(os.path.abspath(pdf)),
                            os.path.splitext(os.path.basename(pptx))[0] + ".pdf")
    if not os.path.isfile(produced):
        return {"backend": "soffice", "ok": False,
                "error": (proc.stderr or proc.stdout or "no pdf")[:400]}
    if os.path.abspath(produced) != os.path.abspath(pdf):
        shutil.move(produced, pdf)
    pngs = []
    try:
        import fitz
        doc = fitz.open(pdf)
        os.makedirs(pngdir, exist_ok=True)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            fn = os.path.join(pngdir, "slide-%02d.png" % (i + 1))
            pix.save(fn)
            pngs.append(fn)
        doc.close()
    except Exception as exc:
        return {"backend": "soffice", "ok": True, "pdf": pdf, "png": pngs,
                "warning": "pdf ok, png failed: %s" % exc}
    return {"backend": "soffice", "ok": True, "pdf": pdf, "png": pngs,
            "note": "LibreOffice headless 导出"}


# ------------------------------------------------------------------ PDF 回测

def _norm(s: str) -> str:
    s = s.replace("\u00ad", "")
    return re.sub(r"\s+", "", s).lower()


# 字体名对齐表：同一字体在不同渲染端/PDF 里的写法不一样（黑体 ↔ SimHei、
# Times New Roman ↔ TimesNewRomanPSMT）。不做这张表，"字体是否被替换"会全判成缺失。
FONT_ALIASES = {
    "simhei": ["黑体", "heiti", "stheiti", "simhei"],
    "simsun": ["宋体", "songti", "stsong", "simsun", "nsimsun"],
    "microsoftyahei": ["微软雅黑", "msyh", "yahei", "microsoftyahei"],
    "dengxian": ["等线", "dengxian"],
    "kaiti": ["楷体", "kaiti", "stkaiti"],
    "fangsong": ["仿宋", "fangsong", "stfangsong"],
    "sourcehansanssc": ["sourcehansanssc", "思源黑体", "sourcehansans"],
    "sourcehanserifsc": ["sourcehanserifsc", "思源宋体", "sourcehanserif"],
    "notosanscjksc": ["notosanscjksc", "notosanscjk"],
    "notoserifcjksc": ["notoserifcjksc"],
    "arial": ["arial", "arialmt", "liberationsans", "helvetica"],
    "timesnewroman": ["timesnewroman", "timesnewromanpsmt", "liberationserif", "times"],
    "calibri": ["calibri", "carlito"],
    "cambria": ["cambria", "caladea"],
    "georgia": ["georgia"],
    "sourcesanspro": ["sourcesanspro", "sourcesans3"],
    "sourceserifpro": ["sourceserifpro", "sourceserif4"],
    "dejavusans": ["dejavusans"],
}


def font_key(name: str) -> str:
    if not name:
        return ""
    n = re.sub(r"[\s\-_]+", "", name.strip().lower())
    n = re.sub(r"(psmt|regular|bold|italic|light|semibold|medium|black|thin)$",
               "", n) or n
    for canon, aliases in FONT_ALIASES.items():
        for a in aliases:
            if a in n or n in a:
                return canon
    return n


def font_close(a: str, b: str) -> bool:
    ka, kb = font_key(a), font_key(b)
    return bool(ka) and (ka == kb or ka in kb or kb in ka)


def pdf_probe(pdf_path: str, pptx_texts: list) -> dict:
    import fitz
    doc = fitz.open(pdf_path)
    pages = []
    fonts_all = {}
    for i, page in enumerate(doc):
        rect = page.rect
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        text = "\n".join(b[4] for b in blocks)
        bbox = None
        for b in blocks:
            r = fitz.Rect(b[:4])
            bbox = r if bbox is None else (bbox | r)
        over = None
        if bbox is not None:
            over = {"left": round(bbox.x0, 2), "top": round(bbox.y0, 2),
                    "right": round(rect.width - bbox.x1, 2),
                    "bottom": round(rect.height - bbox.y1, 2),
                    "ms": round(max(-bbox.x0, -bbox.y0, bbox.x1 - rect.width,
                                    bbox.y1 - rect.height), 2)}
        fonts = []
        for f in page.get_fonts():
            name = (f[3] or "").split("+")[-1]
            fonts.append(name)
            fonts_all[name] = fonts_all.get(name, 0) + 1
        imgs = len(page.get_images(full=True))
        src = pptx_texts[i] if i < len(pptx_texts) else ""
        ntgt, nsrc = _norm(text), _norm(src)
        cov = 1.0
        if nsrc:
            hit = sum(1 for ch in nsrc if ch in ntgt)
            cov = round(hit / float(len(nsrc)), 4)
        pages.append({
            "page": i + 1, "width_pt": round(rect.width, 2), "height_pt": round(rect.height, 2),
            "text_chars": len(text), "bbox_margins_pt": over, "fonts": sorted(set(fonts)),
            "images": imgs, "text_coverage": cov,
            "text_head": text[:160].replace("\n", " "),
        })
    doc.close()
    return {"pages": pages, "page_count": len(pages), "fonts_used": fonts_all,
            "fonts": sorted(fonts_all)}


def check_pdf(pdf_info: dict, expect_fonts: list, expect_slides: int,
              expect_images: int) -> dict:
    issues = []
    if pdf_info["page_count"] != expect_slides:
        issues.append({"severity": "high", "item": "页数不一致",
                       "detail": "pptx %d 页 / pdf %d 页" % (expect_slides, pdf_info["page_count"])})
    for p in pdf_info["pages"]:
        if p["text_coverage"] < 0.97:
            issues.append({"severity": "high", "item": "渲染丢字/裁剪",
                           "page": p["page"],
                           "detail": "pptx 文本在 PDF 中覆盖率 %.1f%%（<97%%）" % (p["text_coverage"] * 100)},
                          )
        m = p["bbox_margins_pt"]
        if m and m["ms"] > PAGE_MARGIN_PT:
            issues.append({"severity": "medium", "item": "文本越出页面",
                           "page": p["page"],
                           "detail": "文本包围盒超出页面 %.1fpt" % m["ms"]})
    embedded = {font_key(f) for f in pdf_info["fonts"]}
    missing = []
    for f in expect_fonts:
        if not f:
            continue
        if font_key(f) in embedded or any(font_close(f, e) for e in pdf_info["fonts"]):
            continue
        missing.append(f)
    if missing:
        issues.append({"severity": "medium", "item": "字体被替换",
                       "detail": "pptx 请求但 PDF 未使用的字体：%s；PDF 实际字体：%s"
                                 % (", ".join(sorted(set(missing))),
                                    ", ".join(pdf_info["fonts"][:8]))})
    if expect_images and pdf_info["pages"]:
        got = sum(p["images"] for p in pdf_info["pages"])
        if got < expect_images:
            issues.append({"severity": "medium", "item": "图片缺失",
                           "detail": "pptx 期望 ≥%d 张图，PDF 里 %d 张" % (expect_images, got)})
    return {"issues": issues, "pdf_fonts": pdf_info["fonts"],
            "missing_fonts": sorted(set(missing)),
            "ok": not any(i["severity"] == "high" for i in issues)}


# ------------------------------------------------------------------ 兜底预览

def write_fallback(pptx_texts: list, plan: dict | None, outdir: str, error: str,
                   pptx_path: str | None = None) -> dict:
    os.makedirs(outdir, exist_ok=True)
    html = ["<!doctype html><meta charset='utf-8'><title>deck preview (fallback)</title>",
            "<style>body{font-family:system-ui,sans-serif;margin:24px}"
            ".s{border:1px solid #ccc;border-radius:6px;padding:16px;margin:16px 0;"
            "box-shadow:0 1px 3px #ddd}h3{margin:0 0 8px}p{margin:4px 0;white-space:pre-wrap}</style>",
            "<h1>未能渲染 PDF/PNG（渲染后端不可用）</h1><p>报错原文：<code>%s</code></p>" % error]
    for i, t in enumerate(pptx_texts, 1):
        html.append("<div class='s'><h3>第 %d 页</h3><p>%s</p></div>"
                    % (i, (t or "").replace("<", "&lt;")[:1200]))
    with open(os.path.join(outdir, "preview.html"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(html))
    # METHOD.md 承诺的第二个兜底产物：**页级版式摘要**（无 PDF 时仍可离线核对版式与几何）
    layout_md = write_layout_digest(pptx_path, plan, outdir, error) if pptx_path else None
    return {"backend": "none", "ok": False, "error": error,
            "html": os.path.join(outdir, "preview.html"),
            "layout_md": layout_md,
            "note": "不伪造 PDF/PNG；状态由 audit 记 partial"}


def write_layout_digest(pptx_path: str, plan: dict | None, outdir: str, error: str) -> str | None:
    """写 `preview.layout.md`：逐页列出版式、每个形状的 kind/位置/尺寸/字号。

    用途：渲染后端不可用时，评审仍能核对"版式是否继承、几何是否来自版式、有没有溢出候选"。
    """
    try:
        from pptx import Presentation
        from pptx.util import Emu
        E = 914400.0
        prs = Presentation(pptx_path)
    except Exception as exc:  # 打不开就如实返回 None，不写半成品
        return None
    plans = {s.get("index"): s for s in (plan or {}).get("slides") or []}
    out = ["# preview.layout.md · 页级版式摘要（无渲染后端时的兜底产物）",
           "", "> 渲染后端不可用：不伪造 PDF/PNG。本文件由 pptx 本体读出，用于离线核对版式与几何。",
           "> 报错原文：`%s`" % error.replace("\n", " ")[:200], "",
           "| 页 | 版式 | 形状 | 类型 | 位置(in) | 尺寸(in) | 字号(pt) | 字符数 | a:xfrm |",
           "|---|---|---|---|---|---|---|---|---|"]
    for i, slide in enumerate(prs.slides, 1):
        lay = slide.slide_layout.name
        sp = plans.get(i) or {}
        for sh in slide.shapes:
            sizes = []
            if sh.has_text_frame:
                for p in sh.text_frame.paragraphs:
                    sizes += [r.font.size.pt for r in p.runs if r.font.size is not None]
            try:
                kind = sh.placeholder_format.type
                kind = str(kind).split(" ")[0] if kind is not None else "textbox"
            except Exception:
                kind = "textbox"
            xfrm = sh._element.find(
                "{http://schemas.openxmlformats.org/presentationml/2006/main}spPr")
            has_xfrm = xfrm is not None and xfrm.find(
                "{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm") is not None
            out.append("| %d | %s | %s | %s | %.2f,%.2f | %.2f×%.2f | %s | %d | %s |" % (
                i, lay, (sh.name or "")[:24], kind,
                (sh.left or 0) / E, (sh.top or 0) / E,
                (sh.width or 0) / E, (sh.height or 0) / E,
                ",".join("%g" % s for s in sorted(set(sizes))[:4]) or "—",
                len(sh.text_frame.text) if sh.has_text_frame else 0,
                "有" if has_xfrm else "无（继承）"))
        if sp.get("role") or sp.get("title"):
            out.append("| %d | %s | _主张:_ %s | _角色:_ %s | | | | | |" % (
                i, "", (sp.get("claim") or "")[:40], sp.get("role")))
    out += ["", "**判读**：内容占位符 `a:xfrm` = 无 → 坐标来自版式继承；出现「有」的占位符需人工确认。"]
    p = os.path.join(outdir, "preview.layout.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    return p


def pptx_texts(path: str) -> list:
    """取每页的可见文本（**跳过 a:fld 域**，如页码域，否则会把 ‹#› 当成丢字）。"""
    from pptx import Presentation
    from pptx.oxml.ns import qn
    prs = Presentation(path)
    out = []
    for slide in prs.slides:
        chunks = []
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                kept = []
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        if r._r.getparent() is not None and r._r.getparent().tag == qn("a:fld"):
                            continue
                        kept.append(r.text)
                    kept.append("\n")
                txt = "".join(kept).strip()
                if txt:
                    chunks.append(txt)
            elif getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    chunks.append(" | ".join(c.text for c in row.cells))
        out.append("\n".join(chunks))
    return out


def expected_fonts(plan: dict) -> list:
    f = (plan.get("meta") or {}).get("fonts") or {}
    out = []
    for kind in ("title", "body", "caption"):
        node = f.get(kind) or {}
        out += [node.get("latin"), node.get("ea")]
    return sorted({x for x in out if x})


def render(pptx: str, outdir: str, backend: str = "auto", dpi: int = 110,
           plan: dict | None = None, width: int = 1600, height: int = 900) -> dict:
    os.makedirs(outdir, exist_ok=True)
    pv = os.path.join(outdir, "preview")
    os.makedirs(pv, exist_ok=True)
    pdf = os.path.join(pv, "deck.pdf")
    pngdir = os.path.join(pv, "png")
    avail = detect_backends()
    attempts = []
    result = None
    order = []
    if backend == "auto":
        order = [b for b in ("powerpoint", "soffice") if avail.get(b)]
    elif backend in ("powerpoint", "soffice"):
        order = [backend]
    for b in order:
        # PowerPoint COM 不是并发安全的（多个实例抢同一份文件会 E_FAIL）；
        # 失败后等一下重试一次，仍失败才换下一个后端。
        for attempt in (1, 2):
            try:
                if b == "powerpoint":
                    r = render_powerpoint(pptx, pdf, pngdir, width, height)
                else:
                    r = render_soffice(pptx, pdf, pngdir, dpi)
            except Exception as exc:
                r = {"backend": b, "ok": False, "error": str(exc)[:400]}
            r["attempt"] = attempt
            attempts.append(r)
            if r.get("ok"):
                break
            if attempt == 1:
                time.sleep(2.0)
                for stale in (pdf,):
                    if os.path.isfile(stale):
                        try:
                            os.remove(stale)
                        except OSError:
                            pass
        if attempts and attempts[-1].get("ok"):
            result = attempts[-1]
            break
    if result is None:
        texts = pptx_texts(pptx)
        err = "；".join("%s: %s" % (a.get("backend"), a.get("error", "")[:160])
                       for a in attempts) or "no render backend (office-renderer 未提供)"
        fb = write_fallback(texts, plan, pv, err, pptx_path=pptx)
        return {"ok": False, "backend": "none", "attempts": attempts,
                "fallback": fb, "pdf": None, "png": [],
                "note": "渲染链全失败：保留 pptx + HTML 预览，不伪造 PDF/PNG"}
    texts = pptx_texts(pptx)
    info = pdf_probe(result["pdf"], texts)
    exp_fonts = expected_fonts(plan or {})
    imgs = 0
    try:
        from pptx import Presentation
        prs = Presentation(pptx)
        for s in prs.slides:
            imgs += sum(1 for sh in s.shapes if sh.shape_type == 13)
    except Exception:
        pass
    checks = check_pdf(info, exp_fonts, len(texts), imgs)
    return {
        "ok": True, "backend": result["backend"], "attempts": attempts,
        "pdf": result["pdf"], "png": result.get("png") or [],
        "page_count": info["page_count"],
        "pages": info["pages"],
        "pdf_fonts": checks["pdf_fonts"], "missing_fonts": checks["missing_fonts"],
        "images_in_pptx": imgs,
        "checks": checks,
        "note": result.get("note", ""),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="render pptx → pdf/png and back-check")
    ap.add_argument("--pptx", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--backend", default="auto", choices=["auto", "powerpoint", "soffice", "none"])
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--plan")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan, encoding="utf-8")) if a.plan else None
    rep = render(a.pptx, a.out, a.backend, a.dpi, plan)
    with open(os.path.join(a.out, "render_report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    if rep["ok"]:
        print("render_preview: backend=%s pages=%d pdf=%s png=%d fonts=%s" % (
            rep["backend"], rep["page_count"], os.path.basename(rep["pdf"]),
            len(rep["png"]), ",".join(rep["pdf_fonts"][:5])))
        for i in rep["checks"]["issues"]:
            print("  [%s] %s %s" % (i["severity"], i["item"], i.get("detail", "")[:100]))
    else:
        print("render_preview: RENDER_FAILED (%s)" % rep.get("note"))
    return 0 if rep["ok"] else 4


if __name__ == "__main__":
    sys.exit(main())
