"""plan_validate.py - the evidence lock.

Everything downstream (deck build, notes, audit) trusts a plan only after this
module has checked it against the *actual* source.  Four hard gates:

G1  every figure/table/equation reference on a page exists in the source
G2  every number on a page exists in the source (value and unit)
G3  every evidence quote is verbatim-locatable (or explicitly marked paraphrased)
G4  every content page carries at least one locator

Plus soft checks (bullets, title length, slide limit, genre coverage) that
produce warnings the author can accept on the record via ``plan.accepted[]``.

Findings are machine-readable so ``qa.py``, ``result.json`` and the human
reviewer all report the same numbers.
"""
from __future__ import annotations

import re

from inventory import (Inventory, _kind_of, norm_number, norm_unit, numbers_in, refs_in,
                       verify_locator, verify_value)
from util import norm_key, one_line, truncate

CONTENT_ROLES = {"question", "gap", "approach", "evidence", "result", "limits",
                 "takeaway", "backup", "outline"}

ROLE_LABELS = {
    "title": ("封面", "title"),
    "outline": ("提纲", "outline"),
    "question": ("问题与动机", "problem statement"),
    "gap": ("研究空白", "research gap"),
    "approach": ("方法与设计", "approach"),
    "evidence": ("证据页", "evidence"),
    "result": ("主要结果", "result"),
    "limits": ("局限与适用", "limitations"),
    "takeaway": ("结论与展望", "takeaway"),
    "backup": ("备用", "backup"),
}

DIMENSIONS = {
    "mainline": "论文主线（问题/空白/做法/证据/结论可讲成一条线）",
    "page_structure": "页级主张与信息分层（一页一主张、要点数量受控）",
    "figure_evidence": "图表引用与证据保留（编号、图注、单位、来源定位）",
    "narrative_notes": "讲解逻辑与备注（过渡、强调点、预设问答）",
    "template_layout": "模板约束与版面适配（占位符、字号层级、溢出）",
    "render_editability": "导出渲染与可编辑性（PDF/PNG 渲染、源文件可编辑）",
}

_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


class Finding(dict):
    pass


def _f(code, severity, message, slide=None, field=None, **extra):
    d = {"code": code, "severity": severity, "message": message,
         "slide": slide, "field": field}
    d.update(extra)
    return Finding(d)


