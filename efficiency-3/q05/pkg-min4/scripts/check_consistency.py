#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_consistency.py -- 只判**跨产物一致性**：材料 ↔ IR ↔ SVG ↔ result.json。

不含 IR 自身合规（那是 validate_ir.py 的事）。双向：`source.quote` 逐字回溯（防无中生有）；
`extraction_index` 每条提及有归宿、每个画出图元有记账（防漏画/多画）；另查 id 集合、
输出文件 bytes/sha256、箭头几何、图上数字来源、状态诚实。

    python3 scripts/check_consistency.py --ir <ir.json> --materials <case_dir> \\
            --svg <figure.svg> --result <result.json> [--report consistency.json]
退出码 0 = 通过 / 1 = 有硬失败。
"""
from __future__ import annotations

import argparse, hashlib, json, math, os, re, sys
import xml.etree.ElementTree as ET

NS = "{http://www.w3.org/2000/svg}"
TEXT_EXT = (".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".yaml", ".yml", ".log")
NUM = re.compile(r"(?<![\w.\-])(\d+(?:[.,]\d+)?)(?![\w.\-])")


def normalize(t):
    t = str(t or "").replace("\u00ad", "").replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", t).strip()


def material_blob(materials_dir):
    parts = []
    for root, _ds, fs in os.walk(materials_dir):
        for f in sorted(fs):
            if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                continue
            try:
                parts.append(open(os.path.join(root, f), "rb").read().decode("utf-8", "replace"))
            except Exception:                                     # noqa: BLE001
                pass
    return normalize(" ".join(parts))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def run(ir_path, materials_dir, svg_path, result_path, report=None):
    """返回 {schema, ok, hard_failures[], items[], stats{}}。"""
    items, hard = [], []

    def ck(name, ok, detail, severity="hard"):
        items.append({"check": name, "ok": bool(ok), "severity": severity, "detail": str(detail)[:240]})
        if severity == "hard" and not ok:
            hard.append(name)

    ir = json.load(open(ir_path, encoding="utf-8"))
    res = json.load(open(result_path, encoding="utf-8"))
    blob = material_blob(materials_dir)
    els, rels, idx = ir.get("elements") or [], ir.get("relations") or [], ir.get("extraction_index") or []

    # 1) 反向：逐字回溯（防无中生有 / 防改写）
    bad = []
    checked = 0
    for e in els + rels:
        q = normalize((e.get("source") or {}).get("quote"))
        if q:
            checked += 1
            if q not in blob:
                bad.append({"id": e.get("id"), "quote": q[:90]})
    for it in idx:
        q = normalize(it.get("quote"))
        if q and q not in blob:
            bad.append({"id": "index:" + str(it.get("mention"))[:24], "quote": q[:90]})
    ck("source.quotes_verbatim", not bad, {"bad": bad[:3]} if bad else {"checked": checked})

    # 2) 正向：覆盖索引
    drawn_ids = {e.get("id") for e in els}
    mapped = {it.get("mapped_id") for it in idx if it.get("mapped_id")}
    unmapped = [it.get("mention") for it in idx
                if it.get("status") != "omitted" and it.get("mapped_id") not in drawn_ids]
    orphan = sorted(drawn_ids - mapped)
    ck("coverage.index_maps_every_mention", not unmapped, {"unmapped": unmapped[:5]} if unmapped
       else {"items": len(idx), "mapped": len(mapped),
             "omitted_with_reason": sum(1 for it in idx if it.get("status") == "omitted")})
    ck("coverage.every_element_in_index", not orphan, {"not_in_index": orphan[:4]} if orphan else {"elements": len(drawn_ids)})

    # 3) SVG <-> IR id 集合
    root = ET.parse(svg_path).getroot()
    svg_nodes = {el.get("data-node") for el in root.iter() if el.get("data-node")}
    svg_fids = {el.get("data-fid") for el in root.iter() if el.get("data-fid")}
    layers = [el.get("id") for el in root.iter() if el.tag == NS + "g" and (el.get("id") or "").startswith("layer-")]
    ck("svg.covers_ir", drawn_ids <= svg_nodes, {"missing_in_svg": sorted(drawn_ids - svg_nodes)[:5]})
    ck("ir.covers_svg", svg_nodes <= drawn_ids, {"foreign_in_svg": sorted(svg_nodes - drawn_ids)[:5]})
    ck("svg.relations_drawn", {r.get("id") for r in rels} <= svg_fids,
       {"missing_fids": sorted({r.get("id") for r in rels} - svg_fids)[:5]})
    ck("svg.layers_present", len(layers) >= 3, "layers=%s" % layers)

    # 4) result.json 与 IR 同源
    r_els = {e.get("id"): e.get("label") for e in (res.get("elements") or [])}
    i_els = {e.get("id"): e.get("label") for e in els}
    ck("result.elements_match_ir", r_els == i_els,
       {"only_result": sorted(set(r_els) - set(i_els))[:4],
        "only_ir": sorted(set(i_els) - set(r_els))[:4],
        "label_diff": [k for k in set(r_els) & set(i_els) if r_els[k] != i_els[k]][:4]})
    ck("result.relations_match_ir",
       len(res.get("relations") or []) == len(rels),
       "result=%d ir=%d" % (len(res.get("relations") or []), len(rels)))

    # 5) 输出文件与 result.json.outputs[] 的 bytes/sha256 一致
    mism = []
    for o in (res.get("outputs") or []):
        p = os.path.join(os.path.dirname(os.path.abspath(result_path)), o.get("path") or "")
        if not os.path.exists(p) or os.path.getsize(p) != o.get("bytes") or sha256(p) != o.get("sha256"):
            mism.append(o.get("path"))
    ck("outputs.hashes_match", bool(res.get("outputs")) and not mism,
       "outputs=%d mismatched=%s" % (len(res.get("outputs") or []), mism))

    # 6) 溯源引文覆盖 + 箭头几何
    shapes = [el for el in root.iter() if el.get("data-role") == "node-shape"]
    ids = {el.get("data-node") for el in shapes if el.get("data-node")}
    quo = {el.get("data-node") for el in shapes if el.get("data-node") and (el.get("data-quote") or "").strip()}
    ck("provenance.blocks_have_quote", bool(ids) and len(quo) >= max(1, int(0.8 * len(ids))),
       "%d/%d node blocks carry data-quote" % (len(quo), len(ids)))
    conns = [el for el in root.iter() if el.get("data-role") == "connector"]
    heads = [el for el in root.iter() if el.get("data-role") == "arrowhead"]
    tf, hf = {}, {}
    for c in conns:
        tf.setdefault(c.get("data-fid") or "", []).append(c)
    for h in heads:
        hf.setdefault(h.get("data-fid") or "", []).append(h)
    ck("arrow.one_head_per_connector", not [f for f in tf if f and len(hf.get(f, [])) != 1],
       "connectors=%d heads=%d" % (len(conns), len(heads)))
    skew = []
    for fid, cs in tf.items():
        if not fid or fid not in hf:
            continue
        pts = [tuple(float(v) for v in p.split(",")) for p in (cs[0].get("points") or "").split()]
        tip = max((tuple(float(v) for v in p.split(",")) for p in (hf[fid][0].get("points") or "").split()),
                  key=lambda p: math.dist(p, pts[-2] if len(pts) > 1 else pts[0]))
        if len(pts) > 1 and math.dist(tip, pts[-1]) > 1.5:
            skew.append({"fid": fid, "gap_px": round(math.dist(tip, pts[-1]), 2)})
    ck("arrow.head_sits_on_endpoint", not skew, skew[:4] if skew else "ok")

    # 7) 图上数字必须能在材料里找到（或来自图元序号 / 画布尺寸）
    allowed = {float(v) for v in re.findall(r"\d+(?:\.\d+)?", blob)}
    allowed |= {float(e.get("seq") or 0) for e in els}
    allowed |= {float(e.get("value") or 0) for e in (ir.get("numbers") or [])}
    allowed |= {float(v) for v in (ir.get("canvas_mm") or [])}
    label_txt = " ".join((el.text or "") for el in root.iter()
                         if el.tag == NS + "text"
                         and el.get("data-role") in ("node-label", "phase-title", "label"))
    invented = sorted({m.group(1) for m in NUM.finditer(label_txt)
                       if float(m.group(1).replace(",", "")) not in allowed})
    ck("provenance.no_invented_numbers", not invented, "unexplained=%s" % invented[:6])

    # 8) 状态诚实：有任何硬失败时 result.status 必须是 partial
    ck("result.status_honest", (not hard) or res.get("status") == "partial",
       "status=%s hard=%s" % (res.get("status"), hard[:3]))

    rep = {"schema": "apparatus/consistency/1", "ok": not hard, "hard_failures": hard,
           "soft_warnings": [i["check"] for i in items if i["severity"] != "hard" and not i["ok"]],
           "items": items,
           "stats": {"elements": len(els), "relations": len(rels), "index": len(idx),
                     "svg_nodes": len(svg_nodes), "layers": len(layers), "quotes_checked": checked}}
    if report:
        json.dump(rep, open(report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return rep


def main(a=None):
    ap = argparse.ArgumentParser(description="material <-> IR <-> SVG <-> result.json consistency only")
    ap.add_argument("--ir", required=True)
    ap.add_argument("--materials", required=True)
    ap.add_argument("--svg", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--report", default="")
    x = ap.parse_args(a)
    rep = run(x.ir, x.materials, x.svg, x.result, x.report or None)
    for i in rep["items"]:
        if not i["ok"]:
            print("[%s] %-36s %s" % ("FAIL" if i["severity"] == "hard" else "warn", i["check"], i["detail"]))
    print("[check_consistency] ok=%s hard_failures=%d stats=%s"
          % (rep["ok"], len(rep["hard_failures"]), rep["stats"]))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
