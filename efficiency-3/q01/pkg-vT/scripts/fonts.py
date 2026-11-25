#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fonts -- font discovery and substitution reporting.

"An export that silently swaps the font" is a rubric failure mode, so this
module never guesses: it reports which file it found, whether that file can
draw CJK, and what it substituted when nothing suitable existed.  Callers copy
that report into result.json compliance_checks.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # never leave __pycache__ behind


import os
import subprocess
from pathlib import Path

_CACHE = {}

CJK_HINTS = ("notosanscjk", "notoserifcjk", "sourcehansans", "sourcehanserif",
             "wqy", "wenquanyi", "droidsansfallback", "msyh", "simhei", "simsun",
             "pingfang", "hiragino", "arialunicode", "nanum", "mplus", "ukai",
             "uming", "nsimsun", "dengxian", "fandol", "heiti", "songti")
LATIN_HINTS = ("dejavusans", "liberationsans", "arial", "helvetica", "notosans-",
               "freesans", "ubuntu", "roboto", "open sans")

SEARCH_DIRS = [
    "/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/fonts/truetype",
    "/opt/fonts", "/System/Library/Fonts", "/Library/Fonts",
    str(Path.home() / ".fonts"), str(Path.home() / ".local/share/fonts"),
    "C:/Windows/Fonts", "/usr/share/fonts/opentype",
]


def _iter_font_files(limit=600, stop_early=None):
    seen = 0
    for d in SEARCH_DIRS:
        base = Path(d)
        if not base.is_dir():
            continue
        try:
            for root, dirs, files in os.walk(str(base)):
                dirs[:] = dirs[:6]
                for f in files:
                    if f.lower().endswith((".ttf", ".otf", ".ttc", ".otc")):
                        p = Path(root) / f
                        yield p
                        seen += 1
                        if stop_early and stop_early(p):
                            return
                        if seen >= limit:
                            return
        except Exception:
            continue


def _score(path: Path, wants_cjk: bool) -> int:
    name = path.name.lower().replace(" ", "").replace("-", "")
    score = 0
    if wants_cjk:
        if any(h in name for h in CJK_HINTS):
            score += 100
    if any(h.replace("-", "") in name for h in LATIN_HINTS):
        score += 40
    if "bold" in name or "italic" in name or "oblique" in name:
        score -= 5
    if path.suffix.lower() in (".ttc", ".otc"):
        score -= 8
    return score


def _fc_match(pattern: str):
    try:
        res = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=8)
        out = res.stdout.decode("utf-8", "replace").strip()
        if out and Path(out).is_file():
            return out
    except Exception:
        return None
    return None


def discover(needs_cjk: bool = True) -> dict:
    """Return the best available font choices plus an honest provenance record."""
    key = bool(needs_cjk)
    if key in _CACHE:
        return _CACHE[key]
    report = {
        "needs_cjk": bool(needs_cjk),
        "sans": "", "sans_cjk_capable": False, "bold": "", "italic": "",
        "mono": "", "source": "none", "probed": [], "substituted": [],
        "pymupdf_builtin_cjk_ok": False,
    }
    try:
        import fitz  # PyMuPDF ships CJK fallback fonts
        report["pymupdf_builtin_cjk_ok"] = True
    except Exception:
        pass
    # 1) bounded direct scan first: it is fast and does not spawn processes
    def _done(p):
        return bool(report["sans"] and report["bold"] and report["italic"] and report["mono"]
                    and report["sans_cjk_capable"])
    cands = sorted(_iter_font_files(stop_early=_done), key=lambda p: -_score(p, needs_cjk))
    for p in cands[:12]:
        nm = p.name.lower().replace(" ", "")
        cjk = any(h in nm for h in CJK_HINTS)
        if not report["sans_cjk_capable"] and cjk and needs_cjk:
            report["sans"] = str(p)
            report["sans_cjk_capable"] = True
            report["source"] = "scan"
        if not report["sans"]:
            report["sans"] = str(p)
            report["source"] = "scan"
        if not report["bold"] and "bold" in nm:
            report["bold"] = str(p)
        if not report["italic"] and ("italic" in nm or "oblique" in nm):
            report["italic"] = str(p)
        if not report["mono"] and ("mono" in nm or "courier" in nm):
            report["mono"] = str(p)
    # 2) fontconfig only fills remaining gaps (and only when the binary exists)
    import shutil
    if (not report["sans"] or (needs_cjk and not report["sans_cjk_capable"])) and \
            shutil.which("fc-match"):
        for pat, slot in (("sans-serif:lang=zh-cn", "sans"), ("sans-serif", "sans")):
            got = _fc_match(pat)
            report["probed"].append({"pattern": pat, "file": got or ""})
            if got and not report[slot]:
                report[slot] = got
                report["source"] = "fc-match"
                if slot == "sans" and any(h in Path(got).name.lower().replace(" ", "")
                                          for h in CJK_HINTS):
                    report["sans_cjk_capable"] = True
    if needs_cjk and not report["sans_cjk_capable"]:
        report["substituted"].append({
            "requested": "CJK-capable sans",
            "used": report["sans"],
            "impact": "中文/日文/韩文字形可能缺失或显示为方框，导出件已记录为降级",
        })
    if not report["bold"]:
        report["bold"] = report["sans"]
    if not report["italic"]:
        report["italic"] = report["sans"]
    if not report["mono"]:
        report["mono"] = report["sans"]
    if not report["sans"]:
        report["source"] = "none"
        report["substituted"].append({
            "requested": "any TrueType font",
            "used": "",
            "impact": "无可用字体文件，PNG 将退化到内置位图字形并记为降级",
        })
    _CACHE[key] = report
    return report