def validate(plan: dict, src, inv: Inventory) -> dict:
    findings: list[Finding] = []
    slides = plan.get("slides") or []
    limit = int((plan.get("deck") or {}).get("slide_limit") or 16)
    accepted = set(plan.get("accepted") or [])

    if not slides:
        findings.append(_f("PLAN_EMPTY", "error", "plan contains no slides"))

    cover: dict[str, int] = {}
    evidence_ok = 0
    slides_with_locator = 0
    content_slides = 0

    for idx, s in enumerate(slides):
        sid = s.get("id") or f"#{idx + 1}"
        role = s.get("role") or "evidence"
        cover[role] = cover.get(role, 0) + 1
        if role in CONTENT_ROLES:
            content_slides += 1
        slide_grounded = False

        # ---- G4 evidence presence (declarable absence is downgraded, not hidden)
        evs = s.get("evidence") or []
        absent_reason = one_line(s.get("evidence_absent_reason") or "")
        if role in CONTENT_ROLES and not evs:
            if absent_reason:
                findings.append(_f("EVIDENCE_ABSENT_DECLARED", "warn",
                                   f"{sid} ({role}) has no locator and declares why: "
                                   f"{absent_reason}", slide=sid, field="evidence"))
            else:
                findings.append(_f("EVIDENCE_MISSING", "error",
                                   f"{sid} ({role}) has no source locator and no "
                                   f"evidence_absent_reason", slide=sid, field="evidence"))

        # ---- G3 quote must be locatable
        for e in evs:
            quote = (e.get("quote") or "").strip()
            locator = (e.get("locator") or "").strip()
            if not locator:
                findings.append(_f("LOCATOR_MISSING", "error",
                                   f"{sid} evidence entry lacks a locator",
                                   slide=sid, field="evidence"))
                continue
            if quote and not e.get("paraphrase"):
                seg, found, match_kind = src.quote_locator(quote)
                if seg is None:
                    findings.append(_f(
                        "QUOTE_NOT_FOUND", "error",
                        f"{sid} quote is not verbatim in the source: {quote[:70]!r}",
                        slide=sid, field="evidence"))
                else:
                    evidence_ok += 1
                    slide_grounded = True
                    if match_kind != "verbatim":
                        findings.append(_f(
                            "QUOTE_NORMALISED", "info",
                            f"{sid} quote matched after normalising extraction artefacts "
                            f"({match_kind})", slide=sid, field="evidence"))
            else:
                evidence_ok += 1
                slide_grounded = True

            label = e.get("label")
            if label:
                v = verify_locator(inv, label)
                if not v["ok"]:
                    findings.append(_f("REF_NOT_IN_SOURCE", "error",
                                       f"{sid}: {v['reason']}", slide=sid,
                                       field="evidence", label=label))

        if slide_grounded and role in CONTENT_ROLES:
            slides_with_locator += 1

        # ---- G1/G2 must be judged **per field**, never on a concatenation:
        #      joining two fields can fuse a bare number with the next field's
        #      metric label ("12" + "R2 = 0.86" -> the pair 12 R2), which the
        #      material can never confirm.  A fabricated number still fails.
        declared = {norm_number(n) for n in _declared_numbers(s)}
        for ftxt in _page_fields(s):
            for label in refs_in(ftxt):
                v = verify_locator(inv, label)
                if not v["ok"]:
                    findings.append(_f("REF_NOT_IN_SOURCE", "error",
                                       f"{sid} body cites {v['reason']}", slide=sid,
                                       field="body", label=label))
            for raw, unit in numbers_in(ftxt):
                v = verify_value(inv, raw, unit)
                if not v["ok"]:
                    findings.append(_f("NUMBER_NOT_IN_SOURCE", "error",
                                       f"{sid}: {v['reason']} \u2014 text {ftxt[:60]!r}",
                                       slide=sid, field="body", value=norm_number(raw),
                                       unit=norm_unit(unit)))
        page_text = _page_text(s)
        if role in CONTENT_ROLES:
            for raw, unit in numbers_in(" ".join(_page_fields(s, authors_only=True))):
                if norm_number(raw) not in declared:
                    findings.append(_f("NUMBER_UNDECLARED", "warn",
                                       f"{sid}: number {raw}{unit} appears on the page but is "
                                       f"not in the slide's numbers[] list", slide=sid,
                                       field="numbers"))

        # ---- structure
        bl = s.get("bullets") or []
        if len(bl) > 5:
            findings.append(_f("TOO_MANY_BULLETS", "warn",
                               f"{sid} has {len(bl)} bullets; split the page or demote detail",
                               slide=sid, field="bullets"))
        for b in bl:
            if len(b) > 130:
                findings.append(_f("BULLET_TOO_LONG", "warn",
                                   f"{sid} bullet is {len(b)} chars; a slide bullet should "
                                   f"be speakable, not a sentence from the paper",
                                   slide=sid, field="bullets"))
            if len(b) > 90 and _is_paper_prose(b):
                findings.append(_f("BULLET_IS_PROSE", "warn",
                                   f"{sid} bullet reads as copied paper prose: {b[:50]!r}",
                                   slide=sid, field="bullets"))
        title = one_line(s.get("title") or "")
        if len(title) > 90:
            findings.append(_f("TITLE_TOO_LONG", "warn",
                               f"{sid} title is {len(title)} chars", slide=sid,
                               field="title"))
        if role in CONTENT_ROLES and not one_line(s.get("claim") or ""):
            findings.append(_f("CLAIM_MISSING", "warn",
                               f"{sid} ({role}) has no one-sentence claim", slide=sid,
                               field="claim"))

        # ---- schematic presented as data
        fig = s.get("figure") or {}
        if fig:
            kind = (fig.get("kind") or "").lower()
            if kind in ("schematic", "diagram", "flow", "workflow", "illustration"):
                if re.search(r"\b(result|accuracy|mae|rmse|improve|outperform|"
                             r"performance|achiev)\w*", page_text, re.I):
                    findings.append(_f(
                        "SCHEMATIC_AS_DATA", "error",
                        f"{sid} shows a schematic ({kind}) inside a results claim; "
                        f"label it as a schematic or move it off the results page",
                        slide=sid, field="figure"))

    # ---- deck-level
    if len(slides) > limit:
        findings.append(_f("SLIDE_LIMIT", "warn",
                           f"plan has {len(slides)} pages but the limit is {limit}",
                           slide=None, field="slides"))
    for role in ("question", "gap", "approach", "result", "limits", "takeaway"):
        if cover.get(role, 0) == 0:
            findings.append(_f("ROLE_MISSING", "warn",
                               f"no page with role '{role}'; the narrative spine is "
                               f"incomplete", slide=None, field="slides"))
    storyline = plan.get("storyline") or {}
    for key in ("problem", "gap", "approach", "evidence", "result", "limits", "takeaway"):
        if not one_line(storyline.get(key) or ""):
            findings.append(_f("STORYLINE_GAP", "warn",
                               f"storyline.{key} is empty; state it explicitly or mark "
                               f"it not-derivable", slide=None, field="storyline"))

    # ---- summarise
    errors = [f for f in findings if f["severity"] == "error" and f["code"] not in accepted]
    warns = [f for f in findings if f["severity"] == "warn" and f["code"] not in accepted]
    infos = [f for f in findings if f["severity"] == "info"]
    findings.sort(key=lambda f: (_SEVERITY_ORDER[f["severity"]], f["slide"] or "", f["code"]))

    return {
        "ok": not errors,
        "status": "PASS" if not errors and not warns else ("FAIL" if errors else "WARN"),
        "counts": {"error": len(errors), "warn": len(warns), "info": len(infos),
                   "accepted_suppressed": len([f for f in findings if f["code"] in accepted])},
        "errors": errors,
        "warnings": warns,
        "findings": findings,
        "accepted": sorted(accepted),
        "rigor_report": rigor_report(plan, src, inv, findings),
        "metrics": {
            "slides": len(slides),
            "content_slides": content_slides,
            "slides_with_locator": slides_with_locator,
            "evidence_entries_verified": evidence_ok,
            "evidence_coverage": round(slides_with_locator / content_slides, 3) if content_slides else 0.0,
            "role_coverage": cover,
            "roles_covered": sorted(c for c in cover if c in CONTENT_ROLES),
        },
    }


