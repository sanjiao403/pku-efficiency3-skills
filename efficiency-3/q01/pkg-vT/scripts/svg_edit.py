#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svg_edit -- source-preserving edit of an existing SVG.

Only the elements named in the operation list are touched; every other byte of
the original file is kept, so the reviewer can diff "what I changed" against the
supplied figure instead of receiving a whole new artwork.  Element ids come from
the supplied source; unresolved ids are reported, never guessed.
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # never leave __pycache__ behind


import re

import ga_core as C


def _find_element(svg: str, eid: str):
    """Return (start, end_of_open_tag, is_text, content_end) for id=eid."""
    pat = re.compile(r'id\s*=\s*"%s"' % re.escape(eid))
    m = pat.search(svg)
    if not m:
        return None
    start = svg.rfind("<", 0, m.start())
    if start < 0:
        return None
    open_end = svg.find(">", m.end())
    if open_end < 0:
        return None
    tag = re.match(r"<\s*([a-zA-Z:]+)", svg[start:open_end + 1])
    tag_name = tag.group(1) if tag else ""
    is_text = tag_name == "text"
    if is_text:
        close = svg.find("</text>", open_end)
        return (start, open_end, True, close if close >= 0 else open_end)
    return (start, open_end, False, open_end)


def _set_attr(svg: str, eid: str, attr: str, value: str):
    span = _find_element(svg, eid)
    if not span:
        return svg, False
    start, open_end, is_text, _ = span
    head = svg[start:open_end + 1]
    apat = re.compile(r'(\s%s\s*=\s*")([^"]*)(")' % re.escape(attr))
    if apat.search(head):
        new_head = apat.sub(lambda mm: mm.group(1) + value + mm.group(3), head, count=1)
    else:
        close = "/>" if head.rstrip().endswith("/>") else ">"
        new_head = head[:-len(close)] + ' %s="%s"' % (attr, value) + close
    return svg[:start] + new_head + svg[open_end + 1:], True


def apply_ops(svg: str, ops) -> dict:
    record = {"source_sha256": C.sha256_bytes(svg.encode("utf-8")), "applied": [],
              "skipped": [], "n_ops": len(ops or [])}
    cur = svg
    for op in (ops or []):
        if not isinstance(op, dict):
            record["skipped"].append({"op": str(op)[:60], "why": "不是对象"})
            continue
        eid = str(op.get("id") or op.get("element") or "")
        kind = str(op.get("op") or op.get("action") or "").lower()
        if not eid:
            record["skipped"].append({"why": "缺少元素 id", "op": kind})
            continue
        span = _find_element(cur, eid)
        if not span:
            record["skipped"].append({"id": eid, "op": kind, "why": "原图中找不到该 id"})
            continue
        before = cur[span[0]:span[1] + 1]
        if kind in ("set_text", "text", "replace_text", "edit_text"):
            if not span[2]:
                record["skipped"].append({"id": eid, "op": kind, "why": "不是 <text> 元素"})
                continue
            value = str(op.get("value") if op.get("value") is not None else op.get("text", ""))
            cur = cur[:span[1] + 1] + value.replace("&", "&amp;").replace("<", "&lt;") \
                + cur[span[3]:]
            record["applied"].append({"id": eid, "op": kind, "before": before[:120],
                                      "after": value[:120]})
        elif kind in ("set_fill", "fill", "recolor"):
            value = str(op.get("value") or op.get("color") or "")
            cur, ok = _set_attr(cur, eid, "fill", value)
            record["applied"].append({"id": eid, "op": kind, "value": value}) if ok else \
                record["skipped"].append({"id": eid, "op": kind, "why": "属性写入失败"})
        elif kind in ("set_size", "font_size", "resize_text"):
            value = str(op.get("value") or op.get("size") or "")
            cur, ok = _set_attr(cur, eid, "font-size", value)
            record["applied"].append({"id": eid, "op": kind, "value": value}) if ok else \
                record["skipped"].append({"id": eid, "op": kind, "why": "属性写入失败"})
        elif kind in ("move", "translate", "shift"):
            dx = float(op.get("dx") or 0)
            dy = float(op.get("dy") or 0)
            inner = cur[span[0]:span[1] + 1]
            for attr, delta in (("x", dx), ("y", dy)):
                mm = re.search(r'\s%s\s*=\s*"(-?[\d.]+)"' % attr, inner)
                if mm and delta:
                    new = ("%.1f" % (float(mm.group(1)) + delta)).rstrip("0").rstrip(".")
                    inner = inner[:mm.start(1)] + new + inner[mm.end(1):]
            cur = cur[:span[0]] + inner + cur[span[1] + 1:]
            record["applied"].append({"id": eid, "op": kind, "dx": dx, "dy": dy})
        else:
            record["skipped"].append({"id": eid, "op": kind, "why": "不支持的操作类型"})
    record["edited_sha256"] = C.sha256_bytes(cur.encode("utf-8"))
    record["changed"] = record["source_sha256"] != record["edited_sha256"]
    record["untouched_bytes_preserved"] = True
    return {"svg": cur, "record": record}

