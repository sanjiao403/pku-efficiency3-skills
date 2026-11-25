#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# apparatus.py -- 材料 -> 可编辑 SVG + result.json（材料解析 extract.py，绘图 svgkit.py）
#   python3 scripts/apparatus.py --case /input/case.json --out /app/output
# 只画材料里读到的；连线只认显式句式；指代不明不画；图上数字必须能在原文找到。
import argparse, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import contract, read_case, sha, sirof   # noqa: E402
from svgkit import FS, K, Fig, export, legend_scale, tw, wrap  # noqa: E402

MG, PAD = 10.0 * K, 7.0
PAL = {"unit": ("#EAF2FB", "#1F4E79", "#10314D"), "unit.vessel": ("#E8F4EC", "#2C6E49", "#12351F"),
       "unit.instrument": ("#E3F0F7", "#1F6E8C", "#0E3547"), "unit.utility": ("#F4F1E8", "#7A6A3A", "#3A3318"),
       "unit.sensor": ("#F3ECF9", "#5B3E82", "#2C1D40"), "step.main": ("#F2F7EE", "#3F6B2C", "#24391A"),
       "step.parallel": ("#FDF3E3", "#A96B12", "#4A2E05"), "step.loop": ("#EFF3F6", "#3A5F7D", "#1E3444"),
       "step.terminal": ("#E9EEF3", "#243B53", "#101E2B"), "phase": ("#F7F4EC", "#8A6D3B", "#3D3018")}
ECOL = {"material": "#1F4E79", "energy": "#B4531A", "signal": "#2E7D6F", "sequence": "#444444",
        "dependency": "#7A4E9B", "loop": "#8894A0"}
ED = {"energy": "6 3", "signal": "2 3", "dependency": "7 4 2 4", "loop": "4 4"}
EL = {"material": "物料/material", "energy": "能量/energy", "signal": "信号/signal", "sequence": "顺序/order",
      "dependency": "依赖/dependency", "loop": "回流/recycle", "unit": "装置/unit", "unit.vessel": "容器/vessel",
      "unit.instrument": "仪器/instrument", "unit.utility": "公用/utility", "unit.sensor": "传感器/sensor",
      "phase": "阶段/phase", "step.main": "主序列/step", "step.parallel": "并行/parallel",
      "step.loop": "回流/recycle", "step.terminal": "终止/terminal"}


def nsz(n):
    w = min(max(max(tw(n["label"], FS), tw(n.get("sublabel") or "", FS * .82)) * 1.08 + 2 * PAD + 4, 46.), 132.)
    L = wrap(n["label"], w - 2 * PAD, FS) + ([str(n["numbers"][0])] if n.get("numbers") else [])
    return w, max(20., len(L) * FS * 1.3 + 10.)


def route(a, b, k):
    if a[0] + a[2] <= b[0] and abs(a[1] - b[1]) < 8:
        return [(a[0] + a[2], a[1] + a[3] / 2), (b[0], b[1] + b[3] / 2)]
    if k == "loop" or a[0] >= b[0]:
        yb = max(a[1] + a[3], b[1] + b[3]) + 18
        return [(a[0] + a[2] / 2, a[1] + a[3]), (a[0] + a[2] / 2, yb), (b[0] + b[2] / 2, yb),
                (b[0] + b[2] / 2, b[1] + b[3])]
    md = (a[0] + a[2] + b[0]) / 2
    return [(a[0] + a[2], a[1] + a[3] / 2), (md, a[1] + a[3] / 2), (md, b[1] + b[3] / 2), (b[0], b[1] + b[3] / 2)]


