"""pathway.py — compact mechanism/pathway figure Skill (entry point).

    python3 scripts/pathway.py --case /input/case.json --out /app/output

material -> typed entities + directed interactions (EN/中文) -> layered mechanism SVG (text)
+ PNG run-time preview -> result.json (contract echoed) + check-report.json.
Rules: one arrow shape per interaction meaning, width = evidence strength, transmembrane receptor
straddles the membrane, passive voice / 被/由/受 flips arguments, negated claims are excluded (not
drawn), unresolved clauses are listed (never guessed), every entity/edge carries a locator, and a
value without a locator is refused. Layout, drawing and export are in this file.
"""
import argparse, csv, io, json, math, os, re, sys
from datetime import datetime, timezone

VER = "1.0.0-min"
# type|label|line|arrow|colour|english cues|chinese cues|chinese passive patterns
VOC = """
activates|activation|solid|tri|#2E7D32|activates promotes induces stimulates drives triggers mediates|激活 活化 促进 诱导 增强 上调 增加 驱动 导致 引起 介导|被激活 被诱导 由.*?激活
inhibits|inhibition|solid|tbar|#C62828|inhibits suppresses represses blocks prevents reduces|抑制 阻断 下调 降低 减少 削弱 拮抗 限制 沉默 负调控|被抑制 被阻断 由.*?抑制
binds|binding / association|solid|circ|#1565C0|binds interacts associates recruits|结合 相互作用 互作 形成复合物 招募|与.*?结合 和.*?结合
modifies|covalent modification|dash|tri|#6A1B9A|phosphorylates ubiquitinates methylates cleaves hydroxylates|磷酸化 泛素化 甲基化 乙酰化 羟化 修饰|被磷酸化 被泛素化 由.*?磷酸化
transports|transport / translocation|dashdot|tri_o|#EF6C00|transports translocates imports exports secretes|转运 转位 易位 入核 出核 分泌 释放 进入细胞核|被转运 被分泌
expresses|transcription / expression|solid|chev|#00695C|transcribes encodes expresses|转录激活 转录 表达 编码 翻译|由.*?编码
degrades|degradation|dot|tri|#4E342E|degrades destabilizes|降解 促降解 清除|被降解
unspecified|interaction (type not stated)|dash|none|#616161|interacts associates|相互作用 关联|
regulates_unknown|regulation (direction not stated)|dash|none|#616161|regulates modulates affects controls|调控 调节 影响 相关 参与|受.*?调控
"""
CMP = [("extracellular", "Extracellular space", "extracellular secreted 细胞外 分泌"),
       ("plasma_membrane", "Plasma membrane", "membrane transmembrane 细胞膜 跨膜"),
       ("cytosol", "Cytosol", "cytosol cytoplasm 细胞质 胞质"),
       ("nucleus", "Nucleus", "nucleus nuclear 细胞核 核内"),
       ("outcome", "Cellular outcome (not a compartment)", "proliferation apoptosis 增殖 凋亡")]
TYP = {"gene": ("Gene", "#E8F1FB", "#1565C0"), "protein": ("Protein", "#EAF5EA", "#2E7D32"),
       "complex": ("Complex", "#F3E9F7", "#6A1B9A"), "drug": ("Drug", "#FDECEA", "#B23A2E"),
       "phenotype": ("Phenotype / output", "#ECEFF1", "#37474F"),
       "compartment": ("Compartment target", "#FFFFFF", "#78909C")}
R = {}
for _ln in VOC.strip().split("\n"):
    _p = _ln.split("|")
    R[_p[0]] = {"lab": _p[1], "line": _p[2], "arrow": _p[3], "col": _p[4], "en": _p[5],
                "zh": _p[6], "pz": _p[7]}
DSH = {"solid": None, "dash": "7 4", "dot": "1.6 2.6", "dashdot": "9 3 1.6 3"}
SEM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "references", "arrow-semantics.json")
try:
    SEM = json.load(open(SEM_PATH, encoding="utf-8"))
except Exception:                                # the package still runs without the table
    SEM = {"edge_types": {}, "head_shapes": {}, "legend_requirements": {}}
DIR_CUES = ("activates inhibits phosphorylates ubiquitinates methylates cleaves hydroxylates promotes "
            "blocks recruits induces suppresses drives triggers mediates transports translocates "
            "imports exports secretes transcribes encodes expresses degrades destabilizes 激活 活化 促进 "
            "诱导 增强 上调 提高 增加 触发 驱动 导致 引起 介导 抑制 阻断 下调 降低 减少 削弱 拮抗 沉默 "
            "磷酸化 泛素化 甲基化 乙酰化 羟化 修饰 转运 转位 易位 入核 出核 分泌 释放 转录 表达 编码 翻译 "
            "降解 促降解 清除").split()


_DIR_PAT = []


def direction_stated(quote):
    """True when the quoted statement itself expresses a direction (inflection-tolerant for
    English, literal for Chinese). Built lazily: the CJK test is defined later in the module."""
    if not _DIR_PAT:
        _DIR_PAT.append(re.compile("|".join(
            [_en_pat(c) for c in DIR_CUES if not CJK.search(c)] +
            [re.escape(c) for c in DIR_CUES if CJK.search(c)]), re.I))
    return bool(_DIR_PAT[0].search(quote or ""))
WID = {"strong": 2.6, "moderate": 1.9, "weak": 1.3}
STRONG, WEAK = "demonstrated 证实 直接".split(), "may might putative 可能 推测".split()
ALIAS = {"p53": "TP53", "erbb1": "EGFR", "her1": "EGFR", "pkb": "AKT1", "erk": "MAPK1", "mek": "MAP2K1",
         "raf": "RAF1", "ras": "KRAS", "pi3k": "PIK3CA", "hif2a": "EPAS1", "phd2": "EGLN1",
         "mtorc1": "MTOR", "glut1": "SLC2A1", "c-myc": "MYC"}
SUF = {"复合物": "complex", "基因": "gene", "蛋白": "protein", "受体": "protein", "激酶": "protein",
       "因子": "protein", "酶": "protein", "细胞": "cell_type"}
CLASS_EN = set("""protein gene kinase receptor complex pathway cell membrane nucleus cytosol cytoplasm
 enzyme inhibitor drug molecule factor transcription expression signalling signaling domain motif
 protein-protein ligand antibody symbol note protocol experiment sample figure table
 method result value dataset patient control treatment measurement reagent buffer assay""".split())
REJ = set("""the a an this that these those it its they them we our and or but not no all any both each other such
 same than then thus however figure fig table data results method materials example only note task test tests
 synthetic fixture official platform answer prepared skill agent png pdf svg dpi api json csv html url doi into
 from with within using used use also more most less least are was were has have been can may must""".split())
REJZ = set("转录因子 细胞因子 信号通路 细胞膜 细胞核 细胞质 复合物 蛋白酶体 激酶 受体 蛋白 基因 因子 酶 通路 "
           "稳定性 活性 水平 表达 磷酸化 泛素化 降解 转运 结合 抑制剂".split())
PH = ["细胞凋亡", "凋亡", "增殖", "迁移", "侵袭", "存活", "分化", "衰老", "自噬", "血管生成", "糖酵解",
      "proliferation", "apoptosis", "migration", "invasion", "survival", "differentiation"]
NEG = ["does not", "do not", "did not", "fails to", "is not", "are not", "no evidence", "并不", "不", "未",
       "无", "并非", "未见", "尚未", "不能"]
CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]")
TOK = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z]{1,6}[0-9]+[A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*"
                 r"|[A-Z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*|[A-Z]{2,}[0-9]*|[a-z]{3,20}"
                 r"|[\u4e00-\u9fff](?:\s?[\u4e00-\u9fff]){1,7})(?![A-Za-z0-9])")
