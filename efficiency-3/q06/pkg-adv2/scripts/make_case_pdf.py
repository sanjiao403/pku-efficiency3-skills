"""make_case_pdf.py - build a paper-like PDF fixture (text layer + figure + table).

    python3 scripts/make_case_pdf.py --src examples/case_en_pdf/paper.src.json \
                                     --out work/case_en_pdf/paper.pdf

The package ships only *text*; a PDF input is generated on demand so that the
PDF reader, the figure harvester and the evidence lock can all be exercised on a
real file.  The generated paper is clearly synthetic (its own footer says so) and
is **not** a prepared answer to any evaluation case.
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

import pdf_lite


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="paper source JSON (see examples/)")
    ap.add_argument("--out", required=True, help="destination .pdf")
    ap.add_argument("--footer", default="synthetic fixture - not a prepared answer")
    args = ap.parse_args(argv)
    with open(args.src, "r", encoding="utf-8-sig") as fh:
        doc = json.load(fh)
    doc["footer"] = doc.get("footer") or args.footer
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    pdf_lite.write_pdf_paper(args.out, doc)
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
