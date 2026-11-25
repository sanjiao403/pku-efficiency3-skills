import argparse, hashlib, io, json, os, re, sys, unicodedata, zipfile
import minipptx
from datetime import datetime, timezone

V = "1.3-min"
sys.dont_write_bytecode = True
T = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
nz = lambda t: re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(t or ""))).strip()
sq = lambda t: nz(t).lower().replace(" ", "")
cj = lambda t: bool(re.search(r"[\u3400-\u9fff\u3040-\u30ff]", t or ""))

def cl(t, n=160):
    t = nz(t)
    return t if len(t) <= n else t[:n - 1] + "\u2026"

def jl(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return d

def jd(o, p):
    os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)

def wt(s, p):
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)

NUM = re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?(?:\s*[eE]\s*[+-]?\d+)?(?:\s*%)?)(?![\w])")
STAT = re.compile(r"p\s*[<=>]\s*0?\.\d+|95%\s*CI|n\s*=\s*\d+|\u00b1\s*\d", re.I)
HED = re.compile(r"\bmay\b|\bsuggest|\bindicat|\u53ef\u80fd|\u521d\u6b65", re.I)
NUMs = lambda t: [m.group(1).strip() for m in NUM.finditer(nz(t))]
SENTS = lambda t: [x.strip() for x in re.split(r"(?<=[.!?;\u3002\uff01\uff1f\uff1b])\s+", nz(t)) if x.strip()]

def _un(b):
    s = b.decode("latin-1", "replace") if isinstance(b, bytes) else b
    s = re.sub(r"\\([nrtbf()\\])", lambda m: {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
                                              "(": "(", ")": ")", "\\": "\\"}[m.group(1)], s)
    return re.sub(r"\\([0-7]{1,3})", lambda m: chr(int(m.group(1), 8)), s)

def rpdf(p):
    raw = open(p, "rb").read()
    o = []
    for m in re.finditer(rb"stream\r?\n", raw):
        e = raw.find(b"endstream", m.end())
        if e < 0:
            continue
        b = raw[m.end():e]
        try:
            d = __import__("zlib").decompress(b.strip(b"\r\n"))
        except Exception:
            d = b if (b"BT" in b and (b"Tj" in b or b"TJ" in b)) else b""
        if not d:
            continue
        for t in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*Tj|\[((?:[^\[\]]|\\.)*)\]\s*TJ|T\*|Td", d):
            s = t.group(0)
            if s.endswith(b"Tj"):
                o.append(_un(s[:s.rfind(b")") + 1][1:-1]))
            elif s.endswith(b"TJ"):
                o += [_un(x.group(0)[1:-1]) for x in re.finditer(rb"\((?:\\.|[^\\()])*\)", t.group(1) or b"")]
            else:
                o.append("\n")
    t = re.sub(r"\n{3,}", "\n\n", " ".join(o)).strip()
    return (t, None) if len(sq(t)) >= 40 else (None, "skipped_no_text_layer")

def rd(p):
    n, x = os.path.basename(p), os.path.splitext(os.path.basename(p))[1].lower()
    r = {"file": n, "bytes": os.path.getsize(p) if os.path.exists(p) else 0, "readable": False,
         "note": None, "lines": [], "figures": [], "numbers": []}
    try:
        if x == ".pdf":
            t, note = rpdf(p)
        elif x == ".docx":
            t = re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n",
                       zipfile.ZipFile(p).read("word/document.xml").decode("utf-8", "replace")))
            note = None
        elif x in (".md", ".txt", ".json", ".csv", ".tsv", ""):
            t, note = io.open(p, encoding="utf-8", errors="replace").read(), None
        else:
            t, note = None, "unsupported_ext"
    except Exception as e:
        t, note = None, "%s_unreadable" % (x or "file")
    if t is None:
        r["note"] = note
        return r
    r.update(readable=True, note=note, lines=t.splitlines(), numbers=sorted(set(NUMs(t)), key=lambda s: -len(s))[:300])
    for i, ln in enumerate(r["lines"], 1):
        m = re.match(r"^\s*(?:#{1,6}\s*|\d+(?:\.\d+)*[.)]?\s+)(\S.{0,100})$", ln)
        if m:
            r.setdefault("sections", []).append(cl(m.group(1), 80))
        c = re.match(r"^\s*(Figure|Fig\.?|Table|\u56fe|\u8868)\s*([0-9]+[a-z]?)\s*[.:\uff1a]?\s*(.{0,170})", ln, re.I)
        if c:
            r["figures"].append({"id": "%s %s" % ("Figure" if re.match(r"^\s*(Figure|Fig\.?|\u56fe)", ln, re.I)
                                                  else "Table", c.group(2)),
                                 "caption": cl(c.group(3), 150), "line": i})
    return r

