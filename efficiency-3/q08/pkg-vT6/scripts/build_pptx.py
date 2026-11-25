# -*- coding: utf-8 -*-
"""build_pptx.py —— 把 plan.json 套进模板，产出**真正继承了母版/版式/占位符**的 pptx。

关键点（也是与"把文字塞进默认模板"的区别）：
  1. 不新建 Presentation()，而是打开模板/起始稿再 add_slide(layout)：
     母版-版式-占位符继承链留在包里（audit 会从 XML 复核）。
  2. date/footer/slide-number 是 latent 占位符，add_slide 不会克隆 —— 这里手动 clone，
     页码写成可编辑域 a:fld type="slidenum"。
  3. 字体分 latin / ea 两路写：中文走 a:ea，避免渲染端按 latin 字体回退导致版式错乱；
     主题字体可用就沿用主题，不可用按 fallback 链替换并记账。
  4. 溢出先用「字号阶梯 + normAutofit fontScale」，再不行把多余内容移入备注，
     字号永不低于 plan.meta.ladders.min_body_pt。
  5. 图片按容器**等比**放置（fit/cover 明确选择），并记录缩放与宽高比偏差。

用法：
    python build_pptx.py --plan plan.json --template t.pptx --out deck.pptx \
        [--template-map template_map.json] [--build-log build_log.json]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）

from pptx.util import Emu, Inches, Pt

import pptx_util as U
import units

DEFAULT_LADDER_BODY = [20, 18, 16, 14]
DEFAULT_MIN_BODY = 14.0
DEFAULT_LADDER_TITLE = [40, 36, 32, 28, 24]


def _pt(plan: dict, kind: str, default: float) -> float:
    fonts = (plan.get("meta") or {}).get("fonts") or {}
    node = fonts.get(kind) or {}
    return float(node.get("size_pt") or default)


def _fonts(plan: dict) -> dict:
    f = (plan.get("meta") or {}).get("fonts") or {}
    return {
        "title": (f.get("title") or {}).get("latin") or "Arial",
        "title_ea": (f.get("title") or {}).get("ea") or "SimHei",
        "body": (f.get("body") or {}).get("latin") or "Times New Roman",
        "body_ea": (f.get("body") or {}).get("ea") or "SimSun",
        "caption": (f.get("caption") or {}).get("latin") or "Times New Roman",
        "caption_ea": (f.get("caption") or {}).get("ea") or "SimSun",
    }


def _find_ph(slide, kind, idx=None):
    for ph in slide.placeholders:
        if idx is not None:
            try:
                if int(ph.placeholder_format.idx) == int(idx):
                    return ph
            except Exception:
                pass
        if U.ph_kind(ph) == kind:
            return ph
    return None


def _layout_ph(layout, kind, prefer_idx=None):
    for ph in layout.placeholders:
        if U.ph_kind(ph) == kind:
            if prefer_idx is None or int(ph.placeholder_format.idx) == prefer_idx:
                return ph
    if prefer_idx is not None:
        for ph in layout.placeholders:
            try:
                if int(ph.placeholder_format.idx) == prefer_idx:
                    return ph
            except Exception:
                pass
    return None


def _geom(ph, slide_w, slide_h) -> dict:
    left = ph.left if ph.left is not None else 0
    top = ph.top if ph.top is not None else 0
    width = ph.width if ph.width is not None else slide_w // 2
    height = ph.height if ph.height is not None else slide_h // 2
    return {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}


def _fit_text_to_box(entries, box_w_in, box_h_in, sizes, min_pt, line_spacing=1.0):
    """给定若干行文字与容器，返回 (最终字号, fontScale, 是否仍溢出, 每行估算行数)。

    entries: [{"text":..,"size_pt":..}]；只有 level 0 参与字号阶梯，level>0 用 0 级的 80%。
    """
    def need(size):
        h = 0.0
        for e in entries:
            pt = size if e.get("_level", 0) == 0 else max(min_pt, size * 0.82)
            h += units.block_height_in(e["text"], box_w_in, pt, line_spacing,
                                       space_before_pt=4 if e is not entries[0] else 0)
        return h

    for size in sizes:
        if size < min_pt:
            break
        if need(size) <= box_h_in:
            return float(size), 1.0, False
    base = max(min_pt, sizes[-1])
    required = need(base)
    # 0.95 余量：估算有误差，宁可让 PowerPoint 的 normAutofit 再补一点，也不要贴边
    scale = max(0.62, min(1.0, (box_h_in * 0.95) / required if required else 1.0))
    return float(base), round(scale, 4), required > box_h_in * 1.02


def _apply_lines(tf, entries, latin, ea, size_pt, line_spacing, align, anchor,
                 font_scale=1.0, color=None):
    lines = []
    for e in entries:
        lvl = int(e.get("_level", 0))
        lines.append({"text": e["text"], "level": max(0, lvl),
                      "size_pt": size_pt if lvl == 0 else max(12.0, size_pt * 0.82),
                      "bold": bool(e.get("bold", lvl == 0 and e.get("_claim"))),
                      "bullet": bool(e.get("bullet", lvl >= 0)),
                      "color_rgb": color if lvl == 0 else None,
                      "space_before_pt": 6 if lvl == 0 and e.get("_claim") else 3})
    U.set_text_frame(tf, lines, latin, ea, size_pt, line_spacing, align, anchor)
    if font_scale < 0.999:
        U.set_norm_autofit(tf, font_scale)


def build(plan: dict, template_path: str, out_path: str,
          template_map: dict | None = None, starting_deck: str | None = None) -> dict:
    if not os.path.isfile(template_path):
        raise FileNotFoundError(template_path)
    prs = U.load(template_path)
    slide_w, slide_h = int(prs.slide_width), int(prs.slide_height)
    theme = U.theme_info(template_path)
    fonts = _fonts(plan)
    meta = plan.get("meta") or {}
    ladders = meta.get("ladders") or {}
    body_ladder = [float(x) for x in (ladders.get("body") or DEFAULT_LADDER_BODY)]
    title_ladder = [float(x) for x in (ladders.get("title") or DEFAULT_LADDER_TITLE)]
    cap_ladder = [float(x) for x in (ladders.get("caption") or [14, 12, 11, 10])]
    min_body = float(ladders.get("min_body_pt") or DEFAULT_MIN_BODY)

    removed = U.strip_slides(prs)
    total_slides = len(plan.get("slides") or [])
    build_log = {
        "template": os.path.basename(template_path),
        "template_sha256": units.sha256_file(template_path),
        "stripped_slides": removed,
        "mode": "adapt" if starting_deck else "build",
        "starting_deck": os.path.basename(starting_deck) if starting_deck else None,
        "slide_size": U.slide_size(prs),
        "theme_fonts": theme.get("fonts", {}),
        "slides": [],
        "warnings": [],
    }

    for spec in plan.get("slides") or []:
        role = spec.get("role") or "bullets"
        layout, linfo, why = U.pick_layout(
            prs, {"bullets": "bullets", "conclusion": "bullets", "figure": "figure",
                  "title": "title", "agenda": "agenda", "section": "section",
                  "closing": "closing"}.get(role, role),
            explicit=spec.get("layout_index") if spec.get("layout_index") is not None
            else spec.get("layout_hint"))
        slide = U.new_slide(prs, layout)
        rec = {
            "index": spec.get("index"), "role": role,
            "layout": layout.name, "layout_index": list(prs.slide_layouts).index(layout),
            "layout_rationale": why,
            "placeholders_filled": [], "placeholders_synthesized": [],
            "font_sizes": {}, "font_scale": {}, "overflow_to_notes": [],
            "figure": None, "title_inherited": True,
        }

        # ---------------- 标题 ----------------
        title_text = spec.get("title") or ""
        ph_title = _find_ph(slide, "title") or _find_ph(slide, "subtitle")
        if ph_title is not None and title_text:
            # 内容页标题阶梯收窄（封面/章节页 40-36，内容页 ≤32），避免标题喧宾夺主
            t_ladder = title_ladder if role in ("title", "section", "closing") else \
                ([s for s in title_ladder if s <= 32] or title_ladder)
            g = _geom(ph_title, slide_w, slide_h)
            size, scale, over = _fit_text_to_box(
                [{"text": title_text, "_level": 0}], g["width"] / 914400.0,
                g["height"] / 914400.0, t_ladder, 20.0, 1.0)
            U.set_placeholder_text(ph_title, [{"text": title_text, "bullet": False, "level": -1}],
                                   fonts["title"], fonts["title_ea"], size, 1.0,
                                   "left", "middle", font_scale=scale)
            rec["placeholders_filled"].append({"idx": int(ph_title.placeholder_format.idx),
                                               "kind": "title", "px": size})
            rec["font_sizes"]["title"] = size
            if scale < 1:
                rec["font_scale"]["title"] = scale
            if over:
                build_log["warnings"].append(
                    "slide %s 标题仍溢出（%d 字），建议改短标题" % (spec.get("index"), len(title_text)))
                rec["overflow_to_notes"].append({"kind": "title"})

        # ---------------- 封面/收尾的副标题 ----------------
        ph_sub = _find_ph(slide, "subtitle")
        sub_bits = [x for x in (spec.get("subtitle"), spec.get("meta_line")) if x]
        if ph_sub is not None and sub_bits:
            g = _geom(ph_sub, slide_w, slide_h)
            size, scale, _ = _fit_text_to_box(
                [{"text": s, "_level": 0} for s in sub_bits],
                g["width"] / 914400.0, g["height"] / 914400.0, cap_ladder, 10.0, 1.0)
            U.set_placeholder_text(ph_sub,
                                   [{"text": s, "bullet": False, "level": -1} for s in sub_bits],
                                   fonts["body"], fonts["body_ea"], size, 1.0,
                                   "left", "top", font_scale=scale)
            rec["placeholders_filled"].append({"idx": int(ph_sub.placeholder_format.idx),
                                               "kind": "subtitle", "px": size})

        # ---------------- 正文 ----------------
        body_phs = [ph for ph in slide.placeholders if U.ph_kind(ph) in ("body", "object")]
        ph_body = body_phs[0] if body_phs else None
        ph_body2 = body_phs[1] if len(body_phs) > 1 else None
        # 页脚带会占掉底部一条；把正文容器高度收到页脚上方，避免文字压页脚
        footer_top = None
        for ph in slide.placeholders:
            if U.ph_kind(ph) == "footer" and ph.top is not None:
                footer_top = int(ph.top)
        entries = []
        if spec.get("claim"):
            entries.append({"text": spec["claim"], "_level": 0, "_claim": True,
                            "bullet": False, "bold": False})
        for b in spec.get("bullets") or []:
            entries.append({"text": b["text"], "_level": int(b.get("level", 0)),
                            "bullet": True})
        if entries and ph_body is not None:
            g = _geom(ph_body, slide_w, slide_h)
            h_in = g["height"] / 914400.0
            if footer_top is not None and footer_top > g["top"]:
                avail = footer_top - g["top"] - Pt(4)
                if avail > 0:
                    h_in = min(h_in, avail / 914400.0)
            size, scale, over = _fit_text_to_box(
                entries, g["width"] / 914400.0, h_in,
                body_ladder, min_body, 1.0)
            U.set_placeholder_text(ph_body, entries, fonts["body"], fonts["body_ea"],
                                   size, 1.0, "left", "top", font_scale=scale)
            rec["placeholders_filled"].append({"idx": int(ph_body.placeholder_format.idx),
                                               "kind": "body", "px": size})
            rec["font_sizes"]["body"] = size
            if scale < 1:
                rec["font_scale"]["body"] = scale
            if over:
                # 阶梯到底仍溢出：把最后几条 bullet 移入备注，字号不动
                moved = []
                while len(entries) > 2 and _fit_text_to_box(
                        entries, g["width"] / 914400.0, g["height"] / 914400.0,
                        [size], min_body, 1.0)[2]:
                    moved.insert(0, entries.pop())
                if moved:
                    U.set_placeholder_text(ph_body, entries, fonts["body"], fonts["body_ea"],
                                           size, 1.0, "left", "top", font_scale=scale)
                    notes_add = "\n[超容器移入备注]\n" + "\n".join(
                        "- " + m["text"] for m in moved)
                    spec["notes"] = (spec.get("notes") or "") + notes_add
                    rec["overflow_to_notes"] = [m["text"][:80] for m in moved]
                    build_log["warnings"].append(
                        "slide %s 正文超容器，%d 条移入备注（字号保持 %.0fpt）"
                        % (spec.get("index"), len(moved), size))
        elif entries:
            # 版式没有正文占位符：合成文本框（记录为 placeholder_synthesized）
            cfg = (template_map or {}).get("slide_size") or {}
            w_in = cfg.get("width_in") or slide_w / 914400.0
            h_in = cfg.get("height_in") or slide_h / 914400.0
            box = {"left": int(0.08 * w_in * 914400), "top": int(0.24 * h_in * 914400),
                   "width": int(0.84 * w_in * 914400), "height": int(0.60 * h_in * 914400)}
            size, scale, over = _fit_text_to_box(
                entries, box["width"] / 914400.0, box["height"] / 914400.0,
                body_ladder, min_body, 1.0)
            U.add_textbox(slide, box["left"], box["top"], box["width"], box["height"],
                          [{"text": e["text"], "level": max(0, int(e.get("_level", 0))),
                            "bullet": bool(e.get("bullet", True)),
                            "size_pt": size if e.get("_level", 0) == 0 else size * 0.82}
                           for e in entries],
                          fonts["body"], fonts["body_ea"], size, 1.0,
                          font_scale=scale, name="SynthBody")
            rec["placeholders_synthesized"].append({"kind": "body", "reason": "版式无 body/object 占位符",
                                                    "geometry_in": [round(box[k] / 914400.0, 3)
                                                                    for k in ("left", "top", "width", "height")]})
            rec["font_sizes"]["body"] = size
            if over:
                build_log["warnings"].append("slide %s 合成正文仍溢出" % spec.get("index"))

        # ---------------- 图 ----------------
        fig = spec.get("figure")
        if fig and fig.get("path") and os.path.isfile(fig["path"]):
            ph_pic = _find_ph(slide, "picture")
            if ph_pic is not None:
                container = _geom(ph_pic, slide_w, slide_h)
                pic_in = "版式 picture 占位符"
            elif ph_body2 is not None:
                # 两栏版式：左栏放文字，右栏放图 → 删掉右栏空占位符再插图（保持可编辑）
                container = _geom(ph_body2, slide_w, slide_h)
                pic_in = "两栏版式右栏（body 占位符位置）"
                ph_body2._element.getparent().remove(ph_body2._element)
            elif ph_body is not None:
                g = _geom(ph_body, slide_w, slide_h)
                bottom = int(g["top"] + g["height"])
                if footer_top is not None and footer_top > g["top"]:
                    bottom = min(bottom, footer_top - Pt(4))
                container = {"left": g["left"], "top": int(g["top"] + (bottom - g["top"]) * 0.52),
                             "width": g["width"],
                             "height": int((bottom - g["top"]) * 0.48)}
                pic_in = "正文容器下半部（版式无图占位符）"
            else:
                container = {"left": int(slide_w * 0.5), "top": int(slide_h * 0.25),
                             "width": int(slide_w * 0.44), "height": int(slide_h * 0.55)}
                pic_in = "合成区域（版式无正文/图占位符）"
            cap = None
            if fig.get("label") or fig.get("caption"):
                cap = "%s %s" % (fig.get("label") or "", fig.get("caption") or "")
                cap = cap.strip()[:140]
            placed = U.fit_picture(slide, fig["path"], container, mode=fig.get("mode", "fit"),
                                   caption=cap, latin=fonts["caption"],
                                   ea=fonts["caption_ea"],
                                   caption_pt=cap_ladder[1] if len(cap_ladder) > 1 else 12)
            rec["figure"] = placed
            rec["figure"]["label"] = fig.get("label")
            rec["figure"]["source_locator"] = fig.get("source_locator")
            rec["figure"]["container_source"] = pic_in
        elif fig:
            build_log["warnings"].append("slide %s 声明了图但文件缺失：%s"
                                         % (spec.get("index"), fig.get("path")))

        # ---------------- 页脚 / 页码 ----------------
        if role not in ("title", "closing", "section"):
            U.ensure_header_footer_flags(slide, footer=True, slide_number=True)
            ftr_ph_layout = _layout_ph(layout, "footer")
            if ftr_ph_layout is not None:
                ph = U.clone_placeholder(slide, ftr_ph_layout)
                if ph is not None:
                    footer_text = spec.get("footer") or meta.get("footer") or ""
                    # 页脚按占位符宽度裁到一行（页脚溢出会把版面顶乱）
                    fg = _geom(ph, slide_w, slide_h)
                    cap_chars = max(12, units.est_capacity(
                        fg["width"] / 914400.0, 0.34, 9.0))
                    footer_text = str(footer_text)[:cap_chars]
                    # 页码同时写进页脚文本（可编辑、任何渲染端都看得见）：
                    # 克隆的 sldNum 域占位符在部分渲染端不被绘制，页脚文本是保底可见通道。
                    if spec.get("index") and total_slides:
                        pn = " · %d/%d" % (spec["index"], total_slides)
                        footer_text = footer_text[:max(0, cap_chars - len(pn))] + pn
                    U.set_placeholder_text(ph, [{"text": footer_text, "bullet": False,
                                                 "level": -1}],
                                           fonts["body"], fonts["body_ea"], 9.0, 1.0,
                                           "left", "middle")
                    rec["placeholders_filled"].append({"idx": int(ph.placeholder_format.idx),
                                                       "kind": "footer", "px": 9.0})
            num_ph_layout = _layout_ph(layout, "slide_number")
            if num_ph_layout is not None:
                ph = U.clone_placeholder(slide, num_ph_layout)
                if ph is not None:
                    # 页面域写成 a:fld type="slidenum"，同时把可见文本填成真实页码：
                    # PowerPoint 会把它当域随时更新；不支持域解析的渲染端也能显示数字。
                    U.set_slide_number(ph, start_number_text=str(spec.get("index") or ""))
                    rec["placeholders_filled"].append({"idx": int(ph.placeholder_format.idx),
                                                       "kind": "slide_number", "px": 10.0})
                    rec["page_number_field"] = True
                else:
                    rec["page_number_field"] = False
            else:
                build_log["warnings"].append("slide %s 版式无页码占位符" % spec.get("index"))

        # ---------------- 备注 ----------------
        notes = spec.get("notes") or ""
        if spec.get("overflow_to_notes"):
            notes += "\n" + json.dumps(spec["overflow_to_notes"], ensure_ascii=False)
        if notes:
            U.set_notes(slide, notes)
            rec["notes_chars"] = len(notes)

        # 清掉没用到的空占位符（否则导出里会留空框）
        for ph in list(slide.placeholders):
            keep = {"title", "subtitle", "body", "object", "picture", "footer",
                    "slide_number", "date"}
            if U.ph_kind(ph) not in keep:
                continue
            if ph.has_text_frame and not ph.text_frame.text.strip() and \
                    U.ph_kind(ph) not in ("footer", "slide_number"):
                if U.ph_kind(ph) == "picture":
                    continue
                ph._element.getparent().remove(ph._element)
                rec.setdefault("placeholders_removed", []).append(U.ph_kind(ph))

        rec["geometry"] = U.placeholder_geometry_report(slide)
        build_log["slides"].append(rec)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    prs.save(out_path)
    build_log["out"] = os.path.basename(out_path)
    build_log["out_bytes"] = os.path.getsize(out_path)
    build_log["out_sha256"] = units.sha256_file(out_path)
    build_log["slides_count"] = len(prs.slides)
    return build_log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fill pptx template per plan (inheritance preserved)")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--template-map")
    ap.add_argument("--starting-deck")
    ap.add_argument("--build-log", default="build_log.json")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan, encoding="utf-8"))
    tm = json.load(open(a.template_map, encoding="utf-8")) if a.template_map else None
    log = build(plan, a.template, a.out, tm, starting_deck=a.starting_deck)
    with open(a.build_log, "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=2)
    print("build_pptx: %d slides → %s (%.1fKB, sha256=%s…)" % (
        log["slides_count"], a.out, log["out_bytes"] / 1024.0, log["out_sha256"][:12]))
    for w in log["warnings"]:
        print("  ! %s" % w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
