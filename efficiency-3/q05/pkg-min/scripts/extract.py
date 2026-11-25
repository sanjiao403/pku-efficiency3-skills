#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# extract.py -- 材料 -> 结构化中间结果（实体/连线/步骤/阶段/数值），供 apparatus.py 使用
# 原则：只写读到的。连线只认显式句式；一个称呼对应多个单元时不猜；每个条目带原文定位。
import json, os, re, sys

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


def collect(d):
    T, bad = {}, []
    for root, _s, fs in os.walk(d):
        for f in sorted(fs):
            p, rel = os.path.join(root, f), os.path.relpath(os.path.join(root, f), d).replace("\\", "/")
            if os.path.splitext(f)[1].lower() in SKIP:
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


def guess(case, T):
    h = ((json.dumps(case, ensure_ascii=False) if case else "") + " " + " ".join(t[:2500] for t in T.values())).lower()
    return "roadmap" if re.search(r"(技术路线|roadmap|阶段目标|milestone|phase)", h) else "schematic"


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(65536), b""):
            h.update(b)
    return h.hexdigest()[:16]


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


def sirof(case):
    """materials -> (sir, numbers, ambiguities, unreadable)"""
    ind = os.path.dirname(os.path.abspath(case)) or "."
    T, bad = collect(ind)
    bl = []
    for n, t in T.items():
        bl += blocks_of(n, t)
    E, NU, ST, PH = ents(bl), nums_of(bl), stps(bl), phs(bl)
    ED, AMB = flows(bl, E)
    for e in E:
        own = [x["text"] for x in NU if x["source"]["quote"].find(e["label"][:10]) >= 0]
        if own:
            e["numbers"] = own[:2]
    return E, ED, ST, PH, NU, AMB, T, bad


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "/input"
    cp = os.path.join(d, "case.json")
    case, cid = read_case(d, cp)
    E, ED, ST, PH, NU, AMB, T, bad = sirof(cp)
    print(json.dumps({"case_id": cid, "entities": E, "edges": ED, "steps": ST, "phases": PH,
                      "numbers": NU, "ambiguities": AMB, "materials": sorted(T), "unreadable": bad},
                     ensure_ascii=False, indent=2))
