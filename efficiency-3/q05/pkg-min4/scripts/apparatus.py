#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apparatus.py -- 实验材料 -> 可核验图稿（单入口，纯启发式，零外部前提）。

    python3 scripts/apparatus.py --case /input/case.json --out /app/output

材料 -> 启发式抽取 -> IR（figure.ir.json，含覆盖索引）-> 分层 SVG -> PDF/PNG ->
validate_ir.py + check_consistency.py 双重只读复核 -> result.json。
底线：只画读到的；指代不明不画只记；图中数字必须原文可查；0 图元一律 partial；
输入发现只认 case 目录之下的相对路径。契约见 references/ir_schema.md。
"""
import argparse, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ir as ir_mod                                    # noqa: E402
import check_consistency as cc_mod                              # noqa: E402

LEX = [("unit.sensor", "thermocouple|sensor|probe|gauge|热电偶|传感器|探头|压力表|温度计"),
       ("unit.instrument", "pump|valve|furnace|oven|centrifuge|oxygenator|mixer|stirrer|filter|flow meter|"
                           "logger|泵|阀|炉|烘箱|离心机|氧合器|搅拌|滤器|流量计|记录仪|研磨"),
       ("unit.utility", "waste|exhaust|vacuum|coolant|gas cylinder|chiller|废液|废气|真空|冷却|气瓶"),
       ("unit.vessel", "reservoir|reactor|flask|vessel|tank|chamber|bottle|column|trap|储液瓶|反应釜|反应器|"
                       "培养腔|烧瓶|罐|槽|腔|瓶|柱|捕集器")]
VB = [("loop", "recycled|returned|recirculated|循环|回流|返回"),
      ("signal", "is recorded by|monitored|measured|recorded|监测|测量|记录"),
      ("energy", "heated|cooled|irradiated|加热|冷却|水浴|控温"),
      ("material", "is fed from|delivers to|connected to|passes to|flows into|leaves|exits|feeds|transfer|"
                   "接入|连接|流入|通入|泵入|输送|加入|排出|流出|插入")]
NUM = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)\s*(°C|℃|mL|ml|μL|L|h|min|s|rpm|mbar|bar|kPa|MPa|nm|μm|um|mm|cm|"
                 r"m|g|mg|kg|mol|mM|M|V|mA|A|W|kW|J|kJ|Hz|kHz|MHz|%|目)(?![\w])")
CJK = re.compile(r"[\u4e00-\u9fff]")
GEN = {"medium", "media", "sample", "data", "system", "device", "unit", "test", "value"}
LST = re.compile(r"^(#{1,6}\s|\[\[|---)|^\||^\s*(?:[-*•]\s+|\d{1,2}[.、)）]\s+|[（(]\d{1,2}[)）]\s+)")
TXT = (".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".yaml", ".yml", ".log")
SKIP = (".png", ".jpg", ".jpeg", ".svg", ".gif")

def kind_of(s):
    low, b, ln = (s or "").lower(), None, 0
    for k, pat in LEX:
        for m in re.finditer(pat, low, re.I):
            if len(m.group(0)) > ln:
                b, ln = k, len(m.group(0))
    return b

def ali(lab):
    o = {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", lab or "") if t.lower() not in GEN}
    for r in re.findall(r"[\u4e00-\u9fff]{2,}", lab or ""):
        for n in range(len(r), max(2, len(r) - 3), -1):
            for i in range(len(r) - n + 1):
                o.add(r[i:i + n])
    return {a for a in o if len(a) >= 3}

def read_any(p):
    e = os.path.splitext(p)[1].lower()
    if e in TXT:
        raw = open(p, "rb").read()
        for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
    if e == ".pdf":
        try:
            import fitz
            try:
                fitz.TOOLS.mupdf_display_errors(False); fitz.TOOLS.mupdf_display_warnings(False)
            except Exception:
                pass
            dn, sd = os.open(os.devnull, os.O_WRONLY), os.dup(2)
            try:
                os.dup2(dn, 2)
                return "\n".join(g.get_text("text") for g in fitz.open(p))
            finally:
                os.dup2(sd, 2); os.close(dn); os.close(sd)
        except Exception as x:
            raise RuntimeError("pdf read failed: %s" % str(x)[:80])
    raise RuntimeError("unsupported %s" % e)

REFS = ("materials", "material", "material_files", "inputs", "input", "files", "attachments")
ORDER = ("case_dir (case.json 所在目录)", "cwd (调用者工作目录)", "/input")

def case_refs(case):
    """case.json 里显式点名的材料路径（字符串或 {"path": ...}）。"""
    out = []
    for k in REFS:
        v = (case or {}).get(k)
        for it in (v if isinstance(v, (list, tuple)) else [v]):
            s = it if isinstance(it, str) else (it.get("path") if isinstance(it, dict) else None)
            if isinstance(s, str) and s.strip() and s.strip() not in out:
                out.append(s.strip())
    return out

def resolve_ref(ref, cdir):
    """case_dir -> cwd -> /input；绝对路径优先。返回 (abs|None, 来源标签)。"""
    s = str(ref or "").strip()
    if not s:
        return None, "empty"
    if os.path.isabs(s):
        return s, "absolute"
    for tag, base in (("case_dir", os.path.abspath(cdir or ".")),
                      ("cwd", os.path.abspath(os.getcwd())),
                      ("input", os.path.abspath("/input"))):
        p = os.path.join(base, s)
        if os.path.exists(p):
            return os.path.abspath(p), tag
    return None, "unresolved"

def resolve_all(case, cdir, indir):
    extra, refs = [], []
    for r in case_refs(case):
        p, src = resolve_ref(r, cdir)
        ok = bool(p) and os.path.isfile(p)
        refs.append({"ref": r, "resolved": p if ok else None, "resolved_from": src})
        if ok:
            inside = os.path.realpath(p).startswith(os.path.realpath(indir) + os.sep)
            extra.append((os.path.relpath(p, indir).replace("\\", "/") if inside else r, p))
    return extra, {"case_dir": os.path.abspath(cdir), "search_order": list(ORDER), "refs": refs,
                   "unresolved": [r["ref"] for r in refs if not r["resolved"]]}

def collect(d, extra=()):
    """材料发现：只 glob case 目录之下（外加 case.json 显式点名、已解析的文件）。

    绝不对**绝对路径的目录段**做任何过滤（outputs/runs/stage/...）：包或案例可以合法地
    放在这类目录下，那种过滤会静默吞掉全部输入却仍像是跑通了。
    """
    T, bad = {}, []
    pairs = []
    for root, _s, fs in os.walk(d):
        for f in sorted(fs):
            pairs.append((os.path.join(root, f),
                          os.path.relpath(os.path.join(root, f), d).replace("\\", "/")))
    seen = {rel for _p, rel in pairs}
    for rel, p in extra:
        if rel not in seen:
            pairs.append((p, rel))
            seen.add(rel)
    for p, rel in pairs:
        if os.path.splitext(p)[1].lower() in SKIP:
            continue
        try:
            T[rel] = read_any(p)
        except Exception as x:
            bad.append({"file": rel, "why": str(x)[:110]})
    return T, bad

def blocks_of(name, text):
    o, buf, st = [], [], None

    def fl(e):
        nonlocal buf, st
        if buf:
            o.append({"loc": "%s#L%d-%d" % (name, st, e), "text": " ".join(buf)}); buf, st = [], None

    for i, ln in enumerate(text.splitlines(), 1):
        s = ln.strip()
        if not s:
            fl(i - 1)
        elif LST.match(s):
            fl(i - 1); o.append({"loc": "%s#L%d" % (name, i), "text": s})
        else:
            st = i if st is None else st; buf.append(s)
    fl(10 ** 9)
    return o

def ents(bl):
    E, idre = [], re.compile(r"\b([A-Z]{1,4}[-–]?\d{1,3}[A-Za-z]?)\b")

    def add(lab, q, loc, inf):
        lab = re.sub(r"\s+", " ", lab or "").strip(" 　|,，;；-–—")
        if len(lab) < 2 or not (re.search(r"[A-Za-z]", lab) or CJK.search(lab)):
            return
        tg = set(re.findall(r"[A-Za-z]{0,3}[-–]?\d{1,3}", lab))
        for e in E:
            ot = set(re.findall(r"[A-Za-z]{0,3}[-–]?\d{1,3}", e["label"]))
            if tg and ot and tg != ot:
                continue                                    # A-1 与 A-2 是两台，不是一台
            lo, old = lab.lower(), e["label"].lower()
            if lo in old or old in lo or (ali(lo) & ali(old)):
                return
        k = kind_of(lab) or kind_of(q)
        if k:
            E.append({"id": "U%d" % (len(E) + 1), "label": lab, "kind": k, "inferred": bool(inf),
                      "source": {"locator": loc, "quote": q[:140]}})

    for b in bl:
        t = b["text"]
        if t.count("|") >= 2:
            c = [x.strip() for x in t.strip().strip("|").split("|")]
            if len(c) >= 2 and c[0] and not re.match(r"^[-:\s]+$", "".join(c)) and kind_of(c[0]) \
                    and (len(c) >= 3 or any(NUM.search(x) for x in c[1:])):
                add(c[0], t, b["loc"], False)
            continue
        for m in idre.finditer(t):
            tg = m.group(1)
            if re.fullmatch(r"[A-Z]{2}\d|[MYQTW]\d{1,3}", tg):
                continue
            ctx = t[max(0, m.start() - 50):m.end() + 50]
            if kind_of(ctx) and not any(tg.lower() in e["label"].lower() for e in E):
                add(tg, ctx, b["loc"], False)
    return E

def flows(bl, E):
    am = [(e, sorted(ali(e["label"]), key=len, reverse=True)) for e in E]
    o, amb, seen = [], [], set()
    for b in bl:
        for s in re.split(r"(?<=[.!?;。！？；])\s*", b["text"]):
            lo, k, v = s.lower(), None, None
            for kk, pat in VB:
                m = None
                for mm in re.finditer(pat, lo, re.I):
                    if m is None or len(mm.group(0)) > len(m.group(0)):
                        m = mm
                if m:
                    k, v = kk, m.group(0); break
            if not k:
                continue
            f = []
            for e, tk in am:
                bs = None
                for t in tk:
                    p = lo.find(t)
                    if p >= 0 and (bs is None or p < bs[0] or (p == bs[0] and len(t) > len(bs[1]))):
                        bs = (p, t)
                if bs:
                    f.append((bs[0], e, bs[1]))
            f.sort(key=lambda x: x[0])
            if len(f) < 2:
                continue
            by = {}
            for _p, e, t in f:
                by.setdefault(t, []).append(e)
            if any(len(x) > 1 for x in by.values()):        # 指代不明 -> 不画，只记录
                amb.append({"locator": b["loc"], "sentence": s.strip()[:110],
                            "alias": sorted(t for t, x in by.items() if len(x) > 1),
                            "candidates": sorted({e["label"] for x in by.values() for e in x}),
                            "handling": "指代不明，未画连线（不猜）"})
                continue
            a, c = f[0][1], f[1][1]
            hd = lo[:lo.find(v)]
            if re.search(r"(is|are|was|were)\s+\w*\s*from\s*$", hd) or re.search(r"(由|自)\s*$", hd):
                a, c = c, a
            if re.search(r"(recycl|循环|回流|返回)", lo):
                k = "loop"
            if (a["id"], c["id"], k) not in seen:
                seen.add((a["id"], c["id"], k))
                o.append({"id": "E%d" % (len(o) + 1), "src": a["id"], "dst": c["id"], "kind": k,
                          "source": {"locator": b["loc"], "quote": s.strip()[:140]}})
    return o, amb

def stps(bl):
    P = (re.compile(r"^\s*(?:step|Step|STEP)\s*(\d+)\s*[:.\-)\]]?\s*(.+)$"),
         re.compile(r"^\s*(?:步骤|第)\s*([0-9一二三四五六七八九十]+)\s*步?\s*[:：.\-、)）]?\s*(.+)$"),
         re.compile(r"^\s*[（(]?\s*(\d{1,2})\s*[.、)）]\s+(\S.*)$"))
    CN = dict(zip("一二三四五六七八九十", range(1, 11)))
    o = []
    for b in bl:
        m = next((p.match(b["text"]) for p in P if p.match(b["text"])), None)
        if not m:
            continue
        n, body = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        sq = int(n) if n.isdigit() else CN.get(n, 0)
        if sq <= 0 or not 6 <= len(body) <= 300 or any(x["label"][:40].lower() == body[:40].lower() for x in o):
            continue
        kd = "parallel" if re.search(r"(同时|并行|parallel|simultaneous)", body, re.I) else "main"
        if re.search(r"(结束|终止|判定|stop|end|terminate)", body, re.I):
            kd = "terminal"
        if re.search(r"(?:回到|返回|repeat|return to|go to)\s*(?:step|步骤)?\s*\d+", body, re.I):
            kd = "loop"
        o.append({"id": "S%d" % (len(o) + 1), "seq": len(o) + 1, "label": body, "kind": kd,
                  "source": {"locator": b["loc"], "quote": b["text"][:140]}})
    return o

def phs(bl):
    mk = re.compile(r"(?:phase|stage|wp|task|阶段)\s*([0-9]{1,2}|[一二三四五六七八九十])", re.I)
    CN = dict(zip("一二三四五六七八九十", range(1, 11)))
    o, sn = [], set()
    for b in bl:
        for m in mk.finditer(b["text"]):
            sq = int(m.group(1)) if m.group(1).isdigit() else CN.get(m.group(1), 0)
            if sq and sq not in sn:
                sn.add(sq)
                o.append({"id": "P%d" % sq, "seq": sq,
                          "label": b["text"][m.end():m.end() + 90].strip(" 　:：-"),
                          "source": {"locator": b["loc"], "quote": b["text"][:140]}})
    return sorted(o, key=lambda x: x["seq"])

def nums_of(bl):
    o, sn = [], set()
    for b in bl:
        for m in NUM.finditer(b["text"]):
            if (m.group(1), m.group(2)) not in sn:
                sn.add((m.group(1), m.group(2)))
                o.append({"text": "%s %s" % (m.group(1), m.group(2)), "value": m.group(1), "unit": m.group(2),
                          "source": {"locator": b["loc"], "quote": b["text"][max(0, m.start() - 40):m.end() + 40]}})
    return o

def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(65536), b""):
            h.update(b)
    return h.hexdigest()

def contract(case):
    """case.json 的 output_contract -> {字段: 类型提示}（成功时全键透传，缺值给 ""/[]）。"""
    F = {}
    for n in (list(case.values()) if isinstance(case, dict) else []):
        if not isinstance(n, dict):
            continue
        for k, v in n.items():
            if k.lower() in ("output_contract", "contract", "outputs", "output_schema",
                             "expected_outputs", "deliverables"):
                if isinstance(v, dict):
                    F.update({x: "string" for x in v})
                elif isinstance(v, list):
                    for it in v:
                        if isinstance(it, str):
                            F.setdefault(it, "string")
                        elif isinstance(it, dict) and (it.get("name") or it.get("field")):
                            F.setdefault(it.get("name") or it.get("field"), "string")
    return F

def read_case(indir, cpath):
    case = {}
    if os.path.exists(cpath):
        try:
            case = json.load(open(cpath, encoding="utf-8-sig"))
        except Exception as x:
            case = {"_case_json_error": str(x)[:100]}
    cid = case.get("case_id") or case.get("id") or os.path.basename(os.path.abspath(indir))
    return case, cid

def sirof(cpath, case=None, cdir=None):
    """materials -> (entities, edges, steps, phases, numbers, ambiguities, files, bad, resolved)"""
    ind = os.path.dirname(os.path.abspath(cpath)) or "."
    extra, RSV = resolve_all(case or {}, cdir or ind, ind)
    T, bad = collect(ind, extra)
    for r in RSV["refs"]:
        if not r["resolved"]:
            bad.append({"file": r["ref"], "why": "unresolved material ref (case_dir/cwd/input)"})
    bl = []
    for n, t in T.items():
        bl += blocks_of(n, t)
    E, NU, ST, PH = ents(bl), nums_of(bl), stps(bl), phs(bl)
    ED, AMB = flows(bl, E)
    for e in E:
        own = [x["text"] for x in NU if x["source"]["quote"].find(e["label"][:10]) >= 0]
        if own:
            e["numbers"] = own[:2]
    return E, ED, ST, PH, NU, AMB, T, bad, RSV

K = 96.0 / 25.4
FS = 9.0
WIDE = ((0x1100, 0x115F), (0x2E80, 0xA4CF), (0xAC00, 0xD7A3), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6))

def tw(s, z):
    return sum(z * (1.0 if any(a <= ord(c) <= b for a, b in WIDE) else 0.545) for c in (s or ""))

def wrap(s, mw, z, ml=3):
    s = (s or "").strip()
    if not s:
        return []
    o, cur = [], ""
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/._°%+]*\s*|.", s):
        if tw(cur + t, z) <= max(mw, z) or not cur:
            cur += t
        else:
            o.append(cur.rstrip()); cur = t.lstrip()
    if cur.strip():
        o.append(cur.rstrip())
    if len(o) > ml:
        t = o[ml - 1]
        while t and tw(t + "…", z) > mw:
            t = t[:-1]
        o = o[:ml - 1] + [t.rstrip() + "…"]
    return o

def esc(s):
    return (str("" if s is None else s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

class Fig:
    def __init__(self, wm, hm, t=""):
        self.wm, self.hm, self.t, self.w, self.h, self.e = wm, hm, t, wm * K, hm * K, []

    def rect(self, x, y, w, h, f, s, rx=4, L="units", role="node-shape", **d):
        self.e.append(("rect", dict(layer=L, role=role, x=x, y=y, w=w, h=h, fill=f, stroke=s, rx=rx, **d)))

    def poly(self, p, f, L="units", role="arrowhead", **d):
        self.e.append(("poly", dict(layer=L, role=role, pts=p, fill=f, **d)))

    def line(self, p, c, sw=1.5, dash=None, L="connectors", role="connector", **d):
        self.e.append(("line", dict(layer=L, role=role, pts=p, stroke=c, sw=sw, dash=dash, **d)))

    def text(self, x, y, t, z=FS, c="#1A1A1A", an="middle", L="labels", role="text", wt="normal", **d):
        self.e.append(("text", dict(layer=L, role=role, x=x, y=y, s=str(t or ""), size=round(z * 2) / 2.,
                                    fill=c, anchor=an, wt=wt, **d)))

    def arw(self, p0, p1, c, sz=7.5, L="connectors", role="arrowhead", **d):
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        dd = math.hypot(dx, dy) or 1.
        ux, uy, n = dx / dd, dy / dd, max(5.5, sz)
        bx, by, W = p1[0] - ux * n, p1[1] - uy * n, n * .46
        self.poly([p1, (bx - uy * W, by + ux * W), (bx + uy * W, by - ux * W)], c, L, role, **d)

    def svg(self, meta=None):
        m = " ".join('%s="%s"' % (k, esc(v)) for k, v in (meta or {}).items())
        o = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %.2f %.2f" '
             'data-generator="apparatus.py" %s>' % (self.wm, self.hm, self.w, self.h, m),
             "<title>%s</title>" % esc(self.t),
             '<rect id="page" x="0" y="0" width="%.2f" height="%.2f" fill="#FFFFFF"/>' % (self.w, self.h)]
        for L in ("rulers", "units", "connectors", "labels", "legend", "annotations"):
            es = [x for x in self.e if x[1]["layer"] == L]
            if not es:
                continue
            o.append('<g id="layer-%s">' % L)
            for tg, a in es:
                # role -> data-role（显式 data-role 优先，避免重复属性）
                d = " ".join('%s="%s"' % ("data-role" if k == "role" else k, esc(v))
                             for k, v in a.items()
                             if (k.startswith("data-") or k == "role")
                             and not (k == "role" and "data-role" in a))
                if tg == "rect":
                    o.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f"%s fill="%s" stroke="%s" '
                             'stroke-width="1.3" %s/>' % (a["x"], a["y"], a["w"], a["h"],
                                                          ' rx="%g"' % a["rx"] if a["rx"] else "", a["fill"],
                                                          a["stroke"], d))
                elif tg == "poly":
                    o.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="1" %s/>'
                             % (" ".join("%.2f,%.2f" % p for p in a["pts"]), a["fill"], a["fill"], d))
                elif tg == "line":
                    o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.2f"%s %s/>'
                             % (" ".join("%.2f,%.2f" % p for p in a["pts"]), a["stroke"], a["sw"],
                                ' stroke-dasharray="%s"' % a["dash"] if a["dash"] else "", d))
                else:
                    o.append('<text x="%.2f" y="%.2f" font-size="%.2f" fill="%s" text-anchor="%s"%s '
                             'xml:space="preserve" %s>%s</text>'
                             % (a["x"], a["y"], a["size"], a["fill"], a["anchor"],
                                ' font-weight="%s"' % a["wt"] if a["wt"] != "normal" else "", d, esc(a["s"])))
            o.append("</g>")
        return "\n".join(o) + "\n</svg>\n"

def legend_scale(f, ks, pal, y, inr, colors, dashes, labels, mg=37.795):
    """图例（按用到的语义生成 -> 颜色与图形同源）+ 40 mm 比例尺。"""
    f.text(mg + 2, y + 4, "图例 legend（按用到的语义自动生成，颜色与图形同源）", FS * .86, "#1A1A1A",
           "start", "legend", "legend-title")
    lx, ly = mg + 2, y + 13
    for k in ks:
        if k in colors:
            f.line([(lx, ly + 2), (lx + 18, ly + 2)], colors[k], 2., dashes.get(k), "legend", "legend-line",
                   **{"data-legend": k})
            f.arw((lx, ly + 2), (lx + 18, ly + 2), colors[k], 6, "legend", "legend-arrow", **{"data-legend": k})
        else:
            F0, S0, _ = pal.get(k, pal["unit"])
            f.rect(lx, ly - 2, 17, 8.4, F0, S0, 2, "legend", "legend-swatch", **{"data-legend": k})
        lab = labels.get(k, k)
        f.text(lx + 22, ly + 5, lab, FS * .86, "#1A1A1A", "start", "legend", "legend-text", **{"data-legend": k})
        lx += 24 + tw(lab, FS * .86) + 16
        if lx > mg + inr - 130:
            lx, ly = mg + 2, ly + FS * 1.6
    ly += FS * 2.
    bp = 40 * K
    f.line([(mg, ly), (mg + bp, ly)], "#1A1A1A", 1.6, None, "rulers", "scale-bar")
    for tx in (mg, mg + bp / 2, mg + bp):
        f.line([(tx, ly - 3), (tx, ly + 3)], "#1A1A1A", 1.2, None, "rulers", "scale-bar")
    f.text(mg, ly + 11, "0", FS * .78, "#1A1A1A", **{"data-role": "scale-bar-text"})
    f.text(mg + bp, ly + 11, "40 mm", FS * .78, "#1A1A1A", **{"data-role": "scale-bar-text"})
    f.text(mg, ly + 24, "画布 %g×%g mm · 可编辑 SVG 源（真实文本 + data-* 溯源）" % (f.wm, f.hm), FS * .78,
           "#5A6672", "start", "annotations", "figure-footer")

def export(sv, pdb, png, dpi=300):
    """有后端就出 PDF/PNG，没有就如实记录（不伪造）。"""
    o = {"pdf": None, "png": None, "notes": []}
    try:
        import fitz
        try:
            fitz.TOOLS.mupdf_display_errors(False); fitz.TOOLS.mupdf_display_warnings(False)
        except Exception:
            pass
        dn, sd = os.open(os.devnull, os.O_WRONLY), os.dup(2)
        try:
            os.dup2(dn, 2)
            d = fitz.open(sv)
            open(pdb, "wb").write(d.convert_to_pdf())
            d[0].get_pixmap(matrix=fitz.Matrix(dpi / 72., dpi / 72.), alpha=False).save(png)
        finally:
            os.dup2(sd, 2); os.close(dn); os.close(sd)
        o.update(pdf=pdb, png=png, backend="pymupdf")
    except Exception as x:
        o["notes"].append("pymupdf: %s" % str(x)[:90])
        o["notes"].append("SVG 源文件完整可交；PDF/PNG 缺失已如实记录")
    return o


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

def build_naive(ind, title=""):
    """对照臂 A：真实可执行的极简直通——按材料顺序逐行画框，不分类/不溯源/不连线/不自检。

    只排掉 `case.json`（那是案例元数据，不是材料正文），其余材料一行不删、不合并、不排序。
    """
    T, bad = collect(ind)
    T = {k: v for k, v in T.items() if os.path.basename(k).lower() != "case.json"}
    L = [ln.strip() for n in sorted(T) for ln in (T[n] or "").splitlines() if len(ln.strip()) >= 4]
    per, W = 34, 180.
    cols = max(1, (len(L) + per - 1) // per)
    f = Fig(W, round((14. + 2 * 7. + per * 6.6) / K, 2), title)
    cw = (W * K - 2 * 7.) / cols
    for i, s in enumerate(L):
        c, r = divmod(i, per)
        x, y = 7. + c * cw, 14. + r * 6.6
        f.rect(x, y, cw - 4, 4.8, "#FFFFFF", "#BBBBBB", 0, "units", "block", **{"data-kind": "raw-line"})
        f.text(x + 2, y + 3.6, s[:72], 8., "#1A1A1A", "start")
    return f, L, T, bad

def _write(out, name, obj):
    p = os.path.join(out, name)
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p

def run(cpath, out, dpi=300, arm="skill"):
    ind = os.path.dirname(os.path.abspath(cpath)) or "."
    case, cid = read_case(ind, cpath)
    E, ED_, ST, PH, NU, AMB, T, bad, RSV = sirof(cpath, case, ind)
    kd = case.get("figure_kind") or ("roadmap" if PH else "schematic")
    os.makedirs(os.path.join(out, "figures"), exist_ok=True)
    sv = os.path.join(out, "figures", "figure.svg")

    if arm == "naive":
        f, L, T, bad = build_naive(ind, case.get("title") or "")
        open(sv, "w", encoding="utf-8").write(f.svg({"data-case": cid, "data-kind": "naive"}))
        ex = export(sv, os.path.join(out, "figures", "figure.pdf"),
                    os.path.join(out, "figures", "figure.png"), dpi)
        R = {"case_id": cid, "task": "实验装置与技术路线图：naive 对照臂（真实执行的极简管线）",
             "mode": "naive-baseline", "status": "success" if L else "partial",
             "status_reason": "按材料顺序逐行画框：不分类/不溯源/不连线/无图例/不自检",
             "figure_kind": "naive", "canvas_mm": [f.wm, f.hm],
             "elements": [{"id": "L%d" % (i + 1), "label": s[:72], "kind": "raw-line", "source": {}}
                          for i, s in enumerate(L)],
             "relations": [], "sources": [{"path": m, "kind": "material"} for m in sorted(T)],
             "change_log": [{"field": "materials.discovered", "value": len(T)},
                            {"field": "elements.drawn", "value": len(L)}],
             "uncertainty": [], "gaps": [],
             "data_mapping": [], "deliverable": {"editable_source": {"path": "figures/figure.svg"},
                                                 "exports": [], "render_backend": ex.get("backend")},
             "provenance": {"materials": sorted(T), "unreadable": bad, "trace_ok": 0,
                            "trace_total": len(L), "rule_based": False,
                            "note": "naive 臂不写任何来源标记"},
             "resolved_from": RSV,
             "outputs": [{"path": os.path.relpath(p, out).replace("\\", "/"), "bytes": os.path.getsize(p),
                          "sha256": sha(p)} for p in [sv] + ([ex["pdf"], ex["png"]] if ex["pdf"] else [])],
             "contract_echo": {k: "naive 臂不做契约回填" for k in contract(case)},
             "checks": {"verify": {"ok": None, "note": "对照臂不做独立自检（这正是它的短板）"}}}
        _write(out, "result.json", R)
        print("[apparatus:naive] case=%s lines=%d status=%s" % (cid, n, R["status"]))
        return R

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
    n_items = sum(len(p.get("nodes") or []) + len(p.get("steps") or []) + len(p.get("phases") or [])
                  for p in P)
    # ---- 覆盖索引：材料里找到的每个部件/步骤/阶段一条；画了填 mapped_id，没画必须写 omitted+reason
    dn = {x["id"] for p in P for x in (p.get("nodes") or [])}
    ds = {x["id"] for p in P for x in (p.get("steps") or [])}
    dp = {x["id"] for p in P for x in (p.get("phases") or [])}
    IDX = []
    for e in E:
        ok = e["id"] in dn
        IDX.append({"mention": e["label"], "quote": e["source"]["quote"][:140],
                    "mapped_id": e["id"] if ok else None,
                    "status": None if ok else "omitted",
                    "reason": None if ok else ("图类为 roadmap：装置实体不在该图类绘制范围" if kd == "roadmap"
                                               else "超出装置面板容量（最多 12 个）或未达入图阈值")})
    for s in ST:
        ok = s["id"] in ds
        IDX.append({"mention": s["label"][:60], "quote": s["source"]["quote"][:140],
                    "mapped_id": s["id"] if ok else None, "status": None if ok else "omitted",
                    "reason": None if ok else "未进入绘制面板（图类或阈值）"})
    for q in PH:
        ok = q["id"] in dp
        IDX.append({"mention": (q["label"] or q["id"])[:60], "quote": q["source"]["quote"][:140],
                    "mapped_id": q["id"] if ok else None, "status": None if ok else "omitted",
                    "reason": None if ok else "未进入绘制面板（图类或阈值）"})
    f = build(P, case.get("title") or "")
    tok = (sum(1 for e in E if e["source"]["quote"]) + sum(1 for s in ST if s["source"]["quote"])
           + sum(1 for q in PH if q["source"]["quote"]))
    tal = len(E) + len(ST) + len(PH)
    open(sv, "w", encoding="utf-8").write(f.svg({"data-case": cid, "data-kind": kd,
                                                 "data-trace": "%d/%d" % (tok, tal)}))
    ex = export(sv, os.path.join(out, "figures", "figure.pdf"),
                os.path.join(out, "figures", "figure.png"), dpi)
    U = [{"item": 'ambiguous reference "%s"' % "、".join(a["alias"]),
          "why": "同一称呼对应多个单元（%s），无法判定指代" % "、".join(a["candidates"]),
          "handling": a["handling"], "source": {"locator": a["locator"]}} for a in AMB]
    if E and not NU:
        U.append({"item": "numeric parameters", "why": "材料未给出任何带单位的数值",
                  "handling": "图中不标注数值，不用典型值顶替"})
    if E and not ED_:
        U.append({"item": "connections", "why": "材料未给出可判定的流向句（连线留空，不按常识补管路）",
                  "handling": "如需连线请在材料中写明流向"})
    for e in E:
        if e.get("inferred"):
            U.append({"item": "entity %s (%s)" % (e["id"], e["label"]), "why": "装置名词仅出现在行文中",
                      "handling": "按原文引文保留"})
    PB = list(G) + [{"item": x["file"], "why": x["why"]} for x in bad]
    if not ex["pdf"]:
        PB.append({"item": "pdf/png export", "why": "; ".join(ex["notes"])})
    # 空产物守卫：0 图元一律 partial + 明确原因（防"输入被吞掉仍报 success"）
    if n_items == 0:
        PB.append({"item": "empty figure",
                   "why": "0 drawable elements (materials discovered=%d, text blocks=%d)"
                          % (len(T), sum(len(blocks_of(n, t)) for n, t in T.items()))})
    ELEMS = ([{"id": e["id"], "label": e["label"], "kind": e["kind"], "panel": "A",
               "certainty": "inferred" if e.get("inferred") else "quoted",
               "source": e["source"]} for e in E] +
             [{"id": s["id"], "label": s["label"], "kind": "step." + s["kind"], "seq": s["seq"],
               "panel": "B", "certainty": "quoted", "source": s["source"]} for s in ST] +
             [{"id": q["id"], "label": q["label"], "kind": "phase", "seq": q["seq"], "panel": "A",
               "certainty": "quoted", "source": q["source"]} for q in PH])
    ELEMS = list(ELEMS)
    RELS = [{"id": e["id"], "from": e["src"], "to": e["dst"], "kind": e["kind"],
             "certainty": "quoted", "source": e["source"]} for e in ED_]
    for p in P:                                    # 面板按数据补全（roadmap 只有 phases）
        for x in (p.get("nodes") or []):
            for el in ELEMS:
                if el["id"] == x["id"]:
                    el["panel"] = p["id"]
        for x in (p.get("steps") or []):
            for el in ELEMS:
                if el["id"] == x["id"]:
                    el["panel"] = p["id"]
    IR = {"schema": "apparatus/ir/1",
          "figure_type": "apparatus" if kd == "schematic" else "route",
          "figure_kind": kd, "case_id": cid, "title": case.get("title") or "",
          "canvas_mm": [f.wm, f.hm], "elements": ELEMS, "relations": RELS,
          "extraction_index": IDX,
          "numbers": [{"label": n["text"], "value": n["value"], "unit": n["unit"],
                       "source": n["source"]} for n in NU],
          "materials": sorted(T), "unreadable": bad, "resolved_from": RSV, "gaps": G}
    irp = os.path.join(out, "figure.ir.json")
    _write(out, "figure.ir.json", IR)
    outs = [{"path": os.path.relpath(p, out).replace("\\", "/"), "bytes": os.path.getsize(p),
             "sha256": sha(p)}
            for p in [sv, irp] + ([ex["pdf"], ex["png"]] if ex["pdf"] else [])]
    F = contract(case)
    R = {"case_id": cid, "task": "实验装置与技术路线图：生成图稿并保留可编辑来源",
         "status": "partial" if PB else "success",
         "status_reason": "；".join("%s: %s" % (x["item"], x["why"]) for x in PB) if PB
         else "结构/连线/来源/导出自检通过（见 scripts/check_consistency.py）",
         "summary": "%s：%d 面板 / %d 图元 / %d 连线；溯源 %d/%d" % (kd, len(P), n_items, len(ED_), tok, tal),
         "figure_kind": kd, "canvas_mm": [f.wm, f.hm], "outputs": outs, "resolved_from": RSV,
         "deliverable": {"editable_source": {"path": "figures/figure.svg",
                                             "why": "分层 SVG，真实 <text> 未转曲，每块带 data-node/data-quote"},
                         "exports": ([{"path": "figures/figure.pdf", "format": "pdf"},
                                      {"path": "figures/figure.png", "format": "png", "dpi": dpi}]
                                     if ex["pdf"] else []),
                         "render_backend": ex.get("backend")},
         "elements": ELEMS,
         "relations": RELS,
         "data_mapping": [{"label": n["text"], "value": n["value"], "unit": n["unit"], "source": n["source"]}
                          for n in NU],
         "sources": ([{"path": m, "kind": "material"} for m in sorted(T)] +
                     [{"path": x["source"]["locator"], "kind": x["kind"], "id": x["id"],
                       "quote": x["source"]["quote"][:120]} for x in E] +
                     [{"path": s["source"]["locator"], "kind": "step." + s["kind"], "id": s["id"],
                       "quote": s["source"]["quote"][:120]} for s in ST] +
                     [{"path": q["source"]["locator"], "kind": "phase", "id": q["id"],
                       "quote": q["source"]["quote"][:120]} for q in PH]),
         "provenance": {"materials": sorted(T), "unreadable": bad, "trace_ok": tok, "trace_total": tal,
                        "ambiguities": AMB, "rule_based": True, "resolved_from": RSV},
         "change_log": [{"field": "materials.discovered", "value": len(T)},
                        {"field": "elements.drawn", "value": n_items},
                        {"field": "post_edit", "value": "none"},
                        {"field": "render_backend", "value": ex.get("backend")}],
         "checks": {"connections": {"edges": len(ED_), "direction_from_sentence": True,
                                    "ambiguous_skipped": len(AMB)},
                    "render": {"backend": ex.get("backend"), "notes": ex["notes"]}},
         "uncertainty": U, "gaps": G,
         "not_reported": [{"field": "scientific_judgement", "why": "题面排除：不评价实验方案科学合理性"}],
         "contract_echo": {}}
    for k in F:
        R[k] = R.get(k) if R.get(k) not in (None, "", [], {}) else (
            [] if "array" in F[k].lower() else "")
        R["contract_echo"][k] = "filled from computed result" if R[k] not in ("", [], {}) \
            else "no direct source in materials"
    _write(out, "result.json", R)
    # 两个职责单一的校验器：validate_ir 只判中间表示；check_consistency 只判跨产物一致性。
    # 先判一次 -> 有硬失败就如实翻 partial -> 写盘 -> 再判一次（记录最终一致的那份审计）。
    rj = os.path.join(out, "result.json")
    iv, cv = ir_mod.run(irp), cc_mod.run(irp, ind, sv, rj)
    if not iv["ok"] or not cv["ok"]:
        R["status"] = "partial"
        extra = "中间表示/一致性硬失败: %s" % ",".join((iv["errors"] + cv["hard_failures"])[:6])
        R["status_reason"] = (R["status_reason"] + "；" + extra) if R["status_reason"] else extra
    _write(out, "result.json", R)
    iv, cv = ir_mod.run(irp), cc_mod.run(irp, ind, sv, rj)
    R["checks"]["ir"] = {"ok": iv["ok"], "errors": iv["errors"], "warnings": iv["warnings"]}
    R["checks"]["consistency"] = {"ok": cv["ok"], "hard_failures": cv["hard_failures"],
                                  "checks": len(cv["items"]), "stats": cv["stats"]}
    _write(out, "result.json", R)
    print("[apparatus] case=%s status=%s kind=%s type=%s panels=%d elements=%d edges=%d "
          "trace=%d/%d index=%d backend=%s ir=%s consistency=%s"
          % (cid, R["status"], kd, IR["figure_type"], len(P), n_items, len(ED_), tok, tal,
             len(IDX), ex.get("backend"), iv["ok"], cv["ok"]))
    for x in PB[:4]:
        print("[apparatus]   ! %s: %s" % (x["item"], x["why"]))
    return R

def main(a=None):
    ap = argparse.ArgumentParser(description="materials -> editable figure + result.json")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--arm", default="skill", choices=("skill", "naive"),
                    help="skill=本包主路径（默认）；naive=公平对照臂 A")
    x = ap.parse_args(a)
    run(x.case, x.out, x.dpi, x.arm)
    return 0

if __name__ == "__main__":
    sys.exit(main())