def mp(case, root):
    pool = {}
    for dp, _d, fs in os.walk(root):
        for f in fs:
            pool.setdefault(f.lower(), os.path.join(dp, f))
    got, miss = [], []
    for e in (list(case.get("materials") or []) or sorted(pool)):
        b = os.path.basename(str(e)).lower()
        (got.append(pool[b]) if b in pool else miss.append(os.path.basename(str(e))))
    return got, miss

FORCE = (("limitation", r"\blimitation|\u5c40\u9650|\u672a\u9a8c\u8bc1|\bwe did not\b|\u672a\u505a"),
         ("next_step", r"\u4e0b\u4e00\u6b65|\u5224\u636e|\u5361\u70b9|\u5c1a\u672a\u8dd1\u5b8c|\bnext step"),
         ("setup", r"\u6570\u636e\u96c6|\bdataset\b|\u5212\u5206|\bseed\b|\u968f\u673a\u79cd\u5b50"),
         ("result", r"\u76f8\u5bf9.{0,12}\u63d0\u5347|p\s*[<=]\s*0?\.\d+|95%\s*CI|\u00b1"))
SIG = (("problem", r"\bhowever\b|\bremains?\b|\bchalleng|\u4f46|\u7136\u800c|\u96be\u9898|\u95ee\u9898"),
       ("limitation", r"\blimitation|\bcannot\b|\bfuture work|\u5c40\u9650|\u4e0d\u8db3"),
       ("next_step", r"\u4e0b\u4e00\u6b65|\u5224\u636e|\u5361\u70b9|\u5c1a\u672a"),
       ("contribution", r"\bwe (?:propose|introduce|present|contribute)|\bnovel\b|\u63d0\u51fa|\u8d21\u732e|\u521b\u65b0"),
       ("method", r"\bwe (?:train|fine-?tune|fit|compute|run)\b|\b(?:framework|pipeline|algorithm|module|objective)\b|\u65b9\u6cd5|\u6846\u67b6|\u6d41\u7a0b|\u6b65\u9aa4"),
       ("setup", r"\bdataset\b|\bseed\b|\bGPU\b|\u6570\u636e\u96c6|\u6837\u672c|\u5b9e\u9a8c\u8bbe\u7f6e"),
       ("result", r"\bimprov|\boutperform|\bachiev|\bincreas|\breduc|\bcompared? (?:with|to)\b|\u63d0\u9ad8|\u964d\u4f4e|\u8d85\u8fc7|\u4f18\u4e8e"),
       ("background", r"\bin recent years\b|\u8fd1\u5e74\u6765|\u80cc\u666f"))
_F = [(k, re.compile(v, re.I)) for k, v in FORCE]
_S = [(k, re.compile(v, re.I)) for k, v in SIG]

def klass(s):
    for k, r in _F:
        if r.search(s):
            return k, 6 + (2 if NUMs(s) else 0)
    for k, r in _S:
        if r.search(s):
            return k, 3 + (2 if NUMs(s) else 0) + (2 if STAT.search(s) else 0)
    return None, 0

