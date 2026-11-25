"""outline.py - draft a page plan (thesis-line first, pages second).

The plan is plain JSON so a human or the calling agent can edit any page before
the deck is built.  The drafter never invents content: every claim, bullet and
number is copied or compressed from a located source segment, and every page
carries ``evidence[]`` entries pointing back at that segment.

Page roles form the narrative spine, not the paper's section order:

    title -> question -> gap -> approach -> evidence -> result -> limits -> takeaway

That ordering is what turns a continuous paper into a discrete talk.  A paper
that has no explicit gap sentence still gets a ``gap`` page, but it is marked
``gap_status: "inferred"`` and the missing source is recorded instead of being
papered over.
"""
from __future__ import annotations

import os
import re

from inventory import Inventory, numbers_in, refs_in
from util import one_line, sha256_text, truncate

MAX_BULLETS = 5
MAX_BULLET_CHARS = 96
MAX_TITLE_CHARS = 88

_ROLE_ORDER = ["title", "question", "gap", "approach", "evidence", "result",
               "limits", "takeaway"]

_GAP_CUES = re.compile(
    r"\b(however|yet|remain(?:s)? (?:unclear|unknown|open)|no (?:study|work|method)|"
    r"none of|little (?:is )?known|fail(?:s)? to|limited|gap|we still|"
    r"\u4f46|\u7136\u800c|\u5c1a\u672a|\u7f3a\u4e4f|\u4e0d\u8db3|\u672a\u89e3\u51b3)",
    re.I)
_APPROACH_CUES = re.compile(
    r"\b(we (?:propose|present|introduce|develop|design|build|train|use|apply|combine)|"
    r"our (?:method|approach|framework|model|pipeline|system)|"
    r"the proposed)\b", re.I)
_RESULT_CUES = re.compile(
    r"\b(improv\w*|reduc\w*|outperform\w*|achiev\w*|reach\w*|increase\w*|decrease\w*|"
    r"higher|lower|better than|compared (?:to|with))\b", re.I)
_LIMIT_CUES = re.compile(
    r"\b(limitation|limited to|caveat|future work|not (?:account|consider|include|"
    r"capture)|remains?|assum|only|constrain|underestimat|overestimat|"
    r"\u5c40\u9650|\u4e0d\u8db3|\u672a\u6765\u5de5\u4f5c)\b", re.I)


# ---------------------------------------------------------------- helpers

_METRIC_UNITS = {"r²", "r2", "rmse", "mae", "mape", "auc", "f1", "iou", "miou",
                 "psnr", "ssim", "kappa", "nse", "kge", "accuracy", "precision",
                 "recall", "n", "p"}


def fmt_num(num: str, unit: str = "") -> str:
    """Render a number + unit the way a slide should read it."""
    u = (unit or "").strip()
    if not u:
        return num
    if u.lower() in _METRIC_UNITS:
        return f"{u} = {num}"
    if u in ("%", "\u2030", "\u00b0C", "\u2103"):
        return f"{num}{u}"
    return f"{num} {u}"


def nums_of(text: str, limit: int = 4) -> list[str]:
    return [fmt_num(n, u) for n, u in numbers_in(text)][:limit]


def _distinct(sentences, limit: int = MAX_BULLETS) -> list[str]:
    """Compress sentences to bullets, dropping near-duplicates."""
    out, seen = [], set()
    for text in sentences:
        b, _ = _compress(text)
        if not b:
            continue
        key = b[:28].lower()
        if any(key.startswith(s) or s.startswith(key) for s in seen):
            continue
        seen.add(key)
        out.append(b)
        if len(out) >= limit:
            break
    return out


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+", one_line(text))
    return [p.strip() for p in parts if len(p.strip()) > 24]


def _pick(segments, cue, limit=4, exclude=()) -> list[dict]:
    out = []
    for seg in segments:
        if any(id(seg) == id(e) for e in exclude):
            continue
        for sent in _sentences(seg["text"]):
            if cue.search(sent):
                out.append({"text": sent, "seg": seg})
                break
        if len(out) >= limit:
            break
    return out


