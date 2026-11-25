#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest -- run the packaged skill end-to-end and write tests/selftest-report.json.

It drives the shipped entry point exactly as the evaluator would
(`ga_build.py <cmd> --input ... --work ... --output ...`), on the three bundled
**example** cases plus a set of degradation cases, and verifies the produced
files rather than trusting stdout.  `tests/ab-report.json` (skill vs. ablated
baseline) is produced by `tests/ab_harness.py`.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # keep the package free of __pycache__

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EXAMPLES = ROOT / "examples"
REPORT = ROOT / "tests" / "selftest-report.json"
ENTRY = SCRIPTS / "ga_build.py"

CASES = [
    {"id": "case-a-mechanism", "case_id": "example-a-mechanism", "kind": "text/mechanism",
     "ir": "figure-ir.example.json"},
    {"id": "case-b-results", "case_id": "example-b-results", "kind": "data/chart",
     "ir": "figure-ir.example.json"},
    {"id": "case-c-edit", "case_id": "example-c-edit", "kind": "edit/existing-svg",
     "ir": None, "ops": "edit-ops.example.json"},
]
CONTRACT_KEYS = ["case_id", "status", "editable_source", "export_artifact",
                 "content_map", "compliance_checks", "exceptions"]


def sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return ""


def run(args, timeout=180):
    t0 = time.time()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        res = subprocess.run([sys.executable] + args, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=timeout, env=env)
        out = res.stdout.decode("utf-8", "replace")
        code = res.returncode
    except subprocess.TimeoutExpired:
        out, code = "TIMEOUT", 124
    return {"code": code, "out": out, "seconds": round(time.time() - t0, 2)}


def png_ihdr(path):
    try:
        import struct
        data = Path(path).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
        return {"width": w, "height": h, "bit_depth": depth, "color_type": ctype}
    except Exception:
        return None


class Checks:
    def __init__(self):
        self.items = []

    def add(self, cid, case, category, ok, detail, command="", seconds=0.0):
        self.items.append({"id": cid, "case": case, "category": category,
                           "ok": bool(ok), "detail": detail, "command": command,
                           "seconds": round(seconds, 2)})
        print("%-4s %-34s %s" % ("PASS" if ok else "FAIL", cid, detail))

    def passed(self):
        return sum(1 for i in self.items if i["ok"])