def atoms_of(mats, cap=140):
    out, drop = [], 0
    for r in mats:
        if not r["readable"]:
            continue
        for i, ln in enumerate(r["lines"], 1):
            for s in SENTS(ln):
                if len(s) < 24:
                    continue
                k, sc = klass(s)
                if not k or sc < 3:
                    drop += 1
                    continue
                c = re.sub(r"^(?:In (?:this|the) (?:paper|work),\s*)", "", s, flags=re.I)
                for cut in (r",?\s*(?:we|which)\b", r"\uff0c?\s*\u56e0\u6b64"):
                    m = re.search(cut, c)
                    if m and m.start() > 30:
                        c = c[:m.start()]
                out.append({"kind": k, "score": sc, "claim": cl(c.rstrip(" ,;\u3001\uff0c"), 140), "src": cl(s, 360),
                            "material": r["file"], "line": i, "numbers": NUMs(s)[:6],
                            "stat": bool(STAT.search(s)), "hedge": bool(HED.search(s))})
        for f in r["figures"]:
            out.append({"kind": "figure", "score": 6, "claim": f["caption"], "src": f["caption"],
                        "material": r["file"], "line": f["line"], "numbers": NUMs(f["caption"])[:6],
                        "stat": False, "hedge": False, "fig": f["id"]})
    out.sort(key=lambda a: (-a["score"], a["material"], a["line"]))
    seen, uniq = set(), []
    for a in out:
        k = sq(a["claim"])[:110]
        if k in seen:
            continue
        seen.add(k)
        a["id"] = "A%02d" % (len(uniq) + 1)
        uniq.append(a)
        if len(uniq) >= cap:
            break
    return uniq, drop

ARCS = (("committee-defense", r"\u7b54\u8fa9|\u5b66\u4f4d|\u8bc4\u5ba1|\u8bc4\u59d4|defense|committee|viva", "strong", 5,
         ("title", "problem", "gap", "contribution", "method-overview", "method-detail", "setup", "result-1",
          "result-2", "limitation", "conclusion")),
        ("lab-meeting", r"\u7ec4\u4f1a|\u8fdb\u5ea6|\u5408\u4f5c\u8005|\u540c\u4e8b|lab meeting|group meeting|progress", "moderate", 4,
         ("title", "problem", "method-overview", "setup", "result-1", "result-2", "limitation", "conclusion")),
        ("reviewer-symposium", r"\u8bc4\u5ba1|\u4f1a\u8bae|\u7814\u8ba8\u4f1a|\u540c\u884c|reviewer|review|symposium|conference", "strong", 3,
         ("title", "problem", "gap", "method-overview", "setup", "result-1", "result-2", "ablation", "limitation", "conclusion")),
        ("teaching-seminar", r"\u6559\u5b66|\u8bb2\u5ea7|\u5b66\u751f|teaching|lecture|student|tutorial", "moderate", 3,
         ("title", "background", "problem", "method-overview", "method-detail", "result-1", "conclusion")),
        ("grant-panel", r"\u7acb\u9879|\u7533\u8bf7|\u9879\u76ee|\u57fa\u91d1|grant|proposal|funding", "moderate", 5,
         ("title", "problem", "gap", "method-overview", "setup", "result-1", "limitation", "conclusion")))
KIND = {"title": None, "background": "background", "problem": "problem", "gap": "problem", "contribution": "contribution",
        "method-overview": "method", "method-detail": "method", "setup": "setup", "result-1": "result",
        "result-2": "result", "ablation": "result", "limitation": "limitation", "conclusion": "contribution"}
W = {"title": .6, "background": .9, "problem": 1.2, "gap": 1.1, "contribution": 1.1, "method-overview": 1.6,
     "method-detail": 1.3, "setup": 1.1, "result-1": 1.8, "result-2": 1.4, "ablation": 1.2, "limitation": 1.3, "conclusion": 1.2}
RK = {"weak": 0, "moderate": 1, "strong": 2}
LAT, CJ = 96, 42

def pick(case):
    hay = nz(" ".join(str(case.get(k) or "") for k in ("audience", "goal", "presentation_type", "task"))).lower()
    best, hit = None, 0
    for a in ARCS:
        c = sum(1 for w in a[1].split("|") if re.search(w, hay))
        if c > hit:
            best, hit = a, c
    return (best or ARCS[2]), ("matched %d keyword(s)" % hit if best else "default arc")

def bud(case, arc):
    o = []
    d = case.get("duration_min") or 12
    if not case.get("duration_min"):
        o.append("duration_min missing -> 12 min")
    q = case.get("qa_min")
    if q in (None, ""):
        q, _ = arc[3], o.append("qa_min missing -> %s min" % arc[3])
    n = case.get("slide_count")
    if n:
        o.append("slide_count=%s from case" % n)
    else:
        n, _ = max(6, min(20, int(round(float(d) / .85)))), o.append("slide_count missing -> derived")
    n = int(n)
    nb = min(3 if n >= 12 else (2 if n >= 8 else 1), max(0, int(round(n * .28))))
    nc = max(3, n - nb)
    talk = max(60, int(round((float(d) - float(q)) * 60)))
    per = talk / 60.0 / nc
    return {"duration_min": float(d), "qa_min": float(q), "slide_count": n, "content_slides": nc, "backup_planned": nb,
            "talk_seconds": talk, "min_per_slide": round(per, 3), "origin": o,
            "band_ok": .85 * .72 <= per <= .85 * 1.55}

