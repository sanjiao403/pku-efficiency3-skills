"""notes.py - speaker notes that are written for the speaker.

The rubric is explicit that notes must not merely echo the slide.  So a note is
composed from *speaker moves* rather than from the page text:

* a transition that names the link to the previous page,
* one emphasis sentence that says what to do with this page,
* the evidence pointer (figure/table/section + locator) to open if challenged,
* one to three anticipated questions with the evidence that answers them,
* a rough time budget for the page.

A redundancy guard measures character 4-gram overlap against everything the
audience can read on the slide and asks for a rewrite above
``MAX_REDUNDANCY``; the check is re-run in ``qa.py`` on the exported notes, not
only here, so a hand-edited note cannot quietly become a copy of the bullets.
"""
from __future__ import annotations

import re

from util import norm_key, one_line, truncate

MAX_REDUNDANCY = 0.34
TITLE_ROLES = {"title"}
QA_MIN = 1


def _grams(text: str, n: int = 4) -> set[str]:
    s = norm_key(text)
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s)
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def redundancy(notes: str, visible: str) -> float:
    a, b = _grams(notes), _grams(visible)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 3)


def visible_text(slide: dict) -> str:
    parts = [str(slide.get("title") or ""), str(slide.get("claim") or "")]
    parts += [str(b) for b in slide.get("bullets") or []]
    for k in slide.get("kpis") or []:
        parts += [str(k.get("value") or ""), str(k.get("label") or "")]
    fig = slide.get("figure") or {}
    if fig:
        parts.append(str(fig.get("caption") or ""))
    tbl = slide.get("table") or {}
    if tbl:
        parts.append(str(tbl.get("caption") or ""))
        for row in tbl.get("rows") or []:
            parts += [str(c) for c in row]
    return " ".join(parts)


_ROLE_INTENT = {
    "title": ("开场：用一句话说清这次汇报的主题与听众收益，然后立刻进入问题，"
              "不要在封面停留超过 20 秒。",
              "Open with one sentence: what this talk is and why this room should care. "
              "Leave the title page inside 20 seconds."),
    "outline": ("预告路线：说明接下来听众会依次看到问题、做法、证据与结论，"
                "并告诉他们哪一页是重点。",
                "Preview the route: problem, approach, evidence, conclusion - and say which "
                "page is the one to remember."),
    "question": ("把问题立起来：先说这件事为什么现在要紧，再指出论文要解决的具体缺口，"
                 "最后用一句话把问题收成一个可回答的问句。",
                 "Set the stake: why this matters now, then narrow to the concrete question "
                 "the work answers."),
    "gap": ("指出前人做到哪一步、留下什么没做；如果这一页的依据来自作者推断，"
            "要口头说明是推断而不是原文结论。",
            "Show where prior work stopped and what it left open; if the gap is inferred, "
            "say so out loud."),
    "approach": ("讲做法只讲三个决定性的设计点，其余细节回答问题时再展开；"
                 "强调哪个设计点换来了后面的结果。",
                 "Give the three design decisions that produced the result; keep the rest "
                 "for questions."),
    "evidence": ("先读图注，再指图；把图里最关键的对比用一句话讲出来，"
                 "并明确这是实验数据还是示意图。",
                 "Read the caption first, then point at the artefact; say explicitly whether "
                 "it is measured data or a schematic."),
    "result": ("先把结论说出来，再给数字；数字要带单位和口径，"
               "并说明和谁比、在什么条件下比。",
               "State the conclusion, then the number with its unit and baseline."),
    "limits": ("主动交底：适用范围、失效条件、以及论文自己承认的不足；"
               "主动说出局限比被问出来更可信。",
               "Volunteer the scope, the failure modes and the paper's own admitted limits."),
    "takeaway": ("收束：重复那一条最该被记住的结论，给出下一步或可迁移的场景，"
                 "然后停住等提问。",
                 "Close on the single memorable conclusion plus one next step, then stop."),
    "backup": ("备用页：只在被追问时翻到，不要主动讲。",
               "Backup page: show it only if asked."),
}

