# -*- coding: utf-8 -*-
"""run.py —— 一键流水线：case → 模板解析 → 材料抽取 → 页级计划 → 套版 → 复核 → 渲染 → result.json。

    python scripts/run.py --input /input/case.json --out /app/output --backend auto

设计要点：
  * **幂等**：同一 case 复跑，除时间戳外结果可复现（所有产物带 sha256）；
  * **可中断**：每一步的中间产物都落盘（template_map/source_map/slide_plan/…），
    后一步失败时前面的成果仍可交付；
  * **诚实降级**：缺模板用自带学术模板并记 uncertainty；缺源文件→partial；
    渲染不可用→保留 HTML 预览 + partial，绝不伪造 PDF；
  * **可交付**：最后一定写出 result.json（status 反映真实完成度）。

参数：
  --input       case.json 或包含 case.json 的目录（平台给的是 /input/case.json）
  --out         产物目录（平台要求 /app/output）
  --work        中间文件目录（默认 <out>/work）
  --template    覆盖 case 里的模板路径
  --plan        用 agent 改过的 plan.json（不再自动生成）
  --backend     auto | powerpoint | soffice | none
  --iterations  渲染回测-修正的轮数上限（默认 2）
  --baseline    额外跑一次"直接粘正文"的基线并给出对照指标
  --narrative   agent 写的叙述 md，合并进 result.json.narrative
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）
import time
import traceback

import units
import pptx_util as U
import pptx_util
import template_probe
import source_extract
import plan_deck
import build_pptx
import fit_check
import render_preview
import audit

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED_TEMPLATE = os.path.join(SKILL_ROOT, "templates", "academic-16x9.pptx")


def log(msg: str) -> None:
    print("[run] " + msg, flush=True)


def resolve_input(path: str) -> tuple:
    """返回 (case_dict, case_dir)。允许直接给目录。"""
    if os.path.isdir(path):
        cj = os.path.join(path, "case.json")
        if os.path.isfile(cj):
            return json.load(open(cj, encoding="utf-8")), path
        # 没有 case.json：按目录里的文件推断（平台也可能只给材料）
        case = {"case_id": "INLINE-" + os.path.basename(os.path.abspath(path)),
                "task": "从目录材料推断：学术汇报套版",
                "source": None, "template": None}
        for f in sorted(glob.glob(os.path.join(path, "*"))):
            low = f.lower()
            if low.endswith((".pptx",)) and "template" in low:
                case["template"] = f
            elif low.endswith((".pptx",)):
                case.setdefault("starting_deck", f)
            elif low.endswith((".pdf", ".md", ".docx", ".txt")):
                case["source"] = {"path": f}
        case["_inferred"] = True
        return case, path
    if os.path.isfile(path):
        return json.load(open(path, encoding="utf-8")), os.path.dirname(os.path.abspath(path))
    raise FileNotFoundError(path)


def resolve_path(p: str | None, case_dir: str) -> str | None:
    return resolve_with_origin(p, case_dir)[0]


def resolve_with_origin(p: str | None, case_dir: str) -> tuple:
    """路径解析顺序（D14-R1b，与 cwd 无关）：**case.json 所在目录** → cwd → `/input`。

    返回 (绝对路径|None, 来源标记)。来源标记写进 result.resolution / source_map，
    便于复核"这份材料到底是从哪儿找到的"。
    """
    if not p:
        return None, None
    if os.path.isabs(p):
        return (os.path.abspath(p), "absolute") if os.path.isfile(p) else (None, None)
    cands = [("case_dir", case_dir), ("cwd", os.getcwd()), ("input", "/input")]
    for tag, base in cands:
        if not base:
            continue
        c = os.path.normpath(os.path.join(base, p))
        if os.path.isfile(c):
            return os.path.abspath(c), tag
    return None, None


def prepare_source(case: dict, case_dir: str, work: str) -> tuple:
    """把源材料复制到 work（md 的图路径改写成 work 里生成的绝对路径），并出图。

    D14-R1b：材料与数据表一律**先相对 case.json 所在目录**解析，再回退 cwd、`/input`；
    解析来源记进 info["resolved_from"]（写进 result.resolution）。
    """
    src = case.get("source")
    kind = None
    src_path = None
    origin = None
    if isinstance(src, dict):
        src_path, origin = resolve_with_origin(src.get("path") or src.get("file"), case_dir)
        kind = src.get("kind")
    elif isinstance(src, str):
        src_path, origin = resolve_with_origin(src, case_dir)
    if not src_path:
        # 兜底：case 目录里唯一一份论文类文件
        for pat in ("*.pdf", "*.md", "*.docx", "*.txt"):
            hits = glob.glob(os.path.join(case_dir, pat))
            if len(hits) == 1:
                src_path = hits[0]
                origin = "case_dir_scan"
                break
    if not src_path:
        return None, None, {"error": "未找到源材料（case.source 缺失且目录里没有唯一候选）"}

    ext = os.path.splitext(src_path)[1].lstrip(".").lower()
    info = {"original": src_path, "kind": kind or ext, "copied": None,
            "resolved_from": origin}
    figures = []
    figdir = os.path.join(work, "figures")
    os.makedirs(figdir, exist_ok=True)
    for i, spec in enumerate(case.get("figure_specs") or [], 1):
        try:
            out = os.path.join(figdir, "fig%d.png" % i)
            csv_given = spec.get("csv")
            csv_path, csv_origin = resolve_with_origin(csv_given, case_dir)
            spec2 = dict(spec)
            if csv_path:
                spec2["csv"] = csv_path      # 先按 case 目录解析，再回退 cwd//input
            rep = source_extract.make_figure(spec2, case_dir, out)
            rep["label"] = spec.get("label") or ("Figure %d" % i)
            rep["spec_index"] = i
            rep["csv_resolved_from"] = csv_origin
            figures.append(rep)
        except Exception as exc:
            figures.append({"error": str(exc), "spec": spec.get("label"), "spec_index": i,
                            "csv": spec.get("csv")})
    info["figures_generated"] = figures

    if ext in ("md", "txt"):
        text = open(src_path, encoding="utf-8", errors="replace").read()
        for rep in figures:
            if rep.get("out") and os.path.isfile(rep["out"]):
                # 源稿里可能写 figures/fig1.png、fig01.png、或别的目录名：
                # 用序号匹配 basename，统一改写成 work 里真实存在的绝对路径。
                idx = rep.get("spec_index") or 1
                pat = re.compile(r"\(([^)\s]+)\)")
                want = re.compile(r"fig0*%d\.(png|jpe?g|svg|pdf)" % idx, re.I)
                newpath = rep["out"].replace("\\", "/")

                def _repl(m, want=want, newpath=newpath):
                    inner = m.group(1).strip("<>")
                    base = os.path.basename(inner).lower()
                    return "(%s)" % newpath if want.fullmatch(base) else m.group(0)
                text, n = pat.subn(_repl, text)
                rep["rewritten_in_source"] = n
        dst = os.path.join(work, "source.md")
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(text)
        info["copied"] = dst
        return dst, "md", info
    if ext == "pdf":
        dst = os.path.join(work, "source.pdf")
        shutil.copyfile(src_path, dst)
        info["copied"] = dst
        return dst, "pdf", info
    if ext == "docx":
        dst = os.path.join(work, "source.docx")
        shutil.copyfile(src_path, dst)
        info["copied"] = dst
        return dst, "docx", info
    return None, None, {"error": "不支持的源类型：%s" % ext}


def naive_baseline(case: dict, source_map: dict, template_map: dict, template: str,
                   work: str, backend: str) -> dict:
    """基线：模拟"把论文整段粘进模板"的做法（不做阶梯/不做定位/图片拉伸），用于量化增益。

    这是**自建基线**，代表基础做法在同输入下的产物，不是组织方白板。
    """
    from pptx.util import Pt, Inches
    from pptx import Presentation as P
    prs = U.load(template)
    U.strip_slides(prs)
    blocks = [b for b in source_map.get("blocks") or [] if b["kind"] in ("para", "caption")]
    body = "\n".join(b["text"] for b in blocks)
    layouts = prs.slide_layouts

    def layout_by_role(role, fallback=1):
        info = plan_deck._layout_for_role(template_map, role)
        return layouts[info["index"]] if info else layouts[min(fallback, len(layouts) - 1)]

    slides_plan = [{"index": 1, "role": "title", "title": source_map.get("title") or "Untitled",
                    "subtitle": "", "bullets": [], "figure": None, "notes": ""}]
    s = U.new_slide(prs, layout_by_role("title", 0))
    ph = _find_ph_baseline(s, "title") or _find_ph_baseline(s, "subtitle")
    if ph is not None and ph.has_text_frame:
        ph.text_frame.text = source_map.get("title") or "Untitled"
    chunks = [body[i:i + 900] for i in range(0, len(body), 900)] or [""]
    pic = next((f for f in (source_map.get("figures") or []) if f.get("image")
                and os.path.isfile(f["image"])), None)
    for i, ch in enumerate(chunks, 2):
        slide = U.new_slide(prs, layout_by_role("bullets", 1))
        t = _find_ph_baseline(slide, "title")
        if t is not None and t.has_text_frame:
            t.text_frame.text = "内容 %d" % (i - 1)
        b = _find_ph_baseline(slide, "body") or _find_ph_baseline(slide, "object")
        if b is not None and b.has_text_frame:
            tf = b.text_frame
            tf.text = ch              # 整段粘贴：不做阶梯、不写 autofit、不做定位
            for para in tf.paragraphs:
                for r in para.runs:
                    r.font.size = Pt(18)
        if pic and i == 2:            # 图片直接按容器宽高塞进去 → 拉伸变形
            try:
                slide.shapes.add_picture(pic["image"], Inches(8.6), Inches(1.4),
                                         Inches(4.4), Inches(4.6))
            except Exception:
                pass
        slides_plan.append({"index": i, "role": "bullets", "title": "内容 %d" % (i - 1),
                            "claim": "", "bullets": [{"text": ch, "level": 0, "locator": ""}],
                            "figure": None, "notes": ""})
    plan = {"case_id": case.get("case_id"), "meta": {"fonts": plan_deck._font_plan(case, template_map),
            "ladders": {"body": [18], "title": [32], "caption": [14], "min_body_pt": 14}},
            "slides": slides_plan}
    out_pptx = os.path.join(work, "baseline.pptx")
    try:
        prs.save(out_pptx)
        fit = fit_check.check(out_pptx, plan, source_map, template_map)
        ren = render_preview.render(out_pptx, os.path.join(work, "baseline_render"),
                                    backend, plan=plan)
    except Exception as exc:
        return {"error": "baseline failed: %s" % exc}
    fm, rm = fit["metrics"], ren
    m = {
        "slides": len(slides_plan),
        "slides_with_overflow": fm.get("slides_with_text_overflow"),
        "min_body_pt": fm.get("min_body_pt"),
        "locator_coverage": fm.get("locator_coverage"),
        "quote_verified_rate": fm.get("quote_verified_rate"),
        "figure_aspect_max_deviation": fm.get("figure_aspect_max_deviation"),
        "figures": fm.get("figures"),
        "render_ok": rm.get("ok"),
        "pdf_text_coverage_min": min([p.get("text_coverage", 1.0)
                                      for p in rm.get("pages") or []], default=None),
    }
    return {"metrics": m, "plan_slides": len(slides_plan),
            "note": "自建基线：正文按 900 字整段粘进模板正文占位符（18pt、无 autofit、无定位、"
                    "图按容器宽高直接拉伸）。用于同输入下的效果对照，不代表组织方白板。"}


def _find_ph_baseline(slide, kind):
    for ph in slide.placeholders:
        if U.ph_kind(ph) == kind:
            return ph
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="academic paper → templated editable pptx (pipeline)")
    ap.add_argument("--input", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default=None)
    ap.add_argument("--template", default=None)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "powerpoint", "soffice", "none"])
    ap.add_argument("--iterations", type=int, default=2)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--narrative", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    outdir = os.path.abspath(a.out)
    work = os.path.abspath(a.work or os.path.join(outdir, "work"))
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    pipeline = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "steps": [], "errors": [], "args": vars(a)}
    result_written = None

    def step(name, **kv):
        pipeline["steps"].append(dict(step=name, **kv))
        if not a.quiet:
            log("%s %s" % (name, json.dumps(kv, ensure_ascii=False)[:160]))

    case, case_dir = resolve_input(a.input)
    case_id = case.get("case_id") or case.get("id") or "UNKNOWN"
    # D14-R1b：解析来源账本（与 cwd 无关：case 目录 → cwd → /input）
    resolution = {"cwd": os.getcwd(), "case_json": os.path.abspath(a.input),
                  "case_dir": os.path.abspath(case_dir), "entries": []}

    def note_resolution(kind, given, found, origin):
        resolution["entries"].append({"kind": kind, "given": given,
                                      "resolved": os.path.basename(found) if found else None,
                                      "resolved_from": origin or "not_found"})
        return found

    step("1_case", case_id=case_id, case_dir=os.path.basename(case_dir),
         inferred=bool(case.get("_inferred")), cwd=os.path.basename(os.getcwd()))

    # ---- 模板：案例模板 → 包内遗留 pptx（若有）→ **按文本 spec 运行时合成**
    tmpl, tmpl_origin = resolve_with_origin(a.template, case_dir)
    if not tmpl:
        tmpl, tmpl_origin = resolve_with_origin(case.get("template"), case_dir)
    note_resolution("template", a.template or case.get("template"), tmpl, tmpl_origin)
    case_spec = None
    if tmpl and tmpl.lower().endswith(".json"):
        # 案例给的是**文本模板规格**（不是 pptx）：当作 spec 源，稍后运行期合成
        case_spec, _ = tmpl, tmpl_origin
        tmpl, tmpl_origin = None, None
        note_resolution("template_spec", case_spec, case_spec, "case_dir")
    template_source = "case(%s)" % (tmpl_origin or "?") if tmpl else None
    spec_note = None
    # 包内**没有任何二进制模板**（平台预检会拒二进制资源）：BUNDLED_TEMPLATE 只是历史占位，
    # 这里显式判定而不是靠 os.path.isfile 静默兜底 —— 缺失时留下可核对的降级记录。
    degraded = []
    if not tmpl:
        if os.path.isfile(BUNDLED_TEMPLATE):
            tmpl = BUNDLED_TEMPLATE
            template_source = "bundled-pptx"
        elif os.path.basename(BUNDLED_TEMPLATE) and not os.path.isfile(BUNDLED_TEMPLATE):
            degraded.append(
                "BUNDLED_TEMPLATE 不存在（%s）：按设计走文本规格合成母版，不使用任何二进制 pptx"
                % os.path.relpath(BUNDLED_TEMPLATE, SKILL_ROOT).replace("\\", "/"))
    if not tmpl:
        spec_path = case_spec or os.path.join(SKILL_ROOT, "templates", "template-spec.json")
        if os.path.isfile(spec_path):
            spec = pptx_util.load_template_spec(spec_path)
            tmpl = os.path.join(work, "template.pptx")
            try:
                info = pptx_util.build_template_from_spec(
                    spec, case.get("template_spec") or None, tmpl)
                template_source = "spec-synth(%s:%s)" % (
                    os.path.basename(spec_path), info.get("spec_name"))
                spec_note = ("模板由文本规格在运行时合成（Skill 包内不含二进制资源）：%s；结构复核 %s"
                             % (os.path.basename(spec_path),
                                json.dumps(info.get("spec_check"), ensure_ascii=False)))
            except Exception as exc:
                tmpl = None
                pipeline["errors"].append("spec 合成模板失败: %s" % exc)
        else:
            spec_note = "案例未提供模板，且包内无 template-spec.json —— 将无模板生成（版式全部合成）"
    if not tmpl:
        # 最后兜底：直接用 python-pptx 默认模板（仍能产出可编辑 pptx，但会记 uncertainty）
        tmpl = os.path.join(work, "template.pptx")
        from pptx import Presentation as _P
        _P().save(tmpl)
        template_source = "python-pptx-default"
    if spec_note:
        case.setdefault("_notes", []).append(spec_note)
    for d in degraded:  # 显式降级记录（不经 isfile 静默兜底）
        case.setdefault("_notes", []).append(d)
    step("2_template", path=os.path.basename(tmpl), source=template_source,
         degraded=len(degraded))
    tmap = template_probe.probe(tmpl)
    # 模板来源（case-pptx / spec-synth(<spec名>) / bundled / python-pptx-default）写进模板事实，
    # 供 result.json 与只读审计器核对"模板是否真的来自文本 spec 的运行期合成"
    tmap["template_origin"] = template_source
    tmap["degradations"] = degraded
    with open(os.path.join(outdir, "template_map.json"), "w", encoding="utf-8") as fh:
        json.dump(tmap, fh, ensure_ascii=False, indent=2)

    # ---- 材料
    src_path, src_kind, prep = prepare_source(case, case_dir, work)
    if prep.get("resolved_from") is not None or src_path:
        note_resolution("source", (case.get("source") or {}).get("path")
                        if isinstance(case.get("source"), dict) else case.get("source"),
                        src_path, prep.get("resolved_from"))
    for fg in prep.get("figures_generated") or []:
        note_resolution("figure_asset", fg.get("csv"), fg.get("out") or None,
                        fg.get("csv_resolved_from"))
    resolution["template_origin"] = template_source
    resolution["spec_file"] = os.path.relpath(
        os.path.join(SKILL_ROOT, "templates", "template-spec.json"), SKILL_ROOT)
    if not src_path:
        res = {"case_id": case_id, "task": case.get("task"), "status": "partial",
               "status_reason": "源材料不可用：" + prep.get("error", "?"),
               "summary": "没有可读取的论文/材料，未生成演示文稿。",
               "results": {"template": tmap, "plan": None, "build": None, "fit": None,
                           "render": None},
               "slides": [], "evidence": [], "sources": [], "uncertainty": [
                   {"item": "输入", "why": prep.get("error"), "handling": "如实报 partial"}],
               "change_log": [], "artifacts": [], "pipeline": pipeline,
               "output_contract_echo": {k: None for k in audit._contract_fields(case)},
               "contract_unresolved_fields": audit._contract_fields(case)}
        result_written = os.path.join(outdir, "result.json")
        json.dump(res, open(result_written, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        log("材料不可用 → partial（result.json 已写）")
        return 2
    step("3_source", file=os.path.basename(src_path), kind=src_kind,
         figures=len([f for f in prep.get("figures_generated") or [] if f.get("out")]))
    smap = source_extract.extract(src_path, work)
    page_texts = smap.pop("_page_texts", None)
    if page_texts:
        with open(os.path.join(work, "page_text.json"), "w", encoding="utf-8") as fh:
            json.dump(page_texts, fh, ensure_ascii=False, indent=1)
    # 源材料哈希按**原始文件**记（不是 work 里的副本）
    orig = prep.get("original")
    smap["source"]["resolved_from"] = prep.get("resolved_from") or "not_found"
    if orig and os.path.isfile(orig):
        smap["source"]["original_file"] = os.path.basename(orig)
        smap["source"]["sha256_original"] = units.sha256_file(orig)
        smap["source"]["source_sha256_used_for_extraction"] = smap["source"].get("sha256")
        smap["source"]["sha256"] = smap["source"]["sha256_original"]
    with open(os.path.join(outdir, "source_map.json"), "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in smap.items()}, fh, ensure_ascii=False, indent=2)
    step("4_extract", blocks=smap["stats"]["blocks"], sections=smap["stats"]["sections"],
         figures=smap["stats"]["figures"], chars=smap["stats"]["chars"])

    # 图绑定：源稿里图注存在但图片引用没对上时，按图序号把 figure_specs 生成的图接上
    gen = [g for g in (prep.get("figures_generated") or []) if g.get("out")]
    bound = []
    for f in smap.get("figures") or []:
        if f.get("image") and os.path.isfile(f["image"]):
            continue
        m = re.search(r"(\d+)", f.get("label") or "")
        idx = int(m.group(1)) if m else None
        cand = next((g for g in gen if idx and g.get("spec_index") == idx), None)
        if not cand and len(gen) == 1:
            cand = gen[0]
        if cand:
            f["image"] = cand["out"]
            f["kind"] = "generated"
            f["note"] = "由 case.figure_specs 从数据表生成（非论文原图）"
            bound.append(f.get("label"))
    if bound:
        step("4b_figure_bind", figures=bound)
    # ---- 计划
    if a.plan:
        plan = json.load(open(a.plan, encoding="utf-8"))
        plan_src = "agent"
    else:
        plan = plan_deck.build_plan(case, smap, tmap, work)
        plan_src = "auto-seed"
    val = plan_deck.validate_plan(plan, case, smap, tmap)
    step("5_plan", source=plan_src, slides=len(plan.get("slides") or []),
         ok=val["ok"], findings=len(val["findings"]))
    with open(os.path.join(outdir, "slide_plan.json"), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)

    # ---- 套版 + 复核 + 渲染（含渲染回测修正）
    deck = os.path.join(outdir, "%s.pptx" % re.sub(r"[^\w.-]+", "-", case_id)[:40])
    build_log = None
    fit = None
    render = None
    for it in range(max(1, a.iterations)):
        build_log = build_pptx.build(plan, tmpl, deck, tmap,
                                     starting_deck=case.get("starting_deck"))
        fit = fit_check.check(deck, plan, smap, tmap, build_log)
        render = render_preview.render(deck, outdir, a.backend, plan=plan)
        step("6_build_fit_render", iter=it + 1, slides=fit["metrics"]["slides"],
             overflow=fit["metrics"]["textboxes_over_container"],
             render_ok=render.get("ok"), pages=render.get("page_count"))
        high_fit = [i for i in fit["issues"] if i["severity"] == "high"]
        # 只对"确实溢出"做一轮保守修正：把该页最后一条 bullet 移入备注
        if not high_fit or it + 1 >= a.iterations:
            break
        changed = False
        for issue in high_fit:
            if issue["item"] != "文本框溢出容器":
                continue
            idx = issue.get("slide")
            spec = next((s for s in plan["slides"] if s.get("index") == idx), None)
            if not spec or len(spec.get("bullets") or []) <= 1:
                continue
            moved = spec["bullets"].pop()
            spec.setdefault("overflow_to_notes", []).append(
                {"text": moved["text"][:120], "locator": moved.get("locator")})
            spec["notes"] = (spec.get("notes") or "") + "\n[回测移入] " + moved["text"][:160]
            plan.setdefault("change_log", []).append(
                {"what": "渲染回测溢出修正", "slide": idx,
                 "why": "第 %d 轮 PDF/复核判定溢出，移入 1 条到备注" % (it + 1)})
            changed = True
        if not changed:
            break
        step("6b_replan", iter=it + 1, note="溢出修正后重建")

    # ---- 空产物守卫（教训：输入发现被路径段过滤吞掉时会产出 0 页却报 success）
    empty_guard = []
    if not (plan.get("slides") or []):
        empty_guard.append("计划为空（0 页）：输入材料/模板可能未被发现或解析为空")
    if fit and fit.get("metrics", {}).get("slides") == 0:
        empty_guard.append("生成的 pptx 页数为 0")
    if not (smap.get("blocks") or []):
        empty_guard.append("材料解析出 0 个内容块（源文件可能是空文件/扫描件/路径未命中）")
    if empty_guard:
        pipeline.setdefault("guards", []).extend(empty_guard)

    # ---- 基线对照（可选）
    base = None
    if a.baseline:
        base = naive_baseline(case, smap, tmap, tmpl, work, a.backend)
        if "metrics" in base and build_log:
            def d(key, get):
                b = base["metrics"].get(key)
                c = get()
                if b is None or c is None:
                    return None
                return round((c - b), 4)
            fm = fit["metrics"]
            base["deltas"] = {
                "slides": d("slides", lambda: fm["slides"]),
                "overflow_slides": d("slides_with_overflow", lambda: fm["slides_with_text_overflow"]),
                "min_body_pt": d("min_body_pt", lambda: fm["min_body_pt"]),
                "locator_coverage": d("locator_coverage", lambda: fm["locator_coverage"]),
                "quote_verified_rate": d("quote_verified_rate", lambda: fm["quote_verified_rate"]),
                "figures": d("figures", lambda: fm["figures"]),
                "figure_aspect_max_deviation": d(
                    "figure_aspect_max_deviation", lambda: fm["figure_aspect_max_deviation"]),
                "pdf_text_coverage_min": d("pdf_text_coverage_min", lambda: min(
                    [p.get("text_coverage", 1.0) for p in render.get("pages") or []],
                    default=None)),
            }
            base["deltas_note"] = ("delta = 本 Skill − 基线；正数表示本 Skill 更大/更高。"
                                   "检出的问题数（overflow_slides / aspect / coverage）越小越好。")
            with open(os.path.join(outdir, "baseline_comparison.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(base, fh, ensure_ascii=False, indent=2)
            step("7_baseline", ok=bool(base.get("metrics")), deltas=base.get("deltas"))

    # ---- 汇总
    narrative = open(a.narrative, encoding="utf-8").read() if a.narrative else None
    res = audit.build_result(case, plan, smap, tmap, build_log, fit, render, outdir,
                             deck, narrative=narrative, baseline=base)
    res["pipeline"] = pipeline
    # D14-R1b：路径解析账本（case 目录 → cwd → /input），供复核"与 cwd 无关"
    res["resolution"] = resolution
    if empty_guard:  # 空产物一律降级为 partial，并写清具体原因
        res["status"] = "partial"
        res["status_reason"] = "空产物守卫：" + "；".join(empty_guard) + \
            "（已产出物不作数）"
        res.setdefault("uncertainty", []).append(
            {"item": "空产物", "why": "；".join(empty_guard),
             "handling": "降级为 partial，避免 0 页却报 success（同类 bug 的教训）"})
    if case.get("_notes"):
        res["uncertainty"].append({"item": "输入", "why": "；".join(case["_notes"]),
                                   "handling": "已在结果中说明"})
    if degraded:  # 模板降级单列一条，评审可在 uncertainty 里直接看到码与判据字段
        res["uncertainty"].append({
            "item": "模板降级（BUNDLED_TEMPLATE_MISSING）",
            "why": "；".join(degraded),
            "handling": "按文本规格合成母版；判据字段 results.template.origin==spec-synth(...)、"
                        "results.template.degradations[]、template_map.json.degradations[]"})
    if prep.get("figures_generated"):
        res["results"]["figures"] = prep["figures_generated"]
    audit.write_outputs(res, outdir, plan, smap)
    result_written = os.path.join(outdir, "result.json")
    elapsed = round(time.time() - t0, 1)
    res["pipeline"] = pipeline
    res["pipeline"]["elapsed_s"] = elapsed
    # 所有文件写完后重算产物哈希，保证 outputs[] 自述与磁盘一致（D14-R3 只读审计据此比对）
    audit.refresh_artifacts(res, outdir, deck)
    json.dump(res, open(result_written, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # result.json 的自身完整性另写 result.sha256（自指哈希放不进 result.json 本身）
    with open(os.path.join(outdir, "result.sha256"), "w", encoding="utf-8") as fh:
        fh.write("%s  result.json\n" % units.sha256_file(result_written))
    step("8_audit", status=res["status"], elapsed_s=elapsed,
         artifacts=len([x for x in res["artifacts"] if x.get("exists")]))
    print("[run] DONE status=%s → %s (%.1fs)" % (res["status"], outdir, elapsed))
    return 0 if res["status"] == "success" else (6 if res["status"] == "partial" else 1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