SENT = re.compile(r"[^.!?。！？]+[.!?。！？]?")
CL = ",;:\uff0c\uff1b\uff1a\u3001\u3002\uff08\uff09()"
LOC = re.compile(r"(?:in|at|on|into|to|within)\s+(?:the\s+)?(plasma membrane|membrane|cytosol|cytoplasm|"
                 r"nucleus|nuclear|extracellular)", re.I)
LOCZ = re.compile("(?:在|于|至|进入|转入|位于)?\\s*(细胞外|细胞膜|质膜|细胞质|胞质|细胞核|核内)")
ZBY, PRO, PAIR = (re.compile("[\u7531\u88ab\u53d7]"), re.compile("[\u5176\u8be5\u6b64\u8fd9]"),
                  re.compile("^[\u4e0e\u548c]"))
CZ = ["并且", "同时", "而且", "并", "且", "从而", "进而", "因此", "所以", "也", "则", "而"]
CE = re.compile(r"\b(and|therefore|thus|hence|then|so|thereby)\b", re.I)
def _en_pat(cue):
    """Inflection-tolerant English cue: 'activates' also matches activate/activated/activating."""
    stem = cue[:-1] if cue.endswith(("s", "e")) else cue
    return re.escape(stem) + r"(?:s|es|e|ed|ing|ion)?"


CUE = sorted([(_en_pat(c), t, 0, c) for t, r in R.items() for c in r["en"].split()] +
             [(re.escape(c), t, 0, c) for t, r in R.items() for c in r["zh"].split()] +
             [(c, t, 1, c) for t, r in R.items() for c in r["pz"].split()], key=lambda x: -len(x[0]))
def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
def ky(s):
    return re.sub(r"^(the|a|an)\s+", "", re.sub(r"\s+", " ", (s or "").strip().lower())).strip()
def tw(s, z):
    return z * sum(1.0 if CJK.match(c) else (0.28 if c == " " else (0.58 if c.isupper() or c.isdigit() else 0.52))
                   for c in (s or ""))
def rgb(c):
    c = (c or "#000000").lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
def norm(t):
    ch, ln, st, p = list(t or ""), (t or "").split("\n"), [], 0
    for x in ln:
        st.append(p); p += len(x) + 1
    for i, x in enumerate(ln):
        for j, c in enumerate(x):
            if c in "#>*_`":
                ch[st[i] + j] = " "
        if i + 1 < len(ln) and x.strip() and ln[i + 1].strip() \
                and not x.rstrip().endswith((".!?。！？:：",)) \
                and not ln[i + 1].lstrip().startswith(("#", ">", "-", "|")) and not x.rstrip().endswith("-"):
            ch[st[i] + len(x)] = " "
    return "".join(ch)
def lmap(t):
    st, p = [], 0
    for x in (t or "").split("\n"):
        st.append(p); p += len(x) + 1
    def of(i):
        lo, hi = 0, len(st) - 1
        while lo < hi:
            m = (lo + hi + 1) // 2
            lo, hi = (m, hi) if st[m] <= i else (lo, m - 1)
        return lo + 1
    return of
def sents(t):
    out = []
    for m in SENT.finditer(t or ""):
        aw, s = m.group(0), m.group(0).strip()
        if s:
            k = len(aw) - len(aw.lstrip())
            out.append((s, m.start() + k, m.start() + k + len(s)))
    return out
def ok(tk, hint=""):
    low = tk.lower()
    if low in CLASS_EN:
        return False
    if len(tk) < 2 or tk.isdigit() or low.replace("-", " ") in REJ:
        return False
    if low in ALIAS:
        return True
    if CJK.search(tk):
        f = tk.replace(" ", "")
        if f in REJZ or any(v in f for v in ("诱导", "促进", "激活", "抑制", "磷酸化", "泛素化",
                                             "降解", "结合", "调控", "表达", "转录")):
            return False                      # a clause or a class word, not an entity name
        if len(f) <= 3 and f.endswith(("酶", "体", "物", "因")):
            return False                      # fragment left over from a phrase
        return any(f == p or f.endswith(p) for p in PH) or any(f.endswith(x) for x in SUF)
    if tk.isupper() and tk in ("EXAMPLE", "ONLY", "NOTE", "PDF", "PNG", "SVG", "SKILL", "TASK"):
        return False
    return bool(re.fullmatch(r"[A-Z]{2,}[0-9]*", tk) or (re.search(r"\d", tk) and re.search(r"[A-Za-z]", tk))
                or re.search(r"[a-z][A-Z]", tk) or hint)
def czh(t):
    p = [x for x in re.split("(?:促进|抑制|激活|诱导|转运|降解|结合|识别|调控|表达|分泌|释放|翻译|介导)", t) if x]
    p = re.split("[的和与及或由被后是了在为对于从至到也并而则使将把受所·\\s]+", p[-1] if p else t)
    return next((x for x in reversed(p) if x), t)
def cls(t, a, b):
    af = re.sub(r"^\s*[,\u2014-]\s*", "", t[b: b + 24]).lower()
    hd = t[max(0, a - 24): a].lower()
    for nm, pat in (("complex", "complex|dimer|复合物|二聚体"), ("gene", "gene|locus|基因"),
                    ("protein", "kinase|receptor|protein|激酶|受体|蛋白|酶")):
        if re.match("(?:%s)" % pat, af) or re.search("(?:%s)\\s*$" % pat, hd):
            return nm
    for s, ty in sorted(SUF.items(), key=lambda kv: -len(kv[0])):
        if af.lstrip().startswith(s):
            return ty
    return ""
def typ(sf, sent, hint, t, a, b):
    low = sf.lower()
    tail = re.sub(r"^\s*[,\u2014-]\s*", "", t[b: b + 140]).lower()
    bef = re.split("[,;.]", t[max(0, a - 60): a])[-1].lower()
    role = ("tf" if re.search("transcription factor|转录因子", tail + bef) else
            "receptor" if re.search("transmembrane|receptor tyrosine kinase|跨膜受体", tail) else
            "kinase" if re.search("kinase|phosphorylates|激酶|磷酸化", tail + bef) else "")
    if any(low == p or low.endswith(p) for p in PH):
        return "phenotype", ""
    if any(w in low for w in ("inhibitor", "agonist", "antagonist", "抑制剂", "激动剂")) or \
            low in ("erlotinib", "gefitinib", "imatinib", "rapamycin", "tamoxifen"):
        return "drug", ""
    if hint in TYP:
        return hint, role
    if role:
        return "protein", role
    c = sent.lower()
    g = sum(c.count(x) for x in ("gene", "mrna", "transcript", "promoter", "基因", "敲除"))
    p = sum(c.count(x) for x in ("protein", "kinase", "phosphorylat", "activity", "蛋白", "激酶", "磷酸化"))
    return ("gene" if g > p else "protein"), role
def extract(raw, src):
    t, lof = norm(raw), lmap(raw)
    ss = sents(t)
    ms, seen, order = [], {}, []
    for m in TOK.finditer(t):
        sf, a, b = m.group(1), m.start(1), m.end(1)
        hint = cls(t, a, b)
        if CJK.search(sf):
            sf = czh(sf)
            f = sf.replace(" ", "")
            if any(f == p or f.endswith(p) for p in PH):
                hint = "phenotype"
        if not ok(sf, hint):
            continue
        sn = next((x for x in ss if x[1] <= a <= x[2]), None)
        sent = sn[0] if sn else t[max(0, a - 80): b + 80]
        k = ky(sf)
        rec = seen.get(k) or seen.get(ky(ALIAS.get(k, "")))
        if rec:
            rec["surfaces"].append(sf); seen[k] = rec
        else:
            et, role = typ(sf, sent, hint, t, a, b)
            rec = {"id": "", "key": ky(sf), "canonical": sf, "label": sf, "surfaces": [sf], "type": et,
                   "role": role, "italic": et == "gene", "compartment": "", "compartment_source": "",
                   "ambiguous": et == "protein" and not hint, "count": 0, "first": (a, b), "data": {},
                   "data_source": "", "evidence": []}
            seen[k] = seen[rec["key"]] = rec; order.append(rec)
        rec["count"] += 1
        if len(rec["evidence"]) < 2:
            rec["evidence"].append({"source": src, "locator": "%s#L%d" % (src, lof(a)),
                                    "quote": sent.strip()[:260], "span": [a, b]})
        ms.append({"surface": sf, "start": a, "end": b, "entity_key": rec["key"], "line": lof(a)})
    uniq = sorted(order, key=lambda r: (-r["count"], r["first"][0]))[:40]
    uniq.sort(key=lambda r: r["first"][0])
    im = {}
    for i, r in enumerate(uniq, 1):
        r["id"] = "E%02d" % i; im[r["key"]] = r["id"]
    for m in ms:
        m["entity_id"] = im.get(m["entity_key"], "")
    return t, {"entities": uniq, "mentions": ms, "sentences": ss, "line_of": lof}
