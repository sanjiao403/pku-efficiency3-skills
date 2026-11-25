"""assets.py - harvest real figures out of the source PDF, honestly labelled.

A figure page is worth far more with the paper's own artwork on it.  So for a
PDF source we pull the embedded image XObjects (JPEG ``DCTDecode`` and raw
``FlateDecode`` bitmaps), keep the ones that are big enough to be figures rather
than journal logos, and bind them to the caption that lives on the same page.
Whatever is left unbound stays as a labelled schematic placeholder - the deck
never pretends a redrawn box is the artists' original.

No third-party PDF library is required; Pillow is used only to wrap raw
bitmaps into PNG and to read dimensions.
"""
from __future__ import annotations

import os
import re
import zlib

from util import ensure_dir, sha256_bytes

_IMG_OBJ_RE = re.compile(
    rb"(\d+)\s+(\d+)\s+obj\b(.*?)stream\r?\n(.*?)\r?\nendstream", re.S)
_END_RE = re.compile(rb"endstream")
_MIN_PIXELS = 90          # ignore anything smaller than ~90px on a side
_MAX_KEEP = 10


def harvest(pdf_path: str, inv, src, out_dir: str, log=None) -> dict:
    """Return {caption_label: png_path, ...} plus a report."""
    report = {"pdf": os.path.basename(pdf_path) if pdf_path else None,
              "candidates": 0, "kept": 0, "bound": {}, "notes": []}
    if not pdf_path or not os.path.isfile(pdf_path):
        report["notes"].append("no PDF source; figures cannot be harvested")
        return {"assets": {}, "report": report}
    with open(pdf_path, "rb") as fh:
        blob = fh.read()
    if not blob.startswith(b"%PDF"):
        report["notes"].append("source is not a PDF")
        return {"assets": {}, "report": report}

    # page number -> list of object numbers drawn on that page (content streams)
    page_of_obj = _obj_page_map(blob)
    out_dir = ensure_dir(out_dir)
    found = []
    for m in _IMG_OBJ_RE.finditer(blob):
        objnum = int(m.group(1))
        header = m.group(3)
        if b"/Subtype" not in header or b"/Image" not in header:
            continue
        w, h = _dim(header, b"/Width"), _dim(header, b"/Height")
        if not w or not h or min(w, h) < _MIN_PIXELS:
            continue
        data = m.group(4)
        filt = b"/DCTDecode" if b"/DCTDecode" in header else (
            b"/FlateDecode" if b"/FlateDecode" in header else b"")
        report["candidates"] += 1
        page = page_of_obj.get(objnum)
        png = None
        if filt == b"/DCTDecode":
            png = _save(os.path.join(out_dir, f"fig-obj{objnum}.jpg"), data)
        elif filt == b"/FlateDecode":
            png = _wrap_flate(data, header, w, h,
                              os.path.join(out_dir, f"fig-obj{objnum}.png"))
        if png:
            found.append({"obj": objnum, "path": png, "w": w, "h": h, "page": page})
        if len(found) >= _MAX_KEEP:
            break

    # bind to captions: same page first, then nearest page, largest unused first
    used = set()
    assets = {}
    for cap in (inv.captions if inv else []):
        if cap.get("kind") != "figure":
            continue
        page = cap["seg"].get("page")
        pool = [f for f in found if f["obj"] not in used]
        if not pool:
            break
        pool.sort(key=lambda f: (abs((f["page"] or 0) - (page or 0)), -(f["w"] * f["h"])))
        exact = [f for f in pool if page and f["page"] == page]
        pick = (exact or pool)[0]
        if page and pick["page"] is not None and abs((pick["page"] or 0) - page) > 1:
            report["notes"].append(
                f"{cap['label']}: no image on page {page}; nearest is page {pick['page']}, "
                f"kept with that caveat")
        used.add(pick["obj"])
        assets[cap["label"]] = pick["path"]
        report["bound"][cap["label"]] = {
            "file": os.path.basename(pick["path"]), "page": pick["page"],
            "pixels": f"{pick['w']}x{pick['h']}",
            "sha256_16": sha256_bytes(open(pick["path"], "rb").read()),
        }
        if log:
            log(f"figure {cap['label']} <- {os.path.basename(pick['path'])} "
                f"({pick['w']}x{pick['h']}, page {pick['page']})")
    report["kept"] = len(found)
    if not assets and inv and getattr(inv, "captions", None):
        report["notes"].append("no embedded figure large enough to reuse; figure pages "
                               "will carry labelled schematic placeholders")
    return {"assets": assets, "report": report}


def _dim(header: bytes, key: bytes):
    m = re.search(key + rb"\s+(\d+)", header)
    return int(m.group(1)) if m else None


def _save(path: str, data: bytes):
    try:
        with open(path, "wb") as fh:
            fh.write(data)
        return path
    except OSError:
        return None


def _wrap_flate(data: bytes, header: bytes, w: int, h: int, path: str):
    try:
        raw = zlib.decompress(data)
    except Exception:
        return None
    colors = _dim(header, b"/Colors") or 1
    bpc = _dim(header, b"/BitsPerComponent") or 8
    if bpc != 8 or colors not in (1, 3, 4):
        return None
    expected = w * h * colors
    if len(raw) < expected:
        return None
    mode = {1: "L", 3: "RGB", 4: "CMYK"}[colors]
    try:
        from PIL import Image
        img = Image.frombytes(mode, (w, h), raw[:expected])
        if mode == "CMYK":
            img = img.convert("RGB")
        if any(_dim(header, k) for k in (b"/Decode", b"/SMask")):
            pass
        img.save(path)
        return path
    except Exception:
        return None


def _obj_page_map(blob: bytes) -> dict[int, int]:
    """object number -> 1-based page index it is referenced from."""
    pages = []
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", blob, re.S):
        body = m.group(3)
        if b"/Type" in body[:400] and b"/Page" in body[:400] and b"/Pages" not in body[:400]:
            pages.append((int(m.group(1)), body))
    mapping: dict[int, int] = {}
    for idx, (_num, body) in enumerate(pages, start=1):
        for ref in re.findall(rb"(\d+)\s+\d+\s+R", body):
            mapping.setdefault(int(ref), idx)
        xo = re.search(rb"/XObject\s*<<(.*?)>>", body, re.S)
        if xo:
            for ref in re.findall(rb"(\d+)\s+\d+\s+R", xo.group(1)):
                mapping[int(ref)] = idx
    return mapping
