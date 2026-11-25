"""render.py - produce a *real* rendered preview, and say which engine did it.

Rendering order, and why:

1. ``$SOFFICE_BIN`` / ``soffice`` / ``libreoffice`` - the usual headless build
   on the evaluation host; also exports per-slide PNGs by converting the PDF
   when :mod:`pdf_lite` is unavailable, otherwise via ``--convert-to png``.
2. **PowerPoint COM** on Windows (``pwsh`` + ``New-Object -ComObject``): the
   highest-fidelity path, used by this package's own verification runs.
3. **Model preview** (Pillow): draws the *resolved layout spec* - the same boxes
   and the same wrapped lines the builder used - so a geometry error is still
   visible even with no office suite installed.

The engine actually used is written into ``render.json``; a model preview is
labelled ``preview_mode="model"`` and forces ``status=partial`` upstream.  The
skill never claims a real render it did not get.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

import layout as L
from util import ensure_dir, one_line, truncate

DEFAULT_TIMEOUT = 150


def render(pptx_path: str, out_dir: str, *, specs: list[dict] | None = None,
           plan: dict | None = None, timeout: int = DEFAULT_TIMEOUT,
           log=None) -> dict:
    out_dir = ensure_dir(out_dir)
    info = {"engine": None, "pdf": None, "pngs": [], "preview_mode": None,
            "log": [], "ok": False, "warnings": []}

    def note(msg):
        info["log"].append(msg)
        if log:
            log(msg)

    if not os.path.isfile(pptx_path):
        info["warnings"].append(f"pptx not found: {pptx_path}")
        return info

    for engine in (_try_soffice, _try_powerpoint, None):
        if engine is _try_soffice:
            if not _soffice_bin():
                note("soffice not found; trying next engine")
                continue
            got = _try_soffice(pptx_path, out_dir, timeout, note)
        elif engine is _try_powerpoint:
            if os.name != "nt":
                note("not on Windows; skipping PowerPoint COM")
                continue
            got = _try_powerpoint(pptx_path, out_dir, timeout, note)
        else:
            got = {}
            note("falling back to model preview from the layout spec")
            got = _model_preview(pptx_path, out_dir, specs or [], plan or {}, note)
            info["preview_mode"] = "model"
        if got:
            info.update(got)
            info["ok"] = bool(info["pdf"] or info["pngs"])
            info["preview_mode"] = "model" if info["engine"] == "model" else "real"
            break
        note(f"engine {engine.__name__ if engine else 'model'} produced nothing")

    if not info.get("preview_mode"):
        info["preview_mode"] = "none"
    info["ok"] = bool(info["pdf"] or info["pngs"])
    return info


# ---------------------------------------------------------------- engines

def _soffice_bin() -> str | None:
    env = os.environ.get("SOFFICE_BIN")
    if env and os.path.isfile(env):
        return env
    for name in ("soffice", "libreoffice", "soffice.exe", "soffice.com"):
        found = shutil.which(name)
        if found:
            return found
    for pat in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                "/usr/bin/soffice", "/usr/local/bin/soffice",
                "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.isfile(pat):
            return pat
    return None


def _try_soffice(pptx: str, out_dir: str, timeout: int, note) -> dict:
    exe = _soffice_bin()
    if not exe:
        return {}
    try:
        subprocess.run([exe, "--headless", "--norestore", "--convert-to", "pdf",
                        "--outdir", out_dir, pptx],
                       timeout=timeout, capture_output=True, check=False)
    except subprocess.TimeoutExpired:
        note(f"soffice timed out after {timeout}s")
        return {}
    except OSError as exc:
        note(f"soffice failed to start: {exc}")
        return {}
    pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(pptx))[0] + ".pdf")
    if not os.path.isfile(pdf):
        note("soffice produced no PDF")
        return {}
    note(f"soffice PDF: {os.path.basename(pdf)}")
    pngs = _pdf_to_pngs(pdf, out_dir, note)
    if not pngs:
        note("PNG extraction skipped (no rasteriser); PDF alone is the preview")
    return {"engine": "libreoffice", "pdf": os.path.basename(pdf), "pngs": pngs}


_PPT_COM = r"""
$ErrorActionPreference = 'Stop'
$pptx = {pptx}
$pdf  = {pdf}
$pngDir = {pngdir}
$app = New-Object -ComObject PowerPoint.Application
try {{
  $pres = $app.Presentations.Open($pptx, $true, $false, $false)
  try {{
    $pres.SaveAs($pdf, 32)
    New-Item -ItemType Directory -Force -Path $pngDir | Out-Null
    foreach ($s in $pres.Slides) {{
      $n = '{{0:d2}}' -f $s.SlideIndex
      $s.Export((Join-Path $pngDir ("slide-$n.png")), "PNG", 1600, 900)
    }}
    "SLIDES=" + $pres.Slides.Count
  }} finally {{ $pres.Close() }}
}} finally {{ $app.Quit() }}
"""


def _try_powerpoint(pptx: str, out_dir: str, timeout: int, note) -> dict:
    if os.name != "nt":
        return {}
    pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(pptx))[0] + ".pdf")
    png_dir = ensure_dir(os.path.join(out_dir, "slides"))
    script = os.path.join(out_dir, "_export.ps1")
    body = _PPT_COM.format(pptx=_ps(pptx), pdf=_ps(pdf), pngdir=_ps(png_dir))
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(body)
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        note("no PowerShell available for COM export")
        return {}
    last_err = ""
    for attempt in (1, 2):
        try:
            proc = subprocess.run([exe, "-NoProfile", "-NonInteractive",
                                   "-ExecutionPolicy", "Bypass", "-File", script],
                                  timeout=timeout, capture_output=True, text=True)
            last_err = one_line(proc.stderr)[:200]
        except subprocess.TimeoutExpired:
            note(f"PowerPoint COM timed out after {timeout}s (attempt {attempt})")
            continue
        if os.path.isfile(pdf):
            break
        note(f"PowerPoint COM produced no PDF on attempt {attempt} "
             f"(rc={proc.returncode}); stderr={last_err}")
        time.sleep(1.5)
    if not os.path.isfile(pdf):
        return {}
    note(f"PowerPoint COM PDF: {os.path.basename(pdf)}")
    pngs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(png_dir, "slide-*.png")))
    note(f"PowerPoint COM exported {len(pngs)} slide PNGs")
    return {"engine": "powerpoint-com", "pdf": os.path.basename(pdf),
            "pngs": pngs, "png_dir": "slides"}


def _ps(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def _pdf_to_pngs(pdf: str, out_dir: str, note) -> list[str]:
    """Rasterise with whatever is available; returning [] is acceptable."""
    png_dir = ensure_dir(os.path.join(out_dir, "slides"))
    try:
        import fitz  # PyMuPDF, if the host has it
        doc = fitz.open(pdf)
        out = []
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=110)
            name = f"slide-{i:02d}.png"
            pix.save(os.path.join(png_dir, name))
            out.append(name)
        note(f"PyMuPDF rasterised {len(out)} pages")
        return out
    except Exception:
        pass
    exe = shutil.which("pdftoppm")
    if exe:
        try:
            subprocess.run([exe, "-r", "110", "-png", pdf,
                            os.path.join(png_dir, "slide")], timeout=90,
                           capture_output=True, check=False)
            out = sorted(os.path.basename(p) for p in glob.glob(os.path.join(png_dir, "slide-*.png")))
            if out:
                note(f"pdftoppm rasterised {len(out)} pages")
                return out
        except Exception:
            pass
    return []


# ---------------------------------------------------------------- model preview

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _model_preview(pptx: str, out_dir: str, specs: list[dict], plan: dict, note) -> dict:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        note("Pillow unavailable; cannot draw model preview")
        return {}
    slide = L.DEFAULT_SLIDE
    deck = plan.get("deck") or {}
    w_in = float(deck.get("slide_w_in") or slide["w_in"])
    h_in = float(deck.get("slide_h_in") or slide["h_in"])
    dpi = 110
    W, H = int(w_in * dpi), int(h_in * dpi)
    png_dir = ensure_dir(os.path.join(out_dir, "slides"))
    slides = plan.get("slides") or []
    made = []
    for i, spec in enumerate(specs):
        img = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(img)
        sdef = slides[i] if i < len(slides) else {}
        for name, reg in (spec.get("regions") or {}).items():
            x, y = int(reg["x_in"] * dpi), int(reg["y_in"] * dpi)
            w, h = int(reg["w_in"] * dpi), int(reg["h_in"] * dpi)
            d.rectangle([x, y, x + w, y + h], outline=(180, 190, 205))
            if name not in ("figure", "table"):
                size = int((reg.get("size_pt") or 14) * dpi / 72)
                font = _font(max(8, size))
                text = ""
                if name == "title":
                    text = sdef.get("title") or ""
                elif name == "claim":
                    text = sdef.get("claim") or ""
                elif name == "bullets":
                    text = "\n".join(str(b) for b in sdef.get("bullets") or [])
                elif name == "caption":
                    text = ((sdef.get("figure") or {}).get("caption") or "")
                d.text((x + 4, y + 2), truncate(text, 220), fill=(30, 34, 44), font=font)
        d.text((int(0.62 * dpi), int((h_in - 0.34) * dpi)),
               f"MODEL PREVIEW - not an office render - page {i + 1}", fill=(150, 120, 90),
               font=_font(11))
        name = f"slide-{i + 1:02d}.png"
        img.save(os.path.join(png_dir, name))
        made.append(name)
    note(f"model preview drew {len(made)} page images")
    return {"engine": "model", "pdf": None, "pngs": made, "png_dir": "slides"}
