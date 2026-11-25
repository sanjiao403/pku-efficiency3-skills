# -*- coding: utf-8 -*-
"""plan_deck.py —— 论文主线 → 页级结构（claim / 图表引用 / 讲解顺序 / 版式与字号预算）。

这是本 Skill 的"内容-版式映射层"，也是与"把论文整段粘进默认模板"的分界线：

1. **页结构**：按学术汇报的固定骨架建页（封面 → 目录 → 章节页 → 结果页 → 局限 → 结论 → Q&A），
   页数受案例约束（slide_count.min/max、minutes）约束，超出的章节按可解释的优先级裁剪并记账。
2. **页级主张**：每页标题来自源材料标题（可复核），`claim` 是从源材料**逐字摘出的最强断言**
   （含数值的句子优先），不生成新事实；被截断的句子保留全文进备注。
3. **证据映射**：每条 bullet 带 `locator`（§/p.）+ `block_id` + `quote`，quote 可回源校验
   （fit_check.py 会做逐字比对，`quote_verified` 才为真）。
4. **版式与预算**：用 template_map 里真实占位符几何 + 字号阶梯，算每页能放几行几字；
   放不下的内容**降级进讲稿备注并记账**，而不是把字号压到不可读。
5. **人工/Agent 可改**：产出 plan.json 是普通 JSON，agent 可以直接改文案再 build；
   `--validate` 可在不生成文件的情况下检查改过的 plan 是否越界。

用法：
    python plan_deck.py --case case.json --source-map source_map.json \
        --template-map template_map.json --out plan.json [--validate plan.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）

import units

# 字号阶梯（pt）：从上到下依次尝试，低于下限就宁可拆页/进备注
LADDER = {
    "title": [40, 36, 32, 28, 24],
    "section": [40, 36, 32],
    "body": [20, 18, 16, 14],
    "sub": [16, 14, 12],
    "caption": [14, 12, 11, 10],
    "footer": [12, 10],
}
MIN_SIZE = {"body": 14.0, "caption": 10.0, "title": 20.0, "section": 24.0}

CONTRIB_HINT = re.compile(
    r"\b(we (?:propose|present|introduce|show|demonstrate|develop|report)|this (?:study|paper|work)|"
    r"本文|我们|本研究|提出了|结果(?:表明|显示)|conclude|significant|first)\b", re.I)

LIMIT_HINT = re.compile(r"(limitation|limitations|局限|不足|caveat|future work|展望|讨论|discussion)",
                        re.I)
CONCLUSION_HINT = re.compile(r"(conclusion|conclusions|结论|总结|summary|outlook)", re.I)


def _clip(text: str, limit: int, at="。；;. ") -> tuple:
    """按小句边界截断到 limit 字符内；返回 (截断文本, 是否截断)。

    细节：句点只在"点+空格/点+行尾"时才算边界（否则会把 289.6 / 24.1% 里的点当断句）；
    任何截断都会补省略号，读者一眼能看出被截（不会误以为原文就这么断）。
    """
    text = text.strip()
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    best = -1
    for m in re.finditer(r"[。！？；;!?]\s*|[,，](?=\s|$)|\.(?=\s|$)", cut):
        best = m.end()
    if best >= int(limit * 0.55):
        head = cut[:best].rstrip()
        tail = head[-1] if head else ""
        return (head if tail in "。！？!?" else head + "…"), True
    sp = cut.rfind(" ")
    if sp >= int(limit * 0.55):
        return cut[:sp].strip() + "…", True
    return cut.rstrip() + "…", True


def _score_sentence(text: str, is_topic: bool, order: int) -> float:
    s = 0.0
    if units.__dict__ and re.search(r"\d", text):
        s += 3.0
    if re.search(r"(\d+(?:\.\d+)?\s*%|\bp\s*[<=>]\s*0\.\d+|\bn\s*=\s*\d+|\b\d+\.\d+\b)", text):
        s += 2.0
    if CONTRIB_HINT.search(text):
        s += 2.0
    if is_topic:
        s += 1.5
    if 40 <= len(text) <= 160:
        s += 1.0
    if len(text) > 260:
        s -= 1.0
    return s - 0.02 * order


ROLE_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "templates", "layout_roles.json")
_ROLE_RULES_CACHE = None


def role_order() -> dict:
    """读 templates/layout_roles.json 的角色偏好；缺失或损坏时用内置顺序。"""
    global _ROLE_RULES_CACHE
    if _ROLE_RULES_CACHE is None:
        order = None
        try:
            with open(ROLE_RULES_PATH, encoding="utf-8") as fh:
                order = (json.load(fh) or {}).get("order")
        except Exception:
            order = None
        _ROLE_RULES_CACHE = order if isinstance(order, dict) else {}
    return _ROLE_RULES_CACHE


def _layout_for_role(template_map: dict, role: str, order: list | None = None) -> dict | None:
    roles = template_map.get("roles") or {}
    cfg = role_order()
    want = order or cfg.get(role) or {
        "title": ["title"], "agenda": ["agenda", "content"], "section": ["section"],
        "bullets": ["content"], "two-column": ["two-column"],
        "figure": ["figure", "content"],
        "closing": ["title", "section", "blank"]}.get(role, ["content"])
    for r in want:
        idxs = roles.get(r)
        if idxs:
            return template_map["layouts"][idxs[0]]
    return None


def _content_area(template_map: dict, layout: dict) -> dict:
    """正文容器几何（优先 body/object 占位符，没有就用版心推算），单位 inch。"""
    size = template_map["slide_size"]
    best = None
    for ph in layout.get("placeholders", []):
        if ph["kind"] in ("body", "object") and ph["geometry"].get("width"):
            best = ph["geometry"]
            break
    if not best:
        # 版心估算：左右各留 8%，标题下留 22%
        w, h = size["width_in"], size["height_in"]
        return {"left": 0.08 * w, "top": 0.24 * h,
                "width": 0.84 * w, "height": 0.62 * h, "synthesized": True}
    g = best
    return {"left": g["left"] / 914400.0, "top": g["top"] / 914400.0,
            "width": g["width"] / 914400.0, "height": g["height"] / 914400.0,
            "synthesized": False}


def _title_area(template_map: dict, layout: dict) -> dict:
    size = template_map["slide_size"]
    for ph in layout.get("placeholders", []):
        if ph["kind"] == "title" and ph["geometry"].get("width"):
            g = ph["geometry"]
            return {"left": g["left"] / 914400.0, "top": g["top"] / 914400.0,
                    "width": g["width"] / 914400.0, "height": g["height"] / 914400.0}
    w, h = size["width_in"], size["height_in"]
    return {"left": 0.08 * w, "top": 0.06 * h, "width": 0.84 * w, "height": 0.14 * h}


def _fit_size(area: dict, text_chars: int, ladder: list, min_pt: float,
              lines_estimate=None) -> dict:
    """给一段文字挑阶梯里最大的、能放进容器的字号。"""
    for pt in ladder:
        if pt < min_pt:
            break
        cap = units.est_capacity(area["width"], area["height"], pt, 1.0)
        if cap >= text_chars:
            return {"size_pt": float(pt), "capacity_chars": cap, "fits": True}
    return {"size_pt": float(max(min_pt, ladder[-1])),
            "capacity_chars": units.est_capacity(area["width"], area["height"],
                                                 max(min_pt, ladder[-1]), 1.0),
            "fits": False}


def _font_plan(case: dict, template_map: dict) -> dict:
    """标题/正文的中英文字体对：优先主题字体，缺失则用学术安全对并记 fallback。"""
    tf = template_map.get("theme_fonts") or {}
    major = (tf.get("majorFont") or {})
    minor = (tf.get("minorFont") or {})
    lang = (case.get("language") or "zh").lower()
    override = (case.get("fonts") or {})
    if lang.startswith("zh"):
        default = {"title": {"latin": "Arial", "ea": "黑体"},
                   "body": {"latin": "Times New Roman", "ea": "宋体"},
                   "caption": {"latin": "Times New Roman", "ea": "宋体"}}
    else:
        default = {"title": {"latin": "Arial", "ea": "Arial"},
                   "body": {"latin": "Times New Roman", "ea": "Times New Roman"},
                   "caption": {"latin": "Times New Roman", "ea": "Times New Roman"}}
    plan = {}
    for kind, slot in (("title", major), ("body", minor), ("caption", minor)):
        chosen = dict(default[kind])
        if slot.get("latin"):
            chosen.setdefault("theme_latin", slot["latin"])
        if slot.get("ea"):
            chosen.setdefault("theme_ea", slot["ea"])
        chosen.update(override.get(kind) or {})
        chosen["min_pt"] = MIN_SIZE.get("body" if kind != "title" else "title", 12)
        plan[kind] = chosen
    # 主题字体若已安装，且案例没有明确指定，就沿用主题（"保留主题字体"）
    fonts = template_map.get("fonts") or {}
    for kind in ("title", "body"):
        tl = plan[kind].get("theme_latin")
        if tl and (fonts.get(tl) or {}).get("installed") and not (override.get(kind) or {}).get("latin"):
            plan[kind]["latin"] = tl
        te = plan[kind].get("theme_ea")
        if te and (fonts.get(te) or {}).get("installed") and not (override.get(kind) or {}).get("ea"):
            plan[kind]["ea"] = te
    plan["policy"] = ("中英文分别落到 a:latin / a:ea；字体不可用时按 template_map.fonts 的 "
                      "fallback 链替换，并把替换写进 render_report（不静默回退）")
    return plan


def build_plan(case: dict, source_map: dict, template_map: dict,
               work_dir: str = "work") -> dict:
    constraints = {
        "slide_count": case.get("slide_count") or {},
        "minutes": case.get("minutes"),
        "audience": case.get("audience"),
        "language": case.get("language") or "zh",
        "required_sections": case.get("required_sections") or [],
        "title_override": case.get("deck_title"),
        "subtitle_override": case.get("deck_subtitle"),
    }
    sc = constraints["slide_count"] or {}
    smin = int(sc.get("min", sc.get("target", 8)) or 8)
    smax = int(sc.get("max", sc.get("target", smin)) or smin)
    if smax < smin:
        smax = smin
    plan_target = int(sc.get("target", smax) or smax)
    plan_target = max(smin, min(smax, plan_target))

    sections = source_map.get("sections") or []
    blocks = {b["id"]: b for b in source_map.get("blocks") or []}
    figures = source_map.get("figures") or []

    def sec_figs(sec):
        ids = set(sec.get("blocks") or [])
        out = []
        for f in figures:
            if f.get("block_id") in ids:
                out.append(f)
        return out

    # ---- 章节优先级（决定页数不够时先砍谁）
    ranked = []
    for i, sec in enumerate(sections):
        text = " ".join(blocks[b]["text"] for b in sec.get("blocks", []) if b in blocks)
        score = 0.0
        score += 3.0 * len(sec.get("numeric_blocks") or [])
        score += 2.0 * len(sec_figs(sec))
        score += 1.0 if re.search(r"\d", text) else 0.0
        score += min(2.0, len(text) / 400.0)
        # 局限/结论是学术汇报的必备页（题面明确要求"研究问题、方法、结果和限制"），加权保底
        if LIMIT_HINT.search(sec["title"]):
            score += 6.0
        if CONCLUSION_HINT.search(sec["title"]):
            score += 5.5
        score += 0.6 if sec.get("level", 1) == 1 else 0.0
        score -= 0.05 * i
        ranked.append({"sec": sec, "score": round(score, 3), "index": i,
                       "text": text, "figs": sec_figs(sec)})
    ranked.sort(key=lambda r: -r["score"])

    # ---- 页预算
    fixed = 1  # 封面（永不裁）
    figure_slides_budget = max(0, int(sc.get("figure_slides", 3)))
    # 固定页按优先级占位：封面 > ≥1 页内容 > 结论 > 收尾 > 目录。
    # D14-R4 修复：结论页此前**没计入预算**，导致 target=max 时总页数恒为 max+1，
    # 而汇总仍报 success（假绿）。现在按剩余预算逐项决定，并写进 budget_notes。
    budget_notes = []
    left = smax - fixed - 1          # 扣掉封面与至少 1 页内容
    conclusion = 1 if left >= 1 else 0
    if conclusion:
        left -= 1
    else:
        budget_notes.append("slide_count.max=%d 装不下结论页，已省略" % smax)
    closing = 1 if left >= 1 else 0
    if closing:
        left -= 1
    else:
        budget_notes.append("slide_count.max=%d 装不下收尾页，已省略「谢谢 / Q&A」页" % smax)
    agenda = 1 if (left >= 1 and len(ranked) >= 4) else 0
    if not agenda and len(ranked) >= 4:
        budget_notes.append("slide_count.max=%d 装不下目录页，已省略提纲页" % smax)
    # 内容页 = 目标页数 - 封面 - 目录 - 结论 - 收尾（没有目录/结论时不留空）；上限 max 兜底
    content_budget = max(1, min(smax, plan_target) - fixed - closing - conclusion - agenda)
    if content_budget > len(ranked):
        content_budget = len(ranked)

    chosen, dropped = [], []
    for r in ranked:
        if len(chosen) >= content_budget:
            dropped.append({"section": r["sec"]["title"], "locator": r["sec"]["locator"],
                            "score": r["score"], "why": "超出案例页数上限（slide_count.max=%d）" % smax})
            continue
        chosen.append(r)
    chosen.sort(key=lambda r: r["index"])

    # 案例强制覆盖的章节（required_sections）：被裁掉就让分值最低的一页让位并记账
    req = [x for x in (case.get("required_sections") or []) if isinstance(x, str)]
    for want in req:
        if any(want.lower() in (c["sec"]["title"] or "").lower() for c in chosen):
            continue
        cand = next((r for r in ranked if want.lower() in (r["sec"]["title"] or "").lower()), None)
        if cand is None or len(chosen) < 2:
            continue
        victim = min(chosen, key=lambda c: c["score"])
        if victim is cand:
            continue
        chosen.remove(victim)
        chosen.append(cand)
        dropped.append({"section": victim["sec"]["title"], "locator": victim["sec"]["locator"],
                        "score": victim["score"],
                        "why": "为满足 required_sections=%s 而让位" % want})
        chosen.sort(key=lambda r: r["index"])

    fonts = _font_plan(case, template_map)
    slides = []
    change_log = []
    seq = 0

    # ---- 封面
    seq += 1
    lay = _layout_for_role(template_map, "title")
    t_area = _title_area(template_map, lay) if lay else {"width": 8.0, "height": 1.5}
    title = constraints["title_override"] or source_map.get("title") or case.get("task") or "(untitled)"
    # 封面标题留足长度（长标题用 normAutofit 缩放，不硬裁）；超过 120 字才截断并把全文写进备注
    title_txt, tcut = _clip(title, 120)
    subtitle = constraints["subtitle_override"] or (
        case.get("venue") or "")
    meta_bits = []
    if case.get("audience"):
        meta_bits.append("听众：%s" % case["audience"])
    if case.get("minutes"):
        meta_bits.append("时长：%s 分钟" % case["minutes"])
    src_disp = (source_map.get("source") or {}).get("original_file") or \
        (source_map.get("source") or {}).get("file")
    if src_disp:
        meta_bits.append("材料：%s" % src_disp)
    cover_notes = ("封面：用一句话说明研究问题与结论（标题取自源材料，未改写）。\n"
                   "证据定位：%s" % (src_disp or "n/a"))
    if tcut:
        cover_notes += "\n标题过长已截断，全文：%s" % title
    slides.append({
        "index": seq, "role": "title", "layout_hint": (lay or {}).get("name"),
        "layout_index": (lay or {}).get("index"),
        "title": title_txt, "title_truncated": tcut,
        "subtitle": subtitle,
        "meta_line": " | ".join(meta_bits),
        "bullets": [], "figure": None,
        "notes": cover_notes,
        "budget": _fit_size(t_area, len(title_txt), LADDER["title"], MIN_SIZE["title"]),
    })

    # ---- 目录
    if agenda:
        seq += 1
        lay = _layout_for_role(template_map, "agenda")
        area = _content_area(template_map, lay) if lay else {"width": 8.0, "height": 4.5}
        items = [{"text": r["sec"]["title"], "level": 0, "bullet": True,
                  "locator": r["sec"]["locator"], "block_id": None,
                  "quote": "", "kind": "nav", "truncated": False}
                 for r in chosen]
        size = _fit_size(area, sum(len(i["text"]) + 4 for i in items), LADDER["body"],
                         MIN_SIZE["body"])
        slides.append({"index": seq, "role": "agenda", "layout_hint": (lay or {}).get("name"),
                       "layout_index": (lay or {}).get("index"),
                       "title": "提纲 / Outline", "claim": "", "bullets": items,
                       "figure": None,
                       "notes": "按提纲逐节推进；每节先给主张，再给数据，最后给局限。",
                       "budget": size})

    # ---- 章节页 / 结果页
    body_chars_total = 0
    for r in chosen:
        sec, figs = r["sec"], r["figs"]
        used_fig = None
        if figs and figure_slides_budget > 0:
            fig = figs[0]
            if fig.get("image"):
                used_fig = fig
                figure_slides_budget -= 1

        # 句子候选（逐字，来自 block）
        cands = []
        for bi, bid in enumerate(sec.get("blocks") or []):
            b = blocks.get(bid)
            if not b or b["kind"] in ("heading", "image"):
                continue
            for si, s in enumerate(source_extract_split(b["text"])):
                # 句级定位：同段多句时补 "s2/s3"，让每页每条证据都能唯一指回原文
                loc = b["locator"] + ((" s%d" % (si + 1)) if si else "")
                cands.append({"sentence": s, "block_id": bid, "locator": loc,
                              "topic": bi == 0 and si == 0, "order": len(cands)})
        for c in cands:
            c["score"] = _score_sentence(c["sentence"], c["topic"], c["order"])
        cands.sort(key=lambda c: -c["score"])

        # 图 + 文同页：优先两栏版式（左文右图），没有两栏才退回"图上/文下"
        if used_fig:
            lay = _layout_for_role(template_map, "figure",
                                   ["two-column", "figure", "content"])
        else:
            lay = _layout_for_role(template_map, "bullets")
        area = _content_area(template_map, lay) if lay else {"width": 8.0, "height": 4.5}
        # 一个结果页：主张 + 最多 4 条证据（**主张句不再重复出现在 bullet 里**）
        max_bullets = 4
        claim_cand = cands[0] if cands else None
        picked, overflow = [], []
        for c in cands:
            if claim_cand is not None and c is claim_cand:
                continue
            if len(picked) >= max_bullets:
                overflow.append(c)
                continue
            txt, cut = _clip(c["sentence"], 110 if constraints["language"].startswith("zh") else 170)
            picked.append({"text": txt, "level": 0, "bullet": True,
                           "locator": c["locator"], "block_id": c["block_id"],
                           "quote": c["sentence"], "truncated": cut,
                           "score": c["score"]})
        claim_src = claim_cand["sentence"] if claim_cand else ""
        claim, ccut = _clip(claim_src, 70 if constraints["language"].startswith("zh") else 110)
        chars = sum(len(b["text"]) for b in picked) + len(claim)
        size = _fit_size(area, chars, LADDER["body"], MIN_SIZE["body"])
        seq += 1
        slides.append({
            "index": seq, "role": "figure" if used_fig else "bullets",
            "layout_hint": (lay or {}).get("name"),
            "layout_index": (lay or {}).get("index"),
            "title": _clip(sec["title"], 46)[0],
            "title_truncated": _clip(sec["title"], 46)[1],
            "claim": claim, "claim_truncated": ccut,
            "claim_locator": (claim_cand["locator"] if claim_cand else sec["locator"]),
            "bullets": picked,
            "figure": ({"label": used_fig.get("label"), "caption": used_fig.get("caption"),
                        "path": used_fig.get("image"),
                        "source_locator": used_fig.get("locator"),
                        "origin": used_fig.get("kind")} if used_fig else None),
            "notes": _notes_for(sec, picked, overflow, used_fig),
            "budget": size,
            "overflow_to_notes": [{"text": _clip(o["sentence"], 120)[0], "locator": o["locator"]}
                                  for o in overflow[:6]],
        })
        body_chars_total += chars
        if not size["fits"]:
            change_log.append({"what": "正文超预算", "slide": seq,
                               "why": "内容 %d 字 > 容器容量 %d 字（%gpt 下限），"
                                      "按阶梯降到 %gpt 并把余量移入备注" % (
                                          chars, size["capacity_chars"],
                                          MIN_SIZE["body"], size["size_pt"])})

    # ---- 结论页
    if chosen and conclusion:
        seq += 1
        lay = _layout_for_role(template_map, "bullets")
        area = _content_area(template_map, lay) if lay else {"width": 8.0, "height": 4.5}
        con_items = []
        for r in chosen[:3]:
            b = next((blocks[b] for b in r["sec"].get("blocks", []) if b in blocks
                      and blocks[b]["kind"] == "para"), None)
            if b:
                txt, cut = _clip(b["text"], 100)
                con_items.append({"text": txt, "level": 0, "bullet": True,
                                  "locator": b["locator"], "block_id": b["id"],
                                  "quote": b["text"], "truncated": cut})
        size = _fit_size(area, sum(len(i["text"]) for i in con_items) + 20,
                         LADDER["body"], MIN_SIZE["body"])
        slides.append({"index": seq, "role": "conclusion",
                       "layout_hint": (lay or {}).get("name"),
                       "layout_index": (lay or {}).get("index"),
                       "title": "结论 / Conclusion", "claim": "", "bullets": con_items,
                       "figure": None,
                       "notes": "结论只重复源材料明确写出的结论句；未写结论时说明本册结论由结果页推导。",
                       "budget": size})

    # ---- 收尾
    if closing:
        seq += 1
        lay = _layout_for_role(template_map, "closing")
        slides.append({"index": seq, "role": "closing", "layout_hint": (lay or {}).get("name"),
                       "layout_index": (lay or {}).get("index"),
                       "title": "谢谢 / Q&A", "claim": "", "bullets": [], "figure": None,
                       "notes": "留出提问时间；如需复现本册，见 result.json 的 reproduce 命令。",
                       "budget": {"size_pt": 28.0, "fits": True}})
    else:
        dropped.append({"section": "收尾 / Q&A", "locator": None, "score": None,
                        "why": "slide_count.max=%d 装不下固定页（封面+结论+收尾），"
                               "按优先级让位收尾页" % smax})

    for s in slides:
        s["index"] = s.get("index")  # 保序

    plan = {
        "schema": "q08-deck-plan/1",
        "case_id": case.get("case_id") or case.get("id") or "UNKNOWN",
        "meta": {
            "task": case.get("task"),
            "template": case.get("template"),
            "audience": constraints["audience"], "minutes": constraints["minutes"],
            "language": constraints["language"],
            "slide_count_constraint": sc, "slide_count_planned": len(slides),
            "fonts": fonts,
            "footer": (case.get("footer") or _clip(title, 36)[0]),
            "ladders": {"body": LADDER["body"], "title": LADDER["title"],
                        "caption": LADDER["caption"], "min_body_pt": MIN_SIZE["body"]},
            "source_map_sha256": source_map.get("source", {}).get("sha256"),
            "template_sha256": template_map.get("template", {}).get("sha256"),
            "generated_by": "plan_deck.py（确定性种子；agent 可直接改写本文件再 build）",
            "page_budget_note": "页数 = 封面 + 提纲 + 内容页 + 结论 + 收尾；"
                                "固定页按优先级占位（封面>内容>结论>收尾>目录），"
                                "slide_count.max 溢出时按章节分值裁剪并记入 dropped_content",
            "budget_notes": budget_notes,
        },
        "slides": slides,
        "dropped_content": dropped,
        "change_log": change_log,
        "agent_todo": [
            "用源材料原文核对每条 bullet 的表述（脚本只做逐字摘录，不改写事实）",
            "把 `claim` 改成面向听众的一句话主张（若改动，请保持与 quote 一致）",
            "确认 figure 的 caption 与正文引用编号一致、且图号未被重排",
            "检查讲稿备注的时长（约 %s 分钟 / %d 页）" % (
                constraints["minutes"] or "?", len(slides)),
        ],
        "stats": {
            "slides": len(slides), "bullets": sum(len(s["bullets"]) for s in slides),
            "figures_used": sum(1 for s in slides if s.get("figure")),
            "body_chars": body_chars_total,
            "sections_in_source": len(sections), "sections_used": len(chosen),
        },
    }
    return plan


def source_extract_split(text: str) -> list:
    import source_extract
    return source_extract.split_sentences(text)


def _notes_for(sec: dict, picked: list, overflow: list, fig) -> str:
    lines = ["讲解顺序：先给主张 → 再给证据 → 最后给限制。",
             "证据定位（逐条）："]
    for b in picked:
        lines.append("- %s ← %s%s" % (b["text"], b["locator"],
                                      "（截断，全文见下）" if b["truncated"] else ""))
        if b["truncated"]:
            lines.append("    全文：%s" % b["quote"])
    if overflow:
        lines.append("未上页的备选证据（可口头补充，勿静默删除）：")
        for o in overflow[:6]:
            lines.append("- [%s] %s" % (o["locator"], o["sentence"][:140]))
    if fig:
        lines.append("图：%s（%s）｜定位：%s" % (fig.get("label"), fig.get("caption", "")[:80],
                                                fig.get("locator")))
    return "\n".join(lines)


# ------------------------------------------------------------------ 校验

def validate_plan(plan: dict, case: dict, source_map: dict, template_map: dict) -> dict:
    findings = []
    blocks = {b["id"]: b for b in source_map.get("blocks") or []}
    role_layouts = (template_map.get("roles") or {})
    n = len(plan.get("slides") or [])
    sc = (case.get("slide_count") or {})
    if sc.get("min") and n < int(sc["min"]):
        findings.append({"severity": "high", "item": "页数",
                         "detail": "计划 %d 页 < 案例下限 %s" % (n, sc["min"]),
                         "fix": "补章节页或拆分长页"})
    if sc.get("max") and n > int(sc["max"]):
        findings.append({"severity": "high", "item": "页数",
                         "detail": "计划 %d 页 > 案例上限 %s" % (n, sc["max"]),
                         "fix": "合并/裁章节，别压字号"})
    seen = set()
    unverified = 0
    for s in plan.get("slides") or []:
        idx = s.get("index")
        if idx in seen:
            findings.append({"severity": "medium", "item": "页序号重复", "detail": str(idx)})
        seen.add(idx)
        if not s.get("bullets") and s.get("role") not in ("title", "closing", "section"):
            findings.append({"severity": "medium", "item": "页内容为空", "slide": idx,
                             "detail": "role=%s 没有 bullets 也没有 figure" % s.get("role")})
        for b in s.get("bullets") or []:
            if not b.get("locator"):
                findings.append({"severity": "high", "item": "缺证据定位", "slide": idx,
                                 "detail": b.get("text", "")[:40], "fix": "补 locator"})
            if b.get("kind") == "nav":
                continue  # 提纲页只是导航，不对应原文断言
            src = blocks.get(b.get("block_id"))
            quote = (b.get("quote") or b.get("text") or "")
            if src is None or (quote and quote[:24] not in src["text"]):
                unverified += 1
                findings.append({"severity": "high", "item": "引文无法回源", "slide": idx,
                                 "detail": quote[:48],
                                 "fix": "用源材料原文，或把 block_id 指向正确段落"})
        fig = s.get("figure")
        if fig and not fig.get("path"):
            findings.append({"severity": "low", "item": "图无文件", "slide": idx,
                             "detail": fig.get("label"), "fix": "提供图片或用 case.figure_specs 出图"})
        if s.get("role") not in ("title", "closing") and not s.get("notes"):
            findings.append({"severity": "low", "item": "缺讲稿备注", "slide": idx})
        lay = s.get("layout_index")
        if lay is not None and lay >= template_map.get("layout_count", 0):
            findings.append({"severity": "high", "item": "版式序号越界", "slide": idx,
                             "detail": str(lay)})
        # 页内容体积预算（不改字号硬塞的底线：超容量 1.4 倍就必须拆/裁）
        if s.get("role") not in ("title", "closing"):
            lay_info = next((l for l in template_map.get("layouts") or []
                             if l.get("index") == lay), None)
            if lay_info:
                area = _content_area(template_map, lay_info)
                size = float(s.get("budget", {}).get("size_pt")
                             or LADDER["body"][0])
                cap = units.est_capacity(area["width"], area["height"], size)
                used = len(s.get("claim") or "") + sum(len(b.get("text") or "")
                                                       for b in s.get("bullets") or [])
                if s.get("figure"):
                    used *= 0.55  # 图占掉一半容器
                if cap and used > cap * 1.4:
                    findings.append({"severity": "medium", "item": "页内容超预算",
                                     "slide": idx,
                                     "detail": "%d 字 / 容量 %d 字 @%gpt"
                                               % (used, cap, size),
                                     "fix": "拆页或把次要证据移入讲稿备注"})
    score = {
        "slides": n, "locators": sum(1 for s in (plan.get("slides") or [])
                                     for _ in (s.get("bullets") or [])),
        "unverified_quotes": unverified,
        "layout_roles_available": sorted(role_layouts.keys()),
    }
    return {"findings": findings, "summary": score,
            "ok": not any(f["severity"] == "high" for f in findings)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="paper → page-level deck plan")
    ap.add_argument("--case", required=True)
    ap.add_argument("--source-map", required=True)
    ap.add_argument("--template-map", required=True)
    ap.add_argument("--out", default="plan.json")
    ap.add_argument("--validate", metavar="PLAN")
    a = ap.parse_args(argv)
    case = json.load(open(a.case, encoding="utf-8"))
    sm = json.load(open(a.source_map, encoding="utf-8"))
    tm = json.load(open(a.template_map, encoding="utf-8"))
    if a.validate:
        plan = json.load(open(a.validate, encoding="utf-8"))
        rep = validate_plan(plan, case, sm, tm)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep["ok"] else 3
    plan = build_plan(case, sm, tm)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    rep = validate_plan(plan, case, sm, tm)
    st = plan["stats"]
    print("plan_deck: %d 页 (bullets=%d figures=%d) → %s | validate_ok=%s" % (
        st["slides"], st["bullets"], st["figures_used"], a.out, rep["ok"]))
    for f in rep["findings"][:8]:
        print("  [%s] %s slide=%s %s" % (f["severity"], f["item"], f.get("slide"),
                                         f.get("detail", "")[:70]))
    return 0 if rep["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