def _compress(sentence: str, limit: int = MAX_BULLET_CHARS) -> tuple[str, bool]:
    """Turn a sentence into a talkable bullet.  Returns (text, truncated).

    Truncation always lands on a clause boundary, and never leaves a half-eaten
    number behind - a slide that shows "24" where the paper says "24.5%" is the
    exact class of error this skill exists to prevent.
    """
    s = one_line(sentence)
    s = re.sub(r"^(However|Moreover|Furthermore|In addition|Therefore|Thus|Hence)[,;]\s*", "", s, flags=re.I)
    if len(s) <= limit:
        return s, False
    cut = s[:limit]
    for sep in ("; ", "\u2014", ", which ", ", that ", " and ", ", ", " while ", " where ",
                " at the ", " on the ", " in the ", " for the ", " with the ", " "):
        i = cut.rfind(sep)
        if i > limit * 0.5:
            cut = cut[:i]
            break
    cut = re.sub(r"[\s,;:(\[{]*[-+]?\d+(?:[.,]\d+)?\s*$", "", cut)   # no partial number
    cut = re.sub(r"[\s,;:(\[{]+$", "", cut.rstrip())
    if not cut:
        cut = s[:limit].rstrip()
    return cut + "\u2026", True


_GENERIC_HEADS = re.compile(
    r"^(abstract|keywords?|introduction|related work|background|methods?|methodology|"
    r"materials and methods|results?|experiments?|evaluation|discussion|conclusions?|"
    r"limitations|future work|references|acknowledg\w*|appendix\w*|"
    r"\d+(\.\d+)*\s*$|\u6458\u8981|\u5f15\u8a00|\u7ed3\u679c|\u8ba8\u8bba|\u53c2\u8003\u6587\u732e)",
    re.I)


def _title_from(segments, fallback: str) -> str:
    """The deck title is the paper's title, not its first section heading."""
    # a declared \title{} always wins
    for seg in segments:
        if seg.get("kind") == "meta-title":
            t = one_line(seg["text"])
            if len(t) >= 8:
                return truncate(t, MAX_TITLE_CHARS)
    author_cut = re.compile(r"\s+(?:and\s+)?[A-Z][a-z]{0,2}\.\s*[A-Z][a-z]+\s*,")
    for seg in segments[:12]:
        t = one_line(seg["text"])
        if seg["kind"] in ("heading", "table-row", "caption", "bullet", "reference",
                           "table", "equation"):
            continue
        if "|" in t or _GENERIC_HEADS.match(t):
            continue
        t = author_cut.split(" " + t)[0] if author_cut.search(" " + t) else t
        if 16 <= len(t) <= 220:
            return truncate(t, MAX_TITLE_CHARS)
    for seg in segments:
        t = one_line(seg["text"])
        if seg["kind"] == "heading" and not _GENERIC_HEADS.match(t):
            return truncate(t, MAX_TITLE_CHARS)
    return truncate(fallback, MAX_TITLE_CHARS)


def guess_language(text: str) -> str:
    from util import is_cjk
    cjk = sum(1 for ch in text if is_cjk(ch))
    return "zh" if cjk > max(8, len(text) * 0.02) else "en"


# ---------------------------------------------------------------- drafter

