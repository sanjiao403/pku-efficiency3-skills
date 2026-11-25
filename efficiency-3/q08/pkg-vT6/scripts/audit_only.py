#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_only.py —— **只读产物**的独立审计器（D14-R3）。

它不重新生成任何东西：只读 `<out>/result.json` 与 `<out>/*.pptx`（以及可选 `preview/deck.pdf`），
把 result.json 里**自述的**指标与**重算出来的**实测值逐项对照（expected vs actual），
输出 pass/fail 清单。用途：换个进程/换个人也能验证"自述是否与产物一致"。

    python3 scripts/audit_only.py --out /app/output [--template-map out/template_map.json]
                                 [--source out/source_map.json] [--json audit.json]
退出码：0 全绿 / 4 有 high 级不一致 / 2 用法或文件缺失。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pptx_util as U  # noqa: E402
import units  # noqa: E402


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def schema_errors(res: dict, schema: dict, path: str = "") -> list:
    """零第三方依赖的 JSON Schema 子集校验器（type/required/enum/pattern/minimum/maximum/
    minLength/items/properties）。只实现本包 schema 用到的关键字，够用且不引依赖。"""
    errs = []

    def typ_ok(v, t):
        return {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
                "boolean": bool, "null": type(None)}.get(t) and isinstance(
                    v, {"object": dict, "array": list, "string": str, "integer": int,
                        "number": (int, float), "boolean": bool, "null": type(None)}[t]) and \
            not (t in ("integer", "number") and isinstance(v, bool))

    t = schema.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(typ_ok(res, x) for x in ts):
            return ["%s: 类型应为 %s，实为 %s" % (path or "<root>", ts, type(res).__name__)]
    if isinstance(res, dict):
        for k in schema.get("required") or []:
            if k not in res:
                errs.append("%s.%s 缺失（契约要求必填，产不出应写 null）" % (path, k))
        for k, sub in (schema.get("properties") or {}).items():
            if k in res:
                errs += schema_errors(res[k], sub, ("%s.%s" % (path, k)).lstrip("."))
    if isinstance(res, list) and schema.get("items"):
        for i, v in enumerate(res[:50]):
            errs += schema_errors(v, schema["items"], "%s[%d]" % (path, i))
    if isinstance(res, str):
        if schema.get("minLength") and len(res) < schema["minLength"]:
            errs.append("%s: 长度 < %d" % (path, schema["minLength"]))
        if schema.get("pattern") and not re.match(schema["pattern"], res):
            errs.append("%s: 不匹配 %s" % (path, schema["pattern"]))
    if isinstance(res, (int, float)) and not isinstance(res, bool):
        if schema.get("minimum") is not None and res < schema["minimum"]:
            errs.append("%s: %s < %s" % (path, res, schema["minimum"]))
        if schema.get("maximum") is not None and res > schema["maximum"]:
            errs.append("%s: %s > %s" % (path, res, schema["maximum"]))
    if schema.get("enum") is not None and res not in schema["enum"]:
        errs.append("%s: %r 不在 %s" % (path, res, schema["enum"]))
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="audit_only")
    ap.add_argument("--out", required=True, help="产物目录（含 result.json 与 pptx）")
    ap.add_argument("--pptx", help="显式指定 pptx（默认取 result.outputs/artifacts 里的那份）")
    ap.add_argument("--template-map")
    ap.add_argument("--source")
    ap.add_argument("--json", help="把对照表写到该路径")
    ap.add_argument("--check-schema", action="store_true",
                    help="按 references/result.schema.json 校验 result.json（只读，零依赖）")
    a = ap.parse_args(argv)
    rj = os.path.join(a.out, "result.json")
    if not os.path.isfile(rj):
        print("audit_only: 缺 %s" % rj)
        return 2
    res = load(rj)
    if a.check_schema:
        sp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "references", "result.schema.json")
        if not os.path.isfile(sp):
            print("audit_only: 缺 %s" % sp)
            return 2
        errs = schema_errors(res, load(sp))
        rep = {"check": "result.schema.json", "schema": os.path.basename(sp),
               "case_id": res.get("case_id"), "errors": errs[:40], "error_count": len(errs),
               "ok": not errs}
        print("audit_only(schema): %s 校验 %s → %s（%d 个问题）" % (
            os.path.basename(rj), os.path.basename(sp), "PASS" if rep["ok"] else "FAIL", len(errs)))
        for e in errs[:10]:
            print("  - " + e)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=2)
        return 0 if rep["ok"] else 5
    rows = []

    def chk(name, exp, act, sev="high", note=""):
        ok = (exp == act) if not isinstance(exp, (int, float)) or isinstance(exp, bool) else \
            (act is not None and abs(float(act) - float(exp)) <= max(1e-6, abs(float(exp)) * .02))
        rows.append({"item": name, "expected": exp, "actual": act, "pass": bool(ok),
                     "severity": sev, "note": note})
        return ok

    # 定位 pptx
    pptx = a.pptx
    if not pptx:
        for cand in (res.get("outputs") or []) + (res.get("artifacts") or []):
            if isinstance(cand, dict) and str(cand.get("path", "")).lower().endswith(".pptx"):
                p = os.path.join(a.out, os.path.basename(cand["path"]))
                if os.path.isfile(p):
                    pptx = p
                    break
    if not pptx or not os.path.isfile(pptx):
        print("audit_only: 找不到 ppyts/pptx 产物")
        return 2
    prs = U.load(pptx)
    themes = U.theme_info(pptx)

    # ---- 重算：页数 / 版式数 / 主题字体 / 每页占位符几何继承 / 字号
    n_slides = len(prs.slides)
    n_layouts = len(prs.slide_layouts)
    tm = load(a.template_map) if a.template_map and os.path.isfile(a.template_map) \
        else (load(os.path.join(a.out, "template_map.json"))
              if os.path.isfile(os.path.join(a.out, "template_map.json")) else None)
    reported = ((res.get("results") or {}).get("template") or {})
    chk("pptx 可打开", True, True)
    chk("页数（result.slides vs 实际）", len(res.get("slides") or []), n_slides)
    if tm:
        chk("版式数（模板 vs 产物）", tm.get("layout_count"), n_layouts,
            note="版式数量不变 = 版式继承链未被破坏")
        chk("主题字体（模板 vs 产物）", tm.get("theme_fonts"), themes.get("fonts"),
            sev="medium", note="字体方案被改动会影响排版一致性")
    if reported.get("slide_size") and prs.slide_width:
        chk("画幅宽(in)", reported["slide_size"].get("width_in"),
            round(units.inches(prs.slide_width), 3), sev="medium")

    geom_written = 0
    min_pt = None
    for slide in prs.slides:
        for sh in slide.shapes:
            kind = U.ph_kind(sh) if sh.is_placeholder else "textbox"
            is_body = kind in ("body", "object") or sh.name.startswith("SynthBody") \
                or sh.name.startswith("TextBox")
            if sh.has_text_frame and sh.text_frame.text.strip() and is_body:
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        if r.font.size is not None:
                            pt = r.font.size.pt
                            min_pt = pt if min_pt is None else min(min_pt, pt)
            if sh.is_placeholder:
                spPr = sh._element.find(U.qn("p:spPr")) if hasattr(U, "qn") else None
                if spPr is not None and spPr.find(U.qn("a:xfrm")) is not None:
                    geom_written += 1
    chk("占位符未写死几何（a:xfrm 数）", 0, geom_written,
        note="0 = 坐标来自版式继承，而不是被复制成硬编码坐标")
    fit_metrics = ((res.get("results") or {}).get("fit") or {}).get("metrics") or {}
    if min_pt is not None and fit_metrics.get("min_body_pt") is not None:
        chk("正文最小字号(重算 vs 自述)", fit_metrics["min_body_pt"], round(min_pt, 1),
            sev="medium")

    # ---- 引文回源：用 source_map 重算 evidence[].verified
    sm = load(a.source) if a.source and os.path.isfile(a.source) \
        else (load(os.path.join(a.out, "source_map.json"))
              if os.path.isfile(os.path.join(a.out, "source_map.json")) else None)
    if sm:
        blocks = {b["id"]: b for b in sm.get("blocks") or []}
        ev = [e for e in (res.get("evidence") or []) if e.get("locator")]
        okn = sum(1 for e in ev
                  if (e.get("quote") or "")[:20] in
                  ((blocks.get(e.get("block_id")) or {}).get("text") or ""))
        rate = round(okn / len(ev), 4) if ev else None
        chk("引文回源率(重算 vs 自述)", fit_metrics.get("quote_verified_rate"), rate)
        chk("每条证据都有定位", 0, sum(1 for e in (res.get("evidence") or [])
                                      if not e.get("locator")))

    # ---- 导出件（若存在）：页数与逐页文本覆盖率
    pdf = os.path.join(a.out, "preview", "deck.pdf")
    if os.path.isfile(pdf):
        try:
            import fitz
            d = fitz.open(pdf)
            chk("PDF 页数 = pptx 页数", n_slides, len(d))
            if sm:
                texts = _pptx_texts(prs)
                covs = []
                for i, page in enumerate(d):
                    t = re.sub(r"\s+", "", page.get_text())
                    s = re.sub(r"\s+", "", texts[i] if i < len(texts) else "")
                    covs.append(1.0 if not s else sum(1 for c in s if c in t) / float(len(s)))
                chk("PDF 逐页文本覆盖率 ≥97%", True, min(covs or [1.0]) >= 0.97,
                    note="最低 %.4f" % min(covs or [1.0]))
            d.close()
        except Exception as exc:
            rows.append({"item": "PDF 回测", "expected": "可测量", "actual": str(exc)[:120],
                         "pass": False, "severity": "medium", "note": ""})
    else:
        rows.append({"item": "导出件存在", "expected": "preview/deck.pdf",
                     "actual": None, "pass": not ((res.get("results") or {}).get("render") or {})
                     .get("ok"), "severity": "medium",
                     "note": "无后端时 result.results.render.ok 应为 false 且 status=partial"})

    # ---- 产物完整性：outputs[] 的 bytes/sha256 与磁盘一致
    def _find(rel: str) -> str | None:
        b = os.path.basename(rel)
        for cand in (os.path.join(a.out, rel), os.path.join(a.out, b),
                     os.path.join(a.out, "preview", b),
                     os.path.join(a.out, "preview", "png", b)):
            if os.path.isfile(cand):
                return cand
        return None

    outs = res.get("outputs") or res.get("artifacts") or []
    for o in outs:
        if not isinstance(o, dict) or not o.get("path"):
            continue
        p = _find(o["path"])
        if not p:
            rows.append({"item": "产物存在: %s" % o["path"], "expected": True, "actual": False,
                         "pass": False, "severity": "high", "note": ""})
            continue
        chk("产物字节数: %s" % os.path.basename(p), o.get("bytes"), os.path.getsize(p))
        chk("产物 sha256: %s" % os.path.basename(p), o.get("sha256"), units.sha256_file(p))
    chk("契约字段回显完整（无未决字段）", 0, len(res.get("contract_unresolved_fields") or []))
    # result.json 自身完整性：读旁边的 result.sha256 重算比对（自指哈希不进 outputs[]）
    sfile = os.path.join(a.out, "result.sha256")
    if os.path.isfile(sfile):
        want = open(sfile, encoding="utf-8").read().split()[0]
        chk("result.json 自身哈希（result.sha256）", want, units.sha256_file(rj),
            note="result.json 不能自述自身哈希，故另存 result.sha256")
    else:
        rows.append({"item": "result.sha256 存在", "expected": True, "actual": False,
                     "pass": False, "severity": "medium", "note": "缺自身完整性文件"})

    high = [r for r in rows if not r["pass"] and r["severity"] == "high"]
    rep = {"auditor": "audit_only.py（只读产物重算）", "out": os.path.basename(os.path.abspath(a.out)),
           "case_id": res.get("case_id"), "checks": rows, "total": len(rows),
           "passed": sum(1 for r in rows if r["pass"]), "high_failures": len(high),
           "ok": not high}
    print("audit_only: %d/%d 通过（high 失败 %d）case=%s" % (
        rep["passed"], rep["total"], rep["high_failures"], rep["case_id"]))
    for r in rows:
        if not r["pass"]:
            print("  [%s] %s | expected=%s actual=%s" % (r["severity"], r["item"],
                                                         r["expected"], r["actual"]))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
    return 0 if rep["ok"] else 4


def _pptx_texts(prs) -> list:
    out = []
    for s in prs.slides:
        buf = []
        for sh in s.shapes:
            if sh.has_text_frame:
                for p in sh.text_frame.paragraphs:
                    buf.append("".join(r.text for r in p.runs
                                       if r._r.getparent() is None
                                       or r._r.getparent().tag != U.qn("a:fld")))
        out.append("\n".join(buf))
    return out


if __name__ == "__main__":
    sys.exit(main())
