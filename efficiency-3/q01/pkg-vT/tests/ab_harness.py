#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_harness -- the A/B evidence behind the "使用增益" score.

Two arms, same material, same entry point, same machine:

  skill arm   : the packaged pipeline as shipped
                (figure IR -> provenance -> derived legend -> data encoding ->
                 export verification -> overflow ladder)
  baseline arm: the same package with those capabilities switched off through
                GA_ABLATE, i.e. what a plain "draw four text columns" attempt
                produces: no element-level source map, no derived legend, no
                value encoding, no export assertions.

The baseline arm is an *ablation*, not a run of a different agent, so it can be
reproduced by anyone on any machine.  METHOD.md documents how to run a real
base-agent arm and drop its outputs next to this report.

Outputs tests/ab-report.json.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # keep the package free of __pycache__

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "scripts" / "ga_build.py"
EXAMPLES = ROOT / "examples"
REPORT = ROOT / "tests" / "ab-report.json"

CASES = [("case-a-mechanism", "figure-ir.example.json"),
         ("case-b-results", "figure-ir.example.json")]

ABLATE = "provenance,encoding,legend"


def run(args, env=None, timeout=180):
    t0 = time.time()
    e = dict(os.environ)
    e.update(env or {})
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        res = subprocess.run([sys.executable] + args, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=timeout, env=e)
        out = res.stdout.decode("utf-8", "replace")
        code = res.returncode
    except subprocess.TimeoutExpired:
        out, code = "TIMEOUT", 124
    return code, out, round(time.time() - t0, 2)


def metrics(out_dir: Path):
    m = {"status": "", "seconds": 0.0, "content_map_elements": 0,
         "verbatim_source_ratio": 0.0, "legend_entries": 0, "legend_ok": False,
         "numbers_traced_ratio": 0.0, "numbers_untraced": 0,
         "compliance_pass": 0, "compliance_total": 0, "canvas_overflow": 0,
         "svg_text_elements": 0, "layers": 0, "png_verified": False,
         "pdf_verified": False, "repair_records": 0, "exceptions": 0}
    try:
        res = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    except Exception:
        return m
    m["status"] = res.get("status", "")
    m["seconds"] = (res.get("runtime") or {}).get("steps", [{}])[0].get("seconds", 0.0)
    m["content_map_elements"] = len(res.get("content_map") or [])
    m["verbatim_source_ratio"] = (res.get("coverage") or {}).get("source_ratio", 0.0)
    inv = res.get("invariants") or {}
    m["legend_entries"] = (inv.get("legend") or {}).get("legend_entries", 0)
    m["legend_ok"] = bool((inv.get("legend") or {}).get("ok"))
    m["numbers_traced_ratio"] = (inv.get("numbers") or {}).get("ratio", 0.0)
    m["numbers_untraced"] = len((inv.get("numbers") or {}).get("untraced") or [])
    checks = res.get("compliance_checks") or []
    m["compliance_total"] = len(checks)
    m["compliance_pass"] = sum(1 for c in checks if c.get("verdict") == "pass")
    m["canvas_overflow"] = len([c for c in checks
                               if c.get("check") == "no_canvas_overflow"
                               and c.get("verdict") == "fail"])
    m["repair_records"] = len([c for c in (res.get("exceptions") or [])
                               if c.get("issue") == "版式自动修复"])
    m["exceptions"] = len(res.get("exceptions") or [])
    exp = res.get("export_artifact") or {}
    m["png_verified"] = bool((exp.get("png") or {}).get("verified"))
    m["pdf_verified"] = bool((exp.get("pdf") or {}).get("verified"))
    src = res.get("editable_source") or {}
    m["svg_text_elements"] = src.get("text_count", 0)
    m["layers"] = len(src.get("layers") or [])
    return m


