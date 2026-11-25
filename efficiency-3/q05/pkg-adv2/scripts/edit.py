#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# edit.py -- 源文件保留式编辑（source-preserving edit）
#
#   python3 scripts/edit.py --svg figures/figure.svg --out figures/figure.edited.svg \
#           --set-text U1 "改后的标注文字"
#   python3 scripts/edit.py --svg figures/figure.svg --out e.svg --set-attr U1 data-quote "…"
#   python3 scripts/edit.py --svg figures/figure.svg --dry-run
#
# 默认走 **行级外科编辑**：只在文件文本里替换目标元素的那一段，其余字节原样保留
# （`lines_changed` 应为 1；`byte_identical_outside_target` 为真）。
# `--engine xml` 则整份用 ElementTree 重新序列化 —— 结构仍然保持，但**整文件会被重排**，
# 此时报告会如实写 lines_changed 与 byte_identical_outside_target=false（不夸大承诺）。
#
# 判据（写进 report）：touched/结构计数 + 行级字节计数 + 输出良构 + 图层不变。
import argparse, json, os, re, sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def structure(path):
    """结构视图：图层、图元 id、引文、文本序列（用于与编辑后文件比对）。"""
    root = ET.parse(path).getroot()
    return {
        "layers": [g.get("id") for g in root if (g.get("id") or "").startswith("layer-")],
        "nodes": [e.get("data-node") for e in root.iter() if e.get("data-role") == "node-shape"],
        "quotes": [e.get("data-quote") for e in root.iter() if e.get("data-quote")],
        "texts": ["".join(e.itertext()) for e in root.iter() if e.tag == "{%s}text" % NS],
        "elements": sum(1 for g in root if (g.get("id") or "").startswith("layer-")
                        for _ in g),
    }