def draft(src, inv: Inventory, case: dict | None = None) -> dict:
    case = case or {}
    seg_by_kind = {}
    for seg in src.segments:
        seg_by_kind.setdefault(seg["kind"], []).append(seg)

    full = src.full_text
    lang = case.get("language") or guess_language(full)
    material_name = src.files[0]["path"] if src.files else "material"
    base = os.path.basename(str(material_name))
    deck_title = case.get("title") or _title_from(src.segments, base)

    paras = seg_by_kind.get("para", []) + seg_by_kind.get("abstract", [])
    heads = seg_by_kind.get("heading", [])

    def ev(seg, kind="paragraph", label=None, quote=None):
        entry = {"kind": kind, "label": label, "locator": src.locator(seg),
                 "quote": quote or truncate(seg["text"], 220)}
        return entry

    slides: list[dict] = []

    # ---- title
    authors = []
    for seg in src.segments[:3]:
        if seg["kind"] == "para" and re.search(r"\b(et al\.?|[A-Z]\.\s*[A-Z][a-z]+)", seg["text"]):
            authors.append(seg["text"])
    slides.append({
        "id": "s01", "role": "title", "title": deck_title,
        "claim": truncate(deck_title, MAX_TITLE_CHARS),
        "bullets": [b for b in [case.get("subtitle")] if b],
        "evidence": [ev(src.segments[0], "paragraph", quote=truncate(src.segments[0]["text"], 200))],
        "numbers": [], "density": "low",
    })

    # ---- question (why anyone should care)
    problem = _pick(paras, re.compile(r"\b(is|are|has|have)\b.*\b(problem|challenge|risk|"
                                      r"increase|impact|critical|urgent|important)\b", re.I), 3)
    if not problem and paras:
        problem = [{"text": _sentences(paras[0]["text"])[0], "seg": paras[0]}]
    if problem:
        p = problem[0]
        bullets = _distinct([x["text"] for x in problem[:3]])
        slides.append({
            "id": "", "role": "question",
            "title": _pagetitle(lang, "question", bullets[0]),
            "claim": _compress(p["text"], 140)[0],
            "bullets": bullets,
            "evidence": [ev(p["seg"], quote=truncate(p["text"], 220))],
            "numbers": nums_of(p["text"]),
            "density": "medium",
        })

    # ---- gap
    gaps = _pick(paras, _GAP_CUES, 2, exclude=[x["seg"] for x in problem])
    gap_status = "source-stated"
    if not gaps and inv.objectives:
        gaps = [{"text": inv.objectives[0]["text"], "seg": inv.objectives[0]["seg"]}]
        gap_status = "inferred-from-objective"
    if gaps:
        g = gaps[0]
        slides.append({
            "id": "", "role": "gap",
            "title": _pagetitle(lang, "gap", None),
            "claim": _compress(g["text"], 140)[0],
            "bullets": _distinct([x["text"] for x in gaps[:3]], 3),
            "evidence": [ev(g["seg"], quote=truncate(g["text"], 220))],
            "numbers": [], "density": "medium",
            "gap_status": gap_status,
        })
    else:
        slides.append({
            "id": "", "role": "gap", "title": _pagetitle(lang, "gap", None),
            "claim": "", "bullets": [], "evidence": [], "numbers": [],
            "density": "low", "gap_status": "not-derivable",
            "note": "source states no gap sentence; page left as a placeholder "
                    "for the author and reported in uncertainty",
        })

    # ---- approach
    appro = _pick(paras, _APPROACH_CUES, 3)
    if not appro:
        appro = [{"text": _sentences(x["text"])[0], "seg": x} for x in paras[:2]
                 if _sentences(x["text"])]
    if appro:
        slides.append({
            "id": "", "role": "approach",
            "title": _pagetitle(lang, "approach", None),
            "claim": _compress(appro[0]["text"], 140)[0],
            "bullets": _distinct([x["text"] for x in appro[:MAX_BULLETS]]),
            "evidence": [ev(x["seg"], quote=truncate(x["text"], 220)) for x in appro[:3]],
            "numbers": nums_of(" ".join(x["text"] for x in appro)),
            "density": "medium",
        })

    # ---- evidence pages: one per caption, preferred when numbers exist
    fig_caps = [c for c in inv.captions if c["kind"] == "figure"]
    tab_caps = [c for c in inv.captions if c["kind"] == "table"]
    for cap in (fig_caps + tab_caps)[:3]:
        seg = cap["seg"]
        kind = cap["kind"]
        claim_src = None
        # a figure/table page may only assert what its own section asserts
        same_section = [c for c in inv.claims if c["seg"].get("section") == seg.get("section")]
        for c in (same_section or []):
            if numbers_in(c["text"]) or _RESULT_CUES.search(c["text"]):
                claim_src = c
                break
        if claim_src and cap["num"] and any(
                cap["num"] == r["num"] and r["seg"] is claim_src["seg"] for r in inv.refs):
            pass
        bullets = []
        if claim_src:
            seen = _compress(claim_src["text"], 140)[0]
            for s in _sentences(claim_src["text"])[:3]:
                b = _compress(s)[0]
                # never repeat the page claim as a bullet: the page has one point
                if b and not (seen.startswith(b[:24]) or b.startswith(seen[:24])):
                    bullets.append(b)
        tbl = inv.table_for(cap["label"]) if kind == "table" else None
        slides.append({
            "id": "", "role": "evidence",
            "title": _evidence_title(cap["label"], cap["text"]),
            "claim": _compress(claim_src["text"], 140)[0] if claim_src else truncate(cap["text"], 140),
            "bullets": bullets,
            "figure": {"label": cap["label"], "caption": truncate(cap["text"], 200),
                       "asset": None, "kind": "figure",
                       "source_locator": src.locator(seg)}
            if kind == "figure" else None,
            "table": {"label": cap["label"], "caption": truncate(cap["text"], 160),
                      "columns": (tbl["header"] if tbl and tbl["header"] else []),
                      "rows": (tbl["rows"] if tbl else []),
                      "source_locator": src.locator(seg)}
            if kind == "table" else None,
            "evidence": [ev(seg, kind, label=cap["label"], quote=truncate(cap["text"], 200))],
            "numbers": nums_of(claim_src["text"] if claim_src else ""),
            "density": "medium" if kind == "table" else "low",
        })

    # ---- result page: highest scoring claim with numbers
    best = None
    for c in inv.claims:
        if numbers_in(c["text"]) and _RESULT_CUES.search(c["text"]):
            best = c
            break
    if not best:
        for c in inv.claims:
            if numbers_in(c["text"]):
                best = c
                break
    if best:
        nums = nums_of(best["text"], 5)
        slides.append({
            "id": "", "role": "result",
            "title": _pagetitle(lang, "result", None),
            "claim": _compress(best["text"], 140)[0],
            "bullets": [_compress(s)[0] for s in _sentences(best["text"])[:3]],
            "kpis": [{"value": n, "label": _kpi_label(best["text"], n)} for n in nums][:3],
            "evidence": [ev(best["seg"], quote=truncate(best["text"], 220))],
            "numbers": nums,
            "density": "medium",
        })

    # ---- limits
    lim = [{"text": t["text"], "seg": t["seg"]} for t in inv.limits][:3]
    if not lim:
        lim = _pick(paras, _LIMIT_CUES, 2)
    slides.append({
        "id": "", "role": "limits",
        "title": _pagetitle(lang, "limits", None),
        "claim": _compress(lim[0]["text"], 140)[0] if lim else "",
        "bullets": _distinct([x["text"] for x in lim[:3]], 3),
        "evidence": [ev(x["seg"], quote=truncate(x["text"], 200)) for x in lim[:2]],
        "numbers": [], "density": "low",
        "limits_status": "source-stated" if lim else "none-found",
    })

    # ---- takeaway: a conclusion sentence if one exists, else the paper's own
    #      declarative finding; a takeaway page is never allowed to be empty
    take = ""
    take_seg = None
    for c in inv.claims:
        if _RESULT_CUES.search(c["text"]):
            take, take_seg = c["text"], c["seg"]
            break
    if not take:
        for c in inv.claims:
            take, take_seg = c["text"], c["seg"]
            break
    if not take and paras:
        take, take_seg = paras[0]["text"], paras[0]
    slides.append({
        "id": "", "role": "takeaway",
        "title": _pagetitle(lang, "takeaway", None),
        "claim": _compress(take, 140)[0],
        "bullets": [],
        "evidence": [ev(take_seg, quote=truncate(take, 220))] if take_seg is not None else [],
        "numbers": nums_of(take),
        "density": "low",
    })

    for i, s in enumerate(slides, start=1):
        s["id"] = f"s{i:02d}"
        s.setdefault("bullets", [])
        s.setdefault("numbers", [])
        s.setdefault("evidence", [])
        s.setdefault("density", "medium")

    storyline = {
        "problem": slides[1]["claim"] if len(slides) > 1 else "",
        "gap": slides[2]["claim"] if len(slides) > 2 else "",
        "approach": next((s["claim"] for s in slides if s["role"] == "approach"), ""),
        "evidence": next((s["claim"] for s in slides if s["role"] == "evidence"), ""),
        "result": next((s["claim"] for s in slides if s["role"] == "result"), ""),
        "limits": next((s["claim"] for s in slides if s["role"] == "limits"), ""),
        "takeaway": slides[-1]["claim"],
    }

    plan = {
        "plan_version": 1,
        "deck": {
            "title": deck_title,
            "subtitle": case.get("subtitle") or "",
            "language": lang,
            "audience": case.get("audience") or "",
            "duration_min": case.get("duration_min") or 12,
            "slide_limit": int(case.get("slide_limit") or 16),
            "template": case.get("template"),
            "material": material_name,
            "material_sha256": sha256_text(full),
        },
        "storyline": storyline,
        "slides": slides,
        "draft": {
            "drafter": "outline.py",
            "auto": True,
            "inventory_counts": {
                "numbers": len(inv.numbers), "captions": len(inv.captions),
                "claims": len(inv.claims), "limits": len(inv.limits),
            },
            "notes": inv.notes,
        },
    }
    _finalize_pages(plan)
    return plan