_TRANSITION = {
    "zh": {
        "first": "过渡：这是第一页内容页，先交代全篇的出发点。",
        "default": "过渡：承接上一页（{prev}），这一页回答「{cur}」。",
        "missing": "过渡：上一页没有可直接承接的结论，这一页是路线的新起点。",
    },
    "en": {
        "first": "Transition: first content page - establish the starting point of the talk.",
        "default": "Transition: after \"{prev}\" this page answers \"{cur}\".",
        "missing": "Transition: there is no carry-over claim from the previous page; this "
                   "page starts a new branch of the argument.",
    },
}


def compose(slide: dict, slides_by_id: dict, plan: dict, slide_index: int = 0) -> dict:
    lang = (plan.get("deck") or {}).get("language") or "en"
    zh = lang == "zh"
    role = slide.get("role") or "evidence"
    intent = _ROLE_INTENT.get(role, _ROLE_INTENT["evidence"])
    intent = intent[0] if zh else intent[1]

    # ---- transition
    prev = _prev_content_slide(plan, slide_index)
    tmap = _TRANSITION["zh" if zh else "en"]
    if prev is None:
        transition = tmap["first"]
    else:
        transition = tmap["default"].format(
            prev=truncate(prev.get("title") or prev.get("claim") or "", 34),
            cur=truncate(slide.get("title") or "", 34))
        if not (prev.get("claim") or "").strip():
            transition = tmap["missing"]

    lines = [transition, intent]

    # ---- emphasis: point at, do not restate
    evs = slide.get("evidence") or []
    if evs:
        e0 = evs[0]
        where = e0.get("locator") or "source"
        if zh:
            lines.append(f"强调：本页只留一个记忆点，出处 {where}"
                         f"{'；' + _kind_zh(e0.get('kind')) if e0.get('kind') else ''}。"
                         f"被追问时直接翻到这一处，不要凭印象复述数字。")
        else:
            lines.append(f"Emphasis: one takeaway only. On-screen content traces to {where}"
                         f"{' (' + str(e0.get('kind')) + ')' if e0.get('kind') else ''}. "
                         f"Open that spot instead of recalling numbers from memory.")
    else:
        reason = one_line(slide.get("evidence_absent_reason") or "")
        if zh:
            lines.append("强调：本页没有可锚定的原文句，属于作者补齐页；"
                         f"口头说明这一点。{reason}")
        else:
            lines.append("Emphasis: this page has no anchor sentence in the source and is a "
                         f"declared author placeholder. Say so out loud. {reason}")

    # ---- anticipated questions
    qa = _questions(slide, plan, zh)
    for q in qa[:3]:
        lines.append(q)

    note = "\n".join(x for x in lines if x)
    vis = visible_text(slide)
    red = redundancy(note, vis)
    if red > MAX_REDUNDANCY:
        note = _de_echo(note, vis, zh)
        red = redundancy(note, vis)

    seconds = _time_budget(slide, plan)
    if zh:
        note += f"\n[时间] 本页约 {seconds} 秒。"
    else:
        note += f"\n[Timing] about {seconds}s on this page."
    return {
        "notes": note,
        "redundancy": red,
        "has_transition": bool(re.search(r"(过渡|Transition:)", note)),
        "qa_count": len(qa),
        "seconds": seconds,
    }


def _kind_zh(kind):
    return {"figure": "图", "table": "表", "paragraph": "正文段", "equation": "公式",
            "section": "章节"}.get(str(kind), str(kind))


def _prev_content_slide(plan, index):
    slides = plan.get("slides") or []
    for j in range(min(index, len(slides)) - 1, -1, -1):
        if slides[j].get("role") not in TITLE_ROLES:
            return slides[j]
    return None