def main():
    checks = Checks()
    tmp = Path(os.environ.get("GA_SELFTEST_TMP") or tempfile.mkdtemp(prefix="ga-selftest-"))
    tmp.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    for case in CASES:
        cid = case["id"]
        src = EXAMPLES / cid
        work = tmp / cid / "work"
        out = tmp / cid / "out"
        out2 = tmp / cid / "out2"
        for d in (work, out, out2):
            d.mkdir(parents=True, exist_ok=True)
        base = [str(ENTRY), "--input", str(src), "--work", str(work), "--output", str(out)]
        r0 = run([str(ENTRY), "init", "--input", str(src), "--work", str(work),
                  "--output", str(out)])
        checks.add("%s.init" % cid, cid, "smoke", r0["code"] == 0 and
                   (out / "result.json").exists(), "init exit=%s" % r0["code"],
                   "ga_build.py init", r0["seconds"])
        if case["ir"]:
            shutil.copyfile(src / case["ir"], work / "figure-ir.json")
        if case.get("ops"):
            r1 = run([str(ENTRY), "edit", "--input", str(src), "--work", str(work),
                      "--output", str(out), "--ops", str(src / case["ops"])])
            checks.add("%s.edit" % cid, cid, "smoke", "EDIT_OK" in r1["out"],
                       "edit exit=%s" % r1["code"], "ga_build.py edit", r1["seconds"])
            r4 = run([str(ENTRY), "selfcheck", "--input", str(src), "--work", str(work),
                      "--output", str(out)])
            checks.add("%s.selfcheck" % cid, cid, "gate", "SELFCHECK_OK" in r4["out"],
                       r4["out"].strip().splitlines()[0][:90],
                       "ga_build.py selfcheck", r4["seconds"])
            svg = out / "figure.svg"
            rec = {}
            try:
                rec = json.loads((out / "edit-record.json").read_text(encoding="utf-8"))
            except Exception:
                pass
            checks.add("%s.edit_record" % cid, cid, "gate",
                       len(rec.get("applied") or []) >= 2 and bool(rec.get("source_sha256")),
                       "applied=%d source_sha=%s" % (len(rec.get("applied") or []),
                                                     (rec.get("source_sha256") or "")[:12]),
                       "edit-record.json")
            checks.add("%s.untouched_preserved" % cid, cid, "gate",
                       (svg.read_text(encoding="utf-8").count("<text") >=
                        (src / "source-figure.svg").read_text(encoding="utf-8").count("<text")),
                       "编辑后 <text> 数量不少于原图", "figure.svg")
            continue
        r2 = run([str(ENTRY), "check", "--input", str(src), "--work", str(work),
                  "--output", str(out)])
        checks.add("%s.check" % cid, cid, "gate", "CHECK_OK" in r2["out"],
                   "check 末行 CHECK_OK" if "CHECK_OK" in r2["out"]
                   else r2["out"].strip().splitlines()[-1][:90],
                   "ga_build.py check", r2["seconds"])
        r3 = run([str(ENTRY), "build", "--input", str(src), "--work", str(work),
                  "--output", str(out), "--fast"])
        checks.add("%s.build" % cid, cid, "smoke", "BUILD_OK" in r3["out"] or
                   "BUILD_PARTIAL" in r3["out"], "build exit=%s" % r3["code"],
                   "ga_build.py build --fast", r3["seconds"])
        r4 = run([str(ENTRY), "selfcheck", "--input", str(src), "--work", str(work),
                  "--output", str(out)])
        checks.add("%s.selfcheck" % cid, cid, "gate", "SELFCHECK_OK" in r4["out"],
                   r4["out"].strip().splitlines()[0][:90],
                   "ga_build.py selfcheck", r4["seconds"])
        svg, png, pdf = out / "figure.svg", out / "figure.png", out / "figure.pdf"
        checks.add("%s.artifacts" % cid, cid, "artifact", all(
            p.exists() and p.stat().st_size > 500 for p in (svg, png, pdf)),
            "svg=%s png=%s pdf=%s bytes" % (
                svg.stat().st_size if svg.exists() else 0,
                png.stat().st_size if png.exists() else 0,
                pdf.stat().st_size if pdf.exists() else 0),
            "ls /app/output")
        txt = svg.read_text(encoding="utf-8") if svg.exists() else ""
        checks.add("%s.editable_svg" % cid, cid, "artifact",
                   "<text" in txt and '<g id="layer-' in txt,
                   "text=%d groups=%d" % (txt.count("<text"),
                                          txt.count('<g id="layer-')),
                   "figure.svg")
        res = {}
        try:
            res = json.loads((out / "result.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        missing = [k for k in CONTRACT_KEYS if k not in res]
        checks.add("%s.contract" % cid, cid, "contract", not missing,
                   "缺失键=%s" % (missing or "无"), "result.json")
        checks.add("%s.case_id" % cid, cid, "contract",
                   str(res.get("case_id", "")) == case["case_id"],
                   "case_id=%s" % res.get("case_id"), "result.json")
        exp = ((res.get("export_artifact") or {}).get("png") or {})
        ihdr = png_ihdr(png) if png.exists() else None
        canvas = ((res.get("editable_source") or {}).get("layers") and
                  ((res.get("export_artifact") or {}).get("png") or {}).get("width"),)
        checks.add("%s.png_real" % cid, cid, "artifact",
                   bool(ihdr) and ihdr["width"] == exp.get("width"),
                   "IHDR=%s 声明=%s" % (ihdr, exp.get("width")), "figure.png")
        pdf_bytes = pdf.read_bytes()[:8] if pdf.exists() else b""
        checks.add("%s.pdf_real" % cid, cid, "artifact", pdf_bytes.startswith(b"%PDF-"),
                   "header=%s pages=%s" % (pdf_bytes.decode("latin-1", "replace"),
                                           ((res.get("export_artifact") or {}).get("pdf") or {}).get("pages")),
                   "figure.pdf")
        fails = [c for c in (res.get("compliance_checks") or []) if c.get("verdict") == "fail"]
        checks.add("%s.compliance" % cid, cid, "gate", not fails,
                   "fail项=%s" % ([c["check"] for c in fails] or "无"), "result.json")
        # determinism: second run into out2 must give an identical SVG
        r5 = run([str(ENTRY), "build", "--input", str(src), "--work", str(work),
                  "--output", str(out2), "--fast"])
        same = sha(out / "figure.svg") == sha(out2 / "figure.svg") and sha(out / "figure.svg") != ""
        checks.add("%s.deterministic" % cid, cid, "gate", same,
                   "两跑 svg sha256 %s" % ("一致" if same else "不一致"),
                   "ga_build.py build x2", r5["seconds"])

    # ---- degradation: empty input -------------------------------------------------
    empty = tmp / "empty-input"
    empty.mkdir(parents=True, exist_ok=True)
    work = tmp / "empty" / "work"
    out = tmp / "empty" / "out"
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    r = run([str(ENTRY), "build", "--input", str(empty), "--work", str(work),
             "--output", str(out), "--fast"])
    ok = r["code"] == 0 and (out / "result.json").exists()
    try:
        res = json.loads((out / "result.json").read_text(encoding="utf-8"))
        ok = ok and res.get("status") in ("partial", "insufficient_evidence", "input_error")
    except Exception:
        ok = False
    checks.add("degrade.empty_input", "-", "degrade", ok,
               "exit=%s status=%s" % (r["code"], res.get("status")), "ga_build.py build",
               r["seconds"])

    # ---- degradation: broken case.json -------------------------------------------
    broken = tmp / "broken-input"
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "case.json").write_text("{ this is not json ", encoding="utf-8")
    (broken / "material.md").write_text("# note\n\nSome material text for indexing.\n",
                                        encoding="utf-8")
    work = tmp / "broken" / "work"
    out = tmp / "broken" / "out"
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    r = run([str(ENTRY), "init", "--input", str(broken), "--work", str(work),
             "--output", str(out)])
    r2 = run([str(ENTRY), "build", "--input", str(broken), "--work", str(work),
              "--output", str(out), "--fast"])
    try:
        res = json.loads((out / "result.json").read_text(encoding="utf-8"))
        ok = r["code"] == 0 and r2["code"] == 0 and isinstance(res, dict)
    except Exception:
        ok = False
    checks.add("degrade.broken_json", "-", "degrade", ok,
               "init=%s build=%s" % (r["code"], r2["code"]), "ga_build.py init/build",
               r["seconds"] + r2["seconds"])

    # ---- stress: overlong text on a small canvas must repair, not crash ------------
    stress = tmp / "stress-input"
    stress.mkdir(parents=True, exist_ok=True)
    long_text = ("This bullet is deliberately far longer than any sane panel width so the "
                 "layout ladder has to drop, tighten, shrink or elide it. ") * 6
    ir = {
        "case_id": "stress-overflow", "origin": "curated",
        "title": "Overflow stress case with a very long heading that must still fit",
        "canvas": {"width_px": 900, "height_px": 520, "dpi": 150, "min_font_px": 20},
        "panels": [{"order": i + 1, "role": r, "title": "T", "claim": long_text[:120],
                    "kind": "bullets",
                    "items": [{"id": "s%di%d" % (i + 1, j), "text": long_text,
                               "source": {"id": "S1", "locator": "material.md#para1",
                                          "quote": "Some material text for indexing"}}
                              for j in range(6)]}
                   for i, r in enumerate(["problem", "method", "results", "conclusion"])],
        "sources": [{"id": "S1", "path": "material.md", "locator": "material.md#para1",
                     "quote": "Some material text for indexing"}],
        "notes": {"units": "u", "caption": "stress", "figure_no": "Figure S1"},
    }
    (stress / "material.md").write_text("# note\n\nSome material text for indexing.\n",
                                        encoding="utf-8")
    (stress / "case.json").write_text('{"case_id":"stress-overflow"}', encoding="utf-8")
    work = tmp / "stress" / "work"
    out = tmp / "stress" / "out"
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    (work / "figure-ir.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    run([str(ENTRY), "init", "--input", str(stress), "--work", str(work), "--output", str(out)])
    r = run([str(ENTRY), "build", "--input", str(stress), "--work", str(work),
             "--output", str(out), "--fast"])
    try:
        res = json.loads((out / "result.json").read_text(encoding="utf-8"))
        panels = res.get("invariants", {}).get("panels", [])
        dropped = sum(len(p.get("dropped") or []) for p in panels)
        overflow_check = [c for c in (res.get("compliance_checks") or [])
                          if c.get("check") == "no_canvas_overflow"]
        no_overflow = bool(overflow_check) and overflow_check[0].get("verdict") != "fail"
        ok = (r["code"] == 0 and (out / "figure.svg").exists() and
              bool(res.get("exceptions")) and no_overflow)
        detail = "exit=%s 修复/异常记录=%d 丢弃条目=%d 越界闸=%s" % (
            r["code"], len(res.get("exceptions") or []), dropped,
            overflow_check[0].get("verdict") if overflow_check else "n/a")
    except Exception as exc:
        ok, detail = False, "异常 %s" % exc
    checks.add("stress.overflow_repair", "-", "stress", ok, detail,
               "ga_build.py build (900x520, 长文本)", r["seconds"])

    # ---- fallback engines: exercised in-process so the claim is verified ----------
    sys.path.insert(0, str(SCRIPTS))
    try:
        import ga_core as _C
        import layout as _L
        import render_pdf as _RP
        import render_png as _PNG
        _ir = _C.normalize_ir(json.loads(
            (EXAMPLES / "case-a-mechanism" / "figure-ir.example.json").read_text(encoding="utf-8")),
            "example-a-mechanism")
        _scene = _L.build_scene(_ir)
        _p = tmp / "fallback"
        _p.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        _eng = _RP._write_stdlib_pdf(_scene, _p / "stdlib.pdf")
        _info = _RP.pdf_info(_p / "stdlib.pdf")
        checks.add("fallback.stdlib_pdf", "-", "fallback",
                   bool(_info) and _info["pages"] >= 1 and _info["bytes"] > 4000,
                   "engine=%s pages=%s bytes=%s vector=%s" % (
                       _eng, _info and _info["pages"], _info and _info["bytes"],
                       _info and _info["vector"]), "render_pdf._write_stdlib_pdf",
                   time.time() - t0)
        t0 = time.time()
        _eng2 = _PNG._via_stdlib(_scene, _p / "stdlib.png", 1.0)
        _ihdr = png_ihdr(_p / "stdlib.png")
        _ink = _PNG._nonwhite_ratio(_p / "stdlib.png")
        checks.add("fallback.stdlib_png", "-", "fallback",
                   _eng2 == "stdlib" and bool(_ihdr) and _ihdr["width"] == 2400 and
                   (_ink or 0) > 0.01,
                   "engine=%s %sx%s ink=%s" % (_eng2, _ihdr and _ihdr["width"],
                                               _ihdr and _ihdr["height"], _ink),
                   "render_png._via_stdlib", time.time() - t0)
    except Exception as exc:
        checks.add("fallback.stdlib_pdf", "-", "fallback", False, "异常 %s" % exc)
        checks.add("fallback.stdlib_png", "-", "fallback", False, "异常 %s" % exc)

    # ---- environment facts ---------------------------------------------------------
    engines = []
    for mod, want in (("cairosvg", "cairosvg"), ("fitz", "pymupdf"), ("PIL", "pillow"),
                      ("matplotlib", "matplotlib"), ("playwright", "playwright")):
        try:
            __import__(mod)
            engines.append(want)
        except Exception:
            pass
    try:
        import fonts  # noqa
        frep = fonts.discover(needs_cjk=True)
    except Exception as exc:
        frep = {"error": str(exc)}
    env_facts = {"python": sys.version.split()[0], "platform": platform.platform(),
                 "optional_engines": engines,
                 "font_sans_file": Path(frep.get("sans") or "").name,
                 "font_cjk_capable": frep.get("sans_cjk_capable"),
                 "font_source": frep.get("source"),
                 "sandbox": "临时目录（路径不入包）"}

    total = len(checks.items)
    passed = checks.passed()
    report = {
        "generated_by": "tests/selftest.py",
        "skill_version": (ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()[0] if
                         (ROOT / "SKILL.md").exists() else "",
        "environment": env_facts,
        "cases": [c["id"] for c in CASES],
        "checks": checks.items,
        "totals": {"checks": total, "passed": passed, "failed": total - passed,
                   "seconds": round(time.time() - t_start, 2)},
        "verdict": "pass" if passed == total else "fail",
        "notes": ["全部命令以子进程方式调用真实入口 ga_build.py，并回读产出文件核验；",
                  "示例案例为包内自带示例（标「示例」），非组织方固定案例；",
                  "deterministic 检查对同一 IR 重跑两次并比较 figure.svg 的 sha256。"],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("\nSELFTEST %s  %d/%d passed  %.1fs  -> %s" %
          (report["verdict"].upper(), passed, total, report["totals"]["seconds"], REPORT))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())