def _finalize_pages(plan: dict) -> None:
    """Declare every audience-visible number, drop claim echoes, flag real gaps."""
    for s in plan["slides"]:
        claim_key = one_line(s.get("claim") or "")[:28].lower()
        kept, seen = [], set()
        for b in s.get("bullets") or []:
            b = one_line(str(b))
            if not b:
                continue
            key = b[:28].lower()
            if claim_key and (key.startswith(claim_key) or claim_key.startswith(key)):
                continue                      # a bullet must add, not echo the claim
            if key in seen:
                continue
            seen.add(key)
            kept.append(b)
        s["bullets"] = kept[:5]
        author_text = " ".join([str(s.get("title") or ""), str(s.get("claim") or "")]
                               + [str(b) for b in s["bullets"]]
                               + [str(k.get("value") or "") for k in s.get("kpis") or []])
        merged = list(s.get("numbers") or [])
        for x in nums_of(author_text, 8):
            if x not in merged:
                merged.append(x)
        s["numbers"] = merged[:8]
        if not s.get("evidence") and s.get("role") in ("gap", "limits", "evidence", "result"):
            s["evidence_absent_reason"] = (
                "source contains no sentence this page can be anchored to; "
                "page is a declared placeholder for the author")
        if s.get("role") == "limits" and not s.get("bullets"):
            s["limits_status"] = "none-found"