def _questions(slide, plan, zh: bool) -> list[str]:
    out = []
    role = slide.get("role")
    nums = [str(n) for n in slide.get("numbers") or []][:2]
    ev = (slide.get("evidence") or [{}])[0]
    where = ev.get("locator") or "source"
    if nums:
        if zh:
            out.append(f"[可能被问] 这个数字的口径是什么（单位/基线/样本）？"
                       f"答：按 {where} 的原文口径回答，不要换单位或四舍五入。")
        else:
            out.append(f"[Q] What is the exact scope of {nums[0]} (unit, baseline, sample)? "
                       f"[A] Quote it as written at {where}; do not re-round or convert.")
    if role in ("limits", "takeaway"):
        if zh:
            out.append("[可能被问] 这个结论能外推到什么范围？答：先给适用边界，"
                       "再给论文未覆盖的部分。")
        else:
            out.append("[Q] How far does this generalise? [A] Give the declared scope first, "
                       "then what the paper does not cover.")
    if role == "evidence":
        fig = slide.get("figure") or {}
        tbl = slide.get("table") or {}
        label = fig.get("label") or tbl.get("label") or "the artefact"
        if zh:
            out.append(f"[可能被问] {label} 是实验结果还是示意？答：明确说明它的类型与来源，"
                       f"不把示意图当数据。")
        else:
            out.append(f"[Q] Is {label} measured or schematic? [A] Name the artefact type and "
                       f"its source; never present a schematic as data.")
    if role == "approach":
        if zh:
            out.append("[可能被问] 和最初方案相比改了什么？答：只讲与结果直接相关的改动，"
                       "并指出对应证据位置。")
        else:
            out.append("[Q] What changed versus the first design? [A] Name only the changes "
                       "that the evidence depends on.")
    if not out:
        story = one_line((plan.get("storyline") or {}).get("takeaway") or "")
        if story:
            out.append(("[可能被问] 这与结论的关系？[A] " if zh else
                        "[Q] How does this serve the conclusion? [A] ") + truncate(story, 120))
    return out


def _de_echo(note: str, visible: str, zh: bool) -> str:
    """Last resort: keep the speaker moves, drop quoted slide wording."""
    keep = []
    for line in note.split("\n"):
        if redundancy(line, visible) > MAX_REDUNDANCY and not line.startswith(("[时间]", "[Timing]")):
            keep.append("[以幻灯片为准，此处不复述]" if zh else "[see the slide; not repeated here]")
        else:
            keep.append(line)
    return "\n".join(keep)


def _time_budget(slide, plan) -> int:
    total = int((plan.get("deck") or {}).get("duration_min") or 12) * 60
    n = max(1, len([s for s in plan.get("slides") or []
                    if s.get("role") not in ("backup",)]))
    weight = {"title": 0.5, "outline": 0.6, "evidence": 1.3, "result": 1.3,
              "limits": 1.1, "takeaway": 0.9}.get(slide.get("role"), 1.0)
    base = total / n
    return max(20, int(round(base * weight / 5.0) * 5))


def audit_notes(plan: dict) -> dict:
    """Re-check notes exactly as they will be exported."""
    rows = []
    for i, s in enumerate(plan.get("slides") or []):
        info = compose(s, {}, plan, i)
        rows.append({
            "slide": s.get("id"), "role": s.get("role"),
            "redundancy": info["redundancy"],
            "has_transition": info["has_transition"],
            "qa_count": info["qa_count"],
            "chars": len(info["notes"]),
            "seconds": info["seconds"],
        })
    bad = [r for r in rows if r["redundancy"] > MAX_REDUNDANCY
           or not r["has_transition"]
           or (r["qa_count"] < QA_MIN and r["role"] not in TITLE_ROLES)]
    return {
        "slides": len(rows),
        "max_redundancy": max((r["redundancy"] for r in rows), default=0.0),
        "mean_redundancy": round(sum(r["redundancy"] for r in rows) / len(rows), 3) if rows else 0.0,
        "missing_transition": [r["slide"] for r in rows if not r["has_transition"]],
        "slides_without_qa": [r["slide"] for r in rows
                              if r["qa_count"] < QA_MIN and r["role"] not in TITLE_ROLES],
        "total_seconds": sum(r["seconds"] for r in rows),
        "rows": rows,
        "ok": not bad,
    }