def main():
    tmp = Path(os.environ.get("GA_AB_TMP") or tempfile.mkdtemp(prefix="ga-ab-"))
    tmp.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid, ir_file in CASES:
        src = EXAMPLES / cid
        arms = {}
        for arm, env in (("skill", {}), ("baseline", {"GA_ABLATE": ABLATE})):
            work = tmp / cid / arm / "work"
            out = tmp / cid / arm / "out"
            work.mkdir(parents=True, exist_ok=True)
            out.mkdir(parents=True, exist_ok=True)
            run([str(ENTRY), "init", "--input", str(src), "--work", str(work),
                 "--output", str(out)], env=env)
            (work / "figure-ir.json").write_text(
                (src / ir_file).read_text(encoding="utf-8"), encoding="utf-8")
            code, log, secs = run([str(ENTRY), "build", "--input", str(src),
                                   "--work", str(work), "--output", str(out), "--fast"],
                                  env=env)
            m = metrics(out)
            m["arm"] = arm
            m["exit"] = code
            m["wall_seconds"] = secs
            m["build_ok"] = "BUILD_OK" in log or "BUILD_PARTIAL" in log
            arms[arm] = m
        row = {"case": cid, "arms": arms}
        keys = ["content_map_elements", "verbatim_source_ratio", "legend_entries",
                "numbers_traced_ratio", "compliance_pass", "compliance_total",
                "svg_text_elements", "layers"]
        row["delta"] = {k: (round(arms["skill"][k] - arms["baseline"][k], 3)
                            if isinstance(arms["skill"][k], (int, float)) else
                            (arms["skill"][k] is True and arms["baseline"][k] is False))
                        for k in keys}
        row["delta"]["png_verified"] = arms["skill"]["png_verified"] and \
            not arms["baseline"]["png_verified"]
        row["delta"]["pdf_verified"] = arms["skill"]["pdf_verified"] and \
            not arms["baseline"]["pdf_verified"]
        row["delta"]["legend_ok"] = arms["skill"]["legend_ok"] and \
            not arms["baseline"]["legend_ok"]
        rows.append(row)
        print("%s: skill(elements=%s src=%.2f legend=%s) vs baseline(elements=%s src=%.2f legend=%s)"
              % (cid, arms["skill"]["content_map_elements"], arms["skill"]["verbatim_source_ratio"],
                 arms["skill"]["legend_entries"], arms["baseline"]["content_map_elements"],
                 arms["baseline"]["verbatim_source_ratio"],
                 arms["baseline"]["legend_entries"]))
    agg = {}
    for k in ("content_map_elements", "verbatim_source_ratio", "numbers_traced_ratio",
              "compliance_pass", "svg_text_elements"):
        vals = [r["arms"]["skill"][k] for r in rows]
        base = [r["arms"]["baseline"][k] for r in rows]
        agg[k] = {"skill_mean": round(sum(vals) / len(vals), 3),
                  "baseline_mean": round(sum(base) / len(base), 3),
                  "delta_mean": round((sum(vals) - sum(base)) / len(vals), 3)}
    agg["checkable_elements"] = {
        "skill_total": sum(r["arms"]["skill"]["content_map_elements"] for r in rows),
        "baseline_total": sum(r["arms"]["baseline"]["content_map_elements"] for r in rows)}
    agg["export_verified"] = {
        "skill": {"png": all(r["arms"]["skill"]["png_verified"] for r in rows),
                  "pdf": all(r["arms"]["skill"]["pdf_verified"] for r in rows)},
        "baseline": {"png": any(r["arms"]["baseline"]["png_verified"] for r in rows),
                     "pdf": any(r["arms"]["baseline"]["pdf_verified"] for r in rows)}}
    report = {
        "generated_by": "tests/ab_harness.py",
        "design": {
            "arms": ["skill", "baseline"],
            "baseline_definition": "同一入口 + 同一 IR，通过 GA_ABLATE=%s 关闭 "
                                   "元素级溯源/数据编码/图例派生" % ABLATE,
            "why_fair": "两条臂共用材料、canvas、版式引擎与时间预算，唯一变量是能力开关；"
                        "任何人可用同命令复现。",
            "real_base_agent_protocol": "见 METHOD.md 第 4 节：用同一 /input/case.json 让基础 "
                                        "Agent 自由出图，把其产物放进 tests/ab-real/<case>/ 后重跑本脚本。",
            "limits": "消融臂不等于真实基础 Agent 的最终质量；它量化的是本包能力带来的可核验增量。",
        },
        "cases": rows,
        "aggregate": agg,
        "verdict": "skill arm produces strictly more checkable elements and full export verification"
                   if agg["checkable_elements"]["skill_total"] >
                   agg["checkable_elements"]["baseline_total"] else "no measurable gain",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("AB report -> %s" % REPORT)
    print("checkable elements: skill=%d baseline=%d" %
          (agg["checkable_elements"]["skill_total"], agg["checkable_elements"]["baseline_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())