def _evidence_title(label: str, caption: str) -> str:
    """Short page title: the artefact label plus the caption's first clause."""
    body = one_line(caption)
    body = re.sub(r"^(Figure|Fig\.?|Table|Tab\.?|\u56fe|\u8868)\s*\d+\s*[.:\u2014\u3001-]\s*",
                  "", body, flags=re.I)
    head = re.split(r"[.;\u3002\uff1b;]|,\s+(?:and|which|where|showing|comparing)\b|"
                    r"[:\uff1a]",
                    body, maxsplit=1)[0].strip()
    if len(head) < 12:
        head = body
    label = label.replace("Figure", "\u56fe").replace("Table", "\u8868") \
        if re.search(r"[\u4e00-\u9fff]", body) else label
    return truncate(f"{label} \u00b7 {head}" if head else label, 48)


def _pagetitle(lang: str, role: str, fallback: str | None) -> str:
    zh = {
        "question": "\u95ee\u9898\uff1a\u4e3a\u4ec0\u4e48\u8fd9\u4ef6\u4e8b\u91cd\u8981",
        "gap": "\u73b0\u6709\u5de5\u4f5c\u7684\u7a7a\u767d",
        "approach": "\u6211\u4eec\u7684\u505a\u6cd5",
        "evidence": "\u8bc1\u636e",
        "result": "\u4e3b\u8981\u7ed3\u679c",
        "limits": "\u5c40\u9650\u4e0e\u9002\u7528\u8303\u56f4",
        "takeaway": "\u7ed3\u8bba\u4e0e\u4e0b\u4e00\u6b65",
    }
    en = {
        "question": "Why this question matters",
        "gap": "What is still missing",
        "approach": "What we did",
        "evidence": "Evidence",
        "result": "Main result",
        "limits": "Limits and scope",
        "takeaway": "Takeaway",
    }
    title = (zh if lang == "zh" else en).get(role, role)
    if fallback:
        title = f"{title}" if len(title) < 40 else fallback
    return title[:MAX_TITLE_CHARS]


def _kpi_label(text: str, num: str) -> str:
    """Name the metric a KPI value belongs to, from the sentence it came from."""
    m = re.search(r"(R\s*[\u00b2\u2070-\u2079]|R2|RMSE|MAE|MAPE|AUC|F1|IoU|mIoU|PSNR|SSIM|"
                  r"kappa|NSE|KGE|Accuracy|Precision|Recall)\s*=\s*" + re.escape(num), text, re.I)
    if m:
        return m.group(1)
    idx = text.find(num)
    if idx < 0:
        return ""
    before = text[:idx].rstrip(" ,;:(=")
    word = re.findall(r"[A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\-]*", before)
    if not word:
        return ""
    tail = word[-1]
    # keep only a plausible metric word, never a clause fragment
    if re.fullmatch(r"(?:R|R\s*[\u00b2\u2070-\u2079]|R2|RMSE|MAE|MAPE|AUC|F1|IoU|mIoU|PSNR|SSIM|"
                    r"kappa|NSE|KGE|Accuracy|Precision|Recall|\u8bef\u5dee|\u7cbe\u5ea6|"
                    r"\u91cd\u590d\u5b9e\u9a8c|\u53d8\u5316|\u63d0\u5347|\u4e0b\u964d|\u8bc4\u5206)", tail, re.I):
        return tail
    return ""


__all__ = ["draft", "guess_language", "MAX_BULLETS", "MAX_TITLE_CHARS", "MAX_BULLET_CHARS"]