def compw(w):
    w = (w or "").lower()
    for cid, ks in (("plasma_membrane", "membrane 膜"), ("nucleus", "nucleus nuclear 核"),
                    ("cytosol", "cytosol cytoplasm 胞质 细胞质"), ("extracellular", "extracellular secreted 细胞外")):
        if any(k in w for k in ks.split()):
            return cid
    return ""
def setcmp(ents, t, ss):
    for e in ents:
        a, role = e["first"][0], e.get("role")
        m = re.search(r"(extracellular|secreted|nuclear|cytosolic|membrane-bound)\s+(?:the\s+)?$",
                      t[max(0, a - 20): a], re.I)
        comp = compw(m.group(1)) if m else ""
        if not comp:
            for s in ss:
                if s[1] <= a <= s[2]:
                    mm = LOC.search(s[0]) or LOCZ.search(s[0])
                    comp = compw(mm.group(1)) if mm else ""
                    break
        e["compartment"], e["compartment_source"] = (
            ("plasma_membrane", "role: transmembrane receptor") if role == "receptor" else
            ("extracellular", "drug acts from outside") if e["type"] == "drug" else
            (comp, "explicit localisation phrase") if comp else
            ("nucleus", "role: transcription factor") if role == "tf" else
            ({"gene": "nucleus", "protein": "cytosol", "complex": "cytosol", "phenotype": "outcome",
              "drug": "extracellular"}.get(e["type"], "cytosol"), "type default"))
    return ents
def bnd(s, a, b):
    return (max([i + 1 for i in range(a) if s[i] in CL] + [0]),
            min([i for i in range(b, len(s)) if s[i] in CL] + [len(s)]))
def pk(ms, pos, side, lo=None, hi=None):
    c = [m for m in ms if m["entity_id"] and (lo is None or m["start"] >= lo) and (hi is None or m["end"] <= hi)
         and ((m["end"] <= pos) if side == "before" else (m["start"] >= pos))]
    if not c:
        return None
    m = min(c, key=lambda x: (pos - x["end"]) if side == "before" else (x["start"] - pos))
    return m if ((pos - m["end"]) if side == "before" else (m["start"] - pos)) <= 120 else None
def pm(ms, pos):
    c = [m for m in ms if m["entity_id"] and m["end"] <= pos]
    return min(c, key=lambda m: pos - m["end"]) if c else None
def lt(ms, pos, by, ty):
    c = [m for m in ms if m["end"] <= pos and (by.get(m.get("entity_id")) or {}).get("type") == ty]
    return min(c, key=lambda m: pos - m["end"]) if c else None
def ng(s, a):
    """Clause-local negation. ASCII markers need word boundaries, CJK markers must not use \\b
    (Python counts CJK as word characters, so \\b不 never matches inside 缺氧并不激活)."""
    lo = max([i + 1 for i in range(max(0, a - 34), a) if s[i] in CL] + [max(0, a - 34)])
    win = s[lo:a]
    for c in NEG:
        if CJK.search(c):
            if c in win:
                return c
        elif re.search(r"\b%s\b" % re.escape(c), win, re.I):
            return c
    return ""
def stre(s):
    return "strong" if any(c in s for c in STRONG) else ("weak" if any(c.lower() in s.lower() for c in WEAK) else "moderate")
def rels(t, src, an, ents):
    by = {e["id"]: e for e in ents}
    E, X, U = [], [], []
    for s, s0, _ in an["sentences"]:
        ms = [dict(m) for m in an["mentions"] if s0 <= m["start"] and m["end"] <= s0 + len(s)]
        if not ms:
            continue
        used = []
        for pat, tn, passive, cue in CUE:
            for m in re.finditer(pat, s, re.I):
                cs, ce = s0 + m.start(), s0 + m.end()
                if any(cs < u1 and ce > u0 for u0, u1 in used):
                    continue
                if CJK.search(m.group(0)) and s[m.end():m.end() + 1] == "的":
                    used.append((cs, ce)); continue
                clo, chi = bnd(s, m.start(), m.end())
                lo, hi = s0 + clo, s0 + chi
                bad = ng(s, m.start())
                if PAIR.match(m.group(0)):
                    sj, oj = pm(ms, cs), pk(ms, cs, "after", lo, hi)
                elif passive:
                    zb, bm = ZBY.search(s, clo, m.start()), re.search(r"\bby\b", s[m.end():m.end() + 30], re.I)
                    bf = pk(ms, cs, "before", lo, hi) or pm(ms, cs)
                    if ZBY.match(m.group(0)):
                        sj, oj = pk(ms, cs, "after", lo, hi), bf
                    elif bm:
                        sj, oj = pk(ms, s0 + m.end() + bm.end(), "after", lo, hi), bf
                    elif zb:
                        sj = pk(ms, s0 + zb.end(), "after", lo, hi)
                        oj = pk(ms, s0 + zb.start(), "before", lo, hi) or bf
                    else:
                        sj, oj = pm(ms, cs), bf
                else:
                    sj, oj = pk(ms, cs, "before", lo, hi), pk(ms, ce, "after", lo, hi)
                    win = s[max(0, m.start() - 80): m.start()]
                    if "复合物" in win and PRO.search(win):
                        sj = lt(an["mentions"], cs, by, "complex") or sj
                    if sj is None:
                        sj = pk(ms, cs, "before") or (lt(an["mentions"], cs, by, "complex")
                                                      if PRO.search(win) else pm(ms, cs))
                    if oj is None:
                        gap = s[m.end(): chi]
                        if any(c in gap for c in CZ) or CE.search(gap):
                            oj = pk(ms, ce, "after") or (pm(ms, cs) if PRO.search(gap) else None)
                    elif sj is not None:
                        gap = s[clo:m.start()]
                        if any(c in gap for c in CZ) or CE.search(gap):
                            f = min([x for x in ms if x["entity_id"]], key=lambda x: x["start"], default=None)
                            if f and f["entity_id"] != oj["entity_id"]:
                                sj = f
                used.append((cs, ce))
                loc = "%s#L%d" % (src, an["line_of"](cs))
                if not sj or not oj or sj["entity_id"] == oj["entity_id"]:
                    fb_s = sj or pk(ms, cs, "before", lo, hi) or pm(ms, cs)
                    fb_t = oj or pk(ms, ce, "after", lo, hi)
                    if fb_s is not None and fb_t is not None and \
                            fb_s.get("entity_id") == fb_t.get("entity_id"):
                        fb_t = None                     # do not record a self loop
                    r = {"sentence": s.strip()[:190], "cue": cue, "type": tn,
                         "source": (fb_s or {}).get("entity_id", ""),
                         "target": (fb_t or {}).get("entity_id", ""),
                         "locator": loc, "why": "could not resolve both arguments to known entities"}
                    if bad:
                        r["removed_because"] = "negated by '%s'" % bad
                        r["evidence"] = [{"source": src, "locator": loc, "quote": s.strip()[:260]}]
                    (X if bad else U).append(r)
                    continue
                rl = R[tn]
                downgraded = ""
                if (SEM.get("edge_types", {}).get(tn, {}).get("requires_direction")
                        and not direction_stated(s)):
                    downgraded = tn
                    tn, rl = "unspecified", R["unspecified"]
                e = {"source": sj["entity_id"], "target": oj["entity_id"], "type": tn, "label": "",
                     "line": rl["line"], "arrow": rl["arrow"], "color": rl["col"], "strength": stre(s),
                     "feedback": bool(re.search("feedback|反馈", s)),
                     "modification_tag": next((v for k, v in (("phosphorylat", "P"), ("ubiquitinat", "Ub"),
                                                              ("methylat", "Me"), ("acetyl", "Ac"),
                                                              ("磷酸化", "P"), ("泛素化", "Ub"), ("羟化", "OH"))
                                               if k in cue.lower()), ""),
                     "origin": "cue '%s'%s%s" % (cue, " (passive)" if passive else "",
                                                 " downgraded from '%s' (no direction stated)" % downgraded
                                                 if downgraded else ""),
                     "downgraded_from": downgraded,
                     "uncertainty": ("direction not stated in the source: drawn as an undirected "
                                     "dashed edge" if downgraded else ""),
                     "evidence": [{"source": src, "locator": loc, "quote": s.strip()[:260]}], "uncertainty": ""}
                if bad:
                    X.append(dict(e, removed_because="negated by '%s'" % bad))
                else:
                    E.append(e)
    out, seen = [], {}
    for e in E:
        k = (e["source"], e["target"], e["type"])
        if k in seen:
            seen[k]["evidence"] += e["evidence"]
        else:
            seen[k] = e; out.append(e)
    for i, e in enumerate(out, 1):
        e["id"] = "R%02d" % i
    for i, e in enumerate(X, 1):
        e["id"] = "X%02d" % i
    return out, X, U
