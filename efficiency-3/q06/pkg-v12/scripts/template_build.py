"""template_build.py - synthesise a master/layout .pptx from a declarative spec.

The package ships text, not binaries, so the demo template is *generated*:

    python3 scripts/template_build.py --spec templates/template-spec.example.json \\
                                      --out work/case_zh_md/group-template.pptx

``deck.py`` then treats that file exactly like an organiser-supplied template:
it opens it, keeps the theme, reuses the layouts by name, and only resizes
placeholders.  This is the same code path a real case template takes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True  # keep the submitted tree clean

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


def build(spec: dict, out_path: str) -> str:
    prs = Presentation()
    size = spec.get("slide_size_in") or {"w": 13.333, "h": 7.5}
    prs.slide_width = Inches(size["w"])
    prs.slide_height = Inches(size["h"])
    theme = spec.get("theme") or {}
    accent = theme.get("accent") or "1F4E79"

    # --- master background: a very light tint, so the deck visibly inherits a look
    master = prs.slide_masters[0]
    try:
        from pptx.dml.color import RGBColor as _RGB
        master.background.fill.solid()
        master.background.fill.fore_color.rgb = _RGB(0xFA, 0xFB, 0xFD)
    except Exception:
        pass

    # --- layouts get their names rewritten so deck.py can match by role
    names = spec.get("layout_names") or {}
    for idx, name in names.items():
        try:
            prs.slide_layouts[int(idx)].name = name
        except (IndexError, ValueError):
            continue

    # --- title layout: a wide title band, still using real placeholders
    title_layout = prs.slide_layouts[0]
    for ph in list(title_layout.placeholders):
        idx = ph.placeholder_format.idx
        try:
            if idx == 0:
                ph.left, ph.top = Inches(0.78), Inches(1.55)
                ph.width, ph.height = Inches(11.7), Inches(1.7)
            elif idx == 1:
                ph.left, ph.top = Inches(0.78), Inches(3.35)
                ph.width, ph.height = Inches(11.7), Inches(0.8)
        except Exception:
            pass

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    prs.save(out_path)
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.spec, "r", encoding="utf-8-sig") as fh:
        spec = json.load(fh)
    print("wrote", build(spec, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
