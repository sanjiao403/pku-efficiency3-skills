#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# verify.py -- 独立复核：只读写出的 SVG 与 result.json，不信作者的数据结构。
#   python3 scripts/verify.py --svg figures/figure.svg --result result.json [--materials /input]
# 退出码 0 通过 / 2 有硬失败。检查：结构、图层、真实文本、箭头一一对应、比例尺真实、
# 来源可追、图上数字都能在材料里找到、result.json 键齐全且状态诚实。
import argparse, json, math, os, re, sys
import xml.etree.ElementTree as ET

K = 96.0 / 25.4
NS = "{http://www.w3.org/2000/svg}"
NUM = re.compile(r"(?<![\w.\-])(\d+(?:[.,]\d+)?)(?![\w.\-])")


def main(a=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--result", default="")
    ap.add_argument("--materials", default="")
    x = ap.parse_args(a)
    it, fails = [], []

    def ck(name, ok, detail, hard=True):
        it.append({"check": name, "ok": bool(ok), "hard": bool(hard), "detail": str(detail)[:260]})
        if hard and not ok:
            fails.append(name)

    # ---- SVG ----------------------------------------------------------
    try:
        root = ET.parse(x.svg).getroot()
        ck("svg.well_formed", True, "%d bytes" % os.path.getsize(x.svg))
    except Exception as e:
        print("[verify] FAIL svg.well_formed %s" % e)
        return 2
    tags = {}
    for el in root.iter():
        t = el.tag.split("}")[-1]
        tags[t] = tags.get(t, 0) + 1
    ck("svg.no_raster_or_foreign", tags.get("image", 0) == 0 and tags.get("foreignObject", 0) == 0,
       "image=%d foreignObject=%d" % (tags.get("image", 0), tags.get("foreignObject", 0)))
    texts = [el for el in root.iter() if el.tag == NS + "text"]
    ck("svg.text_is_real_text", len(texts) >= 4, "%d <text>" % len(texts))
    layers = [el.get("id") for el in root.iter() if el.tag == NS + "g" and (el.get("id") or "").startswith("layer-")]
    ck("svg.layers_present", len(layers) >= 2, "%s" % layers)
    w = float(re.sub(r"[^0-9.]", "", root.get("width") or "0") or 0)
    vb = (root.get("viewBox") or "").split()
    ok = len(vb) == 4 and abs(float(vb[2]) - w * K) < 0.05
    ck("svg.mm_scale_consistent", ok, "width=%smm viewBox=%s (1mm=%.4fpx)" % (root.get("width"), vb, K))

    # 箭头：每条 connector 恰好一个箭头，且端点重合
    conns = [el for el in root.iter() if el.get("data-role") == "connector"]
    heads = [el for el in root.iter() if el.get("data-role") == "arrowhead"]
    cf = {}
    for c in conns:
        cf.setdefault(c.get("data-fid") or "", []).append(c)
    hf = {}
    for h in heads:
        hf.setdefault(h.get("data-fid") or "", []).append(h)
    bad = [f for f in cf if f and len(hf.get(f, [])) != 1]
    ck("arrow.one_head_per_connector", not bad, "connectors=%d heads=%d offenders=%s" % (len(conns), len(heads), bad[:5]))
    skew = []
    for f, cs in cf.items():
        if not f or f not in hf:
            continue
        pts = [tuple(float(v) for v in p.split(",")) for p in (cs[0].get("points") or "").split()]
        tip = max((tuple(float(v) for v in p.split(",")) for p in (hf[f][0].get("points") or "").split()),
                  key=lambda p: math.dist(p, pts[-2] if len(pts) > 1 else pts[0]))
        if len(pts) > 1 and math.dist(tip, pts[-1]) > 1.5:
            skew.append({"fid": f, "gap_px": round(math.dist(tip, pts[-1]), 2)})
    ck("arrow.head_sits_on_endpoint", not skew, "%s" % skew[:4])

    # 比例尺
    bars = [el for el in root.iter() if el.get("data-role") == "scale-bar" and el.tag == NS + "polyline"]
    claims = [el.text or "" for el in root.iter() if el.get("data-role") == "scale-bar-text"]
    mm = next((float(m.group(1)) for t in claims for m in [re.match(r"\s*([\d.]+)\s*mm", t)] if m), None)
    if bars and mm:
        pts = [tuple(float(v) for v in p.split(",")) for p in (bars[0].get("points") or "").split()]
        got = max(math.dist(p, q) for p in pts for q in pts) / K
        ck("scale.bar_length_true", abs(got - mm) <= max(.3, mm * .01), "drawn %.2f mm vs label %s" % (got, mm))
    else:
        ck("scale.bar_present", False, "no scale bar", hard=False)

    # 来源可追
    shapes = [el for el in root.iter() if el.get("data-role") == "node-shape"]
    ids = {el.get("data-node") for el in shapes if el.get("data-node")}
    quo = {el.get("data-node") for el in shapes if el.get("data-node") and (el.get("data-quote") or "").strip()}
    ck("provenance.blocks_have_quote", bool(ids) and len(quo) >= max(1, int(.8 * len(ids))),
       "%d/%d blocks carry data-quote" % (len(quo), len(ids)), hard=False)
    srcs = {el.get("data-src") for el in shapes if el.get("data-src")}
    ck("provenance.locators_present", bool(srcs), "%d distinct locators" % len(srcs), hard=False)

    # ---- result.json --------------------------------------------------
    R = {}
    if x.result and os.path.exists(x.result):
        R = json.load(open(x.result, encoding="utf-8"))
        need = ("case_id", "status", "elements", "relations", "provenance", "uncertainty", "gaps",
                "deliverable", "data_mapping", "contract_echo")
        miss = [k for k in need if k not in R]
        ck("result.required_keys", not miss, "missing=%s" % miss)
        ck("result.no_nulls", not [k for k, v in R.items() if v is None],
           "nulls=%s" % [k for k, v in R.items() if v is None])
        ck("result.status_honest", (R.get("status") == "partial") or (not fails),
           "status=%s prior_hard_failures=%s" % (R.get("status"), fails[:3]))
        outs = R.get("outputs") or R.get("deliverable", {}).get("exports") or []
        ck("result.outputs_listed", bool(outs), "outputs=%d" % len(outs), hard=False)
        if x.materials:
            texts = []
            for root_d, _s, fs in os.walk(x.materials):
                for f in fs:
                    if os.path.splitext(f)[1].lower() in (".md", ".txt", ".csv", ".tsv", ".json", ".tex"):
                        try:
                            texts.append(open(os.path.join(root_d, f), "rb").read().decode("utf-8", "replace"))
                        except Exception:
                            pass
            blob = " ".join(texts)
            allowed = {float(v) for v in re.findall(r"\d+(?:\.\d+)?", blob)}
            allowed |= {float(e.get("seq") or 0) for e in (R.get("elements") or [])}
            lab = " ".join((el.text or "") for el in texts_sel(root))
            inv = sorted({m.group(1) for m in NUM.finditer(lab)
                          if float(m.group(1).replace(",", "")) not in allowed})
            ck("provenance.no_invented_numbers", not inv, "unexplained=%s" % inv[:6])
    else:
        ck("result.present", False, "no result.json given", hard=False)

    for i in it:
        print("[%s] %-34s %s" % ("ok  " if i["ok"] else ("FAIL" if i["hard"] else "warn"),
                                 i["check"], i["detail"]))
    print("[verify] ok=%s hard_failures=%d" % (not fails, len(fails)))
    return 0 if not fails else 2


def texts_sel(root):
    NS_ = NS
    out = []
    for el in root.iter():
        if el.tag == NS_ + "text" and el.get("data-role") in ("node-label", "label", "phase-title"):
            out.append(el)
    return out


if __name__ == "__main__":
    sys.exit(main())