def strength(pool, cap):
    s = "weak"
    if any(a["stat"] for a in pool) and any(a["numbers"] for a in pool):
        s = "strong"
    elif any(a["numbers"] for a in pool) or any(a["kind"] == "figure" for a in pool) or len(pool) >= 2:
        s = "moderate"
    if any(a["hedge"] for a in pool) and s == "strong":
        s = "moderate"
    return cap if RK[s] > RK[cap] else s

def notes(r, claim, st, pool, case):
    z = cj(" ".join(str(case.get(k) or "") for k in ("task", "audience", "goal"))) or any(cj(a["src"]) for a in pool)
    if r == "title":
        return "\u5f00\u573a\u4ea4\u4ee3\u4e3b\u5f20\uff0c\u4e0d\u5ff5\u76ee\u5f55\u3002" if z else "Open with the takeaway; skip the agenda."
    if z:
        o = ["\u8bb2\u4ec0\u4e48\uff1a%s" % (claim or r)]
        if pool:
            o.append("\u6307\u4ec0\u4e48\uff1a%s\uff08%s%s\uff09" % (cl(pool[0]["src"], 80), pool[0]["material"],
                                                                ":L%s" % pool[0]["line"]))
        o.append("\u5f3a\u5ea6\uff1a%s\uff0c\u4e0d\u8d8a\u8fc7\u8bc1\u636e\u3002" % st)
        return "\n".join(o)
    o = ["Say: %s" % (claim or r)]
    if pool:
        o.append("Point at: %s (%s L%s)" % (cl(pool[0]["src"], 80), pool[0]["material"], pool[0]["line"]))
    return "\n".join(o + ["Strength: %s." % st])

