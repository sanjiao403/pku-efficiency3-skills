#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ga_build -- single entry point for the graphical-abstract skill.

    init | show | check | build | selfcheck | edit

Design rules
  * standard library only; optional renderers are probed, never required;
  * every step is wrapped: a failure degrades one field, it never kills the run;
  * exit code is always 0 and a legal result.json exists from `init` onwards;
  * no clock, no randomness inside the figure, so reruns are byte-identical.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # keep the package free of __pycache__

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ga_core as C          # noqa: E402
import layout                # noqa: E402
import provenance            # noqa: E402
import render_pdf            # noqa: E402
import render_png            # noqa: E402
import render_svg            # noqa: E402
import fonts                 # noqa: E402

BUDGET = {"model_requests": 64, "wall_seconds": 900, "response_tokens": 16384,
          "script_soft_seconds": 20, "script_hard_seconds": 120}
TEXT_EXT = (".md", ".txt", ".csv", ".tsv", ".json", ".tex", ".rst", ".html", ".log",
            ".yaml", ".yml", ".srt", ".vtt")
STOP = {"the", "and", "for", "with", "that", "this", "from", "were", "was", "are",
        "using", "used", "figure", "table", "result", "results", "study", "here"}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def log(msg, path=None, echo=True):
    line = "[%s] %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg)
    if echo:
        print(line)
    if path:
        try:
            with open(str(path), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass


def read_case(p):
    case = C.load_json(p["input"] / "case.json", None)
    if case is None:
        for alt in ("case.json", "input.json", "task.json"):
            for cand in sorted(p["input"].glob("**/" + alt)) if p["input"].is_dir() else []:
                case = C.load_json(cand, None)
                if case is not None:
                    break
            if case is not None:
                break
    return case if isinstance(case, dict) else {}


def case_id_of(case, work):
    for key in ("case_id", "id", "task_id", "caseId"):
        if isinstance(case.get(key), (str, int)) and str(case[key]).strip():
            return str(case[key]).strip()
    draft = C.load_json(work / "figure-ir.json", None)
    if isinstance(draft, dict) and draft.get("case_id"):
        return str(draft["case_id"])
    return "unknown-case"


# --------------------------------------------------------------------------
# material index
# --------------------------------------------------------------------------
def split_paragraphs(text, limit=900):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    out = []
    for b in blocks:
        if len(b) <= limit:
            out.append(b)
            continue
        for sent in re.split(r"(?<=[。．.!?；;])\s+", b):
            sent = sent.strip()
            if sent:
                out.append(sent)
    return out


def build_index(p):
    index = {"materials": [], "csv": [], "skipped": [], "generated_by": "ga_build init"}
    if not p["input"].is_dir():
        return index
    for path in sorted(p["input"].rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(p["input"])).replace("\\", "/")
        suffix = path.suffix.lower()
        if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            index["materials"].append({"path": rel, "kind": "image", "text": "",
                                       "paragraphs": [], "note": "位图不能作为文字来源，需 OCR 或人工转写"})
            continue
        if suffix not in TEXT_EXT and suffix not in (".pdf", ".docx", ".xlsx", ".pptx"):
            index["skipped"].append({"path": rel, "why": "unsupported extension"})
            continue
        if suffix == ".pdf":
            txt = extract_pdf_text(path)
            kind = "pdf"
        elif suffix in (".docx", ".xlsx", ".pptx"):
            txt = extract_office_text(path)
            kind = suffix[1:]
        else:
            txt = C.read_text(path)
            kind = "csv" if suffix in (".csv", ".tsv") else "text"
        if kind == "csv":
            rows, header = read_csv(path)
            index["csv"].append({"path": rel, "header": header, "rows": rows[:400],
                                 "n_rows": len(rows)})
            txt = "\n".join([",".join(header)] + [",".join(r) for r in rows[:400]])
        paras = split_paragraphs(txt)
        entry = {"path": rel, "kind": kind, "chars": len(txt),
                 "paragraphs": [{"locator": "%s#para%d" % (rel, i + 1), "text": t}
                                for i, t in enumerate(paras)]}
        if kind == "pdf" and not txt.strip():
            entry["note"] = "PDF 无文字层：需用平台 pdf-render/ocr 工具转写，禁止臆造内容"
        index["materials"].append(entry)
    return index


def extract_pdf_text(path):
    try:
        import fitz
        doc = fitz.open(str(path))
        parts = [pg.get_text() for pg in doc]
        doc.close()
        return "\n\n".join(parts)
    except Exception:
        return ""


def extract_office_text(path):
    try:
        import zipfile
        with zipfile.ZipFile(str(path)) as z:
            parts = []
            for name in z.namelist():
                if name.endswith(".xml") and ("document" in name or "slide" in name or
                                              "sharedStrings" in name):
                    raw = z.read(name).decode("utf-8", "replace")
                    parts.append(re.sub(r"<[^>]+>", " ", raw))
            return "\n\n".join(parts)
    except Exception:
        return ""


def read_csv(path):
    txt = C.read_text(path)
    try:
        dialect = csv.Sniffer().sniff(txt[:4000], delimiters=",;\t")
    except Exception:
        dialect = csv.excel
    rows = []
    lines = [ln for ln in txt.splitlines() if not ln.lstrip().startswith("#")]
    for row in csv.reader(lines, dialect):
        if any(c.strip() for c in row):
            rows.append([c.strip() for c in row])
    header = rows[0] if rows else []
    return rows[1:], header


# --------------------------------------------------------------------------
# draft IR (a scaffold the agent overwrites)
# --------------------------------------------------------------------------
def _unit_after(text, pos):
    tail = text[pos:pos + 22]
    m = re.match(r"\s*(?:±|±\s*[\d.]+\s*)?([a-zA-Z%µμ][a-zA-Z0-9/%^µμ·\-]{0,9})", tail)
    if not m:
        return ""
    tok = m.group(1)
    if tok.lower() in ("and", "the", "in", "of", "to", "was", "were", "with", "for", "at",
                       "from", "by", "is", "are", "as", "on"):
        return ""
    return tok


def draft_ir(case, index, contract):
    cid = case_id_of(case, Path("."))
    title = ""
    for key in ("title", "paper_title", "figure_title", "question", "name"):
        if isinstance(case.get(key), str) and case[key].strip():
            title = case[key].strip()
            break
    sources = []
    sentences = []
    numbers = []
    for m in index["materials"]:
        if not m.get("paragraphs"):
            continue
        sid = "S%d" % (len(sources) + 1)
        first = m["paragraphs"][0]
        sources.append({"id": sid, "path": m["path"], "locator": first["locator"],
                        "quote": first["text"][:220]})
        for para in m["paragraphs"][:60]:
            for sent in re.split(r"(?<=[。．.!?])\s+", para["text"]):
                sent = sent.strip()
                if 12 <= len(sent) <= 260:
                    sentences.append({"text": sent, "sid": sid, "locator": para["locator"]})
            for mm in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)\s*([a-zA-Z%µμ][\w/%µμ·\-]{0,8})?",
                                  para["text"]):
                val, unit = mm.group(1), (mm.group(2) or "")
                if unit.lower() in ("and", "the", "of", "in", "to", "was", "with", "at"):
                    unit = ""
                numbers.append({"value": float(val), "unit": unit, "sid": sid,
                                "locator": para["locator"], "quote": para["text"][:220]})
    if not title:
        title = (sentences[0]["text"][:90] if sentences else "Graphical abstract")
    claims = []
    seen = set()
    for n in numbers:
        key = (n["value"], n["unit"])
        if key in seen or len(claims) >= 4:
            continue
        seen.add(key)
        claims.append({"id": "K%d" % (len(claims) + 1),
                       "label": n["quote"][:48] or ("指标 %d" % (len(claims) + 1)),
                       "value": n["value"], "unit": n["unit"],
                       "compare": {"label": "", "value": None},
                       "source": {"id": n["sid"], "locator": n["locator"], "quote": n["quote"]}})
    for cs in index["csv"][:2]:
        header = cs["header"]
        if len(header) < 2:
            continue
        for col in range(1, min(3, len(header))):
            vals = []
            for r in cs["rows"][:12]:
                if col < len(r):
                    try:
                        vals.append(float(r[col]))
                    except Exception:
                        pass
            if vals:
                claims.append({"id": "K%d" % (len(claims) + 1),
                               "label": header[col][:48] or "measure",
                               "value": max(vals), "unit": "",
                               "compare": {"label": "", "value": None},
                               "source": {"id": "S1", "locator": "%s#header" % cs["path"],
                                          "quote": ",".join(header)}})
    roles = ["problem", "method", "results", "conclusion"]
    buckets = [[], [], [], []]
    for i, s in enumerate(sentences[:12]):
        buckets[min(3, i * 4 // max(1, min(12, len(sentences))))].append(s)
    panels = []
    for i, role in enumerate(roles):
        items = []
        for j, s in enumerate(buckets[i][:3]):
            items.append({"id": "p%di%d" % (i + 1, j + 1), "text": s["text"],
                          "source": {"id": s["sid"], "locator": s["locator"],
                                     "quote": s["text"]}})
        panels.append({"order": i + 1, "role": role,
                       "title": {"problem": "问题", "method": "方法",
                                 "results": "结果", "conclusion": "结论"}[role],
                       "claim": (buckets[i][0]["text"][:80] if buckets[i] else ""),
                       "kind": "bullets", "items": items})
    charts = []
    for ci, cs in enumerate(index["csv"][:2]):
        header = cs["header"]
        if len(header) < 2:
            continue
        series = []
        for col in range(1, min(4, len(header))):
            pts = []
            for r in cs["rows"][:12]:
                if len(r) < 2:
                    continue
                try:
                    y = float(r[col]) if col < len(r) else None
                except Exception:
                    y = None
                if y is None:
                    continue
                pts.append({"x": r[0], "y": y, "raw": (r[col] if col < len(r) else "%g" % y),
                            "source": {"id": "S1", "locator": "%s row %d" % (cs["path"], len(pts) + 1),
                                       "quote": ",".join(r)}})
            if pts:
                series.append({"name": header[col], "color_key": "c%d" % (len(series) + 1),
                               "points": pts})
        if series:
            charts.append({"id": "CH%d" % (ci + 1), "kind": "bar", "title": header[0],
                           "x_label": header[0], "y_label": series[0]["name"], "unit": "",
                           "series": series})
    return {
        "case_id": cid, "origin": "draft", "mode": "create",
        "title": title, "subtitle": "",
        "panels": panels, "entities": [], "relations": [], "charts": charts,
        "claims": claims, "legend": [],
        "notes": {"units": "", "conditions": "", "scale_bar": "", "caption": "",
                  "figure_no": "Figure 1"},
        "sources": sources,
        "_draft_note": "由 init 从材料自动草拟，供 Agent 修改；未经科学判断，status 记为 partial",
    }


# --------------------------------------------------------------------------
# result.json assembly
# --------------------------------------------------------------------------
def blank_contract_values(contract_keys):
    vals = {}
    for key in contract_keys:
        vals[key] = "" if key not in ("content_map", "compliance_checks", "exceptions") else []
    return vals


def minimal_result(cid, contract, status="partial", reason=""):
    res = {"case_id": cid, "status": status, "status_reason": reason,
           "summary": "尚未渲染：init 已建立最小可判交付"}
    res.update(blank_contract_values(contract["keys"]))
    res["case_id"] = cid
    res["status"] = status
    res["outputs"] = {}
    res["sources"] = []
    res["uncertainty"] = []
    res["changes"] = []
    res["errors"] = []
    res["degradations"] = []
    res["gaps"] = []
    res["not_reported"] = []
    res["runtime"] = {"steps": [], "budget": BUDGET}
    res["contract_echo"] = {"declared": contract["declared"], "shape": contract["shape"],
                            "keys": contract["keys"]}
    return res


def echo_contract(res, contract):
    """Guarantee every requested contract key exists (never null)."""
    missing = []
    for key in contract["keys"]:
        if key in res:
            continue
        head = key.split(".")[0]
        if head in res:
            continue
        res[key] = [] if key in ("content_map", "compliance_checks", "exceptions",
                                 "outputs", "sources", "changes", "uncertainty") else ""
        missing.append(key)
    if missing:
        res["not_reported"].append({
            "field": ",".join(missing),
            "why": "输入契约要求但本次运行无法填充，按空值保留键位（不推测内容）"})
    return res


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------
ABLATE = [x for x in (os.environ.get("GA_ABLATE") or "").split(",") if x]


def ablate(ir, features):
    """Turn off named capabilities, for the A/B ablation arm (see tests/ab_harness.py).

    The figure keeps the same four panels and the same material, so the only
    difference between the arms is the capability under test.
    """
    if not features:
        return ir
    out = dict(ir)
    if "provenance" in features:
        out["entities"] = []
        out["relations"] = []
        out["sources"] = []
        out["panels"] = [dict(p, source={},
                              items=[dict(i, source={}) for i in p["items"]])
                         for p in out["panels"]]
    if "encoding" in features:
        out["charts"] = []
        out["claims"] = []
        out["panels"] = [dict(p, kind="bullets", chart="", relations=[])
                         for p in out["panels"]]
    if "legend" in features:
        out["legend"] = []
        out["relations"] = []
        out["charts"] = []
    if "typography" in features:
        out["panels"] = [dict(p, claim="") for p in out["panels"]]
    return out


def cmd_init(p, args):
    t0 = time.time()
    C.ensure_dirs(p)
    case = read_case(p)
    contract = C.resolve_contract(case)
    index = build_index(p)
    C.dump_json(p["work"] / "quote-index.json", index)
    cid = case_id_of(case, p["work"])
    draft_path = p["work"] / "figure-ir.draft.json"
    if not draft_path.exists() or args.force:
        C.dump_json(draft_path, draft_ir(case, index, contract))
    if not (p["work"] / "figure-ir.json").exists():
        C.dump_json(p["work"] / "figure-ir.json", C.load_json(draft_path, {}))
    res = minimal_result(cid, contract, "partial", "init 完成：待撰写 figure IR 并 build")
    res["sources"] = [{"source_id": m.get("id", ""), "path": m["path"], "kind": m["kind"],
                       "pages_or_paras": len(m.get("paragraphs", []))}
                      for m in index["materials"]]
    res["outputs"] = {}
    res["runtime"]["steps"].append({"step": "init", "seconds": round(time.time() - t0, 2),
                                    "materials": len(index["materials"]),
                                    "csv": len(index["csv"])})
    C.dump_json(p["output"] / "result.json", res)
    log("init: %d materials, %d csv, case_id=%s" % (len(index["materials"]), len(index["csv"]), cid))
    log("init: partial result.json written; draft IR at %s" % draft_path.name)
    return 0


def cmd_show(p, args):
    index = C.load_json(p["work"] / "quote-index.json", None)
    if not index:
        cmd_init(p, argparse.Namespace(force=False))
        index = C.load_json(p["work"] / "quote-index.json", {})
    budget = args.chars
    for m in index.get("materials", []):
        print("=" * 78)
        print("MATERIAL %s  (%s, %d chars, %d paragraphs)" %
              (m["path"], m["kind"], m.get("chars", 0), len(m.get("paragraphs", []))))
        if m.get("note"):
            print("NOTE:", m["note"])
        for para in m.get("paragraphs", []):
            if budget <= 0:
                print("… (输出预算用完，可加 --chars 提高)")
                return 0
            txt = para["text"].replace("\n", " ")
            if len(txt) > 420:
                txt = txt[:420] + "…"
            print("[%s] %s" % (para["locator"], txt))
            budget -= len(txt)
    for cs in index.get("csv", []):
        print("=" * 78)
        print("CSV %s  header=%s rows=%d" % (cs["path"], cs["header"], cs.get("n_rows", 0)))
        for i, row in enumerate(cs.get("rows", [])[:12]):
            print("  row %d: %s" % (i + 1, row))
    return 0


def load_ir(p, args):
    curated = C.load_json(p["work"] / "figure-ir.json", None)
    draft = C.load_json(p["work"] / "figure-ir.draft.json", None)
    raw, origin = None, "draft"
    if isinstance(curated, dict) and curated and not curated.get("_draft_note"):
        raw, origin = curated, curated.get("origin") or "curated"
    elif isinstance(curated, dict) and curated:
        raw = curated
        origin = curated.get("origin") or "draft"
    elif isinstance(draft, dict):
        raw = draft
    if raw is None:
        return None, "missing"
    raw = dict(raw)
    raw.setdefault("origin", origin)
    return raw, origin


def cmd_check(p, args):
    case = read_case(p)
    raw, origin = load_ir(p, args)
    if raw is None:
        print("CHECK_FAIL 未找到 figure-ir.json（先运行 init）")
        return 0
    ir = C.normalize_ir(raw, case_id_of(case, p["work"]))
    val = C.validate_ir(ir)
    hay = provenance.material_haystack(p["input"])
    report = {"ok": val["ok"], "errors": val["errors"], "warnings": val["warnings"],
              "origin": origin, "checks": []}

    def add(name, ok, detail, hard=True):
        report["checks"].append({"check": name, "ok": bool(ok), "detail": detail,
                                 "severity": "error" if hard else "warn"})

    add("ir_structure", val["ok"], "; ".join(val["errors"]) or "结构完整")
    roles = {p_["role"] for p_ in ir["panels"]}
    add("four_beats", len(roles & {"problem", "method", "results", "conclusion"}) == 4,
        "roles=%s" % sorted(roles), hard=False)
    if not hay:
        add("materials_present", False, "/input 无可读文本材料（引文无法验证）", hard=False)
    else:
        quotes, hits = 0, 0
        for bucket in (ir["entities"], ir["relations"], ir["claims"], ir["panels"]):
            for item in bucket:
                q = (item.get("source") or {}).get("quote") or ""
                if q:
                    quotes += 1
                    hits += 1 if provenance.quote_hit(q, hay) else 0
        for src in ir["sources"]:
            q = src.get("quote") or ""
            if q:
                quotes += 1
                hits += 1 if provenance.quote_hit(q, hay) else 0
        ratio = hits / float(quotes or 1)
        add("quotes_verbatim", ratio >= 0.8, "%d/%d 命中（%.0f%%）" % (hits, quotes, ratio * 100),
            hard=False)
    for r in ir["relations"]:
        if r["unresolved"]:
            add("relation_endpoints", False, "%s 端点缺失: %s->%s" % (r["id"], r["from"], r["to"]),
                hard=False)
    if ir["must_include"]:
        texts = " ".join([i["text"] for p_ in ir["panels"] for i in p_["items"]] +
                         [e["label"] for e in ir["entities"]] +
                         [s["name"] for c in ir["charts"] for s in c["series"]] +
                         [c.get("unit") or "" for c in ir["charts"]] +
                         [c.get("y_label") or "" for c in ir["charts"]] +
                         [l.get("label", "") for l in ir["legend"]])
        missing = [m for m in ir["must_include"] if m and m not in texts]
        add("workorder_coverage", not missing,
            "缺 %d 项: %s" % (len(missing), "; ".join(missing[:4])), hard=False)
    scene = layout.build_scene(ir)
    add("no_overflow", not scene["out_of_canvas"], "%d 文本越界" % len(scene["out_of_canvas"]))
    add("legend_consistent", provenance.legend_gate(scene, ir)["ok"],
        "legend=%d categories=%d" % (provenance.legend_gate(scene, ir)["legend_entries"],
                                     provenance.legend_gate(scene, ir)["categories"]),
        hard=False)
    C.dump_json(p["work"] / "check-report.json", report)
    hard_fail = [c for c in report["checks"] if not c["ok"] and c["severity"] == "error"]
    for c in report["checks"]:
        print("%-4s %-22s %s" % ("OK" if c["ok"] else ("FAIL" if c["severity"] == "error"
                                                       else "WARN"), c["check"], c["detail"]))
    print("CHECK_%s  (origin=%s, hard_fail=%d, warn=%d)" %
          ("OK" if not hard_fail else "FAIL", origin, len(hard_fail),
           len([c for c in report["checks"] if not c["ok"]]) - len(hard_fail)))
    return 0


def _artifact_paths(p):
    return {"svg": p["output"] / "figure.svg", "png": p["output"] / "figure.png",
            "pdf": p["output"] / "figure.pdf", "ir": p["output"] / "figure-ir.json"}


def render_all(p, ir, args, logp, fast_reason=""):
    """Layout -> SVG -> PNG -> PDF, with the contract trace for each stage."""
    t0 = time.time()
    scene = layout.build_scene(ir)
    arts = _artifact_paths(p)
    svg_info = render_svg.scene_to_svg(scene, meta={
        "title": ir["title"], "case_id": ir["case_id"], "version": C.VERSION,
        "description": "Graphical abstract for case %s; elements carry the ids used in "
                       "result.json content_map." % ir["case_id"]})
    C.write_text(arts["svg"], svg_info["svg"])
    log("layout+svg: %d primitives, %d texts, %d layers, %.2fs" %
        (len(scene["prims"]), scene["text_count"], len(scene["layers"]), time.time() - t0), logp)
    allow_browser = bool(os.environ.get("GA_ALLOW_BROWSER")) and not args.fast
    png_rec = render_png.export_png(scene, arts["svg"], arts["png"], scale=1.0,
                                    allow_browser=allow_browser)
    log("png: engine=%s verified=%s %sx%s %s" %
        (png_rec.get("engine"), png_rec.get("verified"), png_rec.get("width"),
         png_rec.get("height"), png_rec.get("degraded")), logp)
    pdf_rec = render_pdf.export_pdf(scene, arts["svg"], arts["pdf"])
    log("pdf: engine=%s verified=%s pages=%s" %
        (pdf_rec.get("engine"), pdf_rec.get("verified"), pdf_rec.get("pages")), logp)
    C.write_text(arts["ir"], json.dumps(ir, ensure_ascii=False, indent=2) + "\n")
    return scene, svg_info, png_rec, pdf_rec


def cmd_build(p, args):
    t_start = time.time()
    C.ensure_dirs(p)
    logp = p["output"] / "run.log"
    case = read_case(p)
    contract = C.resolve_contract(case)
    cid = case_id_of(case, p["work"])
    raw, origin = load_ir(p, args)
    errors, degradations, gaps = [], [], []
    if raw is None:
        errors.append({"where": "build", "what": "缺少 figure-ir.json，已用空白骨架出图",
                       "impact": "图形无科学内容"})
        raw = {"case_id": cid, "title": "Graphical abstract", "origin": "empty"}
        origin = "empty"
    ir = ablate(C.normalize_ir(raw, cid), ABLATE)
    if ABLATE:
        degradations.append({"what": "A/B 消融臂：关闭能力 %s" % ",".join(ABLATE),
                             "why": "对照实验（tests/ab_harness.py 生成 ab-report.json）",
                             "impact": "仅用于量化增益，正式运行不会设置 GA_ABLATE"})
    if origin in ("draft", "empty"):
        degradations.append({
            "what": "figure IR 由 init 自动草拟（origin=%s），未经 LLM 科学判断" % origin,
            "why": "未检测到经撰写的 /app/work/figure-ir.json",
            "impact": "实体/关系/数值可能不完整，status 记为 partial"})
    if args.fast:
        degradations.append({"what": "fast 模式：跳过浏览器与高开销引擎",
                             "why": "时间预算保护", "impact": "PNG 引擎可能降级"})
    try:
        scene, svg_info, png_rec, pdf_rec = render_all(p, ir, args, logp)
    except Exception as exc:                                     # never die mid-air
        errors.append({"where": "render", "what": "渲染异常: %s" % str(exc)[:200],
                       "impact": "可能只交付了部分产物"})
        res = minimal_result(cid, contract, "partial", "渲染失败，仅保留最小交付")
        res["errors"] = errors
        res["degradations"] = degradations
        C.dump_json(p["output"] / "result.json", res)
        log("render failed: %s" % exc)
        return 0

    hay = provenance.material_haystack(p["input"])
    id_map = svg_info["ids"]
    cmap = provenance.build_content_map(ir, scene, id_map)
    cov = provenance.coverage_report(ir, hay, cmap)
    legend = provenance.legend_gate(scene, ir)
    nums = provenance.number_gate(scene, ir, hay)
    font_rep = fonts.discover(needs_cjk=True)
    checks = provenance.compliance_checks(ir, scene, svg_info, png_rec, pdf_rec,
                                          font_rep, cov, legend, nums)

    exceptions = []
    for o in scene["out_of_canvas"][:8]:
        exceptions.append({"element": o["id"], "issue": "文本超出画布",
                           "detail": "x1=%s > 画布宽" % o["x1"], "handling": "已记入，未截断"})
    for r in scene["repairs"]:
        exceptions.append({"element": r["unit"], "issue": "版式自动修复",
                           "detail": "%s：%s" % (r["action"], r.get("detail", "")),
                           "handling": "已在图面上执行，字号 %.1f px" % r.get("font_px", 0)})
    for a in png_rec.get("attempts", []):
        if a.get("result") not in ("ok",):
            exceptions.append({"element": "figure.png", "issue": "PNG 引擎不可用",
                               "detail": "%s -> %s" % (a.get("engine"), a.get("result")),
                               "handling": "已尝试下一引擎"})
    for d in png_rec.get("degraded", []):
        exceptions.append({"element": "figure.png", "issue": "PNG 降级", "detail": d,
                           "handling": "SVG/PDF 不受影响"})
    for s in font_rep.get("substituted", []):
        exceptions.append({"element": "font", "issue": "字体替换",
                           "detail": "%s -> %s" % (s["requested"], s["used"] or "none"),
                           "handling": s["impact"]})
    for a in pdf_rec.get("attempts", []):
        if a.get("result") not in ("ok",):
            exceptions.append({"element": "figure.pdf", "issue": "PDF 引擎不可用",
                               "detail": "%s -> %s" % (a.get("engine"), a.get("result")),
                               "handling": "已尝试下一引擎"})

    hard_fail = [c for c in checks if c["verdict"] == "fail"]
    warnings = [c for c in checks if c["verdict"] == "warn"]
    if not hay:
        gaps.append({"item": "材料文本", "why": "/input 中没有可读文本材料",
                     "alternative_evidence": "仅使用 case.json 元数据"})
    if origin in ("draft", "empty"):
        gaps.append({"item": "科学内容判断", "why": "IR 未经撰写",
                     "alternative_evidence": "材料原文见 sources[]"})
    status = "ok"
    if errors or origin == "empty" or not png_rec.get("verified"):
        status = "partial"
    if origin == "draft":
        status = "partial"
    if not (p["input"] / "case.json").exists() and not case:
        status = "input_error" if not any(m.get("paragraphs") for m in
                                          (C.load_json(p["work"] / "quote-index.json", {})
                                           .get("materials", []) or [])) else status
    if not any(m.get("paragraphs") for m in
               (C.load_json(p["work"] / "quote-index.json", {}).get("materials", []) or [])) \
            and not any(c.get("series") for c in ir["charts"]):
        if origin != "empty":
            status = "insufficient_evidence"

    res = minimal_result(cid, contract, status)
    res["status_reason"] = ("IR=%s；四面板=%d；元素=%d；引文命中=%.0f%%；PNG=%s；PDF=%s；修复=%d"
                            % (origin, len(ir["panels"]), cov["elements"],
                               cov["source_ratio"] * 100, png_rec.get("engine"),
                               pdf_rec.get("engine"), len(scene["repairs"])))
    res["summary"] = ("%s | %d 个可核验图元，%d 处自动版式修复，导出 SVG+PNG(%s)+PDF(%s)"
                      % (ir["title"][:70], cov["elements"], len(scene["repairs"]),
                         png_rec.get("engine"), pdf_rec.get("engine")))
    res["editable_source"] = {
        "path": "figure.svg", "format": "svg", "editable": True,
        "layers": scene["layers"], "text_count": svg_info["text_count"],
        "sha256": C.sha256_file(_artifact_paths(p)["svg"]),
        "text_preserved": True,
        "model_copy": "figure-ir.json",
        "notes": "文字为真实 <text>，图元 id 与 content_map 一一对应，可在 Illustrator/Inkscape 直接编辑",
    }
    res["export_artifact"] = {
        "png": {"path": "figure.png", "width": png_rec.get("width"),
                "height": png_rec.get("height"), "dpi": png_rec.get("dpi"),
                "engine": png_rec.get("engine"), "verified": png_rec.get("verified"),
                "ink_ratio": png_rec.get("ink_ratio"),
                "attempts": png_rec.get("attempts", [])},
        "pdf": {"path": "figure.pdf", "pages": pdf_rec.get("pages"),
                "vector": pdf_rec.get("vector"), "engine": pdf_rec.get("engine"),
                "verified": pdf_rec.get("verified"),
                "page_pt": [pdf_rec.get("page_width_pt"), pdf_rec.get("page_height_pt")]},
    }
    res["content_map"] = cmap
    res["compliance_checks"] = checks
    res["exceptions"] = exceptions
    res["outputs"] = {"editable_source": "figure.svg", "preview_png": "figure.png",
                      "vector_pdf": "figure.pdf", "result": "result.json",
                      "figure_model": "figure-ir.json", "run_log": "run.log"}
    res["sources"] = [dict(s, source_id=s.get("id", "")) for s in ir["sources"]]
    res["uncertainty"] = ir["uncertainty"] + [
        {"item": "科学内容的正确性", "why": "实体/关系/数值由 IR 声明，脚本不判断其科学真伪",
         "handling": "逐条比对 content_map 中的 locator+quote；未命中者见 compliance_checks"},
    ]
    if nums["untraced"]:
        res["uncertainty"].append({
            "item": "画布上未能回查的数值: %s" % ",".join(nums["untraced"][:8]),
            "why": "这些数字未出现在任何 source quote / claim / 数据点中",
            "handling": "补 quote 或从图面移除，禁止保留无来源数字"})
    res["changes"] = [{"action": "create", "what": "figure.svg/.png/.pdf",
                       "reason": "由 figure IR 确定性渲染"}]
    res["changes"] += [{"action": "repair", "what": r["unit"] + ":" + r["action"],
                        "reason": r.get("detail", "")} for r in scene["repairs"]]
    res["degradations"] = degradations
    res["gaps"] = gaps
    res["errors"] = errors
    res["coverage"] = cov
    res["invariants"] = {"legend": legend, "numbers": nums, "grayscale": provenance.grayscale_gate(scene, ir),
                         "fit": scene["fit"], "panels": scene["panel_metrics"]}
    res["runtime"] = {"steps": [
        {"step": "build", "seconds": round(time.time() - t_start, 2),
         "primitives": len(scene["prims"]), "primitives_text": scene["text_count"]}],
        "budget": BUDGET, "fast": bool(args.fast), "timed_out": False}
    res["font_report"] = {"sans": Path(font_rep.get("sans") or "").name,
                          "source": font_rep.get("source"),
                          "cjk_capable": font_rep.get("sans_cjk_capable"),
                          "substituted": font_rep.get("substituted", [])}
    echo_contract(res, contract)
    C.dump_json(p["output"] / "result.json", res)
    log("build done: status=%s hard_fail=%d warn=%d exceptions=%d %.2fs" %
        (status, len(hard_fail), len(warnings), len(exceptions), time.time() - t_start), logp)
    print("BUILD_%s status=%s png=%s pdf=%s elements=%d" %
          ("OK" if status == "ok" else "PARTIAL", status, png_rec.get("engine"),
           pdf_rec.get("engine"), cov["elements"]))
    return 0


def cmd_selfcheck(p, args):
    res = C.load_json(p["output"] / "result.json", None)
    problems = []
    if not isinstance(res, dict):
        problems.append("result.json 缺失或不可解析")
        res = {}
    arts = _artifact_paths(p)
    for key, path in (("figure.svg", arts["svg"]), ("figure.png", arts["png"]),
                      ("figure.pdf", arts["pdf"])):
        if not path.exists() or path.stat().st_size < 400:
            problems.append("%s 缺失或过小" % key)
    svg_txt = C.read_text(arts["svg"])
    if svg_txt:
        if "<text" not in svg_txt:
            problems.append("figure.svg 没有可编辑 <text>")
        if not re.search(r'<g id="layer-', svg_txt):
            problems.append("figure.svg 没有 layer-* 分组")
        n_text = svg_txt.count("<text")
        claimed = (res.get("editable_source") or {}).get("text_count")
        if claimed and claimed != n_text:
            problems.append("text_count 声明 %s，实际 %s" % (claimed, n_text))
    info = render_png.png_info(arts["png"])
    if not info:
        problems.append("figure.png 不是合法 PNG")
    else:
        exp = (res.get("export_artifact") or {}).get("png") or {}
        if exp.get("width") and exp["width"] != info["width"]:
            problems.append("PNG 宽度与 result.json 声明不一致")
    pinfo = render_pdf.pdf_info(arts["pdf"])
    if not pinfo:
        problems.append("figure.pdf 不是合法 PDF")
    cids = {e.get("id") for e in (res.get("content_map") or []) if e.get("id")}
    if cids and svg_txt:
        missing = [i for i in list(cids)[:200] if ('id="%s"' % i) not in svg_txt]
        if missing:
            problems.append("content_map 有 %d 个 id 不在 SVG 中（如 %s）" %
                            (len(missing), missing[0]))
    if not (res.get("case_id") or "").strip():
        problems.append("result.json 缺 case_id")
    if res.get("status") in ("", None):
        problems.append("result.json 缺 status")
    for c in (res.get("compliance_checks") or []):
        if c.get("verdict") == "fail":
            problems.append("compliance fail: %s (%s)" % (c.get("check"), c.get("measured")))
    print("SELFCHECK_%s  problems=%d" % ("OK" if not problems else "FAIL", len(problems)))
    for pr in problems:
        print("  - %s" % pr)
    return 0


def cmd_edit(p, args):
    """Source-preserving edit: only the named elements change, then re-export."""
    import svg_edit
    C.ensure_dirs(p)
    t0 = time.time()
    case = read_case(p)
    contract = C.resolve_contract(case)
    cid = case_id_of(case, p["work"])
    ops = C.load_json(Path(args.ops), None) if args.ops else None
    if isinstance(ops, dict):
        ops = ops.get("ops") or ops.get("operations") or []
    if not isinstance(ops, list):
        ops = (((case.get("expected_figure") or {}).get("edit_ops")) or
               ((case.get("workorder") or {}).get("edit_ops")) or [])
    src = None
    named = str(case.get("input_svg") or "")
    if named and (p["input"] / named).exists():
        src = p["input"] / named
    else:
        for cand in sorted(p["input"].rglob("*.svg")) if p["input"].is_dir() else []:
            if cand.name != "figure.svg":
                src = cand
                break
    if src is None:
        log("edit: no input .svg found, falling back to create flow")
        return cmd_build(p, args)
    original = C.read_text(src)
    result = svg_edit.apply_ops(original, ops)
    arts = _artifact_paths(p)
    C.write_text(arts["svg"], result["svg"])
    C.dump_json(p["output"] / "edit-record.json", result["record"])

    import re as _re
    mw = _re.search(r'width\s*=\s*"(\d+)', result["svg"])
    mh = _re.search(r'height\s*=\s*"(\d+)', result["svg"])
    width = int(mw.group(1)) if mw else 2400
    height = int(mh.group(1)) if mh else 1350
    scene = {"canvas": {"width_px": width, "height_px": height,
                        "dpi": int(args.edit_dpi), "background": "#FFFFFF",
                        "min_font_px": 8},
             "prims": [], "layers": ["frame"], "text_count": 0, "patterns": [],
             "out_of_canvas": [], "repairs": [], "legend": [], "dropped": [],
             "panel_metrics": [], "legend_shown": 0, "min_font_used": 0,
             "fit": {}, "ledger": {"rows": 0, "drawn": False, "height_px": 0.0}}
    png_rec = render_png.export_png(scene, arts["svg"], arts["png"], scale=1.0,
                                    allow_browser=bool(os.environ.get("GA_ALLOW_BROWSER")))
    pdf_rec = render_pdf.export_pdf(scene, arts["svg"], arts["pdf"])
    svg_text_count = result["svg"].count("<text")
    exceptions = [{"element": s.get("id", ""), "issue": "编辑未应用",
                   "detail": s.get("why", ""), "handling": "保留原值，记入 edit-record.json"}
                  for s in result["record"]["skipped"]]
    checks = [
        {"check": "editable_source_preserved", "required": "输入 SVG 为可编辑文本",
         "measured": "%d <text> 元素" % svg_text_count,
         "verdict": "pass" if svg_text_count > 0 else "warn", "evidence": str(src.name)},
        {"check": "edits_applied", "required": ">=1 处修改",
         "measured": "%d 处（跳过 %d）" % (len(result["record"]["applied"]),
                                          len(result["record"]["skipped"])),
         "verdict": "pass" if result["record"]["applied"] else "fail",
         "evidence": "edit-record.json"},
        {"check": "source_sha_recorded", "required": "记录原图指纹",
         "measured": result["record"]["source_sha256"][:16],
         "verdict": "pass" if result["record"]["source_sha256"] else "fail",
         "evidence": "edit-record.json"},
        {"check": "png_real", "required": "PNG 可解析 IHDR",
         "measured": "engine=%s" % png_rec.get("engine"),
         "verdict": "pass" if png_rec.get("verified") else "fail",
         "evidence": "figure.png"},
        {"check": "pdf_real", "required": "%PDF- 头 + 页对象",
         "measured": "engine=%s pages=%s" % (pdf_rec.get("engine"), pdf_rec.get("pages")),
         "verdict": "pass" if pdf_rec.get("verified") else "fail", "evidence": "figure.pdf"},
    ]
    cmap = [{"kind": "edited_element", "id": a.get("id"), "op": a.get("op"),
             "before": a.get("before", a.get("value", "")), "after": a.get("after", ""),
             "source": {"id": "S1", "path": src.name, "locator": "workorder",
                        "quote": json.dumps(ops, ensure_ascii=False)[:220]}}
            for a in result["record"]["applied"]]
    res = minimal_result(cid, contract, "ok")
    res["status_reason"] = ("edit 模式：%d 处修改已应用、%d 处跳过；PNG=%s；PDF=%s"
                            % (len(result["record"]["applied"]),
                               len(result["record"]["skipped"]),
                               png_rec.get("engine"), pdf_rec.get("engine")))
    res["summary"] = "在 %s 上做保源修改：%d 处，其余元素字节不变" % (
        src.name, len(result["record"]["applied"]))
    res["editable_source"] = {
        "path": "figure.svg", "format": "svg", "editable": True,
        "layers": sorted(set(re.findall(r'<g id="(layer-[^"]+)"', result["svg"]))),
        "text_count": svg_text_count, "sha256": C.sha256_file(arts["svg"]),
        "text_preserved": True,
        "edit_record": "edit-record.json",
        "source_sha256": result["record"]["source_sha256"],
    }
    res["export_artifact"] = {
        "png": {"path": "figure.png", "width": png_rec.get("width"),
                "height": png_rec.get("height"), "dpi": png_rec.get("dpi"),
                "engine": png_rec.get("engine"), "verified": png_rec.get("verified"),
                "ink_ratio": png_rec.get("ink_ratio"),
                "attempts": png_rec.get("attempts", [])},
        "pdf": {"path": "figure.pdf", "pages": pdf_rec.get("pages"),
                "vector": pdf_rec.get("vector"), "engine": pdf_rec.get("engine"),
                "verified": pdf_rec.get("verified")},
    }
    res["content_map"] = cmap
    res["compliance_checks"] = checks
    res["exceptions"] = exceptions
    res["outputs"] = {"editable_source": "figure.svg", "preview_png": "figure.png",
                      "vector_pdf": "figure.pdf", "result": "result.json",
                      "edit_record": "edit-record.json"}
    res["sources"] = [{"source_id": "S1", "path": src.name, "kind": "svg",
                       "pages_or_paras": 1}]
    res["changes"] = [{"action": "edit", "what": "%s.%s" % (a.get("id"), a.get("op")),
                       "reason": "按工单修改，其余元素保留"} for a in result["record"]["applied"]]
    res["uncertainty"] = [{"item": "被改元素之外的语义一致性",
                           "why": "本模式只改点名元素，不复查整图科学内容",
                           "handling": "如需重排/重绘请走 create 流程"}]
    res["runtime"] = {"steps": [{"step": "edit", "seconds": round(time.time() - t0, 2),
                                 "ops": len(ops or [])}], "budget": BUDGET}
    echo_contract(res, contract)
    C.dump_json(p["output"] / "result.json", res)
    log("edit done: applied=%d skipped=%d png=%s pdf=%s" %
        (len(result["record"]["applied"]), len(result["record"]["skipped"]),
         png_rec.get("engine"), pdf_rec.get("engine")))
    print("EDIT_%s applied=%d skipped=%d" % ("OK" if result["record"]["applied"] else "PARTIAL",
                                             len(result["record"]["applied"]),
                                             len(result["record"]["skipped"])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ga_build", description=__doc__)
    ap.add_argument("command", choices=["init", "show", "check", "build", "selfcheck", "edit"])
    ap.add_argument("--input", default=None)
    ap.add_argument("--work", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--fast", action="store_true", help="跳过浏览器/高开销引擎")
    ap.add_argument("--force", action="store_true", help="init 时覆盖已有草稿")
    ap.add_argument("--ops", default=None, help="edit 模式的操作文件")
    ap.add_argument("--chars", type=int, default=14000, help="show 的输出预算（字符）")
    ap.add_argument("--edit-dpi", type=int, default=150, help="edit 模式下导出件声明的 dpi")
    args = ap.parse_args(argv)
    p = C.paths(args.input, args.work, args.output)
    C.ensure_dirs(p)
    t0 = time.time()
    try:
        fn = {"init": cmd_init, "show": cmd_show, "check": cmd_check,
              "build": cmd_build, "selfcheck": cmd_selfcheck, "edit": cmd_edit}[args.command]
        fn(p, args)
    except Exception as exc:                                      # exit code is always 0
        import traceback
        print("GA_BUILD_ERROR %s" % exc)
        traceback.print_exc()
        try:
            C.ensure_dirs(p)
            case = read_case(p)
            contract = C.resolve_contract(case)
            res = minimal_result(case_id_of(case, p["work"]), contract, "partial",
                                 "命令 %s 异常: %s" % (args.command, str(exc)[:150]))
            res["errors"] = [{"where": args.command, "what": str(exc)[:300],
                              "impact": "本次运行未完成"}]
            C.dump_json(p["output"] / "result.json", res)
        except Exception:
            pass
    print("elapsed=%.2fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())





