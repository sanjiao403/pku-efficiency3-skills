"""run.py - zero-argument entry point: /input/case.json -> /app/output.

    python3 scripts/run.py                     # full run on /input/case.json
    python3 scripts/run.py --case X.json --out Y --work Z
    python3 scripts/run.py --plan-only         # stop after the page plan
    python3 scripts/run.py --no-render         # skip the office/PDF step
    python3 scripts/run.py --dry-run           # 8-second smoke test, no render

Timing discipline (the狠 part of the platform contract): a result.json that is
honest but partial is written **first**, within the first second, and rewritten
after every stage.  A crash, a timeout or a missing office suite therefore still
leaves a reviewable deliverable plus an explicit statement of what is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import assets as A
import contract as C
import deck as D
import inventory as I
import layout as L
import notes as N
import outline as O
import papertext as P
import plan_validate as PV
import qa as Q
import render as R
from util import (Log, ensure_dir, one_line, read_json, rel_posix, sha256_text,
                  truncate, write_json, write_text)

SKILL_VERSION = "1.0.0"
DEFAULT_INPUT = "/input/case.json"
DEFAULT_OUT = "/app/output"
DEFAULT_WORK = "/app/work"


# ---------------------------------------------------------------- helpers

def _find_materials(case: dict, case_path: str) -> list[str]:
    """Resolve the material paths a case declares, then fall back to its folder."""
    base = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    cands: list[str] = []
    for key in ("materials", "material", "sources", "inputs", "papers", "files",
                "input_files", "paper"):
        val = case.get(key)
        if isinstance(val, str):
            cands.append(val)
        elif isinstance(val, list):
            cands.extend([v for v in val if isinstance(v, str)])
    out, missing = [], []
    for c in cands:
        p = c if os.path.isabs(c) else os.path.join(base, c)
        if os.path.exists(p):
            out.append(p)
        else:
            missing.append(c)
    if out:
        return out + [f"MISSING:{m}" for m in missing]
    # nothing declared (or nothing found): use the case folder, ignoring the
    # case file itself and anything that looks like an answer key
    for entry in sorted(os.listdir(base)):
        p = os.path.join(base, entry)
        if os.path.abspath(p) == os.path.abspath(case_path):
            continue
        if entry.lower().endswith((".json", ".md")) and "case" in entry.lower():
            continue
        if os.path.isdir(p) or os.path.splitext(entry)[1].lower() in P.SUPPORTED:
            out.append(p)
    return out


def _split_missing(paths: list[str]) -> tuple[list[str], list[str]]:
    real = [p for p in paths if not p.startswith("MISSING:")]
    missing = [p[len("MISSING:"):] for p in paths if p.startswith("MISSING:")]
    return real, missing


def _skeleton(case: dict, contract: dict, case_id, out: str) -> dict:
    """The 'something honest on disk in the first second' result."""
    produced = {
        "deliverable": "",
        "deck": {"pptx": None, "pdf": None, "slides": []},
        "slides": [],
        "evidence_map": [],
        "render": {"engine": None, "preview_mode": None, "pdf": None, "pngs": []},
        "notes": "",
        "status": "partial",
        "sources": [],
        "uncertainty": ["run started; nothing produced yet"],
        "changes": [{"stage": "init", "note": "result skeleton written"}],
    }
    res = C.fill(case, produced, contract=contract)
    res["case_id"] = case_id
    res["skill"] = {"name": "paper2deck", "version": SKILL_VERSION}
    write_json(os.path.join(out, "result.json"), res)
    return res


# ---------------------------------------------------------------- main flow

def run(case_path: str, out_dir: str, work_dir: str, *, do_render: bool = True,
        plan_only: bool = False, dry_run: bool = False) -> dict:
    t0 = time.time()
    out_dir = ensure_dir(out_dir)
    work_dir = ensure_dir(work_dir)
    log = Log(os.path.join(out_dir, "run.log"))
    log(f"paper2deck {SKILL_VERSION} start; case={case_path}")
    perf: list[dict] = []

    def stage(name):
        perf.append({"stage": name, "t": round(time.time() - t0, 2)})

    case = {}
    for cand in (case_path, os.path.join(os.path.dirname(case_path or ""), "case.json")):
        if cand and os.path.isfile(cand):
            try:
                case = C.load_case(cand)
                case_path = cand
                break
            except Exception as exc:
                log.warn(f"cannot parse case json {cand}: {exc}")
    case_id = case.get("case_id") or case.get("id") or (
        (case.get("case") or {}).get("case_id") if isinstance(case.get("case"), dict) else None)
    if case_id is None and case_path:
        case_id = os.path.splitext(os.path.basename(case_path))[0]
    contract = C.detect(case)
    log(f"contract fields: {[f['name'] for f in contract['fields']]} (from {contract['source']})")
    _skeleton(case, contract, case_id, out_dir)
    stage("skeleton")

    changes = [{"stage": "init", "note": "result skeleton written before any work"}]
    uncertainty: list[str] = []
    materials, missing = _split_missing(_find_materials(case, case_path))
    if missing:
        uncertainty.append("declared material(s) not found: " + ", ".join(missing[:6]))
    if not materials:
        uncertainty.append("no readable material found next to the case file; "
                           "deck cannot be built from evidence")
        res = _finish(case, contract, case_id, out_dir, {
            "status": "unsupported",
            "uncertainty": uncertainty,
            "changes": changes + [{"stage": "ingest", "note": "no material"}],
        }, perf, t0, log)
        return res

    # ---------------- ingest
    src = P.Source()
    for m in materials:
        # the case file is an input, not scientific material: never let it be
        # quoted as page evidence when a case declares its whole folder
        part = P.ingest(m, exclude=(case_path,))
        src.segments.extend(part.segments)
        src.files.extend(part.files)
        src.notes.extend(part.notes)
        src.bib.update(part.bib)
        src.text_layer = src.text_layer and part.text_layer
    for i, seg in enumerate(src.segments, start=1):
        seg["id"] = f"seg-{i:04d}"
    log(f"ingested {len(src.segments)} located segments from {len(src.files)} file(s)")
    stage("ingest")
    if not src.text_layer:
        uncertainty.append("source PDF has no usable text layer; figures/labels may be "
                           "incomplete (OCR step not applied here)")
    if len(src.segments) < 4:
        uncertainty.append(f"only {len(src.segments)} text segments recovered from the "
                           f"material; the page plan is necessarily thin")

    inv = I.build(src)
    write_json(os.path.join(out_dir, "inventory.json"), inv.to_dict(src))
    stage("inventory")
    if inv.notes:
        uncertainty.extend(inv.notes[:6])

    # ---------------- plan
    case_meta = dict(case.get("__deck__") or {})
    for k in ("title", "subtitle", "audience", "language", "duration_min", "slide_limit",
              "template", "footer"):
        if case.get(k) is not None:
            case_meta[k] = case[k]
    tmpl_case = case.get("__deck__", {}).get("template") if isinstance(case.get("__deck__"), dict) else None
    if tmpl_case:
        case_meta["template"] = tmpl_case
    plan = O.draft(src, inv, case_meta)
    plan["deck"]["case_id"] = case_id

    # author-supplied plan wins (a human/agent may pre-write pages/*.json)
    plan_path = os.path.join(os.path.dirname(os.path.abspath(case_path)), "plan.json")
    if os.path.isfile(plan_path):
        try:
            ext = read_json(plan_path)
            if isinstance(ext, dict) and ext.get("slides"):
                plan["slides"] = ext["slides"]
                plan["storyline"] = ext.get("storyline") or plan["storyline"]
                plan["deck"].update({k: v for k, v in (ext.get("deck") or {}).items()
                                     if v is not None})
                plan["draft"]["auto"] = False
                plan["draft"]["drafter"] = os.path.basename(plan_path)
                changes.append({"stage": "plan", "note": "author plan.json adopted"})
                log("author plan.json found and adopted")
        except Exception as exc:
            log.warn(f"plan.json rejected: {type(exc).__name__}: {exc}")
            uncertainty.append(f"case plan.json could not be adopted: {exc}")
    O._finalize_pages(plan)

    # ---------------- evidence lock
    validation = PV.validate(plan, src, inv)
    write_json(os.path.join(out_dir, "validation.json"), validation)
    stage("validate")
    if not validation["ok"]:
        log.warn(f"evidence lock: {validation['counts']['error']} error(s)")
        uncertainty.append(
            f"{validation['counts']['error']} page(s)/value(s) could not be anchored in the "
            f"source: " + "; ".join(e["message"] for e in validation["errors"][:3]))
    if dry_run:
        res = _finish(case, contract, case_id, out_dir, {
            "plan": plan, "inventory": inv.to_dict(src), "validation": validation,
            "status": "partial",
            "uncertainty": uncertainty + ["dry-run: deck/render stages skipped"],
            "changes": changes + [{"stage": "dry-run", "note": "stopped after validation"}],
        }, perf, t0, log)
        return res

    # ---------------- assets + layout
    pdf_src = next((f["path"] for f in src.files if f["path"].lower().endswith(".pdf")), None)
    asset_root = ensure_dir(os.path.join(work_dir, "figures"))
    harvested = {"assets": {}, "report": {}}
    if pdf_src:
        pdf_abs = pdf_src if os.path.isabs(pdf_src) else os.path.join(
            os.path.dirname(os.path.abspath(case_path)), pdf_src)
        harvested = A.harvest(pdf_abs, inv, src, asset_root, log)
        for label, path in harvested["assets"].items():
            for s in plan["slides"]:
                if (s.get("figure") or {}).get("label") == label:
                    s["figure"]["asset"] = path
    stage("assets")

    template_path = plan["deck"].get("template")
    if template_path and not os.path.isabs(str(template_path)):
        cand = os.path.join(os.path.dirname(os.path.abspath(case_path)), str(template_path))
        template_path = cand if os.path.isfile(cand) else None
    tinfo = D.describe_template(template_path)
    boxes = L.slide_boxes(tinfo["slide"]["w_in"], tinfo["slide"]["h_in"])
    specs = []
    for s in plan["slides"]:
        specs.append(L.plan_slide_layout(s, boxes, with_figure=bool(s.get("figure")),
                                         with_table=bool(s.get("table")),
                                         with_kpis=bool(s.get("kpis"))))
    write_json(os.path.join(out_dir, "layout.json"), {
        "boxes": {k: v for k, v in boxes.items() if k != "geometry"},
        "slides": specs, "overflow": L.overflow_report(specs),
    })
    write_json(os.path.join(out_dir, "plan.json"), plan)
    stage("layout")

    # ---------------- build
    pptx_path = os.path.join(out_dir, "deck.pptx")
    deck_report = D.build(plan, specs, out_path=pptx_path, template_path=template_path,
                          assets=harvested["assets"], log=log)
    readback = D.read_back(pptx_path)
    write_json(os.path.join(out_dir, "deck-readback.json"), readback)
    log(f"built {deck_report['slides']} slides; readback min_font={readback['min_font_pt']}pt")
    stage("build")

    # ---------------- render
    render_info = {}
    if do_render:
        render_info = R.render(pptx_path, out_dir, specs=specs,
                               plan=dict(plan, deck=dict(plan["deck"],
                                                         slide_w_in=deck_report["slide_size_in"]["w"],
                                                         slide_h_in=deck_report["slide_size_in"]["h"])),
                               log=log)
        write_json(os.path.join(out_dir, "render.json"), render_info)
        if not render_info.get("ok"):
            uncertainty.append("no rendered preview could be produced on this host")
        elif render_info.get("preview_mode") != "real":
            uncertainty.append("preview is a model rendering of the layout spec, "
                               "not an office-suite render")
    else:
        uncertainty.append("rendering skipped by request (--no-render)")
    stage("render")

    # ---------------- audit
    audit = Q.audit(plan=plan, src=src, inv=inv, validation=validation,
                    deck_report=deck_report, readback=readback,
                    render_info=render_info, template_info=tinfo, specs=specs)
    write_json(os.path.join(out_dir, "audit.json"), audit)
    log(Q.summary(audit))
    stage("audit")

    # ---------------- deliverable text + evidence map
    deliverable = _deliverable_md(plan, validation, audit, deck_report, render_info)
    write_text(os.path.join(out_dir, "deck-outline.md"), deliverable)
    evidence_map = _evidence_map(plan, src)
    write_json(os.path.join(out_dir, "evidence-map.json"), evidence_map)
    write_text(os.path.join(out_dir, "speaker-notes.md"),
               _notes_md(plan, src))
    stage("write")

    status = "success"
    hard_fail = (validation["counts"]["error"] > 0
                 or not audit["ok"])
    if do_render and (render_info or {}).get("preview_mode") != "real":
        hard_fail = True
        uncertainty.append("no real rendered preview was produced; status downgraded "
                           "because the rubric requires a rendered preview of the "
                           "editable artefact")
    if hard_fail:
        status = "partial"
    produced = {
        "deliverable": deliverable,
        "deck": {
            "pptx": os.path.basename(pptx_path),
            "pdf": (render_info or {}).get("pdf"),
            "slides": [{"index": i + 1, "role": s.get("role"), "title": s.get("title"),
                        "claim": s.get("claim"),
                        "locator": (s.get("evidence") or [{}])[0].get("locator")}
                       for i, s in enumerate(plan["slides"])],
            "slide_count": deck_report["slides"],
            "template": deck_report["template"],
            "per_slide": deck_report["per_slide"],
        },
        "slides": [{"id": s.get("id"), "role": s.get("role"), "title": s.get("title"),
                    "claim": s.get("claim"), "bullets": s.get("bullets"),
                    "evidence": s.get("evidence"), "numbers": s.get("numbers")}
                   for s in plan["slides"]],
        "evidence_map": evidence_map,
        "render": {
            "engine": (render_info or {}).get("engine"),
            "preview_mode": (render_info or {}).get("preview_mode"),
            "pdf": (render_info or {}).get("pdf"),
            "pngs": (render_info or {}).get("pngs") or [],
            "png_dir": (render_info or {}).get("png_dir"),
            "fonts": _fonts_seen(pptx_path),
        },
        "notes": _notes_md(plan, src),
        "template": {"available": tinfo.get("available"), "path": tinfo.get("path") or "",
                     "layouts": [l["name"] for l in tinfo.get("layouts") or []],
                     "slide_size_in": tinfo.get("slide")},
        "audit": {"passed": audit["passed"], "total": audit["total"],
                  "dimensions": audit["dimensions"], "real_render": audit["real_render"]},
        "status": status,
        "sources": [{"path": f["path"], "reader": f["reader"]} for f in src.files],
        "uncertainty": uncertainty,
        "changes": changes + [
            {"stage": "build", "note": f"{deck_report['slides']} slides "
                                       f"({deck_report['template']['available'] and 'template' or 'built-in'} geometry)"},
            {"stage": "render", "note": f"engine={(render_info or {}).get('engine')}"},
            {"stage": "audit", "note": Q.summary(audit)},
        ],
        "performance": perf,
        "inventory": inv.to_dict(src),
        "validation": validation,
        "case_id": case_id,
    }
    res = _finish(case, contract, case_id, out_dir, produced, perf, t0, log)

    # ---------------- independent audit (artefacts only, never the plan layer)
    cross = _independent_audit(out_dir, case_path, log)
    res["audit_deck"] = cross
    if cross.get("available"):
        log(f"independent audit: {cross['passed']}/{cross['total']} checks passed "
            f"on deck.pptx")
        res.setdefault("changes", []).append(
            {"stage": "audit-deck",
             "note": f"{cross['passed']}/{cross['total']} independent checks passed"})
        if cross["failed"]:
            status = "partial"
            res["status"] = "partial"
            res["uncertainty"] = (res.get("uncertainty") or []) + [
                "independent audit (audit_deck.py) re-derived the deck from the artefacts "
                "and failed " + ", ".join(c["id"] for c in cross["checks"]
                                          if c["verdict"] != "pass")]

    # result.json is written last, and everything it hashes is already final
    log(f"done in {time.time() - t0:.1f}s status={res.get('status')}")
    res["outputs"] = _artifacts(out_dir)
    res["runtime"] = {"seconds": round(time.time() - t0, 2), "stages": perf}
    write_json(os.path.join(out_dir, "result.json"), res)
    return res


def _fonts_seen(pptx_path: str) -> dict:
    """Record which typefaces the file actually asks for (for the version note)."""
    import zipfile
    faces: dict[str, int] = {}
    try:
        with zipfile.ZipFile(pptx_path) as z:
            for name in z.namelist():
                if not name.endswith(".xml"):
                    continue
                data = z.read(name).decode("utf-8", "replace")
                for m in __import__("re").finditer(r'typeface="([^"]+)"', data):
                    faces[m.group(1)] = faces.get(m.group(1), 0) + 1
    except Exception:
        pass
    return dict(sorted(faces.items(), key=lambda kv: -kv[1]))


def _sha256_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


_ARTIFACT_KIND = {
    ".pptx": "editable-deck", ".pdf": "rendered-preview", ".png": "page-preview",
    ".md": "prose", ".json": "machine-readable", ".log": "run-log", ".ps1": "render-helper",
}


def _artifacts(out_dir: str, exclude=("result.json",)) -> list[dict]:
    """``outputs[]``: path / bytes / sha256 for every delivered artefact.

    ``result.json`` is excluded on purpose - a file cannot honestly carry its own
    digest, because writing the digest changes the bytes it would describe.  The
    contract therefore names it separately (``contract.self``) and points at
    ``audit_deck.py`` for the independent re-check.  Every other artefact in
    ``out_dir`` is hashed, so a reviewer can re-verify the delivery byte for byte.
    """
    out: list[dict] = []
    for root, dirs, files in os.walk(out_dir):
        dirs.sort()
        for name in sorted(files):
            p = os.path.join(root, name)
            rel = rel_posix(os.path.relpath(p, out_dir))
            if rel in exclude:
                continue
            ext = os.path.splitext(name)[1].lower()
            out.append({"path": rel, "bytes": os.path.getsize(p), "sha256": _sha256_file(p),
                        "kind": _ARTIFACT_KIND.get(ext, ext.lstrip(".") or "file")})
    out.sort(key=lambda o: o["path"])
    return out


def _independent_audit(out_dir: str, case_path: str, log) -> dict:
    """Re-derive expectations from the delivered artefacts only (never the plan).

    ``audit_deck.py`` reads ``deck.pptx``, ``result.json`` and the case material;
    it does not read ``plan.json``/``inventory.json``/``validation.json``.  A
    failure here is a real disagreement between the plan layer and the delivered
    file, so it is surfaced in ``audit_deck`` *and* downgrades ``status``.
    """
    try:
        import audit_deck
        report = audit_deck.audit(out_dir, case_path if os.path.isfile(case_path) else None)
    except Exception as exc:
        log.warn(f"independent audit could not run: {type(exc).__name__}: {exc}")
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    write_json(os.path.join(out_dir, "audit-deck.json"), report)
    return {
        "available": True,
        "auditor": report["auditor"],
        "passed": report["passed"],
        "total": len(report["checks"]),
        "failed": report["failed"],
        "checks": [{"id": c["id"], "check": c["check"], "verdict": c["verdict"],
                    "expected": c["expected"], "actual": c["actual"]}
                   for c in report["checks"]],
        "report": "audit-deck.json",
    }


def _deliverable_md(plan, validation, audit, deck_report, render_info) -> str:
    deck = plan.get("deck") or {}
    story = plan.get("storyline") or {}
    lines = [f"# {deck.get('title') or 'Academic deck'}", ""]
    if deck.get("audience"):
        lines.append(f"- audience: {deck['audience']}")
    if deck.get("duration_min"):
        lines.append(f"- planned talk: {deck['duration_min']} min, "
                     f"{len(plan.get('slides') or [])} pages")
    lines.append(f"- slide limit: {deck.get('slide_limit')}")
    lines += ["", "## Storyline", ""]
    for key in ("problem", "gap", "approach", "evidence", "result", "limits", "takeaway"):
        val = one_line(story.get(key) or "")
        lines.append(f"- **{key}**: {val or '(not derivable from the source - see uncertainty)'}")
    lines += ["", "## Page-by-page claim ladder", "",
              "| # | role | claim | source locator |", "|---:|---|---|---|"]
    for i, s in enumerate(plan.get("slides") or [], start=1):
        loc = ((s.get("evidence") or [{}])[0].get("locator") or "-")
        lines.append(f"| {i} | {s.get('role')} | {one_line(s.get('claim') or '')} | {loc} |")
    lines += ["", "## Verification", "",
              f"- evidence coverage: {validation['metrics']['evidence_coverage']} "
              f"({validation['metrics']['slides_with_locator']}/"
              f"{validation['metrics']['content_slides']} content pages)",
              f"- gates: {audit['passed']}/{audit['total']}",
              f"- render: {render_info.get('engine')} ({render_info.get('preview_mode')})",
              f"- deck: {deck_report['slides']} slides, "
              f"{deck_report['slide_size_in']['w']}x{deck_report['slide_size_in']['h']} in",
              ]
    return "\n".join(lines) + "\n"


def _evidence_map(plan, src) -> list[dict]:
    out = []
    for i, s in enumerate(plan.get("slides") or [], start=1):
        for e in s.get("evidence") or []:
            seg, found, kind = src.quote_locator(e.get("quote") or "")
            out.append({
                "page": i, "slide_id": s.get("id"), "role": s.get("role"),
                "claim": one_line(s.get("claim") or ""),
                "evidence_kind": e.get("kind"), "label": e.get("label"),
                "locator": e.get("locator"),
                "locator_verified": bool(found),
                "match": kind,
                "verified_locator": found,
                "quote": truncate(e.get("quote") or "", 200),
                "numbers": s.get("numbers") or [],
            })
        if not s.get("evidence"):
            out.append({"page": i, "slide_id": s.get("id"), "role": s.get("role"),
                        "claim": one_line(s.get("claim") or ""), "evidence_kind": None,
                        "label": None, "locator": None, "locator_verified": False,
                        "quote": "", "numbers": s.get("numbers") or [],
                        "not_derivable": one_line(s.get("evidence_absent_reason") or "")})
    return out


def _notes_md(plan, src) -> str:
    lines = ["# Speaker notes", "",
             "每页一段：过渡 / 讲解动作 / 证据位置 / 预设问答 / 时间。", ""]
    for i, s in enumerate(plan.get("slides") or [], start=1):
        info = N.compose(s, {}, plan, i - 1)
        lines += [f"## Page {i} · {s.get('title') or ''}", "", info["notes"], ""]
    return "\n".join(lines)


def _finish(case, contract, case_id, out_dir, produced, perf, t0, log) -> dict:
    produced = dict(produced)
    produced.setdefault("performance", perf)
    res = C.fill(case, produced, contract=contract)
    res["case_id"] = case_id
    res["status"] = produced.get("status", "partial")
    res["skill"] = {"name": "paper2deck", "version": SKILL_VERSION}
    res["runtime"] = {"seconds": round(time.time() - t0, 2), "stages": perf}
    missing = C.missing_for_contract(res, contract)
    if missing:
        res["contract"]["missing"] = missing
        log.warn("contract gaps: " + "; ".join(missing))
    names = [f["name"] for f in contract["fields"]]
    present = [n for n in names if res.get(n) not in (None, "", [], {})]
    res["contract"]["fields_total"] = len(names)
    res["contract"]["fields_present"] = len(present)
    res["contract"]["fields_empty"] = [n for n in names if n not in present]
    res["contract"]["self"] = {
        "path": "result.json",
        "note": ("result.json is not listed in outputs[]: a file cannot carry its own "
                 "sha256 without changing the bytes it describes.  Re-check the delivery "
                 "with scripts/audit_deck.py, which re-derives every expectation from "
                 "deck.pptx, result.json and the case material."),
    }
    # hashed as the very last step so that every declared byte count is current
    res["outputs"] = _artifacts(out_dir)
    write_json(os.path.join(out_dir, "result.json"), res)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="paper -> academic slide deck (evidence-locked)")
    ap.add_argument("--case", default=DEFAULT_INPUT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    ensure_dir(args.out)
    try:
        res = run(args.case, args.out, args.work,
                  do_render=not (args.no_render or args.plan_only),
                  plan_only=args.plan_only, dry_run=args.dry_run)
    except Exception:
        tb = traceback.format_exc()
        write_text(os.path.join(args.out, "error.log"), tb)
        try:
            prev = read_json(os.path.join(args.out, "result.json"))
        except Exception:
            prev = {}
        prev.update({"status": "partial",
                     "uncertainty": (prev.get("uncertainty") or []) +
                                    ["run aborted: " + tb.strip().splitlines()[-1][:300]],
                     "changes": (prev.get("changes") or []) +
                                [{"stage": "abort", "note": "see error.log"}]})
        write_json(os.path.join(args.out, "result.json"), prev)
        print(tb, file=sys.stderr)
        return 2
    print(json.dumps({"status": res.get("status"),
                      "slides": len(res.get("slides") or []),
                      "deck": (res.get("deck") or {}).get("pptx"),
                      "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