def plan(case, atoms, arc, b):
    by, used = {}, set()
    for a in atoms:
        by.setdefault(a["kind"], []).append(a)
    for k in by:
        by[k].sort(key=lambda a: -a["score"])

    def take(kind, n, reuse=False):
        out, ks = [], ([kind, "problem"] if kind == "gap" else [kind, "setup"] if kind == "method" else
                       [kind, "result"] if kind == "result" else [kind])
        for k in ks:
            for a in by.get(k, []):
                if a["id"] not in used:
                    used.add(a["id"])
                    out.append(a)
                    if len(out) >= n:
                        return out
        if kind in ("result", "setup"):
            for a in by.get("figure", []):
                if a["id"] not in used:
                    used.add(a["id"])
                    out.append(a)
                    if len(out) >= n:
                        break
        if len(out) < n and reuse:
            for a in sorted([x for k in ks for x in by.get(k, [])] or atoms, key=lambda x: -x["score"]):
                if all(a["id"] != y["id"] for y in out):
                    z = dict(a)
                    z["reused"] = True
                    out.append(z)
                if len(out) >= n:
                    break
        return out

    roles = [r for r in arc[4] if r in W][:max(3, min(b["content_slides"], len(atoms)))]
    while len(roles) < b["content_slides"]:
        roles.append("result-1")
    res = {r: (take(KIND[r], 1) or [None])[0] if KIND[r] else None for r in roles}
    pages, totw, dropped = [], sum(W[r] for r in roles if r != "title") or 1, []
    for i, r in enumerate(roles, 1):
        prim = [res[r]] if res.get(r) else take(KIND[r], 1, True)
        ev = [a for a in take(KIND[r], 2 if r[:6] == "result" else 1, True) if a and all(a["id"] != p["id"] for p in prim)] if KIND[r] else []
        pool = [p for p in prim + ev if p]
        claim = pool[0]["claim"] if pool else ""
        if r == "title" and not claim:
            claim = cl(case.get("goal") or case.get("task") or "talk", 90)
        if r == "conclusion" and pool:
            rr = next((a for a in pool if a["kind"] == "result"), pool[0])
            lm = next((a for a in atoms if a["kind"] == "limitation"), None)
            claim = "\u672c\u6750\u6599\u8303\u56f4\u5185\uff1a%s" % cl(rr["claim"], 70)
            if lm:
                claim += "\uff1b\u9002\u7528\u8fb9\u754c\uff1a%s" % cl(lm["claim"], 50)
                if all(a["id"] != lm["id"] for a in ev):
                    ev.append(lm)
                pool.append(lm)
        claim = claim or cl(case.get("task") or r, 90)
        st = strength(pool, arc[2]) if pool else "weak"
        bl = [cl(a["claim"], CJ if cj(a["claim"]) else LAT) for a in pool if sq(a["claim"]) != sq(claim)][:4]
        if r == "title":
            bl = [case.get("audience")] if case.get("audience") else []
        pages.append({"index": i, "role": r, "title": cl(claim, 34 if cj(claim) else 60), "claim": claim,
                      "claim_strength": st, "bullets": bl, "figures": sorted({a["fig"] for a in pool if a.get("fig")}),
                      "evidence": [{"atom": a["id"], "material": a["material"], "line": a["line"],
                                    "quote": cl(a["src"], 200), "numbers": a["numbers"]} for a in pool],
                      "seconds": 0 if r == "title" else int(round(b["talk_seconds"] * W[r] / totw)),
                      "speaker_notes": notes(r, claim, st, pool, case)})
    seen, keep = set(), []
    for p in pages:
        if sq(p["claim"])[:100] in seen:
            dropped.append({"kind": p["role"], "claim": cl(p["claim"], 110), "reason": "duplicate claim -> no main page"})
            continue
        seen.add(sq(p["claim"])[:100])
        keep.append(p)
    pages, freed = keep, len(pages) - len(keep)
    for i, p in enumerate(pages, 1):
        p["index"] = i
    sp = sum(p["seconds"] for p in pages)
    if sp:
        for p in pages:
            p["seconds"] = max(5, int(round(p["seconds"] * b["talk_seconds"] / float(sp))))
    backups, extra = [], sorted([a for a in atoms if a["id"] not in used and a["kind"] != "figure"], key=lambda a: -a["score"])
    while len(backups) < b["backup_planned"] + freed and extra:
        a = extra.pop(0)
        used.add(a["id"])
        backups.append({"index": len(pages) + len(backups) + 1, "role": "backup-%s" % a["kind"],
                        "title": "Q&A backup \u00b7 %s" % a["kind"], "claim": a["claim"], "bullets": [cl(a["claim"], 90)],
                        "claim_strength": "moderate", "seconds": 0,
                        "evidence": [{"atom": a["id"], "material": a["material"], "line": a["line"],
                                      "quote": cl(a["src"], 180), "numbers": a["numbers"]}],
                        "speaker_notes": "Backup: quote the cited line and number only."})
    for a in atoms:
        if a["id"] not in used:
            dropped.append({"atom": a["id"], "kind": a["kind"], "claim": cl(a["claim"], 110),
                            "reason": "off-page under the slide/time budget (kept for Q&A)"})
    return pages, backups, dropped[:60]

DEF = {"outline": "\u7ed3\u6784\u5316\u5927\u7eb2", "editable_deck": "\u53ef\u7f16\u8f91\u6f14\u793a\u6587\u4ef6",
       "status": "success / partial / unsupported", "uncertainty": "\u7f3a\u53e3"}
HINT = (("deck", r"deck|pptx|slide|presentation|\u6f14\u793a"), ("outline", r"outline|page_plan|plan|structure|\u5927\u7eb2|\u9875\u7ea7"),
        ("evidence", r"evidence|mapping|anchor|provenance|\u8bc1\u636e|\u6620\u5c04"), ("qa", r"qa|question|backup|\u95ee\u7b54|\u5907\u7528"),
        ("notes", r"notes|script|speaker|\u8bb2\u7a3f|\u5907\u6ce8"), ("time", r"time|duration|budget|\u65f6\u957f"),
        ("audience", r"audience|goal|objective|\u542c\u4f17|\u76ee\u6807"), ("render", r"render|export|preview|version|\u6e32\u67d3|\u5bfc\u51fa"),
        ("uncertainty", r"uncertain|gap|risk|\u4e0d\u786e\u5b9a|\u7f3a\u53e3"), ("status", r"status|\u72b6\u6001"))