def comp_targets(spec, src):
    keep, have = [], {(e.get("source"), e.get("target"), e.get("type")) for e in spec["edges"]}
    by = {ky(e.get("canonical") or ""): e["id"] for e in spec["entities"]}
    for u in spec["unresolved"]:
        mm = (LOC.search(u.get("sentence") or "") or LOCZ.search(u.get("sentence") or "")) \
            if u.get("type") == "transports" and u.get("source") else None
        cid = compw(mm.group(1)) if mm else ""
        if not cid:
            keep.append(u); continue
        lab, kk = next((c[1] for c in CMP if c[0] == cid), cid), "compartment:" + cid
        eid = by.get(kk)
        if not eid:
            eid = "E%02d" % (len(spec["entities"]) + 1)
            spec["entities"].append({"id": eid, "key": kk, "canonical": lab, "label": lab, "surfaces": [lab],
                                     "type": "compartment", "role": "", "italic": False, "compartment": cid,
                                     "compartment_source": "compartment target of a transport statement",
                                     "ambiguous": False, "count": 1, "first": (0, 0), "data": {},
                                     "evidence": [{"source": src, "locator": u.get("locator", ""),
                                                   "quote": (u.get("sentence") or "")[:260]}]})
            by[kk] = eid
        if (u["source"], eid, "transports") in have:
            continue
        have.add((u["source"], eid, "transports"))
        rl = R["transports"]
        spec["edges"].append({"id": "R%02d" % (len(spec["edges"]) + 1), "source": u["source"], "target": eid,
                              "type": "transports", "label": "translocation", "line": rl["line"],
                              "arrow": rl["arrow"], "color": rl["col"], "strength": "moderate",
                              "feedback": False, "modification_tag": "",
                              "origin": "transport cue '%s' with a compartment object" % u.get("cue"),
                              "evidence": [{"source": src, "locator": u.get("locator", ""),
                                            "quote": (u.get("sentence") or "")[:260]}],
                              "uncertainty": "target is a compartment, not a molecule"})
    spec["unresolved"] = keep
def geometry_checks(spec, lay, svg_text, out_dir):
    """Machine-readable figure audit: read the drawn SVG back and compare it with the model.

    Named checks follow the convention of the reference bio-pathway skill so two figures can be
    diffed mechanically: svg_readback_*, svg_layers, legend_covers_used_types,
    legend_no_phantom_entries, label_overflow, canvas_limits, direction_stated_when_required,
    head_style_matches_semantics, exports_exist, result_contract_nulls_explained.
    Written to fig.checks.json and copied into result.json.compliance_checks.geometry.
    """
    import re as _re
    C, E, W = [], [], []

    def chk(name, ok, detail, level="error"):
        C.append({"check": name, "passed": bool(ok), "level": level, "detail": detail})
        if not ok:
            (E if level == "error" else W).append("%s: %s" % (name, detail))

    svg_ids = set(_re.findall(r'id="(E\d+)"', svg_text)) | set(_re.findall(r'id="(R\d+)"', svg_text))
    nodes = {e["id"] for e in spec["entities"]}
    edges = {e["id"] for e in spec["edges"]}
    chk("svg_readback_nodes", nodes <= svg_ids,
        "%d entities -> %d matched%s" % (len(nodes), len(nodes & svg_ids),
                                         "" if nodes <= svg_ids else "; missing %s" % sorted(nodes - svg_ids)))
    chk("svg_readback_edges", edges <= svg_ids,
        "%d edges -> %d matched%s" % (len(edges), len(edges & svg_ids),
                                      "" if edges <= svg_ids else "; missing %s" % sorted(edges - svg_ids)))
    layers = set(_re.findall(r'id="layer-([a-z]+)"', svg_text))
    need = {"compartments", "edges", "nodes", "legend"}
    chk("svg_layers", need <= layers, "layers found: %s" % sorted(layers))
    used_e = {e["type"] for e in spec["edges"]}
    used_n = {e["type"] for e in spec["entities"]}
    legend = svg_text.split('id="layer-legend"')[-1] if 'id="layer-legend"' in svg_text else ""
    keys = set(_re.findall(r'data-key="(node|edge)-([a-z_]+)"', legend))
    missing = [t for t in used_e if ("edge", t) not in keys]
    missing += [t for t in used_n if ("node", t) not in keys]
    chk("legend_covers_used_types", not missing,
        "legend covers %d edge and %d node types%s" % (len(used_e), len(used_n),
                                                       "" if not missing else "; missing %s" % missing))
    phantom = [t for t in R if ("edge", t) in keys and t not in used_e]
    chk("legend_no_phantom_entries", not phantom,
        "; ".join(phantom) or "no legend entry for an unused edge type", level="warning")
    overflow = [{"node": e["id"], "label": e["label"]}
                for e in lay["ents"] if max(tw(l, e["font"]) for l in e["lines"]) > e["w"] - 8]
    chk("label_overflow", not overflow, "%d labels wider than their boxes%s"
        % (len(overflow), "" if not overflow else ": %s" % overflow[:4]))
    cv = lay["cv"]
    chk("canvas_limits", cv["w"] <= 2400 and cv["h"] <= 1800,
        "canvas %dx%d (recommended max 2400x1800)" % (cv["w"], cv["h"]), level="warning")
    bad_dir = [e.get("id") for e in spec["edges"]
               if SEM.get("edge_types", {}).get(e["type"], {}).get("requires_direction")
               and not any(direction_stated((ev or {}).get("quote")) for ev in e.get("evidence") or [])]
    chk("direction_stated_when_required", not bad_dir,
        "%d edge(s) claiming a direction the quote does not state: %s" % (len(bad_dir), bad_dir))
    mism = [e.get("id") for e in spec["edges"]
            if (e.get("arrow"), e.get("line")) != (R[e["type"]]["arrow"], R[e["type"]]["line"])]
    chk("head_style_matches_semantics", not mism,
        "%d edge(s) whose drawn head/line differ from arrow-semantics.json: %s" % (len(mism), mism))
    files = [f for f in ("figure.svg", "result.json", "spec.json", "check-report.json",
                         "fig.checks.json") if os.path.exists(os.path.join(out_dir, f))]
    chk("exports_exist", "figure.svg" in files and "check-report.json" in files,
        "artefacts written before this report: %s (result.json follows)" % files)
    return {"passed": not E, "checks": C, "errors": E, "warnings": W,
            "canvas": {"width_px": cv["w"], "height_px": cv["h"]},
            "counts": {"entities": len(nodes), "edges": len(edges),
                       "edge_types": sorted(used_e), "node_types": sorted(used_n)},
            "semantics_version": SEM.get("version", "unknown")}