# --------------------------------------------------------------------------
# Rigour report: what was proved, what was not, and what cannot be judged
# --------------------------------------------------------------------------

def rigor_report(plan: dict, src, inv: Inventory, findings: list[dict]) -> dict:
    """Per-item accounting for the evidence lock.

    ``covered``    - the claim/number/reference was checked against the material
                     and matched (with the locator and the verbatim span),
    ``uncovered``  - it was checkable but did not match (or was missing),
    ``undecidable``- the material does not allow a judgement (no text layer, no
                     captions at all, quote too short to be meaningful, ...).

    Each row carries the rigour triple *(verbatim, line, verify_cmd)* so that any
    row can be re-proved from a shell with ``scripts/rigor.py``.
    """
    covered, uncovered, undecidable = [], [], []
    by_slide: dict[str, dict] = {}

    def row(slide, kind, value, verbatim, locator, line, cmd, note=""):
        return {"slide": slide, "kind": kind, "value": value,
                "verbatim": truncate(verbatim or "", 200), "locator": locator or "",
                "line": line, "verify_cmd": cmd, "note": note}

    for s in plan.get("slides") or []:
        sid = s.get("id") or "?"
        by_slide[sid] = {"covered": 0, "uncovered": 0, "undecidable": 0}
        for e in s.get("evidence") or []:
            quote = (e.get("quote") or "").strip()
            locator = e.get("locator") or ""
            label = e.get("label")
            if quote and not e.get("paraphrase"):
                seg, found, match = src.quote_locator(quote)
                if seg is None:
                    uncovered.append(row(sid, "quote", truncate(quote, 70), quote, locator,
                                         None, _cmd("quote", quote[:60])))
                else:
                    covered.append(row(sid, "quote", truncate(quote, 70), quote, found,
                                       seg.get("line"), _cmd("quote", quote[:60]),
                                       f"match={match}"))
            elif quote:
                covered.append(row(sid, "quote", truncate(quote, 70), quote, locator, None,
                                   "", "declared paraphrase"))
            else:
                undecidable.append(row(sid, "quote", "-", "", locator, None, "",
                                       "no quote on this page"))
            if label:
                v = verify_locator(inv, label)
                if v["ok"]:
                    cap = inv.caption_for(label)
                    covered.append(row(sid, "reference", label,
                                       (cap or {}).get("text") or (cap or {}).get("verbatim", ""),
                                       src.locator(cap["seg"]) if cap else locator,
                                       cap["seg"].get("line") if cap else None,
                                       _cmd(rkind_label(label), v["num"])))
                else:
                    uncovered.append(row(sid, "reference", label, "", locator, None,
                                         _cmd(rkind_label(label), v["num"]), v["reason"]))
        for ftxt in _page_fields(s):
            for raw, unit in numbers_in(ftxt):
                v = verify_value(inv, raw, unit)
                if v["ok"]:
                    seg = next((n["seg"] for n in inv.numbers if n["value"] == v["value"]), None)
                    covered.append(row(sid, "number", f"{raw}{unit}", raw,
                                       src.locator(seg) if seg else "", seg.get("line") if seg else None,
                                       _cmd("number", v["value"], v["unit"])))
                elif not inv.numbers:
                    undecidable.append(row(sid, "number", f"{raw}{unit}", "", "", None,
                                           "", "material exposes no numbers at all"))
                else:
                    uncovered.append(row(sid, "number", f"{raw}{unit}", "", "", None,
                                         _cmd("number", v["value"], v["unit"]), v["reason"]))
        counts = by_slide[sid]
        counts["covered"] = sum(1 for r in covered if r["slide"] == sid)
        counts["uncovered"] = sum(1 for r in uncovered if r["slide"] == sid)
        counts["undecidable"] = sum(1 for r in undecidable if r["slide"] == sid)

    if not src.text_layer:
        undecidable.append(row("-", "material", "text-layer", "", src.files and "source", None,
                               "", "material has no usable text layer: OCR first"))
    total = len(covered) + len(uncovered) + len(undecidable)
    return {
        "summary": {
            "covered": len(covered), "uncovered": len(uncovered),
            "undecidable": len(undecidable), "items": total,
            "coverage": round(len(covered) / total, 3) if total else 0.0,
        },
        "covered": covered[:400],
        "uncovered": uncovered[:200],
        "undecidable": undecidable[:100],
        "by_slide": by_slide,
        "how_to_re_prove": ("每行 verify_cmd 都可在 shell 直接运行："
                            "python3 scripts/rigor.py --case <case.json> --item <kind>:<value>"
                            "（--all 可一次复核整个 ledger）"),
    }