def con_of(case):
    for f in ("output_contract", "contract", "output_spec", "expected_outputs", "outputs", "deliverables"):
        c = case.get(f)
        if isinstance(c, dict) and c:
            return dict(c), f
        if isinstance(c, list) and c:
            o = {}
            for it in c:
                if isinstance(it, dict):
                    k = it.get("name") or it.get("key") or it.get("field") or it.get("path")
                    if k:
                        o[str(k)] = it.get("description") or it.get("type") or "declared output"
                elif isinstance(it, str):
                    o[it] = "declared output"
            if o:
                return o, f
    return dict(DEF), "built-in default contract"

def fe(p):
    e = {"path": os.path.basename(p), "exists": False, "bytes": 0, "sha256": None}
    if os.path.exists(p):
        d = open(p, "rb").read()
        e.update(exists=True, bytes=len(d), sha256=hashlib.sha256(d).hexdigest())
    return e

def main(av=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--input", default="")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    a = ap.parse_args(av)
    ind = a.input or os.path.dirname(os.path.abspath(a.case)) or "."
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    case = jl(a.case, {}) or {}
    case.setdefault("case_id", os.path.splitext(os.path.basename(a.case))[0])
    con, csrc = con_of(case)
    ps, miss = mp(case, ind)
    mats, deg = [], []
    for p in ps:
        r = rd(p)
        mats.append(r)
        if r["note"]:
            deg.append("%s: %s" % (r["file"], r["note"]))
    deg += ["declared material not found: %s" % m for m in miss]
    at, ndrop = atoms_of(mats)
    arc, why = pick(case)
    b = bud(case, arc)
    pages, backups, dropped = plan(case, at, arc, b) if at else ([], [], [])
    short = (b["slide_count"] - len(pages) - len(backups)) if at else 0
    status = "success" if at else "unsupported"
    reason = "page plan + editable deck + anchors produced" if at else "no anchored content could be extracted; no page was invented"
    if at and (deg or short > 0):
        status = "partial"
        reason = ("material-side gaps recorded in uncertainty" if deg and short <= 0 else
                  "only %d of %d slides could be filled with anchored content; the shortfall is recorded, "
                  "not padded with duplicate or unanchored pages" % (len(pages) + len(backups), b["slide_count"])
                  if short > 0 else reason)
    unc = [{"item": d, "why": "unreadable or declared-but-missing material", "handling": "never used on a slide; recorded instead of invented"} for d in deg] \
        or [{"item": "no material-side gap detected", "why": "all declared materials readable", "handling": "scientific content still needs human review"}]
    if short > 0:
        unc.append({"item": "slide_count target %d vs %d produced" % (b["slide_count"], len(pages) + len(backups)),
                    "why": "the materials only contain %d distinct anchored items; padding the deck would mean "
                           "repeating claims or inventing evidence" % len(at),
                    "handling": "shortfall recorded here; ask for more material or accept a shorter deck"})
    spec = jl(os.path.join(ind, str(case.get("template_spec") or "template-spec.json")), {}) or \
        jl(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "template-spec.json"), {}) or {}
    th = spec.get("theme") or {}
    pt = os.path.join(a.out, "deck.pptx")
    slides = [{"title": p["title"], "bullets": p["bullets"], "claim": p["claim"], "strength": p["claim_strength"],
               "notes": p["speaker_notes"]} for p in pages] + \
             [{"title": "Q&A backup \u00b7 %s" % x["title"], "bullets": x["bullets"], "claim": x["claim"],
               "strength": "moderate", "notes": x["speaker_notes"]} for x in backups]
    if slides:
        minipptx.write(pt, slides, th.get("major_font") or "Calibri", th.get("ea_font") or "Calibri")
        eng = "stdlib-ooxml"
    else:
        eng = "skipped_no_pages"
    anchors = sum(len(p["evidence"]) for p in pages)
    jd({"case_id": case.get("case_id"), "deck": os.path.basename(pt) if slides else None,
        "audience_model": {"audience": case.get("audience"), "goal": case.get("goal"), "archetype": arc[0],
                           "archetype_reason": why, "strength_cap": arc[2]},
        "time_budget": b,
        "pages": [{"index": p["index"], "role": p["role"], "title": p["title"], "claim": p["claim"],
                   "claim_strength": p["claim_strength"], "bullets": p["bullets"], "figures": p["figures"],
                   "seconds": p["seconds"], "evidence_refs": [{"material": e["material"], "line": e["line"],
                                                               "numbers": e["numbers"]} for e in p["evidence"]]} for p in pages],
        "backup_slides": [{"index": x["index"], "role": x["role"], "title": x["title"], "claim": x["claim"]} for x in backups],
        "dropped_atoms": dropped,
        "deck_shortfall": {"target_slides": b["slide_count"], "produced": len(pages) + len(backups),
                           "missing": short}}, os.path.join(a.out, "outline.json"))
    nl = ["# speaker notes", "", "case %s | arc %s | %d pages + %d backup | %.1f min" % (
        case.get("case_id"), arc[0], len(pages), len(backups), b["duration_min"]), ""]
    for p in pages:
        nl += ["## %d. %s  <%s>" % (p["index"], p["title"], p["role"]),
               "- claim (%s): %s" % (p["claim_strength"], p["claim"]),
               "- %ss | anchors: %s" % (p["seconds"], ", ".join("%s:L%s" % (e["material"], e["line"]) for e in p["evidence"]) or "-"), ""]
        nl += ["> " + x for x in p["speaker_notes"].split("\n")] + [""]
    wt("\n".join(nl) + "\n", os.path.join(a.out, "speaker-notes.md"))
    names = (["deck.pptx"] if slides else []) + ["outline.json", "speaker-notes.md"]
    outs = [fe(os.path.join(a.out, n)) for n in names]
    avail = [o["path"] for o in outs if o["exists"]]
    ctx = {"deck": {"file": "deck.pptx", "slides": len(slides), "engine": eng, "editable": True},
           "outline": {"file": "outline.json", "pages": len(pages), "backup_slides": len(backups)},
           "evidence": {"file": "outline.json#pages[].evidence_refs", "anchors": anchors},
           "qa": {"file": "outline.json#backup_slides", "backup_slides": len(backups)},
           "notes": {"file": "speaker-notes.md", "per_page": True}, "time": b, "audience": case.get("audience"),
           "render": {"engine": eng, "preview": None}, "uncertainty": unc, "status": status}
    res, unres = {"case_id": case.get("case_id")}, []
    for k in con:
        kk = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", nz(k).lower())
        kind = next((t for t, pat in HINT if re.search(pat, kk)), None)
        v = ctx.get(kind) if kind else None
        if v is None:
            g = next((o["path"] for o in outs if o["exists"] and
                      re.sub(r"[^a-z0-9]", "", os.path.splitext(o["path"])[0]) in kk), None)
            v = next((o for o in outs if o["path"] == g), None) if g else None
            if v is None:
                unres.append({"key": k, "declared": con[k], "value": None,
                              "why": "no internal artifact matches and no artifact-name match was found; value NOT guessed",
                              "available_artifacts": avail,
                              "how_to_fix": "add a hint regex for this key in scripts/talkplan.py HINT"})
        res[k] = v
    res.update({"task": case.get("task", ""), "status": status, "status_reason": reason,
                "summary": "%d pages + %d backup; %d anchored atom(s) from %d readable file(s)" % (
                    len(pages), len(backups), len(at), sum(1 for m in mats if m["readable"])),
                "sources": [{"material": m["file"], "bytes": m["bytes"], "readable": m["readable"], "note": m["note"]} for m in mats],
                "uncertainty": unc,
                "change_log": [{"what": "materials", "why": "%d of %d readable; %d sentences dropped for no signal" % (
                    sum(1 for m in mats if m["readable"]), len(mats), ndrop)},
                    {"what": "plan", "why": "audience -> arc %s (%s); %d content + %d backup slides" % (arc[0], why, len(pages), len(backups))},
                    {"what": "deck", "why": "engine=%s (%d slides + notes)" % (eng, len(slides))}],
                "deliverables": names, "outputs": outs,
                "contract_passthrough": {"source": csrc, "declared": len(con), "resolved": len(con) - len(unres)},
                "contract_unresolved_fields": unres, "generated_at": T(),
                "skill": {"name": "academic-talk-structurer", "version": V}})
    jd(res, os.path.join(a.out, "result.json"))
    print("talkplan: %d pages + %d backup | arc=%s | anchors=%d | engine=%s | status=%s" % (
        len(pages), len(backups), arc[0], anchors, eng, status))
    return 0

if __name__ == "__main__":
    sys.exit(main())
