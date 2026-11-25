#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fit.py —— **零附加参数入口**（D14-R1）：

    python3 scripts/fit.py --case /input/case.json --out /app/output

只做参数转发：真正的流水线在 run.py（模板解析/合成 → 材料抽取 → 页级计划 → 套版生成 →
静态复核 → 真渲染回测 → result.json）。模板一律由文本规格在**运行期合成**（包内零二进制）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run as pipeline  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fit")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "powerpoint", "soffice", "none"])
    ap.add_argument("--work")
    ap.add_argument("--template")
    ap.add_argument("--plan")
    ap.add_argument("--iterations", type=int, default=2)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--narrative")
    ap.add_argument("--no-render", action="store_true", help="等价 --backend none（最快）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    backend = "none" if a.no_render else a.backend
    fwd = ["--input", a.case, "--out", a.out, "--backend", backend,
           "--iterations", str(a.iterations)]
    for flag, val in (("--work", a.work), ("--template", a.template), ("--plan", a.plan),
                      ("--narrative", a.narrative)):
        if val:
            fwd += [flag, val]
    if a.baseline:
        fwd.append("--baseline")
    if a.quiet:
        fwd.append("--quiet")
    return pipeline.main(fwd)


if __name__ == "__main__":
    sys.exit(main())