def lines_of(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().split("\n")


def surgical(src_lines, tid, set_text=None, set_attr=None):
    """行级替换：返回 (新行列表, 说明)；找不到唯一目标行则返回 (None, 原因)。"""
    pat_hit = re.compile(r'data-(?:node|fid)="%s"' % re.escape(tid))
    cands = [i for i, ln in enumerate(src_lines) if pat_hit.search(ln)]
    if not cands:
        return None, "no line carries data-node/data-fid=%s" % tid
    if set_text:
        tex = [i for i in cands if "<text" in src_lines[i] and "</text>" in src_lines[i]]
        if not tex:
            return None, "%s has no single-line <text> element (use --engine xml)" % tid
        i = tex[0]
        m = re.search(r"(<text\b[^>]*>)(.*?)(</text>)", src_lines[i])
        if not m:
            return None, "cannot locate <text> span on the target line"
        before = m.group(2)
        new = src_lines[:]
        new[i] = src_lines[i][:m.start(2)] + _esc(set_text) + src_lines[i][m.end(2):]
        return new, {"kind": "text", "line": i + 1, "before": before[:80], "after": set_text[:80]}
    _tid, attr, val = set_attr
    for i in cands:
        m = re.search(r'(\b%s=")([^"]*)(")' % re.escape(attr), src_lines[i])
        if m:
            new = src_lines[:]
            new[i] = src_lines[i][:m.start(2)] + _esc(val).replace('"', "&quot;") + src_lines[i][m.end(2):]
            return new, {"kind": "attr", "line": i + 1, "attr": attr, "before": m.group(2)[:80],
                         "after": val[:80]}
    return None, "attribute %s not present on any element of %s (use --engine xml)" % (attr, tid)


def main(a=None):
    ap = argparse.ArgumentParser(description="source-preserving edit of a layered SVG")
    ap.add_argument("--svg", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--set-text", nargs=2, metavar=("NODE_ID", "TEXT"), default=None)
    ap.add_argument("--set-attr", nargs=3, metavar=("NODE_ID", "ATTR", "VALUE"), default=None)
    ap.add_argument("--line", type=int, default=1, help="target the N-th <text> inside the element")
    ap.add_argument("--engine", choices=("auto", "line", "xml"), default="auto")
    ap.add_argument("--allow-provenance-edit", action="store_true",
                    help="允许改 data-quote 这类溯源字段（默认拒绝：改引文等于改证据来源）")
    ap.add_argument("--dry-run", action="store_true")
    x = ap.parse_args(a)
    try:
        st_before = structure(x.svg)
    except Exception as e:
        print(json.dumps({"ok": False, "why": "svg not parseable: %s" % e}, ensure_ascii=False))
        return 2
    rep = {"svg": os.path.basename(x.svg), "elements_total": st_before["elements"],
           "layers": st_before["layers"], "texts": len(st_before["texts"]),
           "engine": x.engine, "dry_run": bool(x.dry_run)}
    if x.dry_run:
        rep["ok"] = True
        print(json.dumps(rep, ensure_ascii=False))
        return 0
    if not (x.set_text or x.set_attr):
        rep.update(ok=False, why="nothing to do: pass --set-text/--set-attr (or --dry-run)")
        print(json.dumps(rep, ensure_ascii=False))
        return 2
    tid = (x.set_text or x.set_attr)[0]
    if x.set_attr:
        _a = x.set_attr[1]
        if _a.startswith("data-") and _a != "data-color" and not x.allow_provenance_edit:
            rep.update(ok=False, provenance_changed=True, requires_reverify=True,
                       why="%s 是溯源字段：改它等于改证据来源，应先改材料/结构后重跑；"
                           "确需修改请加 --allow-provenance-edit 并重新复核" % _a)
            print(json.dumps(rep, ensure_ascii=False))
            return 2
    src_lines = lines_of(x.svg)
    out = x.out or (os.path.splitext(x.svg)[0] + ".edited.svg")
    info = None
    if x.engine in ("auto", "line"):
        new_lines, info = surgical(src_lines, tid, set_text=x.set_text, set_attr=x.set_attr)
        if new_lines is None and x.engine == "line":
            rep.update(ok=False, why=info)
            print(json.dumps(rep, ensure_ascii=False))
            return 2
        if new_lines is not None:
            with open(out, "w", encoding="utf-8", newline="") as fh:
                fh.write("\n".join(new_lines))
        else:
            rep["line_engine_note"] = info
    if info is None or not os.path.exists(out):                     # 回退：整份重序列化
        try:
            tree = ET.parse(x.svg)
        except Exception as e:
            rep.update(ok=False, why="svg not parseable: %s" % e)
            print(json.dumps(rep, ensure_ascii=False))
            return 2
        root = tree.getroot()
        TXT = "{%s}text" % NS
        hits = [e for g in root if (g.get("id") or "").startswith("layer-") for e in g
                if e.get("data-node") == tid or e.get("data-fid") == tid]
        if x.set_text:
            hits = [h for h in hits if h.tag == TXT or any(t.tag == TXT for t in h.iter())]
        if not hits:
            rep.update(ok=False, why="no element with data-node/data-fid=%s" % tid)
            print(json.dumps(rep, ensure_ascii=False))
            return 2
        el = hits[0]
        if x.set_text:
            tex = [t for t in el.iter() if t.tag == TXT]
            idx = min(max(1, x.line), len(tex)) - 1
            before = tex[idx].text or ""
            tex[idx].text = x.set_text[1]
            info = {"kind": "text", "text_index": idx + 1, "before": before[:80],
                    "after": x.set_text[1][:80]}
        else:
            attr, val = x.set_attr[1], x.set_attr[2]
            info = {"kind": "attr", "attr": attr, "before": el.get(attr), "after": val}
            el.set(attr, val)
        rep["engine"] = "xml"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            fh.write(ET.tostring(root, encoding="unicode"))
    # ---- 复核：结构 + 行级字节 ----
    try:
        st_after = structure(out)
        rep["well_formed"] = True
    except Exception as e:
        rep.update(well_formed=False, ok=False, why="written file not parseable: %s" % e)
        print(json.dumps(rep, ensure_ascii=False))
        return 2
    out_lines = lines_of(out)
    n = max(len(src_lines), len(out_lines))
    changed = [i for i in range(n) if (src_lines[i] if i < len(src_lines) else None)
               != (out_lines[i] if i < len(out_lines) else None)]
    tdiff = [i for i in range(min(len(st_before["texts"]), len(st_after["texts"])))
             if st_before["texts"][i] != st_after["texts"][i]]
    rep.update(edit=info, total_lines=n, lines_changed=len(changed), changed_line_numbers=changed[:5],
               byte_identical_outside_target=(len(changed) == 1),
               texts_before=len(st_before["texts"]), texts_after=len(st_after["texts"]),
               texts_changed=len(tdiff),
               nodes_equal=st_before["nodes"] == st_after["nodes"],
               quotes_equal=st_before["quotes"] == st_after["quotes"],
               layers_equal=st_before["layers"] == st_after["layers"])
    rep["provenance_changed"] = not rep["quotes_equal"]
    rep["requires_reverify"] = bool(rep["provenance_changed"])
    want_tdiff = 1 if x.set_text else 0
    rep["structure_preserved"] = bool(rep["nodes_equal"] and rep["quotes_equal"]
                                      and rep["layers_equal"] and len(tdiff) == want_tdiff)
    rep["source_preserving_ok"] = bool(rep["structure_preserved"] and rep["well_formed"])
    rep["out"] = os.path.basename(out)
    rep["ok"] = rep["source_preserving_ok"]
    if rep["engine"] == "xml":
        rep["serialization_note"] = ("ElementTree 重新序列化了整份文件：结构不变，但行级字节会变"
                                     "（见 lines_changed）")
    print(json.dumps(rep, ensure_ascii=False))
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())