def rkind_label(label: str) -> str:
    kind = _kind_of(label)
    return {"figure": "figure", "table": "table", "equation": "equation",
            "section": "section"}.get(kind, "figure")


def _cmd(kind: str, value, unit: str = "") -> str:
    item = f"{kind}:{value}" + (f":{unit}" if unit else "")
    return f"python3 scripts/rigor.py --case <this case.json> --item {item}"


def _declared_numbers(s: dict) -> list[str]:
    out = []
    for n in s.get("numbers") or []:
        m = re.findall(r"[-+]?\d+(?:\.\d+)?", str(n))
        out.extend(m)
    for k in s.get("kpis") or []:
        m = re.findall(r"[-+]?\d+(?:\.\d+)?", str(k.get("value", "")))
        out.extend(m)
    return out


def _page_fields(s: dict, authors_only: bool = False) -> list[str]:
    """The page's text as *separate* fields.

    The gates scan field by field: a number and a unit that are only adjacent
    because two different fields were concatenated is not a claim the page makes
    (it produced a false NUMBER_NOT_IN_SOURCE on pages mixing ``12`` with
    ``R2 = 0.86``).  ``_page_text`` keeps the joined form for the rigour ledger.
    """
    parts = [s.get("title") or "", s.get("claim") or ""]
    parts += [str(b) for b in (s.get("bullets") or [])]
    parts += [str(n) for n in (s.get("numbers") or [])]
    for k in s.get("kpis") or []:
        parts.append(str(k.get("value") or ""))
        if not authors_only and k.get("label"):
            parts.append(str(k["label"]))
    fig = s.get("figure") or {}
    if fig:
        parts += [str(fig.get("label") or "")]
        if not authors_only:
            parts.append(str(fig.get("caption") or ""))
    tbl = s.get("table") or {}
    if tbl:
        parts += [str(tbl.get("label") or "")]
        if not authors_only:
            parts.append(str(tbl.get("caption") or ""))
            for row in (tbl.get("rows") or []):
                parts += [str(c) for c in row]
    if not authors_only:
        for e in s.get("evidence") or []:
            if e.get("label"):
                parts.append(str(e["label"]))
            if e.get("quote"):
                parts.append(str(e["quote"]))
    return parts


def _page_text(s: dict, authors_only: bool = False) -> str:
    """Joined page text (used by the rigour ledger and the prose heuristics)."""
    return " ".join(_page_fields(s, authors_only))


_STOP = re.compile(
    r"\b(we|our|the|a|an|of|and|or|to|in|on|for|with|that|this|these|those|is|are|"
    r"was|were|be|been|by|as|at|it|its|from|than|then|which|while|also|can|may)\b", re.I)


def _is_paper_prose(text: str) -> bool:
    """Heuristic: does this bullet still read as running paper text?

    Tuned so an academic bullet that carries a citation or a metric still passes;
    a pasted sentence (many function words, long, several clauses) does not.
    """
    words = _STOP.findall(text)
    if len(words) >= 7:
        return True
    if text.count(",") >= 4 and len(text) > 88:
        return True
    if re.search(r"\([^)]*\b(19|20)\d{2}\b[^)]*\)", text) and len(text) > 100:
        return True
    if re.search(r"\b(which|whereas|thereby|therefore|moreover|furthermore)\b", text, re.I) \
            and len(text) > 80:
        return True
    return False