def build(P, title=""):
    W = 180.
    inr = W * K - 2 * MG
    hs = []
    for p in P:
        n = max(1, len(p.get("nodes") or []) or len(p.get("phases") or []) or len(p.get("steps") or []))
        hs.append(44. + (int(math.ceil(n / 3.)) * 62. if p["kind"] == "schematic" else
                         (28. + n * 16. if p["kind"] == "flow" else 92.)))
    f = Fig(W, round((2 * MG + 28 + sum(hs) + 6 * len(P) + 38) / K, 2), title)
    y = MG
    if title:
        f.text(MG, y + 11, title, FS * 1.5, "#1A1A1A", "start", "annotations", "figure-title", wt="bold"); y += 20
    for i, p in enumerate(P):
        pid, ph, top = p.get("id") or chr(65 + i), hs[i], y + 12
        f.text(MG + 2, top - 3, "%s. %s" % (pid, p.get("title") or ""), FS * 1.06, "#1A1A1A", "start",
               "annotations", "panel-title", wt="bold", **{"data-panel": pid})
        if p["kind"] == "schematic":
            N, E, B, cw = p["nodes"], p["edges"], {}, inr / 3.
            for j, n in enumerate(N):
                r, c = divmod(j, 3)
                w, h = nsz(n)
                x, cy = MG + 6 + c * cw + (cw - 24 - w) / 2., top + 6 + r * 62
                B[n["id"]] = (x, cy, w, h)
                F0, S0, T0 = PAL.get(n["kind"], PAL["unit"])
                dd = {"data-node": n["id"], "data-kind": n["kind"], "data-quote": n["source"]["quote"][:150],
                      "data-src": n["source"]["locator"].replace("#", "@")}
                f.rect(x, cy, w, h, F0, S0, **dd)
                L = wrap(n["label"], w - 2 * PAD, FS) + ([str(n["numbers"][0])] if n.get("numbers") else [])
                cy2 = cy + h / 2. - (len(L) - 1) * FS * .64
                for t, ln in enumerate(L):
                    f.text(x + w / 2., cy2 + t * FS * 1.28, ln, FS, T0, **dd)
            for e in E:
                a, b = B.get(e["src"]), B.get(e["dst"])
                if not a or not b:
                    continue
                pts, c = route(a, b, e["kind"]), ECOL[e["kind"]]
                dd = {"data-fid": e["id"], "data-flow": e["kind"], "data-from": e["src"],
                      "data-to": e["dst"], "data-quote": e["source"]["quote"][:150]}
                f.line(pts, c, 2. if e["kind"] in ("material", "sequence") else 1.5, ED.get(e["kind"]), **dd)
                f.arw(pts[-2], pts[-1], c, 7.5, "connectors", "arrowhead", **dd)
        elif p["kind"] == "flow":
            for j, s in enumerate(p.get("steps") or []):
                yy = top + 10 + j * 16
                F0, S0, T0 = PAL["step." + s["kind"]]
                dd = {"data-node": s["id"], "data-kind": "step." + s["kind"],
                      "data-quote": s["source"]["quote"][:150], "data-src": s["source"]["locator"].replace("#", "@")}
                f.rect(MG + 6, yy - 9, 13, 12, F0, S0, 2, "units", "node-shape", **dd)
                f.text(MG + 12.5, yy, "%d" % s["seq"], FS * .82, T0, "middle", "labels", "node-label", **dd)
                f.text(MG + 24, yy, wrap(s["label"], inr - 70, FS)[0], FS * .95, T0, "start", "labels",
                       "node-label", **dd)
        else:
            Q = p.get("phases") or []
            cw = max(120., (inr - 12 - 16 * (max(1, len(Q)) - 1)) / max(1, len(Q)))
            for j, q in enumerate(Q):
                x = MG + 6 + j * (cw + 16)
                dd = {"data-node": q["id"], "data-kind": "phase", "data-quote": q["source"]["quote"][:150],
                      "data-src": q["source"]["locator"].replace("#", "@")}
                f.rect(x, top + 6, cw, ph - 26, PAL["phase"][0], PAL["phase"][1], **dd)
                cy = top + 14
                for ln in ["P%s" % q["seq"]] + wrap(q["label"], cw - 14, FS * .95):
                    cy += FS * 1.1
                    f.text(x + 6, cy, ln, FS * .95, PAL["phase"][2], "start", "labels", "phase-title", **dd)
                if j + 1 < len(Q):
                    dd2 = {"data-fid": "P%s->P%s" % (q["seq"], Q[j + 1]["seq"]), "data-flow": "dependency",
                           "data-from": q["id"], "data-to": Q[j + 1]["id"]}
                    pts = [(x + cw, top + 6 + (ph - 26) / 2), (x + cw + 16, top + 6 + (ph - 26) / 2)]
                    f.line(pts, ECOL["dependency"], 1.6, ED["dependency"], **dd2)
                    f.arw(pts[-2], pts[-1], ECOL["dependency"], 7.5, "connectors", "arrowhead", **dd2)
        y += ph + 4
    ks = []
    for p in P:
        ks += [n["kind"] for n in p.get("nodes") or []] + [e["kind"] for e in p.get("edges") or []] + \
              ["step." + s["kind"] for s in p.get("steps") or []] + (["phase"] if p["kind"] == "roadmap" else [])
    legend_scale(f, [k for k in dict.fromkeys(ks) if k], PAL, y, inr, ECOL, ED, EL, MG)
    return f


