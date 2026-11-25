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
        print("audit_only: 找不到 pptx 产物")
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
    # ---- D14-R4 新增：**独立**重算页数硬约束 + 抓假绿
    # 仅用产物（result.json 里声明的约束 + pptx 实际页数）判断，不信任汇总自述的 status。
    plan_rep = ((res.get("results") or {}).get("plan") or {})
    scc = plan_rep.get("slide_count_constraint") or {}
    if scc.get("max"):
        chk("页数 ≤ slide_count.max（重算）", True, n_slides <= int(scc["max"]),
            note="超出 = 案例硬约束被违反（slide_count.max=%s，实际 %d 页）" % (scc["max"], n_slides))
    if scc.get("min"):
        chk("页数 ≥ slide_count.min（重算）", True, n_slides >= int(scc["min"]),
            note="slide_count.min=%s，实际 %d 页" % (scc["min"], n_slides))
    pv = plan_rep.get("validation")
    if pv is not None:
        highs = [f for f in (pv.get("findings") or []) if f.get("severity") == "high"]
        chk("计划校验自述无 high 项", True, not highs,
            note=json.dumps(highs[:2], ensure_ascii=False)[:160])
        chk("high 项存在时 status 不得为 success", True,
            not (highs and res.get("status") == "success"),
            note="校验器判 fail、汇总却写 success 即假绿")
    else:
        rows.append({"item": "results.plan.validation 存在", "expected": True, "actual": False,
                     "pass": True, "severity": "low",
                     "note": "旧版 result.json 没有该字段；有则做一致性强校验"})
    if tm:
        chk("版式数（模板 vs 产物）", tm.get("layout_count"), n_layouts,
            note="版式数量不变 = 版式继承链未被破坏")
        chk("主题字体（模板 vs 产物）", tm.get("theme_fonts"), themes.get("fonts"),
            sev="medium", note="字体方案被改动会影响排版一致性")
        # ---- D30 同类：**只读重算**版式映射表（不信任生成器自述）
        # ① 角色映射引用的版式索引必须真实存在（指向不存在的样式 = 映射造假）
        bad_idx = []
        for role, idxs in (tm.get("roles") or {}).items():
            for i in (idxs if isinstance(idxs, list) else [idxs]):
                if not isinstance(i, int) or i < 0 or i >= n_layouts:
                    bad_idx.append("%s→%s" % (role, i))
        chk("角色映射的版式索引都存在", [], bad_idx,
            note="不存在 = 映射指向了不存在的样式；版式数 %d" % n_layouts)
        # ② 关键角色不许缺失（删掉一条映射 = 版式适配能力被悄悄掏空）
        REQUIRED_ROLES = ("title", "content", "section", "two-column",
                          "title-only", "blank", "figure")
        missing = [r for r in REQUIRED_ROLES if r not in (tm.get("roles") or {})]
        chk("版式角色映射齐备（7 类）", [], missing, note="缺失角色 = 映射表被删项")
        # ③ 映射声明的版式必须在 layouts 事实表里有条目（否则映射与模板事实脱节）
        by_idx = {l.get("index"): l for l in tm.get("layouts") or []}
        drift = []
        for i in sorted({j for _r, v in (tm.get("roles") or {}).items()
                         for j in (v if isinstance(v, list) else [v])
                         if isinstance(j, int)}):
            if i not in by_idx:
                drift.append("layout %d 不在 layouts 事实表里" % i)
        chk("角色映射的版式都有事实条目", [], drift, sev="medium")
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
    # ---- D30 同类：**材料 vs 工单**（只读重算，独立于生成器）
    # ① sources[] 只能指向材料类文件；工单/契约/示例/自制 spec 进 sources[] 一律判 high
    MAT_EXT = (".md", ".markdown", ".txt", ".pdf", ".docx")
    WO_NAMES = ("task.md", "task.txt", "tasks.md", "instruction.md", "instructions.md",
                "case.json", "case.md", "readme.md", "skill.md", "method.md",
                "environment.yaml", "environment.yml", "resources.yaml", "resources.yml",
                "github_url.txt", "prompt.md", "question.md")
    WO_PATTERNS = ("*.template.json", "*.example.json", "*.schema.json",
                   "template-spec*.json", "example*.json", "*.spec.json")
    import fnmatch as _fn
    nonmat = []
    for s0 in res.get("sources") or []:
        nm = str(s0.get("original_file") or s0.get("file") or "")
        low = os.path.basename(nm).lower()
        if not low:
            nonmat.append("<unnamed source>")
            continue
        if not low.endswith(MAT_EXT) or low in WO_NAMES \
                or any(_fn.fnmatch(low, p) for p in WO_PATTERNS):
            nonmat.append(nm)
    chk("sources[] 只含材料类文件（无工单/契约/示例/spec）", [], nonmat,
        note="JSON/工单/自制 spec 不能当科学证据来源")
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
        # ② 证据引用的 block_id 必须真实存在于材料块表（指向未读材料 = 编造定位）
        ghost = sorted({str(e.get("block_id")) for e in (res.get("evidence") or [])
                        if e.get("block_id") and e.get("block_id") not in blocks})
        chk("证据引用的 block_id 都存在于材料块表", [], ghost,
            note="不存在的 block_id = 引文指向未读材料")
        # ③ 材料块的文本必须来自材料文件（不是 spec/工单文本）
        src_txt = " ".join((b.get("text") or "") for b in sm.get("blocks") or [])
        chk("材料块文本非空", True, len(src_txt.strip()) > 0, sev="medium")
    else:
        rows.append({"item": "source_map.json 存在", "expected": True, "actual": False,
                     "pass": True, "severity": "low", "note": "缺 source_map 时跳过回源类检查"})

    # ---- D30 同类：产物根不得出现"栅格基准/二进制对照件"
    stray = []
    for base, _dirs, files in os.walk(a.out):
        relbase = os.path.relpath(base, a.out).replace("\\", "/")
        if relbase == "work" or relbase.startswith("work/"):
            continue  # work/ 是中间产物（数据出图的位图源），不算交付件
        for f in files:
            rel = (relbase + "/" + f).lstrip("./") if relbase != "." else f
            ext = os.path.splitext(f)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp") \
                    and not rel.startswith("preview/"):
                stray.append(rel)
            elif ext in (".bin", ".base64", ".zip", ".tar", ".gz", ".7z"):
                stray.append(rel)
    chk("产物根无栅格基准/压缩件（位图只允许在 preview/）", [], stray,
        note="嵌入栅格基准 = 用图片冒充可编辑产物或对照件")

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
            # ---- D31：导出件**逐页**一致性（字节/像素级重测，独立于生成器自述）
            # 题面把"导出渲染"列为横切关注点：pptx 与 PDF/PNG 必须一致，
            # 字体替换 / 图片丢失 / 备注错位都要留记录。这里全部重算并对照自述值。
            png_dir = os.path.join(a.out, "preview", "png")
            pngs = sorted(os.path.join(png_dir, f) for f in os.listdir(png_dir)
                          if f.endswith(".png")) if os.path.isdir(png_dir) else []
            chk("PNG 张数 = pptx 页数", n_slides, len(pngs),
                note="缺页预览 = 导出件不完整")
            self_pages = ((res.get("results") or {}).get("render") or {}).get(
                "consistency") or {}
            self_rows = {r.get("page"): r for r in (self_pages.get("pages") or [])}
            want_ratio = (float(prs.slide_width) / float(prs.slide_height)
                          if prs.slide_height else None)
            blank, aspect_bad, img_loss, notes_bad = [], [], [], []
            try:
                from PIL import Image
                ok_png = True
            except Exception:
                ok_png = False
            for i, page in enumerate(d, 1):
                pptx_pics = sum(1 for sh in prs.slides[i - 1].shapes
                                if getattr(sh, "shape_type", None) == 13)
                pdf_imgs = len(page.get_images(full=True))
                if pptx_pics and pdf_imgs < pptx_pics:
                    img_loss.append("p%d(pptx%d/pdf%d)" % (i, pptx_pics, pdf_imgs))
                try:
                    notes_txt = (prs.slides[i - 1].notes_slide.notes_text_frame.text
                                 if prs.slides[i - 1].has_notes_slide else "")
                except Exception:
                    notes_txt = ""
                self_nc = (self_rows.get(i) or {}).get("notes_chars")
                if self_nc is not None and self_nc != len(notes_txt):
                    notes_bad.append("p%d(自述%s/实测%d)" % (i, self_nc, len(notes_txt)))
                png = os.path.join(png_dir, "slide-%02d.png" % i)
                if not os.path.isfile(png):
                    continue
                if ok_png:
                    with Image.open(png) as im:
                        w, h = im.size
                        if want_ratio and h:
                            dev = abs((w / h) - want_ratio) / want_ratio * 100.0
                            if dev > 0.5:
                                aspect_bad.append("p%d(%.2f%%)" % (i, dev))
                        buf = im.convert("L").resize((160, 90)).tobytes()
                        ink = sum(1 for v in buf if v < 245) / float(len(buf) or 1)
                        if ink <= 0.0005:
                            blank.append("p%d(ink=%.5f)" % (i, ink))
            chk("PNG 逐页画幅与 pptx 一致（宽高比偏差 ≤0.5%）", [], aspect_bad)
            chk("PNG 无整页空白（像素级重测）", [], blank,
                note="整页空白 = 该页渲染丢失")
            chk("图片无丢失（逐页 pptx vs PDF）", [], img_loss)
            chk("讲稿备注字符数与自述一致（逐页）", [], notes_bad, sev="medium")
            dup = {}
            for i in range(1, n_slides + 1):
                try:
                    t = (prs.slides[i - 1].notes_slide.notes_text_frame.text
                         if prs.slides[i - 1].has_notes_slide else "")
                except Exception:
                    t = ""
                k = re.sub(r"\s+", "", t)
                if len(k) >= 20:
                    dup.setdefault(k, []).append(i)
            dup_bad = ["pages %s" % v for v in dup.values() if len(v) > 1]
            chk("备注不重复（无错位拷贝）", [], dup_bad, sev="medium")
            chk("render.consistency 自述 ok 与重算一致", True,
                (self_pages.get("ok") in (None, True)) if not (aspect_bad or blank or img_loss)
                else (self_pages.get("ok") is False),
                note="自述 ok=%s；重算问题：aspect=%d blank=%d img=%d"
                     % (self_pages.get("ok"), len(aspect_bad), len(blank), len(img_loss)))
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