def checks(spec, lay):
    return _V.checks(spec, lay)


def contract_of(case):
    found = {}

    def walk(n, d=0):
        if d > 6 or not isinstance(n, (dict, list)):
            return
        items = n.items() if isinstance(n, dict) else [(None, x) for x in n]
        for k, v in items:
            if isinstance(k, str) and k.lower() in ("output_contract", "contract", "schema", "outputs") \
                    and isinstance(v, (dict, list)):
                src = list(v.items()) if isinstance(v, dict) else \
                    [(x.get("name"), x.get("description") or "") for x in v if isinstance(x, dict)]
                if isinstance(v, dict) and isinstance(v.get("properties"), dict):
                    src = list(v["properties"].items())
                for name, desc in src:
                    if isinstance(name, str):
                        found.setdefault(name, desc if isinstance(desc, str) else "")
            elif isinstance(v, (dict, list)):
                walk(v, d + 1)
    walk(case)
    return found


def echo(name, res):
    low, groups = name.lower(), (
        (("svg", "pdf", "png", "figure", "path", "file", "image", "preview"), lambda: [d["path"] for d in res["deliverables"]]),
        (("entit", "node", "gene"), lambda: res["entities"]),
        (("edge", "relation", "interaction", "arrow"), lambda: res["edges"]),
        (("legend", "encoding", "color", "mapping"), lambda: res["legend"]),
        (("source", "evidence", "provenance"), lambda: res["sources"]),
        (("uncertain", "limitation", "risk"), lambda: res["uncertainty"]),
        (("summary", "notes"), lambda: res["summary"]),
        (("status",), lambda: res["status"]),
        (("check", "valid", "qc", "audit", "verif"), lambda: {"ok": res["checks"]["ok"]}))
    for keys, fn in groups:
        if any(k in low for k in keys):
            return fn()
    return ""


def resolve_path(rel, case_dir, input_dir=""):
    """case.json dir -> cwd -> --input -> /input. Never keyed on absolute path segments: the
    evaluator's own paths (/app/output, …/stage/outputs) contain names that must not hide input."""
    if not rel:
        return "", ""
    if os.path.isabs(rel):
        return rel, "absolute"
    for base, tag in ((case_dir, "case_dir"), (os.getcwd(), "cwd"), (input_dir, "input_dir"),
                      ("/input", "/input")):
        if base and os.path.isfile(os.path.join(base, rel)):
            return os.path.join(base, rel), tag
    return os.path.join(case_dir or ".", rel), "missing"