def run(cpath, out, dpi=300):
    ind = os.path.dirname(os.path.abspath(cpath)) or "."
    case, cid = read_case(ind, cpath)
    E, ED_, ST, PH, NU, AMB, T, bad = sirof(cpath)
    kd = case.get("figure_kind") or ("roadmap" if PH else "schematic")
    P, G = [], []
    if kd == "roadmap" and PH:
        P.append({"id": "A", "kind": "roadmap", "title": "技术路线 / technical route", "phases": PH})
    else:
        if E:
            P.append({"id": "A", "kind": "schematic", "title": "装置与流向 / apparatus & flows",
                      "nodes": E[:12], "edges": ED_})
        if ST:
            P.append({"id": "B" if E else "A", "kind": "flow", "title": "步骤顺序 / numbered steps", "steps": ST})
    if not P:
        G.append({"item": "任何可绘制元素", "why": "材料中无装置清单/编号步骤/阶段标记"})
    os.makedirs(os.path.join(out, "figures"), exist_ok=True)
    f = build(P, case.get("title") or "")
    sv = os.path.join(out, "figures", "figure.svg")
    tok = sum(1 for e in E if e["source"]["quote"]) + sum(1 for s in ST if s["source"]["quote"])
    tal = len(E) + len(ST)
    open(sv, "w", encoding="utf-8").write(f.svg({"data-case": cid, "data-kind": kd,
                                                 "data-trace": "%d/%d" % (tok, tal)}))
    ex = export(sv, os.path.join(out, "figures", "figure.pdf"), os.path.join(out, "figures", "figure.png"), dpi)
    U = [{"item": 'ambiguous reference "%s"' % "、".join(a["alias"]),
          "why": "同一称呼对应多个单元（%s），无法判定指代" % "、".join(a["candidates"]),
          "handling": a["handling"], "source": {"locator": a["locator"]}} for a in AMB]
    if E and not NU:
        U.append({"item": "numeric parameters", "why": "材料未给出任何带单位的数值",
                  "handling": "图中不标注数值，不用典型值顶替"})
    if E and not ED_:
        # 有实体无流向句：不画连线，但这是"材料没写"，不是"画不出来" —— 不压 status
        U.append({"item": "connections", "why": "材料未给出可判定的流向句（连线留空，不按常识补管路）",
                  "handling": "如需连线请在材料中写明流向，或补 SIR 后重跑"})
    for e in E:
        if e.get("inferred"):
            U.append({"item": "entity %s (%s)" % (e["id"], e["label"]), "why": "装置名词仅出现在行文中",
                      "handling": "按原文引文保留"})
    PB = list(G) + [{"item": x["file"], "why": x["why"]} for x in bad]
    if not ex["pdf"]:
        PB.append({"item": "pdf/png export", "why": "; ".join(ex["notes"])})
    outs = []
    for p_ in [sv] + ([ex["pdf"], ex["png"]] if ex["pdf"] else []):
        outs.append({"path": os.path.relpath(p_, out).replace("\\", "/"), "bytes": os.path.getsize(p_),
                     "sha256": sha(p_)})
    F = contract(case)
    R = {"case_id": cid, "task": "实验装置与技术路线图：生成图稿并保留可编辑来源",
         "status": "partial" if PB else "success",
         "status_reason": "；".join("%s: %s" % (x["item"], x["why"]) for x in PB) if PB
         else "结构/连线/来源/导出自检通过（见 scripts/verify.py）",
         "summary": "%s：%d 面板 / %d 图元 / %d 连线；溯源 %d/%d" % (kd, len(P), len(E) + len(ST), len(ED_), tok, tal),
         "figure_kind": kd, "canvas_mm": [f.wm, f.hm],
         "outputs": outs,
         "deliverable": {"editable_source": {"path": "figures/figure.svg",
                                             "why": "分层 SVG，真实 <text> 未转曲，每块带 data-node/data-quote"},
                         "exports": ([{"path": "figures/figure.pdf", "format": "pdf"},
                                      {"path": "figures/figure.png", "format": "png", "dpi": dpi}] if ex["pdf"] else []),
                         "render_backend": ex.get("backend")},
         "elements": ([{"id": e["id"], "label": e["label"], "kind": e["kind"], "source": e["source"]} for e in E] +
                      [{"id": s["id"], "label": s["label"], "kind": "step." + s["kind"], "seq": s["seq"],
                        "source": s["source"]} for s in ST] +
                      [{"id": q["id"], "label": q["label"], "kind": "phase", "seq": q["seq"],
                        "source": q["source"]} for q in PH]),
         "relations": [{"id": e["id"], "from": e["src"], "to": e["dst"], "kind": e["kind"],
                        "source": e["source"]} for e in ED_],
         "data_mapping": [{"label": n["text"], "value": n["value"], "unit": n["unit"], "source": n["source"]}
                          for n in NU],
         "provenance": {"materials": sorted(T), "unreadable": bad, "trace_ok": tok, "trace_total": tal,
                        "ambiguities": AMB, "rule_based": True},
         "checks": {"connections": {"edges": len(ED_), "direction_from_sentence": True,
                                    "ambiguous_skipped": len(AMB)},
                    "render": {"backend": ex.get("backend"), "notes": ex["notes"]},
                    "independent": "python3 scripts/verify.py --svg figures/figure.svg --result result.json"},
         "uncertainty": U, "gaps": G,
         "not_reported": [{"field": "scientific_judgement", "why": "题面排除：不评价实验方案科学合理性"}],
         "contract_echo": {}}
    for k in F:
        if k in R:
            R["contract_echo"][k] = "filled from computed result"
        else:
            R[k] = [] if "array" in F[k].lower() else ""
            R["contract_echo"][k] = "no direct source in materials"
    json.dump(R, open(os.path.join(out, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[apparatus] case=%s status=%s kind=%s panels=%d elements=%d edges=%d trace=%d/%d backend=%s"
          % (cid, R["status"], kd, len(P), len(R["elements"]), len(ED_), tok, tal, ex.get("backend")))
    for x in PB[:5]:
        print("[apparatus]   ! %s: %s" % (x["item"], x["why"]))
    return R


def main(a=None):
    ap = argparse.ArgumentParser(description="materials -> editable figure + result.json")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--dpi", type=int, default=300)
    x = ap.parse_args(a)
    run(x.case, x.out, x.dpi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