def gather(case, cp, idir):
    import glob
    cand, res_from = [], {}
    case_dir = os.path.dirname(os.path.abspath(cp)) if cp else ""
    for k in ("materials", "files", "documents", "sources", "inputs", "attachments", "text"):
        v = case.get(k)
        for x in ([v] if isinstance(v, str) else (v if isinstance(v, list) else [])):
            if not isinstance(x, str):
                continue
            p, frm = resolve_path(x, case_dir, idir)
            res_from[os.path.realpath(p)] = frm
            cand.append(p)
    if os.path.isdir(idir):
        for ext in (".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".pdf", ".docx", ".html"):
            cand += sorted(glob.glob(os.path.join(idir, "**", "*" + ext), recursive=True))
    skip = {"case.json", "result.json", "spec.json", "check-report.json", "pathway.json",
            "result.example.json", "pathway.example.json"}
    mats, seen = [], set()
    for p in cand:
        b = os.path.basename(p)
        if not p or not os.path.isfile(p) or b in skip or b.lower().startswith(("readme", "figure.", "pathway.")):
            continue
        if os.path.realpath(p) in seen:
            continue
        seen.add(os.path.realpath(p))
        scan_tag = ("case_dir_scan"
                    if idir and os.path.normcase(os.path.realpath(idir)) == os.path.normcase(
                        os.path.realpath(os.path.dirname(os.path.abspath(cp)) if cp else idir))
                    else "input_scan")
        m = {"id": "mat%02d" % (len(mats) + 1), "path": b, "kind": os.path.splitext(b)[1].lstrip("."),
             "resolved_from": res_from.get(os.path.realpath(p), scan_tag),
             "text": "", "tables": [], "notes": []}
        try:
            if m["kind"] == "pdf":
                import fitz
                doc = fitz.open(p); m["text"] = "\n".join(pg.get_text() for pg in doc); doc.close()
            elif m["kind"] == "docx":
                import zipfile
                m["text"] = re.sub("<[^>]+>", " ", zipfile.ZipFile(p).read("word/document.xml")
                                   .decode("utf-8", "replace"))
            else:
                m["text"] = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            m["notes"].append("not readable")
        if m["kind"] in ("csv", "tsv") and m["text"]:
            rows = [r for r in csv.reader(io.StringIO(m["text"]),
                                          delimiter="\t" if m["kind"] == "tsv" else ",") if any(x.strip() for x in r)]
            if len(rows) >= 2:
                hd = [h.strip() for h in rows[0]]
                m["tables"] = [{"header": hd,
                                "rows": [dict(zip(hd, r + [""] * (len(hd) - len(r)))) for r in rows[1:]]}]
        mats.append(m)
    return mats
def main(argv=None):
    ap = argparse.ArgumentParser(description="mechanism/pathway figure pipeline (compact)")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--input", default="")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    cp = a.case if os.path.isfile(a.case) else ""
    case = {}
    if cp:
        try:
            case = json.load(open(cp, encoding="utf-8"))
        except Exception:
            case = {}
    idir = a.input or (os.path.dirname(os.path.abspath(cp)) if cp else "/input")
    os.makedirs(a.out, exist_ok=True)
    mats = gather(case, cp, idir)
    src = mats[0]["id"] if mats else "case"
    figh = case.get("figure") if isinstance(case.get("figure"), dict) else {}
    spec = {"case_id": str(case.get("case_id") or case.get("id")
                           or os.path.splitext(os.path.basename(cp))[0] or "case"),
            "figure": {"title": figh.get("title") or case.get("title") or "", "dpi": a.dpi},
            "entities": [], "edges": [], "excluded": [], "unresolved": [],
            "sources": [{"id": m["id"], "path": m["path"], "kind": m["kind"], "notes": m["notes"],
                         "resolved_from": m.get("resolved_from")} for m in mats],
            "materials_resolution": [{"path": m["path"], "resolved_from": m.get("resolved_from"),
                                      "kind": m["kind"], "chars": len(m.get("text") or "")} for m in mats]}
    prose = "\n\n".join(m["text"] for m in mats
                        if m["kind"] in ("md", "txt", "tex", "pdf", "docx", "html"))
    if prose.strip():
        t, an = extract(prose, src)
        spec["entities"] = setcmp(an["entities"], t, an["sentences"])
        spec["edges"], spec["excluded"], spec["unresolved"] = rels(t, src, an, spec["entities"])
    comp_targets(spec, src)
    matched = 0
    for m in mats:
        for tb in m["tables"]:
            lc = next((h for h in tb["header"] if h.strip().lower() in
                       ("entity", "name", "label", "gene", "protein", "symbol", "id")), tb["header"][0])
            for row in tb["rows"]:
                lab, keys = (row.get(lc) or "").strip(), None
                for e in spec["entities"]:
                    if ky(lab) in [ky(e["canonical"])] + [ky(s) for s in e["surfaces"]]:
                        vals = {}
                        for h, v in row.items():
                            if h != lc:
                                try:
                                    vals[h] = float(str(v).replace(",", ""))
                                except ValueError:
                                    pass
                        if vals:
                            e["data"], e["data_source"] = vals, "%s#%s=%s" % (m["id"], lc, lab)
                            e["evidence"].append({"source": m["id"], "locator": e["data_source"],
                                                  "quote": json.dumps(row, ensure_ascii=False)[:200]})
                            matched += 1
                        break
    if not spec["figure"]["title"] and mats and mats[0]["text"]:
        spec["figure"]["title"] = re.split(r"[.\n。]", mats[0]["text"].strip())[0][:110]
    lay = layout(spec)
    meta = json.dumps({"case_id": spec["case_id"], "entities": [e["id"] for e in spec["entities"]],
                       "edges": [e.get("id") for e in spec["edges"]]}, ensure_ascii=False)
    svg_path = os.path.join(a.out, "figure.svg")
    svg_text = svg(spec, lay, meta)
    open(svg_path, "w", encoding="utf-8", newline="\n").write(svg_text)
    backend = png(spec, lay, os.path.join(a.out, "figure.png"), a.dpi)   # vector-only arm
    rep = checks(spec, lay)
    json.dump(rep, open(os.path.join(a.out, "check-report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    geo = geometry_checks(spec, lay, svg_text, a.out)
    json.dump(geo, open(os.path.join(a.out, "fig.checks.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(spec, open(os.path.join(a.out, "spec.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    n_prim = sum(len(v) for v in lay.get("bands", [])) + 2 * len(lay.get("ents", [])) + 2 * len(lay.get("edges", []))
    if not spec["entities"] and not mats:
        st, why = "failed", "no readable material: nothing to derive a figure from"
    elif not spec["entities"]:
        st = "partial"
        why = ("material was read (%d file(s), %d chars) but no biological entity could be extracted: "
               "the figure stays empty on purpose rather than invented" %
               (len(mats), sum(len(m.get("text") or "") for m in mats)))
    elif n_prim <= 4:
        st, why = "partial", "the scene contains only %d primitive(s): nothing was drawn" % n_prim
    elif not rep["ok"]:
        st = "partial"
        why = "%d blocking check(s): %s" % (len(rep["errors"]), ", ".join(rep["errors"]))
    else:
        st = "success"
        why = ("%d/%d checks pass, %d advisory warning(s)"
               % (rep["n_checks"], rep["n_checks"], rep["n_warnings"]))
    res = {"case_id": spec["case_id"], "task": "biological mechanism / pathway figure", "status": st,
           "status_reason": why,
           "summary": "%d entities, %d edges, %d excluded, %d unresolved -> SVG + PNG + result.json"
                      % (len(spec["entities"]), len(spec["edges"]), len(spec["excluded"]), len(spec["unresolved"])),
           "figure": spec["figure"],
           "deliverables": [{"kind": "editable_source", "format": "svg", "path": "figure.svg", "editable": True},
                            {"kind": "preview", "format": "svg", "path": "figure.svg",
                             "editable": True, "note": "vector preview; no raster in this arm"}],
           "entities": spec["entities"], "edges": spec["edges"], "excluded_relations": spec["excluded"],
           "unresolved_statements": spec["unresolved"],
           "legend": [{"token": t, "channel": "shape", "meaning": TYP[t][0]}
                      for t in sorted({e["type"] for e in spec["entities"]})] +
                     [{"token": t, "channel": "arrow", "meaning": R[t]["lab"],
                       "sample": R[t]["arrow"] + "/" + R[t]["line"]}
                      for t in sorted({e["type"] for e in spec["edges"]})] +
                     [{"token": w, "channel": "line-width", "meaning": w, "sample": "width=%s" % WID[w]}
                      for w in sorted({e.get("strength", "moderate") for e in spec["edges"]})],
           "data_encoding": {"rows_matched": matched}, "sources": spec["sources"],
           "materials_resolution": spec.get("materials_resolution") or [],
           "evidence": [dict(ev, what="entity %s" % e["id"]) for e in spec["entities"]
                        for ev in e["evidence"]][:200],
           "change_log": [{"what": "materials", "detail": ", ".join(m["path"] for m in mats)},
                          {"what": "graph", "detail": "%d entities / %d edges"
                           % (len(spec["entities"]), len(spec["edges"]))}],
           "checks": rep,
           "compliance_checks": {"geometry": geo,
                                 "semantics": {"table": "references/arrow-semantics.json",
                                               "version": SEM.get("version", "unknown"),
                                               "undirected_rendering":
                                                   "dashed line, no arrowhead, '?' annotation"}},
           "exports": {"svg": {"path": "figure.svg", "bytes": os.path.getsize(svg_path)},
                       "raster": {"produced": False, "backend": backend,
                                  "why": "this arm ships the editable SVG as its preview; the full "
                                         "package adds PNG/PDF export"}},
           "uncertainty": [{"item": "%s: gene or protein" % e["canonical"], "why": "context does not decide",
                            "handling": "drawn as %s" % e["type"]} for e in spec["entities"] if e["ambiguous"]]
                          + [{"item": "unresolved statement", "why": u["why"], "locator": u["locator"]}
                             for u in spec["unresolved"][:20]],
           "gaps": ([{"item": "unresolved statements",
                      "why": "%d clause(s) not converted" % len(spec["unresolved"])}]
                    if spec["unresolved"] else []),
           "not_reported": [] if mats else [{"field": "material", "why": "no readable material found"}],
           "metrics": {"n_entities": len(spec["entities"]), "n_edges": len(spec["edges"]),
                       "n_excluded": len(spec["excluded"]), "n_unresolved": len(spec["unresolved"]),
                       "n_checks": rep["n_checks"], "n_errors": rep["n_errors"]},
           "output_contract": contract_of(case), "generated_at": now(),
           "generator": "pathway.py " + VER, "self_scored": False}
    for nm in list(res["output_contract"]):
        if nm not in res:
            res[nm] = echo(nm, res)
    json.dump(res, open(os.path.join(a.out, "result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    if not a.quiet:
        print("case     : %s" % res["case_id"])
        print("entities : %d   edges: %d   excluded: %d   unresolved: %d"
              % (len(spec["entities"]), len(spec["edges"]), len(spec["excluded"]), len(spec["unresolved"])))
        print("checks   : %d run, %d errors, %d warnings"
              % (rep["n_checks"], rep["n_errors"], rep["n_warnings"]))
        print("outputs  : figure.svg figure.png spec.json check-report.json result.json -> %s" % a.out)
        print("status   : %s - %s" % (st, why))
    return 0 if st != "failed" else 2


# ---------------------------------------------------------------- layout / draw / export
def head(kind, tip, ang, size, col):
    tx, ty = tip
    ca, sa = math.cos(ang), math.sin(ang)
    pt = lambda lx, ly: (tx + lx * ca - ly * sa, ty + lx * sa + ly * ca)
    if kind in ("tri", "tri_o"):
        L, W = size * 1.6, size * 0.6
        return [{"op": "poly", "pts": [pt(0, 0), pt(-L, -W), pt(-L, W)], "closed": True,
                 "fill": col if kind == "tri" else "#FFFFFF", "stroke": col, "sw": 0.6}]
    if kind == "tbar":
        return [{"op": "line", "x1": pt(0, -size * .6)[0], "y1": pt(0, -size * .6)[1],
                 "x2": pt(0, size * .6)[0], "y2": pt(0, size * .6)[1], "stroke": col, "sw": size * .55}]
    if kind == "circ":
        cx, cy = pt(-size * .25, 0)
        return [{"op": "circle", "cx": cx, "cy": cy, "r": size * .45, "fill": "#FFFFFF",
                 "stroke": col, "sw": size * .32}]
    if kind == "chev":
        return [{"op": "poly", "pts": [pt(o, 0), pt(o - size * 1.1, -size * .55), pt(o - size * 1.1, size * .55)],
                 "closed": False, "fill": None, "stroke": col, "sw": size * .4} for o in (0.0, -size * 1.1)]
    return []
def prims(spec, lay):
    """Return (bands, membrane, edge_groups, node_groups, legend) primitive lists."""
    cv, mb = lay["cv"], next((b for b in lay["bands"] if b["id"] == "plasma_membrane"), None)
    P = []
    for i, b in enumerate(lay["bands"]):
        P.append({"op": "rect", "x": 40, "y": b["y"], "w": cv["w"] - 80, "h": b["h"], "rx": 6,
                  "fill": ["#F4F8FB", "#FBF6EF", "#F6F4FA", "#F2F8F2", "#F7F7F7"][i % 5],
                  "stroke": "#D7DEE3", "sw": .9})
        P.append({"op": "text", "x": 46, "y": b["y"] + 13, "s": b["label"], "size": 9, "fill": "#5F6B73"})
    M = []
    if mb:
        cy = mb["y"] + mb["h"] / 2
        for dy in (-9, 9):
            M.append({"op": "line", "x1": 40, "y1": cy + dy, "x2": cv["w"] - 40, "y2": cy + dy,
                      "stroke": "#8D6E63", "sw": 2.2})
        M += [{"op": "circle", "cx": 40 + 26 * (i + .5), "cy": cy + dy, "r": 2.6, "fill": "#EFE3DC",
               "stroke": "#8D6E63", "sw": .8} for i in range(int((cv["w"] - 80) / 26)) for dy in (-9, 9)]
    EG = []
    for e in lay["edges"]:
        pts = e.get("points") or []
        if len(pts) < 2:
            continue
        r = R[e["type"]]
        w = WID.get(e.get("strength", "moderate"), 1.9)
        col = e.get("color") or r["col"]
        ang = math.atan2(pts[-1][1] - pts[-2][1], pts[-1][0] - pts[-2][0])
        ln = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]) or 1
        body = pts[:-1] + [(pts[-1][0] - (pts[-1][0] - pts[-2][0]) / ln * w * 1.6,
                            pts[-1][1] - (pts[-1][1] - pts[-2][1]) / ln * w * 1.6)]
        pr = [{"op": "line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1], "stroke": col, "sw": w,
               "dash": DSH.get(r["line"])} for a, b in zip(body, body[1:])]
        pr += head(e.get("arrow") or r["arrow"], pts[-1], ang, w, col)
        if e.get("modification_tag"):
            pr.append({"op": "text", "x": pts[-1][0] - 14, "y": pts[-1][1] + 5, "s": e["modification_tag"],
                       "size": 10, "fill": col})
        if (e.get("arrow") or r["arrow"]) == "none":       # direction not stated: annotate, no head
            mid = pts[len(pts) // 2]
            pr.append({"op": "text", "x": mid[0], "y": mid[1] - 5, "s": "?", "size": 12, "fill": col,
                       "anchor": "middle"})
        EG.append((e, pr))
    NG = []
    for e in lay["ents"]:
        ts = TYP.get(e["type"], TYP["protein"])
        pr = []
        if e.get("role") == "receptor" and mb:
            cy = mb["y"] + mb["h"] / 2
            top, bot = min(e["y"], cy - 7.5), max(e["y"] + e["h"], cy + 7.5)
            pr.append({"op": "rect", "x": e["x"], "y": top, "w": e["w"], "h": cy - 7.5 - top, "rx": 8,
                       "fill": ts[1], "stroke": ts[2], "sw": 1.3})
            pr.append({"op": "rect", "x": e["x"], "y": cy + 7.5, "w": e["w"], "h": bot - cy - 7.5, "rx": 8,
                       "fill": ts[1], "stroke": ts[2], "sw": 1.3})
            pr.append({"op": "rect", "x": e["x"] + e["w"] * .18, "y": cy - 8, "w": e["w"] * .64, "h": 16,
                       "fill": "#EAE0DA", "stroke": ts[2], "sw": 1.1})
        else:
            pr.append({"op": "rect", "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"],
                       "rx": e["h"] / 2 if e["type"] == "phenotype" else 9,
                       "fill": ts[1], "stroke": ts[2], "sw": 2.2 if e.get("data") else 1.3,
                       "dash": "5 3" if e["type"] == "compartment" else None})
        tot = len(e["lines"]) * (e["font"] + 3.4)
        ty = e["y"] + (e["h"] - tot) / 2 + e["font"]
        pr += [{"op": "text", "x": e["x"] + e["w"] / 2, "y": ty + i * (e["font"] + 3.4), "s": l,
                "size": e["font"], "anchor": "middle", "fill": "#1A1A1A", "italic": e["italic"]}
               for i, l in enumerate(e["lines"])]
        NG.append((e, pr))
    ly, used_e, used_r = cv["ly"], sorted({e["type"] for e in lay["ents"]},
                                          key=lambda t: list(TYP).index(t)), sorted({e["type"] for e in lay["edges"]},
                                                                                    key=lambda t: list(R).index(t))
    L = [{"op": "rect", "x": 40, "y": ly, "w": cv["w"] - 80, "h": 132, "rx": 6, "fill": "#FCFDFE",
          "stroke": "#D7DEE3", "sw": 1},
         {"op": "text", "x": 52, "y": ly + 20, "size": 12,
          "s": "Legend - shape = entity type, arrow = interaction semantics, line width = evidence strength"}]
    for i, t in enumerate(used_e[:6]):
        y = ly + 40 + i * 18
        L.append({"op": "rect", "x": 56, "y": y - 10, "w": 30, "h": 15, "rx": 5, "fill": TYP[t][1],
                  "stroke": TYP[t][2], "sw": 1.2})
        L.append({"op": "text", "x": 94, "y": y + 2, "s": TYP[t][0], "size": 11, "key": "node-" + t})
    for i, t in enumerate(used_r[:6]):
        y = ly + 40 + i * 18
        r = R[t]
        L.append({"op": "line", "x1": 430, "y1": y - 4, "x2": 496, "y2": y - 4, "stroke": r["col"],
                  "sw": 1.9, "dash": DSH.get(r["line"])})
        L += head(r["arrow"], (496, y - 4), 0.0, 1.9, r["col"])
        L.append({"op": "text", "x": 508, "y": y + 2, "s": r["lab"], "size": 11, "key": "edge-" + t})
    if any((e.get("arrow") or "") == "none" for e in lay["edges"]):
        L.append({"op": "text", "x": 52, "y": ly + 92, "size": 10, "fill": "#5F6B73",
                  "s": "no arrowhead / '?' = direction not stated in source (never guessed)"})
    notes = ["%d negated/unsupported claim(s) omitted (excluded[]) - %d statement(s) unresolved"
             % (len(spec.get("excluded") or []), len(spec.get("unresolved") or [])),
             "sources: " + ", ".join(x.get("path", "?") for x in spec.get("sources") or [])]
    L += [{"op": "text", "x": 52, "y": ly + 104 + i * 10, "s": n[:180], "size": 8, "fill": "#5F6B73"}
          for i, n in enumerate(notes)]
    return P, M, EG, NG, L
def svg(spec, lay, meta):
    P, M, EG, NG, L = prims(spec, lay)
    cv = lay["cv"]
    def one(p):
        op, fill, st = p["op"], p.get("fill"), p.get("stroke")
        sty = 'fill="%s"' % (fill or "none")
        if st:
            sty += ' stroke="%s" stroke-width="%g" stroke-linecap="round" stroke-linejoin="round"' % (st, p.get("sw") or 1)
        if p.get("dash"):
            sty += ' stroke-dasharray="%s"' % p["dash"]
        if op == "rect":
            return '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" %s/>' % (
                p["x"], p["y"], p["w"], p["h"], p.get("rx", 0), sty)
        if op == "line":
            return '<line x1="%g" y1="%g" x2="%g" y2="%g" %s/>' % (p["x1"], p["y1"], p["x2"], p["y2"], sty)
        if op == "circle":
            return '<circle cx="%g" cy="%g" r="%g" %s/>' % (p["cx"], p["cy"], p["r"], sty)
        if op == "poly":
            return '<%s points="%s" %s/>' % ("polygon" if p.get("closed", True) else "polyline",
                                             " ".join("%g,%g" % q for q in p["pts"]), sty)
        bits = ['font-size="%g"' % p["size"]]
        if p.get("key"):
            bits.append('data-key="%s"' % p["key"])
        if p.get("anchor"):
            bits.append('text-anchor="%s"' % p["anchor"])
        if p.get("italic"):
            bits.append('font-style="italic"')
        if fill:
            bits.append('fill="%s"' % fill)
        return '<text x="%g" y="%g" %s>%s</text>' % (p["x"], p["y"], " ".join(bits), esc(p["s"]))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="%g" height="%g" viewBox="0 0 %g %g">'
           % (cv["w"], cv["h"], cv["w"], cv["h"]),
           '<title>%s</title>' % esc((spec.get("figure") or {}).get("title") or "mechanism figure"),
           '<desc>Editable layered mechanism figure: layer-compartments, layer-membrane, layer-edges, '
           'layer-nodes, layer-legend. Node groups carry data-entity-id, edge groups data-edge-id.</desc>',
           '<metadata id="q04-spec"><![CDATA[%s]]></metadata>' % meta.replace("]]>", "]]&gt;"),
           '<defs><style type="text/css"><![CDATA[text{font-family:Noto Sans SC,Source Han Sans SC,'
           'Microsoft YaHei,Helvetica,Arial,sans-serif}]]></style></defs>',
           '<rect id="background" width="%g" height="%g" fill="#FFFFFF"/>' % (cv["w"], cv["h"]),
           '<g id="layer-compartments">%s</g>' % "".join(one(p) for p in P),
           '<g id="layer-membrane">%s</g>' % "".join(one(p) for p in M),
           '<g id="layer-edges">%s</g>' % "".join('<g class="edge edge-%s" data-edge-id="%s" data-edge-type="%s">'
                                                  '%s</g>' % (e["type"], e.get("id", ""), e["type"],
                                                              "".join(one(p) for p in pr)) for e, pr in EG),
           '<g id="layer-nodes">%s</g>' % "".join('<g id="%s" class="node %s" data-entity-id="%s">%s</g>'
                                                  % (e["id"], e["type"], e["id"], "".join(one(p) for p in pr))
                                                  for e, pr in NG),
           '<g id="layer-legend">%s</g>' % "".join(one(p) for p in L), "</svg>"]
    return "\n".join(out) + "\n"
def png(spec, lay, path, dpi=300):
    """Not produced by the compact arm: the SVG is the preview. Reported honestly in result.json."""
    return "not_produced"


def layout(spec, W=1240.0):
    """Compartments -> bands, ranks -> columns, membrane straddling, orthogonal edge routes."""
    ents, ed = [dict(e) for e in spec["entities"]], [dict(e) for e in spec["edges"]]
    by = {}
    for e in ents:
        by.setdefault(e.get("compartment") or "cytosol", []).append(e)
    rank = {e["id"]: 0 for e in ents}
    for _ in range(len(ents) + 2):
        ch = 0
        for x in ed:
            s, t = x.get("source"), x.get("target")
            if s in rank and t in rank and not x.get("feedback") and rank[t] <= rank[s]:
                rank[t] = rank[s] + 1
                ch = 1
        if not ch:
            break
    for e in ents:
        e["rank"] = rank[e["id"]]
        z = 11 if e["type"] == "gene" else 13
        lines, cur = [], ""
        for tk in re.findall(r"[\u2e80-\u9fff]|[^\s\u2e80-\u9fff]+|\s+", e["label"]):
            if tw(cur + tk, z) > 132 and cur.strip():
                lines.append(cur.strip())
                cur = tk if not tk.isspace() else ""
            else:
                cur += tk
        lines.append(cur.strip() or e["label"])
        e["font"], e["lines"] = z, lines
        e["w"] = max(56.0, max(tw(l, z) for l in lines) + 22)
        e["h"] = len(lines) * (z + 4) + 16
        if e.get("role") == "receptor":
            e["h"], e["w"] = max(e["h"], 64.0), max(e["w"], 64.0)
    cols, x = [], 52.0
    for r in range(max([e["rank"] for e in ents] + [0]) + 1):
        ws = [e["w"] for e in ents if e["rank"] == r]
        cols.append(x)
        x += (max(ws) if ws else 96.0) + 54.0
    bands, y = [], 50.0
    for cid, lab, _k in CMP:
        g = by.get(cid, [])
        if cid == "plasma_membrane":
            h = max(104.0, max([e["h"] for e in g] + [56.0]) + 40)
        else:
            st = {}
            for e in g:
                st.setdefault(e["rank"], []).append(e["h"])
            h = max(78.0, max([sum(v) + 20 * (len(v) - 1) for v in st.values()] + [0.0]) + 42)
        bands.append({"id": cid, "label": lab, "y": y, "h": h})
        y += h + 10
    H = max(760.0, y + 180)
    for bd in bands:
        g = by.get(bd["id"], [])
        if bd["id"] == "plasma_membrane":
            cur = -1e9
            for e in sorted(g, key=lambda e: (e["rank"], e["id"])):
                e["x"] = max(cols[min(e["rank"], len(cols) - 1)], cur + 8)
                e["y"] = bd["y"] + bd["h"] / 2 - e["h"] / 2
                cur = e["x"] + e["w"]
            continue
        st = {}
        for e in g:
            st.setdefault(e["rank"], []).append(e)
        for r, gg in st.items():
            gg.sort(key=lambda e: e["id"])
            tot = sum(e["h"] for e in gg) + 20 * (len(gg) - 1)
            cy = bd["y"] + max(22.0, (bd["h"] - tot) / 2)
            for e in gg:
                e["x"], e["y"] = cols[min(r, len(cols) - 1)], cy
                cy += e["h"] + 20
    box = {e["id"]: (e["x"], e["y"], e["x"] + e["w"], e["y"] + e["h"]) for e in ents}
    for x_ in ed:
        s, t = x_.get("source"), x_.get("target")
        if s not in box or t not in box:
            x_["points"] = []
            continue
        x0, y0 = box[s][2], (box[s][1] + box[s][3]) / 2
        x1, y1 = box[t][0], (box[t][1] + box[t][3]) / 2
        if box[t][0] <= box[s][0]:
            c = max(16.0, min(box[s][1], box[t][1]) - 24)
            x_["points"], x_["feedback"] = [(x0, y0), (x0, c), (x1, c), (x1, y1)], True
        else:
            mx = (x0 + x1) / 2
            x_["points"] = [(x0, y0), (mx, y0), (mx, y1), (x1, y1)]
    right = max([e["x"] + e["w"] for e in ents] + [W - 60])
    return {"ents": ents, "edges": ed, "bands": bands, "box": box,
            "cv": {"w": max(W, right + 46), "h": H, "ly": y + 6}}


import verify as _V  # noqa: E402  (independent checks live in verify.py)


if __name__ == "__main__":
    sys.exit(main())
