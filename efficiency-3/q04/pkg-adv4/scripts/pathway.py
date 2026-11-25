"""pathway.py — compact mechanism/pathway figure Skill (entry point).

    python3 scripts/pathway.py --case /input/case.json --out /app/output

material -> typed entities + directed interactions (EN/中文) -> layered mechanism SVG (text) ->
vector PDF + PNG preview -> result.json (contract echoed) + check-report.json.
Rules: one arrow shape per interaction meaning, width = evidence strength, transmembrane receptor
straddles the membrane, passive voice / 被/由/受 flips arguments, a Markdown heading line is topic
metadata and never an entity/mention/subject, the subject of a predicate is the
*matrix* subject of its clause (never the entity nearest the cue: `A forms a complex with B and
phosphorylates C` is A->C), negated claims are excluded (not drawn), unresolved clauses are listed
(never guessed), every entity/edge carries a locator that resolves inside the material file it
names, and a value without a locator is refused.
Layout, drawing and export are in this file.
"""
import argparse, csv, hashlib, io, json, math, os, re, sys
from bisect import bisect_right
from datetime import datetime, timezone

sys.dont_write_bytecode = True          # never leave __pycache__/*.pyc inside the Skill tree

VER = "1.3.0-adv4"
# type|label|line|arrow|colour|english cues|chinese cues|chinese passive patterns
VOC = """
activates|activation|solid|tri|#2E7D32|activates promotes induces stimulates drives triggers mediates|激活 活化 促进 诱导 增强 上调 增加 驱动 导致 引起 介导|被激活 被诱导 由.*?激活
inhibits|inhibition|solid|tbar|#C62828|inhibits suppresses represses blocks prevents reduces|抑制 阻断 下调 降低 减少 削弱 拮抗 限制 沉默 负调控|被抑制 被阻断 由.*?抑制
binds|binding / association|solid|circ|#1565C0|binds interacts associates recruits|结合 相互作用 互作 形成复合物 招募|与.*?结合 和.*?结合
modifies|covalent modification|dash|tri|#6A1B9A|phosphorylates ubiquitinates methylates cleaves hydroxylates|磷酸化 泛素化 甲基化 乙酰化 羟化 修饰|被磷酸化 被泛素化 由.*?磷酸化
transports|transport / translocation|dashdot|tri_o|#EF6C00|transports translocates imports exports secretes|转运 转位 易位 入核 出核 分泌 释放 进入细胞核|被转运 被分泌
expresses|transcription / expression|solid|chev|#00695C|transcribes encodes expresses|转录激活 转录 表达 编码 翻译|由.*?编码
degrades|degradation|dot|tri|#4E342E|degrades destabilizes|降解 促降解 清除|被降解
regulates_unknown|regulation (direction unknown)|dot|tri_o|#616161|regulates modulates affects controls|调控 调节 影响 相关 参与|受.*?调控
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
# --- what must never be read as biological material -------------------------------------------
# The runtime contract guarantees /input/task.md next to the case: a work order is an *instruction*,
# not a source. Reading it injects non-biological tokens (tool names, format names, rubric ids) into
# the entity table. These are skipped by name and the skip is recorded, never silent.
OUT_ARTEFACTS = {"case.json", "result.json", "spec.json", "check-report.json", "pathway.json",
                 "verify-report.json", "audit-report.json", "benchmark.json", "result.example.json",
                 "pathway.example.json"}
INSTRUCTION_NAMES = {"task.md", "task.txt", "task.json", "instruction.md", "instructions.md",
                     "prompt.md", "prompt.txt", "workorder.md", "work-order.md", "rubric.md",
                     "rubrics.md", "grading.md", "meta.json", "environment.yaml", "resources.yaml"}
INSTRUCTION_PREFIX = ("instruction", "rubric", "workorder", "work-order", "grading", "scorecard")
# relation / entity names a structured work order may use, mapped onto the vocabulary
STRUCT_SYN = {"activation": "activates", "activate": "activates", "promotes": "activates",
              "promotion": "activates", "induces": "activates", "upregulat": "activates",
              "inhibition": "inhibits", "inhibit": "inhibits", "suppress": "inhibits",
              "repress": "inhibits", "downregulat": "inhibits", "block": "inhibits",
              "phosphorylation": "modifies", "phosphorylat": "modifies", "ubiquitinat": "modifies",
              "methylat": "modifies", "acetyl": "modifies", "cleav": "modifies",
              "modification": "modifies", "binding": "binds", "bind": "binds",
              "association": "binds", "interaction": "binds", "recruit": "binds",
              "transport": "transports", "translocation": "transports", "import": "transports",
              "export": "transports", "secretion": "transports", "expression": "expresses",
              "transcription": "expresses", "encodes": "expresses", "degradation": "degrades",
              "degrade": "degrades", "destabilis": "degrades", "destabiliz": "degrades",
              "regulation": "regulates_unknown", "modulation": "regulates_unknown",
              "unknown": "regulates_unknown", "regulates": "regulates_unknown"}
TYP_SYN = {"gene": "gene", "protein": "protein", "complex": "complex", "drug": "drug",
           "phenotype": "phenotype", "compartment": "compartment", "tf": "protein",
           "transcription factor": "protein", "kinase": "protein", "receptor": "protein",
           "enzyme": "protein", "细胞因子": "protein", "基因": "gene", "复合物": "complex",
           "蛋白": "protein", "药物": "drug", "表型": "phenotype"}
# directories the additive directory scan never descends into
SCAN_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
                  "site-packages", "dist", "build", ".cache", "skills", "runs", "outputs",
                  "stage", "checkpoints"}
NEG = ["does not", "do not", "did not", "fails to", "is not", "are not", "no evidence", "并不", "不", "未",
       "无", "并非", "未见", "尚未", "不能"]
CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]")
TOK = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z]{1,6}[0-9]+[A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*"
                 r"|[A-Z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*|[A-Z]{2,}[0-9]*|[a-z]{3,20}"
                 r"|[\u4e00-\u9fff](?:\s?[\u4e00-\u9fff]){1,7})(?![A-Za-z0-9])")
SENT = re.compile(r"[^.!?。！？]+[.!?。！？]?")
CL = ",;:\uff0c\uff1b\uff1a\u3001\u3002\uff08\uff09()"
# A Markdown heading/label line — 1-6 `#` at the start of a line (with or without a space after them,
# as in `#MAPK1`), and also inside a blockquote. The whole line is topic metadata: it may not produce
# an entity, a mention or a subject (P0-4). Any `#`-led line is treated this way on purpose: measured,
# `#1 sample of MAPK1` above `EGFR binds MAPK1.` otherwise glues to the body and swallows the edge.
HEADING = re.compile(r"\s{0,3}(?:>\s*)?#{1,6}\s*\S")
LOC = re.compile(r"(?:in|at|on|into|to|within)\s+(?:the\s+)?(plasma membrane|membrane|cytosol|cytoplasm|"
                 r"nucleus|nuclear|extracellular)", re.I)
LOCZ = re.compile("(?:在|于|至|进入|转入|位于)?\\s*(细胞外|细胞膜|质膜|细胞质|胞质|细胞核|核内)")
ZBY, PRO, PAIR = (re.compile("[\u7531\u88ab\u53d7]"),
                  re.compile("[\u5176\u8be5\u6b64\u8fd9]|\u540e\u8005|\u524d\u8005"),
                  re.compile("^[\u4e0e\u548c]"))
CZ = ["并且", "同时", "而且", "并", "且", "从而", "进而", "因此", "所以", "也", "则", "而"]
CE = re.compile(r"\b(and|therefore|thus|hence|then|so|thereby)\b", re.I)
RELPRO = re.compile(r"\b(which|that|who|whose|where)\b", re.I)
# An entity that directly follows one of these is in an *object* slot, so the predicate cannot be
# attached to it: `forms a complex with RPTOR`, `由 HIF1A 激活`, `binds to EGFR` (QA 2026-11-24, P0-3).
OBJE = re.compile(r"(?:(?<![A-Za-z])(?:with|of|by|for|from|via|through|using|including|plus|against|into|in|on|at|to|as|than)"
                  r"|[和与及])(?:\s+(?:the|a|an|its|their|his|her))?\s*$", re.I)
OBJZ = re.compile(r"(?:与|和|及|同|跟|对|向|给|由|被|为|从|在|使|让)\s*$")
# Verbs that are not cues but still end a clause: they are what tells
# `MTOR forms a complex with RPTOR and phosphorylates S6K1` (one subject, two predicates) apart from
# `MTOR and RPTOR phosphorylate S6K1` (two subjects, one predicate).
VERB_EXTRA = """form contain consist require show reveal suggest indicate remain lack include comprise
 feature act function serve lead result occur exist depend allow cause release produce generate carry
 replace adopt undergo exhibit display reach enter exit couple anchor bridge dock target treat expose
 disrupt fail abolish rescue restore raise lower increase decrease accumulate stabilize stabilise bind
 measure report observe detect identify use add remove change affect""".split()
AUX = re.compile(r"\b(?:to|of|will|would|can|could|may|might|must|should|shall|do|does|did|not|n't|"
                 r"and|or|is|are|was|were|be|been|being|has|have|had|it|its|this|these|those|"
                 r"which|that|who|whose|where|when|while|than)\s+$", re.I)
VERBF = re.compile(
    r"\b(?:%s)(?:s|es|ed|ing)?\b" % "|".join(sorted(
        {re.escape(c[:-1] if c.endswith(("s", "e")) else c)
         for _r in R.values() for c in _r["en"].split()} |
        {re.escape(v) for v in VERB_EXTRA}, key=len, reverse=True)), re.I)
def _en_pat(cue):
    """Inflection-tolerant English cue: 'activates' also matches activate/activated/activating."""
    stem = cue[:-1] if cue.endswith(("s", "e")) else cue
    return re.escape(stem) + r"(?:s|es|e|ed|ing|ion)?"


CUE = sorted([(_en_pat(c), t, 0, c) for t, r in R.items() for c in r["en"].split()] +
             [(re.escape(c), t, 0, c) for t, r in R.items() for c in r["zh"].split()] +
             [(c, t, 1, c) for t, r in R.items() for c in r["pz"].split()], key=lambda x: -len(x[0]))
_V = None                               # verify module, imported lazily by checks()


def now():
    ep = (os.environ.get("SOURCE_DATE_EPOCH") or "").strip()
    if ep.isdigit():                      # reproducible builds: pin every timestamp
        return datetime.fromtimestamp(int(ep), timezone.utc).astimezone().isoformat(timespec="seconds")
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
def fingerprint(paths):
    """sha256 over the delivered artefacts: two runs of one input must share it, whatever the
    wall clock and whatever the host says. This is how a reviewer compares two submissions."""
    h = hashlib.sha256()
    for p in paths:
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def file_sha(path):
    """Plain sha256 of one file, so a reviewer can compare it with `sha256sum <file>`."""
    try:
        return "sha256:" + hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError:
        return ""
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
    """Markdown → plain prose, **character-for-character**: every blank is a space at the same
    offset, so a locator still names the physical line of the raw file.

    A heading line is blanked *whole*. It names the topic (`# MAPK1 pathway overview`), and the line
    below it does not start with punctuation, so the old newline-join glued the two together and the
    heading word became the first — therefore the subject — mention of the next sentence:
    `Extracellular EGF binds EGFR.` came out as `MAPK1 --binds--> EGFR` (QA 2026-11-24, P0-4)."""
    ch, ln, st, p = list(t or ""), (t or "").split("\n"), [], 0
    for x in ln:
        st.append(p); p += len(x) + 1
    for i, x in enumerate(ln):
        if HEADING.match(x):
            for j in range(len(x)):
                ch[st[i] + j] = " "
            continue                            # never joined to the line below, never a mention
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
def heading_lines(raw):
    """1-based lines of the raw text that are Markdown headings. A heading names the *topic*
    (`# EGF-stimulated MAPK signalling`), and a word that occurs only there is not an entity of the
    mechanism — that is how a pseudo-entity `MAPK` reached the figure (QA 2026-11-24, P0-2).

    `norm()` blanks these lines outright, so this set is a second, raw-text-level guard: nothing a
    heading says may become an entity, a mention or the subject of the next sentence (P0-4)."""
    return {i + 1 for i, ln in enumerate((raw or "").split("\n")) if HEADING.match(ln)}


def extract(raw, src, loc_of=None):
    t, lof = norm(raw), lmap(raw)
    ss = sents(t)
    ms, seen, order = [], {}, []
    hd = heading_lines(raw)
    # a key mentioned only on heading lines is a topic label, not an entity
    body_keys = set()
    if hd:
        for m in TOK.finditer(t):
            sf = m.group(1)
            if CJK.search(sf):
                sf = czh(sf)
            if lof(m.start(1)) not in hd:
                body_keys.add(ky(sf))
    for m in TOK.finditer(t):
        sf, a, b = m.group(1), m.start(1), m.end(1)
        if hd and lof(a) in hd and ky(czh(sf) if CJK.search(sf) else sf) not in body_keys:
            continue                                    # heading-only token: not a mechanism entity
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
            sid, ln = loc_of(a) if loc_of else (src, lof(a))
            rec["evidence"].append({"source": sid, "locator": "%s#L%d" % (sid, ln),
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
def fore(s, pos, clo):
    """Where the subject of the predicate at `pos` may be looked for: sentence-relative [lo, hi).

    English: a finite verb between the clause boundary and the cue opens the *current* predicate, so
    its own subject is what lies in front of that verb. `which/that/who/where` is blanked first, so a
    relative clause does not end the clause it is attached to. A cue is matched on its 3rd-person
    singular form, so a cue match itself is used as finite evidence; `-ed/-ing` forms after an
    auxiliary, and after a coordinator that takes a bare verb, are participles/gerunds, not
    predicates (that is what made `Activated MAPK1 translocates …` a verb in the parent arm).

    This is the boundary that keeps `MTOR forms a complex with RPTOR and phosphorylates S6K1` from
    reading `RPTOR` as the subject of `phosphorylates` (QA 2026-11-24, P0-3)."""
    w = s[:pos]
    for r in (" which ", " that ", " who ", " whose ", " where ", " thereby "):
        w = w.replace(r, " " * len(r))
    vpos = None
    if not CJK.search(s):
        for vm in VERBF.finditer(s, 0, pos):
            tok, b = vm.group(0).lower(), vm.start()
            if b >= len(w) or not w[b:b + len(vm.group(0))].strip():
                continue                      # inside a blanked relative clause
            if tok.endswith(("ed", "ing")) or AUX.search(s[:b]):
                continue                      # participle / gerund / infinitive: no subject of its own
            vpos = b if vpos is None else min(vpos, b)
    if vpos is not None and vpos > clo:
        return clo, vpos
    return clo, pos


def coord_before(s, s0, ms, clo, pos):
    """True when the cue is the second conjunct of a coordinated predicate: the coordinator
    (`and`, `therefore`, `并`, `从而`, …) sits between the previous predicate and this cue with **no
    noun in between**. `A activates B and activates C` puts the predicate back on the subject of the
    first conjunct; `A activates B, and B activates C` does not (an entity intervenes)."""
    seg = s[clo:pos]
    last = -1
    for m in re.finditer(r"\b(?:and|or|therefore|thus|hence|so|thereby|but|finally)\b", seg, re.I):
        last = max(last, clo + m.end())
    for c in CZ:
        i = seg.rfind(c)
        if i >= 0:
            last = max(last, clo + i + len(c))
    if last < 0:
        return False
    rel = None
    for r in RELPRO.finditer(seg):          # a coordinator inside a relative clause coordinates
        rel = r                            # that clause's own predicates, not the sentence's
    if rel is not None and rel.end() > last - clo:
        return False
    return not [m for m in ms
                if m.get("entity_id") and m["start"] - s0 >= last and m["end"] - s0 <= pos]


def subj_of(s, s0, pos, clo, ms, last_sj):
    """Subject of the predicate that starts at sentence-relative `pos`.

    Deterministic order, and the whole point of this arm: **the matrix subject wins, never "the
    entity nearest the cue"**. In `MTOR forms a complex with RPTOR and phosphorylates S6K1` the
    nearest entity before `phosphorylates` is `RPTOR` — the object of `forms a complex with` — and
    attaching the predicate to it drew `RPTOR -> S6K1` (QA 2026-11-24, P0-3).

    1. the first entity of this predicate's own clause (a candidate that itself sits in an object
       slot of a preposition/conjunction — `with RPTOR`, `与 RPTOR` — cannot be a subject);
    2. a subjectless coordinated predicate inherits the predicate it is coordinated with (`and`,
       `therefore`, `并`, `从而`, … with no noun in between);
    3. `, which then activates C` takes the noun in front of the relative pronoun/anaphor — the
       previous clause's object — which is what removes the layer-skipping `A -> C` edge
       (QA 2026-11-24, P0-2);
    4. otherwise the matrix subject of the sentence (the first entity in front of its first finite
       verb), and only then the first entity of the sentence."""
    lo, hi = fore(s, pos, clo)
    seg = s[clo:pos]
    cand = [m for m in ms if m.get("entity_id") and not anaph(m)
            and lo <= m["start"] - s0 and m["end"] - s0 <= hi]
    if cand:
        c = min(cand, key=lambda m: m["start"])
        head = s[max(0, c["start"] - s0 - 26): max(0, c["start"] - s0)]
        if not (OBJE.search(head) or OBJZ.search(head)):
            return c
    ant, at = None, None
    for r in RELPRO.finditer(seg):
        ant, at = r, clo + r.start()
    if ant is None:
        for r in PRO.finditer(seg):
            ant, at = r, clo + r.start()
    if ant is not None:
        ant = pm(ms, s0 + at)
        if anaph(ant):
            ant = None
    if coord_before(s, s0, ms, clo, pos):
        return last_sj or ant or matrix_subj(s, s0, ms)
    return ant or matrix_subj(s, s0, ms)


def anaph(m):
    """An unresolved anaphor (`该复合物`, `后者`) is never a predicate subject: the figure must not
    grow an edge that starts at a node called `该复合物`. The clause goes to
    `unresolved_statements[]` instead — the anaphor is reported, not drawn (SKILL.md limits).
    A `mention` carries only `surface`; an `entity` carries `canonical`/`label`."""
    m = m or {}
    return bool(PRO.match(str(m.get("canonical") or m.get("label") or m.get("surface") or "").strip()))


def matrix_subj(s, s0, ms):
    """The matrix subject: the first entity in front of the sentence's first finite verb (English),
    or simply the first entity of the sentence when no verb shape is recognised (Chinese)."""
    fv = fore(s, len(s), 0)[1]
    return (min([m for m in ms if m.get("entity_id") and not anaph(m) and m["start"] - s0 < fv],
                key=lambda m: m["start"], default=None) or
            min([m for m in ms if m.get("entity_id") and not anaph(m)],
                key=lambda m: m["start"], default=None))


def rels(t, src, an, ents, loc_of=None):
    by = {e["id"]: e for e in ents}
    E, X, U = [], [], []
    for s, s0, _ in an["sentences"]:
        ms = [dict(m) for m in an["mentions"] if s0 <= m["start"] and m["end"] <= s0 + len(s)]
        if not ms:
            continue
        used = []
        last = None                     # grammatical subject of the previous predicate in this sentence
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
                why_override = ""
                gram = None
                if PAIR.match(m.group(0)):
                    sj, oj = pm(ms, cs), pk(ms, cs, "after", lo, hi)
                    gram = sj
                else:
                    # ---- voice ------------------------------------------------------------------
                    # Documented rule: `B is V-ed by A` => A -> B, and `B 被/由/受 A 动词` => A -> B.
                    # The Chinese passive is a literal cue only when nothing sits between 被 and the
                    # verb; the general case needs the marker between clause start and the cue, and
                    # English needs the be-verb / `by` evidence. Without this test the active branch
                    # reversed the arrow (QA 2026-11-24, P0-1).
                    zb = ZBY.search(s, clo, m.start())
                    bm = re.search(r"\bby\b", s[m.end():chi], re.I)
                    be = re.search(r"\b(?:is|are|was|were|be|been|being)\b[^,;.。；]{0,30}$",
                                   s[clo:m.start()], re.I)
                    if passive or zb or bm or be:
                        patient = pk(ms, s0 + zb.start(), "before", lo, hi) if zb else \
                            (pk(ms, cs, "before", lo, hi) or pm(ms, cs))
                        agent = None
                        if bm:
                            agent = pk(ms, s0 + m.end() + bm.end(), "after", lo, hi)
                        elif zb:
                            agent = pk(ms, s0 + zb.end(), "after", lo, hi)
                        elif ZBY.match(m.group(0)):
                            agent = pk(ms, cs, "after", lo, hi)
                        if agent is not None and patient is not None:
                            sj, oj = agent, patient
                            gram = patient          # the grammatical subject of a passive is the patient
                        else:
                            sj, oj = None, None
                            why_override = ("passive voice with no stated agent: the direction is "
                                            "not drawn rather than guessed")
                    else:
                        oj = pk(ms, ce, "after", lo, hi)
                        win = s[max(0, m.start() - 80): m.start()]
                        sj = lt(an["mentions"], cs, by, "complex") \
                            if ("复合物" in win and PRO.search(win)) else None
                        # The predicate's subject is the *matrix* subject of its own clause — the
                        # first entity in front of that clause's first finite verb — and never "the
                        # entity nearest the cue": `MTOR forms a complex with RPTOR and
                        # phosphorylates S6K1` must give MTOR -> S6K1, not RPTOR -> S6K1
                        # (QA 2026-11-24, P0-3). A subjectless second conjunct inherits the
                        # predicate it is coordinated with; a relative clause (`which then ...`)
                        # takes the most recent noun, which is what keeps the layer-skip
                        # EGFR -> MAPK1 out of the figure (QA 2026-11-24, P0-2).
                        sj = sj or subj_of(s, s0, m.start(), clo, ms, last)
                        if oj is None:
                            gap = s[m.end(): chi]
                            if any(c in gap for c in CZ) or CE.search(gap):
                                oj = pk(ms, ce, "after") or (pm(ms, cs) if PRO.search(gap) else None)
                        gram = sj
                        if tn == "transports" and (LOC.search(s, m.end(), chi) or
                                                   LOCZ.search(s, m.end(), chi)):
                            # `translocates into the nucleus`: the object is a compartment, so the
                            # arrow must not also become a transport to the next molecule in the
                            # clause (that is how MAPK1 -> FOS got two overlapping edges).
                            sj, oj = sj, None
                            why_override = ("transport target is a compartment, not a molecule")
                if gram is not None:
                    last = gram
                used.append((cs, ce))
                sid, sln = loc_of(cs) if loc_of else (src, an["line_of"](cs))
                loc = "%s#L%d" % (sid, sln)
                if not sj or not oj or sj["entity_id"] == oj["entity_id"]:
                    fb_s = sj or pk(ms, cs, "before", lo, hi) or pm(ms, cs)
                    fb_t = oj or pk(ms, ce, "after", lo, hi)
                    if fb_s is not None and fb_t is not None and \
                            fb_s.get("entity_id") == fb_t.get("entity_id"):
                        fb_t = None                     # do not record a self loop
                    r = {"sentence": s.strip()[:190], "cue": cue, "type": tn,
                         "source": (fb_s or {}).get("entity_id", ""),
                         "target": (fb_t or {}).get("entity_id", ""),
                         "locator": loc,
                         "why": why_override or "could not resolve both arguments to known entities",
                         "evidence": [{"source": sid, "locator": loc, "quote": s.strip()[:260]}]}
                    if why_override:
                        r["direction_drawn"] = False
                    if bad:
                        r["removed_because"] = "negated by '%s'" % bad
                    (X if bad else U).append(r)
                    continue
                rl = R[tn]
                e = {"source": sj["entity_id"], "target": oj["entity_id"], "type": tn, "label": "",
                     "line": rl["line"], "arrow": rl["arrow"], "color": rl["col"], "strength": stre(s),
                     "feedback": bool(re.search("feedback|反馈", s)),
                     "modification_tag": next((v for k, v in (("phosphorylat", "P"), ("ubiquitinat", "Ub"),
                                                              ("methylat", "Me"), ("acetyl", "Ac"),
                                                              ("磷酸化", "P"), ("泛素化", "Ub"), ("羟化", "OH"))
                                               if k in cue.lower()), ""),
                     "voice": "passive" if (passive or zb or bm or be) else "active",
                     "origin": "cue '%s'%s" % (cue, " (passive)" if (passive or zb or bm or be) else ""),
                     "evidence": [{"source": sid, "locator": loc, "quote": s.strip()[:260]}], "uncertainty": ""}
                if bad:
                    X.append(dict(e, removed_because="negated by '%s'" % bad, locator=loc))
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
def rel_type(s):
    """Map a declared relation name ('activation', 'inhibition', '激活', 'phosphorylation') to one
    vocabulary type, so a structured work order is drawn with the same grammar as extracted prose."""
    x = (s or "").strip().lower()
    if not x:
        return ""
    for t, r in R.items():
        if x == t or x == r["lab"].lower():
            return t
    for syn, t in STRUCT_SYN.items():
        if x == syn or x.replace(" ", "").startswith(syn):
            return t
    for pat, tn, _passive, _cue in CUE:
        if re.search(pat, x, re.I):
            return tn
    for t, r in R.items():                      # Chinese cues are matched literally
        if any(c and c in x for c in r["zh"].split()):
            return t
    return ""


def struct_spec(case, src, case_path=""):
    """Structured entry: `case.json` already carries `entities` (and `edges`/`interactions`).

    A drawing *work order* is normalised into the same internal spec as extracted prose: ids are
    assigned, roles and compartments are honoured when declared, arrow geometry comes from the
    vocabulary, and every element must carry a locator that resolves to a real line of the case
    descriptor. A declared value without a source locator is refused rather than painted, and the
    refusal is recorded."""
    raw_e = case.get("entities")
    if not isinstance(raw_e, list) or not raw_e:
        return None
    try:
        case_txt = open(case_path, encoding="utf-8", errors="replace").read() if case_path else ""
    except OSError:
        case_txt = ""
    case_lines = [ln.strip().lower() for ln in case_txt.split("\n")]

    def line_of(token, default=1):
        """Physical line of the first occurrence of `token` in the case descriptor."""
        t = str(token or "").strip().strip('"').lower()
        if not t:
            return default
        for i, ln in enumerate(case_lines, 1):
            if t in ln:
                return i
        return default

    def line_locator(declared, token, idx):
        """A locator must be `file#Lnn`. A declared one is kept when it already points at a line;
        otherwise the line is looked up in the case descriptor instead of inventing a shape."""
        d = str(declared or "")
        if re.search(r"#L\d+$", d):
            return d
        return "%s#L%d" % (os.path.basename(case_path) or "case.json", line_of(token, idx + 1))

    ents, by_label, refused = [], {}, []
    for i, e in enumerate(raw_e, 1):
        if not isinstance(e, dict):
            continue
        lab = str(e.get("label") or e.get("name") or e.get("symbol") or e.get("id") or "").strip()
        if not lab:
            continue
        ty = TYP_SYN.get(str(e.get("type") or "").strip().lower(), "")
        role = str(e.get("role") or "").strip().lower()
        role = ("receptor" if "receptor" in role or "跨膜" in role else
                "tf" if role in ("tf", "transcription factor", "转录因子") else
                "kinase" if "kinase" in role or "激酶" in role else "")
        if not ty:
            ty, role2 = typ(lab, lab, "", lab, 0, len(lab))
            role = role or role2
        if ty not in TYP:
            ty = "protein"
        note = str(e.get("localisation") or e.get("localization") or e.get("note") or
                   e.get("compartment") or "")
        mm = LOC.search(note) or LOCZ.search(note)
        comp = compw(str(e.get("compartment") or "")) or (compw(mm.group(1)) if mm else "")
        csrc = "declared in the work order"
        if not comp:
            comp, csrc = (("plasma_membrane", "role: transmembrane receptor") if role == "receptor" else
                          ("extracellular", "drug acts from outside") if ty == "drug" else
                          ("nucleus", "role: transcription factor") if role == "tf" else
                          ({"gene": "nucleus", "protein": "cytosol", "complex": "cytosol",
                            "phenotype": "outcome", "drug": "extracellular",
                            "compartment": "cytosol"}.get(ty, "cytosol"), "type default"))
        ev = e.get("evidence")
        if isinstance(ev, list) and ev:
            ev = [dict(v, locator=line_locator(v.get("locator"),
                                                v.get("quote") or lab, i - 1)) for v in ev]
        if not isinstance(ev, list) or not ev:
            loc = line_locator(e.get("locator") or e.get("source_locator"), lab, i - 1)
            ev = [{"source": str(e.get("source") or src), "locator": loc,
                   "quote": str(e.get("quote") or e.get("sentence") or lab)[:260]}]
        data, dsrc = e.get("data") if isinstance(e.get("data"), dict) else {}, str(e.get("data_source") or "")
        if data and not dsrc:
            refused.append({"sentence": "%s: %s" % (lab, json.dumps(data, ensure_ascii=False)),
                            "cue": "declared value", "type": "data_encoding",
                            "source": "", "target": "", "locator": ev[0].get("locator", ""),
                            "why": "a declared value with no source locator is not painted",
                            "evidence": ev})
            data, dsrc = {}, ""
        rec = {"id": "E%02d" % (len(ents) + 1), "key": ky(lab), "canonical": str(e.get("canonical") or lab),
               "label": lab, "surfaces": [lab], "type": ty, "role": role, "italic": ty == "gene",
               "compartment": comp, "compartment_source": csrc, "ambiguous": False, "count": 1,
               "first": (0, 0), "data": data, "data_source": dsrc, "evidence": ev}
        ents.append(rec)
        by_label[ky(lab)] = rec["id"]
        by_label[ky(rec["canonical"])] = rec["id"]
        if e.get("id"):
            by_label[ky(str(e["id"]))] = rec["id"]
    raw_x = case.get("edges") or case.get("interactions") or case.get("relations") or []
    edges, excluded = [], []
    for x in (raw_x if isinstance(raw_x, list) else []):
        if not isinstance(x, dict):
            continue
        s = by_label.get(ky(str(x.get("source") or x.get("from") or "")))
        t = by_label.get(ky(str(x.get("target") or x.get("to") or "")))
        if not (s and t) or s == t:
            continue
        tn = rel_type(x.get("type") or x.get("relation") or x.get("interaction") or "")
        if not tn:
            continue
        evx = x.get("evidence")
        if not isinstance(evx, list) or not evx:
            evx = [{"source": str(x.get("source_file") or src),
                    "locator": line_locator(x.get("locator"),
                                            x.get("quote") or x.get("sentence") or "", 0),
                    "quote": str(x.get("quote") or x.get("sentence") or "")[:260]}]
        else:
            evx = [dict(v, locator=line_locator(v.get("locator"),
                                                v.get("quote") or x.get("quote") or "", 0))
                   for v in evx]
        rl = R[tn]
        rec = {"source": s, "target": t, "type": tn, "label": "", "line": rl["line"],
               "arrow": rl["arrow"], "color": rl["col"],
               "strength": str(x.get("strength") or stre(str(x.get("quote") or x.get("sentence") or ""))),
               "feedback": bool(x.get("feedback") or re.search("feedback|反馈",
                                                               str(x.get("quote") or ""))),
               "modification_tag": str(x.get("modification_tag") or x.get("modification") or ""),
               "origin": "declared in the work order", "evidence": evx, "uncertainty": "",
               "locator": evx[0].get("locator", "")}
        if str(x.get("negated") or "").lower() in ("1", "true", "yes") or x.get("removed_because"):
            excluded.append(dict(rec, removed_because=str(x.get("removed_because") or "declared negated")))
        else:
            edges.append(rec)
    for i, e in enumerate(edges, 1):
        e["id"] = "R%02d" % i
    for i, e in enumerate(excluded, 1):
        e["id"] = "X%02d" % i
    return {"entities": ents, "edges": edges, "excluded": excluded, "unresolved": refused}


def comp_targets(spec, src):
    keep, have = [], {(e.get("source"), e.get("target"), e.get("type")) for e in spec["edges"]}
    by = {ky(e.get("canonical") or ""): e["id"] for e in spec["entities"]}
    for u in spec["unresolved"]:
        uev = (u.get("evidence") or [{}])[0]
        usrc = uev.get("source") or src
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
                                     "evidence": [{"source": usrc, "locator": u.get("locator", ""),
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
                              "evidence": [{"source": usrc, "locator": u.get("locator", ""),
                                            "quote": (u.get("sentence") or "")[:260]}],
                              "uncertainty": "target is a compartment, not a molecule"})
    spec["unresolved"] = keep
def checks(spec, lay):
    global _V
    if _V is None:                      # lazy: verify.py imports this module, so no import cycle
        import verify as _V
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
    # A contract key that asks for a raster/PDF is answered with the measured export record of the
    # file that was really written — never with a path that does not exist.
    ex = res.get("exports") or {}
    if any(k in low for k in ("png", "raster", "jpeg", "jpg", "tiff", "high_res", "high-res")):
        return ex.get("png", {"produced": False})
    if "pdf" in low:
        return ex.get("pdf", {"produced": False})
    for keys, fn in groups:
        if any(k in low for k in keys):
            return fn()
    return ""


def _clean_rel(rel):
    """A material path written on Windows (`materials\\fig.md`), or with a redundant `./`, must still
    resolve on the evaluator's POSIX host. `\\` is accepted as a separator on both platforms."""
    r = (rel or "").strip().strip('"').strip("'").replace("\\", "/")
    while r.startswith("./"):
        r = r[2:]
    while "//" in r[1:]:
        r = r.replace("//", "/")
    return r


def resolve_path(rel, case_dir, input_dir=""):
    """case.json dir -> cwd -> --input -> /input. Never keyed on absolute path segments: the
    evaluator's own paths (/app/output, …/stage/outputs) contain names that must not hide input."""
    if not rel:
        return "", ""
    rel = _clean_rel(rel)
    if "://" in rel:
        return "", "remote:unsupported (this arm never uses the network)"     # no fabricated fetch
    if os.path.isabs(rel):
        return rel, "absolute"
    for base, tag in ((case_dir, "case_dir"), (os.getcwd(), "cwd"), (input_dir, "input_dir"),
                      ("/input", "/input")):
        if base and os.path.isfile(os.path.join(base, rel)):
            return os.path.join(base, rel), tag
    return os.path.join(case_dir or ".", rel), "missing"


def pdf_text_stdlib(path):
    """FlateDecode + text-operator reader (zlib only). Fallback for hosts without PyMuPDF: without it
    the same PDF case yields 0 entities and `status=partial` for a reason that has nothing to do with
    the material. Limitations are recorded, never hidden: import-only streams and most CID/ToUnicode
    maps are out of scope, so the fallback says so and the primary reader stays preferred."""
    import zlib
    raw = open(path, "rb").read()
    chunks = []
    for m in re.finditer(rb"stream\r?\n", raw):
        s = m.end()
        e = raw.find(b"endstream", s)
        if e < 0:
            continue
        body = raw[s:e]
        try:
            data = zlib.decompress(body)
        except Exception:
            data = body
        if b"Tj" not in data and b"TJ" not in data:
            continue
        chunks.append(data)
    txt = []
    for data in chunks:
        s = data.decode("latin-1", "replace")
        for tm in re.finditer(r"\((?:\\.|[^\\()])*\)|\bTJ\b|\bTj\b|\bTd\b|\bTD\b|\bT\*\b|\bET\b", s):
            g = tm.group(0)
            if g.startswith("("):
                v = re.sub(r"\\([nrtbf()\\])", lambda x: {"n": "\n", "r": "\r", "t": "\t", "b": "",
                                                          "f": ""}.get(x.group(1), x.group(1)),
                           g[1:-1])
                txt.append(v)
            elif g == "Td" or g == "TD" or g == "T*":
                txt.append("\n")
    out = "".join(txt)
    out = re.sub(r"[ \t]+", " ", out)
    return out


def _scan_candidate(idir, p, max_depth=2):
    """Is a file found by the directory scan a plausible case material?

    The scan exists so a case that forgets to list a source does not lose it. It must not walk into
    an unrelated tree that happens to live under the same root — a nested copy of this Skill, a
    previous run's staging area (`runs/…/stage/outputs`) or a checkout would otherwise be read as
    biological material. So: at most `max_depth` directory levels below the input root, and never
    inside a VCS/build/staging directory."""
    rel = os.path.relpath(p, idir)
    parts = [x for x in re.split(r"[\\/]+", rel) if x not in ("", ".")]
    if not parts or len(parts) - 1 > max_depth:
        return False
    return not any(x.lower() in SCAN_SKIP_DIRS for x in parts[:-1])


def gather(case, cp, idir, out_dir=""):
    import glob
    cand, res_from, declared, skipped, missing = [], {}, {}, [], []
    case_dir = os.path.dirname(os.path.abspath(cp)) if cp else ""
    case_base = os.path.basename(cp).lower() if cp else ""
    out_real = os.path.realpath(out_dir) if out_dir else ""
    for k in ("materials", "files", "documents", "sources", "inputs", "attachments", "text"):
        v = case.get(k)
        for x in ([v] if isinstance(v, str) else (v if isinstance(v, list) else [])):
            if not isinstance(x, str):
                continue
            p, frm = resolve_path(x, case_dir, idir)
            if not p:
                missing.append({"declared": x, "why": frm or "unresolved"})
                continue
            res_from[os.path.realpath(p)] = frm
            declared[os.path.realpath(p)] = x
            cand.append(p)
    scanned = False
    if os.path.isdir(idir):
        for ext in (".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".pdf", ".docx", ".html"):
            for p in sorted(glob.glob(os.path.join(idir, "**", "*" + ext), recursive=True)):
                if not _scan_candidate(idir, p):
                    continue
                if os.path.realpath(p) not in declared:
                    cand.append(p)
                    scanned = True
    mats, seen = [], set()
    for p in cand:
        b = os.path.basename(p)
        low = b.lower()
        rp = os.path.realpath(p) if p else ""
        if not p or not os.path.isfile(p):
            continue
        # Anything inside the output directory, and anything that is one of this Skill's own
        # artefacts, is ignored. A *declared* file is still named in `materials_skipped` so a
        # mis-declared source is never silent; a file merely found by the directory scan is ignored
        # without a trace, because listing it would make the report depend on the previous run's
        # leftovers and break byte-reproducibility.
        if out_real and os.path.realpath(p).startswith(out_real + os.sep):
            if rp in declared:
                skipped.append({"path": b, "why": "declared, but it lies inside the output directory"})
            continue
        if low in OUT_ARTEFACTS or low.startswith(("readme", "figure.", "pathway.")):
            if rp in declared:
                skipped.append({"path": b, "why": "declared, but it is this Skill's own artefact or "
                                                  "an overview file, not material"})
            continue
        # the case descriptor itself (whatever it is called) and shipped templates/examples are
        # input shapes, not biological sources
        if low == case_base or re.match(r"^case[._-][^/]*\.json$", low) or \
                low.endswith((".example.json", ".template.json")):
            skipped.append({"path": b, "why": "case descriptor / template, not material"})
            continue
        if low in INSTRUCTION_NAMES or low.startswith(INSTRUCTION_PREFIX):
            # /input/task.md ships next to every official case; a work order is an instruction.
            skipped.append({"path": b, "why": "instruction/work-order file: reading it would inject "
                                              "rubric and tool names into the entity table"})
            continue
        if rp in seen:
            continue
        seen.add(rp)
        scan_tag = ("case_dir_scan"
                    if idir and os.path.normcase(os.path.realpath(idir)) == os.path.normcase(
                        os.path.realpath(os.path.dirname(os.path.abspath(cp)) if cp else idir))
                    else "input_scan")
        m = {"id": "mat%02d" % (len(mats) + 1), "path": b, "kind": os.path.splitext(b)[1].lstrip("."),
             "declared": rp in declared,
             "resolved_from": res_from.get(rp, scan_tag),
             "text": "", "tables": [], "notes": []}
        try:
            if m["kind"] == "pdf":
                try:
                    import fitz
                    doc = fitz.open(p); m["text"] = "\n".join(pg.get_text() for pg in doc); doc.close()
                    m["reader"] = "PyMuPDF"
                except ImportError as e:
                    m["text"] = pdf_text_stdlib(p)
                    m["reader"] = "stdlib(zlib text operators)"
                    m["notes"].append("PyMuPDF unavailable (%s): stdlib reader used; import-only "
                                      "streams and CID/ToUnicode maps may be missed" % e.__class__.__name__)
            elif m["kind"] == "docx":
                import zipfile
                m["text"] = re.sub("<[^>]+>", " ", zipfile.ZipFile(p).read("word/document.xml")
                                   .decode("utf-8", "replace"))
            else:
                m["text"] = open(p, encoding="utf-8", errors="replace").read()
        except Exception as e:
            m["notes"].append("not readable: %s: %s" % (e.__class__.__name__, e))
        if m["kind"] in ("csv", "tsv") and m["text"]:
            rows = [r for r in csv.reader(io.StringIO(m["text"]),
                                          delimiter="\t" if m["kind"] == "tsv" else ",") if any(x.strip() for x in r)]
            if len(rows) >= 2:
                hd = [h.strip() for h in rows[0]]
                m["tables"] = [{"header": hd,
                                "rows": [dict(zip(hd, r + [""] * (len(hd) - len(r)))) for r in rows[1:]]}]
        # read evidence: what was actually opened, measured, so a citation can be checked later even
        # when the material is not reachable from the verifier (and so a source record cannot be
        # fabricated without the bytes to back it)
        try:
            m["bytes"] = os.path.getsize(p)
            m["sha256"] = file_sha(p)
        except OSError as e:
            m["bytes"], m["sha256"] = 0, ""
            m["notes"].append("could not stat: %s: %s" % (e.__class__.__name__, e))
        m["lines"] = (m.get("text") or "").count("\n") + 1
        mats.append(m)
    info = {"declared": len(declared), "scanned": scanned,
            "skipped": sorted(skipped, key=lambda x: x.get("path") or ""), "missing": missing}
    return mats, info


def prose_blob(mats):
    """Join the prose materials and keep an offset -> (material id, line) map, so a locator points
    into the file the sentence actually came from. The single-blob version attributed every sentence
    to mat01 and produced locators such as `mat01#L4` in a one-line file: a false citation."""
    parts, starts, off = [], [], 0
    for m in mats:
        if m["kind"] not in ("md", "txt", "tex", "pdf", "docx", "html"):
            continue
        txt = m.get("text") or ""
        if not txt.strip():
            continue
        starts.append((off, m, lmap(txt)))
        parts.append(txt)
        off += len(txt) + 2

    def loc_of(pos):
        if not starts:
            return "case", 1
        i = max(0, bisect_right([s[0] for s in starts], pos) - 1)
        s0, m, lof = starts[i]
        return m["id"], lof(max(0, pos - s0))
    return "\n\n".join(parts), loc_of
def main(argv=None):
    ap = argparse.ArgumentParser(description="mechanism/pathway figure pipeline (compact)")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--input", default="")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--declared-only", action="store_true",
                    help="read only the files case.json declares (the directory scan is the default "
                         "so a case that forgets to list a source does not lose it)")
    ap.add_argument("--spec", default="",
                    help="rebuild the figure from a previous spec.json (correct semantics without "
                         "touching the SVG by hand)")
    a = ap.parse_args(argv)
    cp = a.case if os.path.isfile(a.case) else ""
    case = {}
    if cp:
        try:
            case = json.load(open(cp, encoding="utf-8"))
        except Exception as e:
            case = {"_case_read_error": "%s: %s" % (e.__class__.__name__, e)}
    idir = a.input or (os.path.dirname(os.path.abspath(cp)) if cp else "/input")
    os.makedirs(a.out, exist_ok=True)
    mats, ginfo = gather(case, cp, idir, a.out)
    if a.declared_only:
        mats = [m for m in mats if m.get("declared")]
    src = mats[0]["id"] if mats else "case"
    figh = case.get("figure") if isinstance(case.get("figure"), dict) else {}
    spec = {"case_id": str(case.get("case_id") or case.get("id")
                           or os.path.splitext(os.path.basename(cp))[0] or "case"),
            "figure": {"title": figh.get("title") or case.get("title") or "", "dpi": a.dpi},
            "entities": [], "edges": [], "excluded": [], "unresolved": [],
            "sources": [{"id": m["id"], "path": m["path"], "kind": m["kind"], "notes": m["notes"],
                         "declared": m.get("declared"), "lines": m.get("lines", 0),
                         "bytes": m.get("bytes", 0), "sha256": m.get("sha256", ""),
                         "reader": m.get("reader", ""),
                         "resolved_from": m.get("resolved_from")} for m in mats],
            "materials_resolution": [{"path": m["path"], "resolved_from": m.get("resolved_from"),
                                      "kind": m["kind"], "declared": m.get("declared"),
                                      "lines": m.get("lines", 0), "bytes": m.get("bytes", 0),
                                      "sha256": m.get("sha256", ""),
                                      "chars": len(m.get("text") or "")} for m in mats]}
    prose, loc_of = prose_blob(mats)
    graph_source = "none"
    if a.spec and os.path.isfile(a.spec):
        # rebuild from a corrected spec.json: same drawing, same checks, no hand-edited SVG
        try:
            sp = json.load(open(a.spec, encoding="utf-8"))
            for k in ("entities", "edges", "excluded", "unresolved"):
                spec[k] = sp.get(k) or []
            graph_source = "spec.json (--spec)"
        except Exception as e:
            spec["unresolved"].append({"sentence": "", "cue": "--spec", "type": "spec_read_error",
                                       "source": "", "target": "", "locator": a.spec,
                                       "why": "could not read --spec: %s: %s" % (e.__class__.__name__, e)})
    if graph_source == "none":
        structured = struct_spec(case, src, cp) if isinstance(case.get("entities"), list) and \
            case.get("entities") else None
        if structured:
            spec["entities"], spec["edges"] = structured["entities"], structured["edges"]
            spec["excluded"], spec["unresolved"] = structured["excluded"], structured["unresolved"]
            graph_source = "case.json entities/edges (structured work order)"
            # the case descriptor is the source here, so it is registered as a source *with read
            # evidence* (bytes / lines / sha256) instead of being cited without proof
            if not any(s.get("id") == src for s in spec["sources"]):
                try:
                    cbytes, csha = os.path.getsize(cp), file_sha(cp)
                    clines = open(cp, encoding="utf-8", errors="replace").read().count("\n") + 1
                except OSError:
                    cbytes, csha, clines = 0, "", 0
                spec["sources"].append({"id": src, "path": os.path.basename(cp) or "case.json",
                                        "kind": "json", "declared": True, "lines": clines,
                                        "bytes": cbytes, "sha256": csha, "reader": "json",
                                        "resolved_from": "case descriptor",
                                        "notes": ["structured entities/edges declared in the case "
                                                  "descriptor; used instead of prose extraction"]})
                spec["materials_resolution"].append({"path": os.path.basename(cp) or "case.json",
                                                     "resolved_from": "case descriptor",
                                                     "kind": "json", "declared": True,
                                                     "lines": clines, "bytes": cbytes,
                                                     "sha256": csha, "chars": cbytes})
        elif prose.strip():
            t, an = extract(prose, src, loc_of)
            spec["entities"] = setcmp(an["entities"], t, an["sentences"])
            spec["edges"], spec["excluded"], spec["unresolved"] = rels(t, src, an, spec["entities"], loc_of)
            graph_source = "prose extraction from %d material file(s)" % len(mats)
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
                            # a data locator must also be a real line of the table, not a synthetic
                            # `#column=row` shape: the citation index has to resolve for a reviewer,
                            # and the quote must be the row as it appears in the file (not a JSON
                            # re-serialisation, which never occurs in the material).
                            tlines = (m.get("text") or "").split("\n")
                            rowno = next((li for li, ln in enumerate(tlines, 1)
                                          if lab and lab in ln), 1)
                            e["data"], e["data_key"] = vals, "%s=%s" % (lc, lab)
                            e["data_source"] = "%s#L%d" % (m["id"], rowno)
                            e["evidence"].append({
                                "source": m["id"], "locator": e["data_source"],
                                "quote": (tlines[rowno - 1] if 0 < rowno <= len(tlines) else
                                          json.dumps(row, ensure_ascii=False)).strip()[:200]})
                            matched += 1
                        break
    if not spec["figure"]["title"] and mats and mats[0]["text"]:
        spec["figure"]["title"] = re.split(r"[.\n。]", mats[0]["text"].strip())[0][:110]
    lay = layout(spec)
    meta = json.dumps({"case_id": spec["case_id"], "entities": [e["id"] for e in spec["entities"]],
                       "edges": [e.get("id") for e in spec["edges"]]}, ensure_ascii=False)
    svg_path = os.path.join(a.out, "figure.svg")
    open(svg_path, "w", encoding="utf-8", newline="\n").write(svg(spec, lay, meta))
    exports = export_all(spec, lay, a.out, a.dpi)      # SVG + vector PDF + PNG, then measured
    rep = checks(spec, lay)
    json.dump(rep, open(os.path.join(a.out, "check-report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(spec, open(os.path.join(a.out, "spec.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    n_prim = sum(len(v) for v in lay.get("bands", [])) + 2 * len(lay.get("ents", [])) + 2 * len(lay.get("edges", []))
    if not spec["entities"] and not mats and graph_source == "none":
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
           "summary": "%d entities, %d edges, %d excluded, %d unresolved -> editable layered SVG "
                      "+ vector PDF + %d dpi PNG + result.json"
                      % (len(spec["entities"]), len(spec["edges"]), len(spec["excluded"]),
                         len(spec["unresolved"]), a.dpi),
           "figure": spec["figure"],
           "deliverables": [{"kind": "editable_source", "format": "svg", "path": "figure.svg",
                             "editable": True,
                             "note": "layered, named, live text, data-entity-id / data-edge-id"},
                            {"kind": "export", "format": "pdf", "path": "figure.pdf",
                             "editable": False,
                             "note": "vector PDF, page box = the figure's own coordinate system, "
                                     "text written as Tj operators (selectable)"},
                            {"kind": "preview", "format": "png", "path": "figure.png",
                             "editable": False,
                             "note": "%d dpi raster preview, measured from the file's IHDR/pHYs" % a.dpi}],
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
           "graph_source": graph_source,
           "materials_skipped": ginfo.get("skipped") or [],
           "materials_missing": ginfo.get("missing") or [],
           "material_discovery": {"mode": ("declared+directory-scan" if ginfo.get("scanned") else "declared"),
                                  "declared_entries": ginfo.get("declared", 0),
                                  "scan_disabled_by": "--declared-only" if a.declared_only else "",
                                  "instruction_files_never_read": sorted(INSTRUCTION_NAMES)},
           "evidence": [dict(ev, what="entity %s" % e["id"]) for e in spec["entities"]
                        for ev in e["evidence"]][:200],
           "change_log": [{"what": "materials", "detail": ", ".join(m["path"] for m in mats) or "(none)"},
                          {"what": "graph_source", "detail": graph_source},
                          {"what": "graph", "detail": "%d entities / %d edges"
                           % (len(spec["entities"]), len(spec["edges"]))}],
           "checks": rep,
           "exports": exports,
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
                       "n_materials_read": len(mats), "n_materials_skipped": len(ginfo.get("skipped") or []),
                       "n_checks": rep["n_checks"], "n_errors": rep["n_errors"]},
           "output_contract": contract_of(case), "generated_at": now(),
           "generator": "pathway.py " + VER, "self_scored": False}
    for nm in list(res["output_contract"]):
        if nm not in res:
            res[nm] = echo(nm, res)
    rp = os.path.join(a.out, "result.json")
    det = [os.path.join(a.out, f) for f in
           ("figure.svg", "figure.pdf", "figure.png", "spec.json", "check-report.json")]
    det = [p for p in det if os.path.isfile(p)]
    res["repo_hashes"] = {os.path.basename(p): fingerprint([p]) for p in det}
    # Two independent runs of one input must be byte-identical apart from `generated_at`; the
    # artefact fingerprint makes that checkable instead of asserted. result.json itself is left out
    # (its `generated_at` would make its own hash time-dependent).
    res["reproducibility"] = {"deterministic_parts": [os.path.basename(p) for p in det],
                              "non_deterministic_parts": ["result.json:generated_at"],
                              "set_SOURCE_DATE_EPOCH": "pins generated_at as well",
                              "note": "the PDF/PNG bytes depend on the engine named in "
                                      "exports.png.writer.engine; the fingerprint is computed from "
                                      "what was actually written",
                              "artefact_fingerprint": fingerprint(det)}
    res["metrics"]["export_checks"] = exports.get("checks", {})
    json.dump(res, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if not a.quiet:
        print("case     : %s" % res["case_id"])
        print("materials: %d read, %d skipped (instruction/output files are never material)"
              % (len(mats), len(ginfo.get("skipped") or [])))
        print("entities : %d   edges: %d   excluded: %d   unresolved: %d"
              % (len(spec["entities"]), len(spec["edges"]), len(spec["excluded"]), len(spec["unresolved"])))
        print("checks   : %d run, %d errors, %d warnings"
              % (rep["n_checks"], rep["n_errors"], rep["n_warnings"]))
        print("exports  : pdf %s %.1f KB pages=%s vector=%s text_ops=%s | png %s %sx%s @%s dpi (%s)"
              % (exports["pdf"]["path"], exports["pdf"]["bytes"] / 1024.0, exports["pdf"].get("pages"),
                 exports["checks"]["pdf_is_vector"], exports["pdf"].get("text_show_ops"),
                 exports["png"]["path"], exports["png"].get("width_px"), exports["png"].get("height_px"),
                 exports["png"].get("dpi_metadata"), exports["png"]["writer"].get("engine")))
        print("outputs  : figure.svg figure.pdf figure.png spec.json check-report.json result.json -> %s"
              % a.out)
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
        L.append({"op": "text", "x": 94, "y": y + 2, "s": TYP[t][0], "size": 11})
    for i, t in enumerate(used_r[:6]):
        y = ly + 40 + i * 18
        r = R[t]
        L.append({"op": "line", "x1": 430, "y1": y - 4, "x2": 496, "y2": y - 4, "stroke": r["col"],
                  "sw": 1.9, "dash": DSH.get(r["line"])})
        L += head(r["arrow"], (496, y - 4), 0.0, 1.9, r["col"])
        L.append({"op": "text", "x": 508, "y": y + 2, "s": r["lab"], "size": 11})
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
    """Deprecated shim: `export_all()` is the entry point now. Kept so an old caller cannot
    silently produce nothing."""
    return png_export(spec, lay, path, dpi).get("engine", "stdlib-zlib rasteriser")


# ---------------------------------------------------------------- export: figure.pdf / figure.png
# The exports are drawn from the SAME primitive list as the SVG (`prims()`), then re-read from disk
# and measured (MediaBox / text operators / image xobjects / IHDR + pHYs), so every export claim in
# result.json is a measured fact rather than a statement of intent. Nothing binary is ever shipped in
# the package: both files are written at run time into --out.
FS_TEXT = 11.0
CJK_FALLBACK_FONT = "STSong-Light"          # Adobe CJK base font, UCS2, not embedded
CJK_CANDIDATES = ("Noto Sans CJK SC", "Noto Sans CJK JP", "Source Han Sans SC", "WenQuanYi Zen Hei",
                  "Microsoft YaHei", "SimHei", "PingFang SC", "Arial Unicode MS")
FONT57 = {
    "A": "0E11111F111111", "B": "1E11111E11111E", "C": "0E1110101011 0E".replace(" ", ""),
    "D": "1E111111111 11E".replace(" ", ""), "E": "1F10101E10101F", "F": "1F10101E101010",
    "G": "0E1110171111 0E".replace(" ", ""), "H": "1111111F111111", "I": "0E04040404040E",
    "J": "0702020202120C", "K": "11121418141211", "L": "1010101010101F",
    "M": "111B1515111111", "N": "11191513111111", "O": "0E11111111110E",
    "P": "1E11111E101010", "Q": "0E11111115120D", "R": "1E11111E141211",
    "S": "0F10100E01011E", "T": "1F040404040404", "U": "1111111111110E",
    "V": "11111111110A04", "W": "11111115151B11", "X": "11110A040A1111",
    "Y": "11110A04040404", "Z": "1F01020408101F",
    "0": "0E11131519110E", "1": "040C040404040E", "2": "0E1101020408 1F".replace(" ", ""),
    "3": "1F02040201110E", "4": "02060A121F0202", "5": "1F101E0101110E",
    "6": "0608101E11110E", "7": "1F010204080808", "8": "0E11110E11110E",
    "9": "0E11110F01020C",
    " ": "00000000000000", "-": "0000001F000000", "+": "0004041F040400",
    "/": "01020204080810", "(": "02040808080402", ")": "08040202020408",
    ".": "00000000000C0C", ",": "000000000C0408", ":": "000C0C000C0C00",
    "=": "00001F001F0000", "%": "11020404081100", "_": "0000000000001F",
    "*": "000A041F040A00", "?": "0E110102040004", ";": "000C0C000C0408",
    "<": "02040810080402", ">": "08040201020408", "[": "0E08080808080E",
    "]": "0E02020202020E", "|": "04040404040404",
}


def _rgb(hex_colour):
    c = str(hex_colour or "#000000").lstrip("#")
    if len(c) != 6:
        c = "333333"
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _pdf_rgb(hex_colour):
    r, g, b = _rgb(hex_colour)
    return "%.3f %.3f %.3f" % (r, g, b)


def _is_cjk(ch):
    return bool(CJK.match(ch))


def _split_runs(s):
    """Split a label into (is_cjk, text) runs: Helvetica/WinAnsi vs the UCS2 CJK font."""
    runs = []
    for ch in str(s or ""):
        c = _is_cjk(ch)
        if runs and runs[-1][0] == c:
            runs[-1][1].append(ch)
        else:
            runs.append([c, [ch]])
    return [("".join(t), c) for c, t in runs]


def _pdf_ascii(s):
    """Base-14 Helvetica + WinAnsiEncoding: keep what it can show, report what it cannot."""
    kept, lost = [], []
    for ch in s:
        if ch in "\\()":
            kept.append("\\" + ch)
        elif 32 <= ord(ch) < 127:
            kept.append(ch)
        else:
            lost.append(ch)
    return "".join(kept), sorted(set(lost))


def _txt_w(s, size):
    """Advance estimate: CJK is one em, Latin about half. Used for anchors and the bitmap font."""
    return sum(size if _is_cjk(c) else 0.5 * size for c in s)


def pdf_export(spec, lay, path):
    """Vector PDF from the same primitives as the SVG. Real text operators (Tj) for both Latin
    (Helvetica) and CJK (UCS2 Type0, viewer-provided base font + ToUnicode CMap so the text is
    extractable even when the font is not embedded); no raster, no font file needed."""
    P, M, EG, NG, L = prims(spec, lay)
    H = lay["cv"]["h"]
    ops, lost, cjk_chars = [], [], 0

    def y(v):
        return H - v

    def rect(p):
        return ("%s rg %s RG %g w %g %g %g %g re B" % (
            _pdf_rgb(p.get("fill") or "#FFFFFF"), _pdf_rgb(p.get("stroke") or "#000000"),
            max(0.2, p.get("sw") or 0.6), p["x"], y(p["y"] + p["h"]), p["w"], p["h"]))

    def line(p):
        s = "%s RG %g w %g %g m %g %g l S" % (_pdf_rgb(p.get("stroke") or "#000000"),
                                              max(0.2, p.get("sw") or 1.0),
                                              p["x1"], y(p["y1"]), p["x2"], y(p["y2"]))
        if p.get("dash"):
            s = "[%s] 0 d %s [] 0 d" % (p["dash"], s)
        return s

    def circle(p):
        cx, cy, r = p["cx"], y(p["cy"]), p["r"]
        k = 0.5523 * r
        return ("%s rg %s RG %g w %g %g m %g %g %g %g %g %g c %g %g %g %g %g %g c "
                "%g %g %g %g %g %g c %g %g %g %g %g %g c B" % (
                    _pdf_rgb(p.get("fill") or "#FFFFFF"), _pdf_rgb(p.get("stroke") or "#000000"),
                    max(0.2, p.get("sw") or 0.6), cx + r, cy,
                    cx + r, cy + k, cx + k, cy + r, cx, cy + r,
                    cx - k, cy + r, cx - r, cy + k, cx - r, cy,
                    cx - r, cy - k, cx - k, cy - r, cx, cy - r,
                    cx + k, cy - r, cx + r, cy - k, cx + r, cy))

    def poly(p):
        pts = [(a, y(b)) for a, b in p["pts"]]
        body = " ".join("%g %g %s" % (a, b, "m" if i == 0 else "l") for i, (a, b) in enumerate(pts))
        head = "%s rg" % _pdf_rgb(p.get("fill") or "#FFFFFF") if p.get("fill") else ""
        op = "f" if p.get("closed", True) else "S"
        return "%s %s RG %g w %s h %s" % (head, _pdf_rgb(p.get("stroke") or "#000000"),
                                          max(0.2, p.get("sw") or 1.0), body, op)

    def text(p):
        nonlocal cjk_chars
        size, x, base = p["size"], p["x"], y(p["y"])
        w = _txt_w(p["s"], size)
        if p.get("anchor") == "middle":
            x -= w / 2
        elif p.get("anchor") == "end":
            x -= w
        out = []
        for run, is_cjk in _split_runs(p["s"]):
            if is_cjk:
                cjk_chars += len(run)
                hexs = run.encode("utf-16-be").hex().upper()
                out.append("BT /F2 %g Tf 1 0 0 1 %g %g Tm <FEFF%s> Tj ET" % (size, x, base, hexs))
            else:
                asc, miss = _pdf_ascii(run)
                lost.extend(miss)
                if asc:
                    out.append("BT /F1 %g Tf 1 0 0 1 %g %g Tm (%s) Tj ET" % (size, x, base, asc))
            x += _txt_w(run, size)
        return "\n".join(out)

    def emit(p):
        return (rect(p) if p["op"] == "rect" else line(p) if p["op"] == "line" else
                circle(p) if p["op"] == "circle" else poly(p) if p["op"] == "poly" else
                text(p) if p["op"] == "text" else "")

    for group in (P, M):
        ops += [emit(p) for p in group]
    for e, pr in EG:
        ops += [emit(p) for p in pr]
    for e, pr in NG:
        ops += [emit(p) for p in pr]
    ops += [emit(p) for p in L]
    stream = ("\n".join(ops) + "\n").encode("latin-1", "replace")
    W = lay["cv"]["w"]
    # ToUnicode: identity mapping UCS2 -> UTF-16BE code point, so extraction works without the font
    tounicode = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
                 "/CMapName /q04-UCS2 def /CMapType 2 def\n"
                 "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
                 "1 beginbfrange <0000> <FFFF> <0000> endbfrange\n"
                 "endcmap CMapName currentdict /CMap defineresource pop end end")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.2f} {H:.2f}] /Resources "
             f"<< /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>").encode("latin-1"),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            (f"<< /Type /Font /Subtype /Type0 /BaseFont /{CJK_FALLBACK_FONT} "
             f"/Encoding /UniGB-UCS2-H /DescendantFonts [7 0 R] /ToUnicode 8 0 R >>").encode("latin-1"),
            (f"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /{CJK_FALLBACK_FONT} "
             f"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> "
             f"/FontDescriptor 9 0 R /DW 1000 >>").encode("latin-1"),
            b"<< /Length " + str(len(tounicode)).encode() + b" >>\nstream\n" +
            tounicode.encode("latin-1") + b"\nendstream",
            (f"<< /Type /FontDescriptor /FontName /{CJK_FALLBACK_FONT} /Flags 4 /FontBBox "
             f"[0 -120 1000 880] /ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 700 "
             f"/StemV 80 >>").encode("latin-1")]
    out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode("latin-1") + body + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (len(objs) + 1)).encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref)).encode()
    open(path, "wb").write(bytes(out))
    return {"engine": "stdlib-vector", "non_ascii_dropped": lost, "cjk_chars_written": cjk_chars,
            "rounded_corners_flattened": True,
            "note": "text is written as real Tj operators; the CJK base font is not embedded "
                    "(no font file may ship), so a viewer without CJK packs substitutes it — the "
                    "ToUnicode CMap keeps the text extractable and selectable either way"}


def _canvas_px(lay, dpi):
    k = dpi / 72.0                              # the layout is in PDF points
    return (max(1, int(round(lay["cv"]["w"] * k))), max(1, int(round(lay["cv"]["h"] * k))), k)


def _has_cjk(spec):
    return any(_is_cjk(c) for e in spec.get("entities") or [] for c in str(e.get("label") or "")) or \
           any(_is_cjk(c) for e in spec.get("edges") or [] for c in str(e.get("origin") or "")) or \
           _is_cjk(str((spec.get("figure") or {}).get("title") or ""))


def png_export(spec, lay, path, dpi=300):
    """PNG at the requested dpi, from the best available engine, each fallback named in the record.

    Ladder: cairosvg (renders the exact SVG) -> matplotlib (the same primitive list, real fonts) ->
    rsvg-convert / inkscape (the SVG) -> a zlib rasteriser of the primitive list, which draws exact
    shapes plus a 5x7 bitmap alphabet. The last one has no CJK font, so it substitutes a placeholder
    for non-ASCII glyphs and says so in `writer.glyph_substitutions`."""
    import subprocess, tempfile
    w, h, _k = _canvas_px(lay, dpi)
    svg_path = os.path.join(tempfile.gettempdir(), "q04-export-%d.svg" % os.getpid())
    open(svg_path, "w", encoding="utf-8", newline="\n").write(
        svg(spec, lay, json.dumps({"case_id": spec.get("case_id")}, ensure_ascii=False)))
    try:
        import cairosvg
        cairosvg.svg2png(url=svg_path, write_to=path, output_width=w, output_height=h)
        return {"engine": "cairosvg (real font rasterisation)", "glyph_substitutions": 0,
                "substitutions": []}
    except Exception:
        pass
    try:
        if (not _has_cjk(spec)) or _cjk_font_available():
            return png_matplotlib(spec, lay, path, dpi)
    except Exception:
        pass
    for exe, argv in (("rsvg-convert", ["rsvg-convert", "-w", str(w), "-h", str(h), "-o", path, svg_path]),
                      ("inkscape", ["inkscape", svg_path, "-w", str(w), "-h", str(h), "-o", path])):
        try:
            r = subprocess.run(argv, capture_output=True, timeout=120)
            if r.returncode == 0 and os.path.isfile(path):
                return {"engine": exe + " (real font rasterisation)", "glyph_substitutions": 0,
                        "substitutions": []}
        except Exception:
            continue
    return png_stdlib(spec, lay, path, dpi)


def _cjk_font_available():
    try:
        from matplotlib import font_manager
    except Exception:
        return False
    names = {f.name for f in font_manager.fontManager.ttflist}
    return any(c in names for c in CJK_CANDIDATES)


def png_matplotlib(spec, lay, path, dpi=300):
    """Rasterise the same primitive list with matplotlib, which draws real glyphs."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle as MplCircle, Polygon as MplPoly, Rectangle as MplRect
    W, H = lay["cv"]["w"], lay["cv"]["h"]
    hits = [c for c in CJK_CANDIDATES if c in {f.name for f in font_manager.fontManager.ttflist}]
    if hits:
        plt.rcParams["font.family"] = hits + ["DejaVu Sans", "sans-serif"]
        plt.rcParams["axes.unicode_minus"] = False
    fig = plt.figure(figsize=(W / 72.0, H / 72.0), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    def draw(p):
        op = p["op"]
        if op == "rect":
            ax.add_patch(MplRect((p["x"], p["y"]), p["w"], p["h"],
                                 facecolor=p.get("fill") or "none",
                                 edgecolor=p.get("stroke") or "none",
                                 linewidth=p.get("sw") or 0.6))
        elif op == "line":
            ln = Line2D([p["x1"], p["x2"]], [p["y1"], p["y2"]], color=p.get("stroke") or "#000000",
                        linewidth=p.get("sw") or 1.0, solid_capstyle="round")
            if p.get("dash"):
                ln.set_dashes([float(x) for x in str(p["dash"]).split()])
            ax.add_line(ln)
        elif op == "circle":
            ax.add_patch(MplCircle((p["cx"], p["cy"]), p["r"], facecolor=p.get("fill") or "none",
                                   edgecolor=p.get("stroke") or "none",
                                   linewidth=p.get("sw") or 0.6))
        elif op == "poly":
            pts = list(p["pts"])
            if p.get("closed", True):
                ax.add_patch(MplPoly(pts, closed=True, facecolor=p.get("fill") or "none",
                                     edgecolor=p.get("stroke") or "none",
                                     linewidth=p.get("sw") or 0.6))
            else:
                ax.add_line(Line2D([q[0] for q in pts], [q[1] for q in pts],
                                   color=p.get("stroke") or "#000000",
                                   linewidth=p.get("sw") or 1.0))
        elif op == "text":
            ax.text(p["x"], p["y"], str(p["s"]), fontsize=p["size"], color=p.get("fill") or "#1A1A1A",
                    ha={"middle": "center"}.get(p.get("anchor"), p.get("anchor") or "left"),
                    va="baseline", style="italic" if p.get("italic") else "normal")

    P, M, EG, NG, L = prims(spec, lay)
    for group in (P, M):
        for p in group:
            draw(p)
    for e, pr in EG + NG:
        for p in pr:
            draw(p)
    for p in L:
        draw(p)
    fig.savefig(path, format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    return {"engine": "matplotlib (real font rasterisation)%s"
                      % (" with %s" % hits[0] if hits else ""),
            "glyph_substitutions": 0, "substitutions": [],
            "rounded_corners_flattened": True}


def png_stdlib(spec, lay, path, dpi=300):
    """zlib-only rasteriser of the same primitive list. Shapes are exact; glyphs come from a 5x7
    bitmap alphabet for ASCII, and a label that cannot be drawn is replaced by its entity id."""
    import zlib
    w, h, k = _canvas_px(lay, dpi)
    buf = bytearray(b"\xff" * (w * h * 3))

    def px(x0, y0, x1, y1, col):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(w, int(x1)), min(h, int(y1))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(col) * (x1 - x0)
        for yy in range(y0, y1):
            o = (yy * w + x0) * 3
            buf[o:o + (x1 - x0) * 3] = row

    def dot(cx, cy, r, col):
        px(cx - r, cy - r, cx + r, cy + r, col)

    def seg(x1, y1, x2, y2, sw, col):
        ln = math.hypot(x2 - x1, y2 - y1)
        steps = int(ln / max(0.5, sw / 3.0)) + 1
        for i in range(steps + 1):
            t = i / steps
            dot(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, max(1.0, sw / 2.0), col)

    def polyfill(pts, col, stroke=None, sw=1.0):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        for yy in range(int(min(ys)) - 1, int(max(ys)) + 2):
            xs_hit = []
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                if (a[1] <= yy < b[1]) or (b[1] <= yy < a[1]):
                    xs_hit.append(a[0] + (yy - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
            xs_hit.sort()
            for i in range(0, len(xs_hit) - 1, 2):
                px(xs_hit[i], yy, xs_hit[i + 1], yy + 1, col)
        if stroke:
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                seg(a[0], a[1], b[0], b[1], sw, stroke)

    def draw_text(p):
        size, s = p["size"] * k * 1.0, str(p["s"])
        scale = max(1, int(round(size / 8.0)))
        col = _rgb_int(p.get("fill") or "#1A1A1A")
        cw = 6 * scale
        total = cw * len(s)
        x0 = p["x"] * k
        if p.get("anchor") == "middle":
            x0 -= total / 2
        elif p.get("anchor") == "end":
            x0 -= total
        y0 = (p["y"] * k) - 7 * scale
        subs = 0
        for i, ch in enumerate(s):
            rows = FONT57.get(ch.upper()) or FONT57.get("?")
            if _is_cjk(ch):
                subs += 1
                rows = FONT57["?"]                     # honest placeholder, substitution reported
            for ry in range(7):
                bits = int(rows[ry * 2:ry * 2 + 2], 16)
                for rx in range(5):
                    if bits & (1 << (4 - rx)):
                        px(x0 + i * cw + rx * scale, y0 + ry * scale,
                           x0 + i * cw + (rx + 1) * scale, y0 + (ry + 1) * scale, col)
        return subs

    def draw(p):
        op = p["op"]
        if op == "rect":
            fill = _rgb_int(p.get("fill") or "#FFFFFF")
            px(p["x"] * k, p["y"] * k, (p["x"] + p["w"]) * k, (p["y"] + p["h"]) * k, fill)
            if p.get("stroke"):
                sc = _rgb_int(p["stroke"])
                sw = max(1.0, (p.get("sw") or 1.0) * k)
                for a, b, c, d in ((p["x"], p["y"], p["x"] + p["w"], p["y"]),
                                   (p["x"], p["y"] + p["h"], p["x"] + p["w"], p["y"] + p["h"]),
                                   (p["x"], p["y"], p["x"], p["y"] + p["h"]),
                                   (p["x"] + p["w"], p["y"], p["x"] + p["w"], p["y"] + p["h"])):
                    seg(a * k, b * k, c * k, d * k, sw, sc)
        elif op == "line":
            seg(p["x1"] * k, p["y1"] * k, p["x2"] * k, p["y2"] * k,
                max(1.0, (p.get("sw") or 1.0) * k), _rgb_int(p.get("stroke") or "#000000"))
        elif op == "circle":
            cx, cy, r = p["cx"] * k, p["cy"] * k, p["r"] * k
            col = _rgb_int(p.get("stroke") or "#000000")
            n = max(12, int(r * 6))
            for i in range(n):
                a1 = 2 * math.pi * i / n
                a2 = 2 * math.pi * (i + 1) / n
                seg(cx + r * math.cos(a1), cy + r * math.sin(a1),
                    cx + r * math.cos(a2), cy + r * math.sin(a2), max(1.0, (p.get("sw") or 1.0) * k), col)
        elif op == "poly":
            pts = [(a * k, b * k) for a, b in p["pts"]]
            fill = _rgb_int(p["fill"]) if p.get("fill") else None
            if fill and p.get("closed", True):
                polyfill(pts, fill)
            for i in range(len(pts) - (0 if p.get("closed", True) else 1)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                seg(a[0], a[1], b[0], b[1], max(1.0, (p.get("sw") or 1.0) * k),
                    _rgb_int(p.get("stroke") or "#000000"))
        elif op == "text":
            return draw_text(p)
        return 0

    P, M, EG, NG, L = prims(spec, lay)
    subs = 0
    for group in (P, M):
        for p in group:
            subs += draw(p)
    for e, pr in EG + NG:
        for p in pr:
            subs += draw(p)
    for p in L:
        subs += draw(p)
    raw = bytearray()
    for yy in range(h):
        raw += b"\x00" + buf[(yy * w) * 3:(yy * w + w) * 3]

    def chunk(typ, data):
        return (len(data).to_bytes(4, "big") + typ + data +
                (zlib.crc32(typ + data) & 0xFFFFFFFF).to_bytes(4, "big"))
    ppm = int(round(dpi / 0.0254))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n"
                           + chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big")
                                   + bytes([8, 2, 0, 0, 0]))
                           + chunk(b"pHYs", ppm.to_bytes(4, "big") + ppm.to_bytes(4, "big") + b"\x01")
                           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                           + chunk(b"IEND", b""))
    return {"engine": "stdlib-zlib rasteriser", "glyph_substitutions": subs,
            "substitutions": (["%d non-ASCII glyph(s) replaced by a placeholder: the stdlib engine "
                               "has no CJK font; use the SVG/PDF or install cairosvg" % subs]
                              if subs else []),
            "rounded_corners_flattened": True}


def _rgb_int(hex_colour):
    r, g, b = _rgb(hex_colour)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def pdf_content(raw):
    """Concatenated content streams, inflated when the writer flate-compressed them."""
    import zlib
    out = []
    for m in re.finditer(rb"stream\r?\n", raw):
        end = raw.find(b"endstream", m.end())
        if end < 0:
            continue
        try:
            out.append(zlib.decompress(raw[m.end():end]))
        except Exception:
            out.append(raw[m.end():end])
    return b"\n".join(out)


def measure_pdf(path):
    """What is really inside the produced PDF — read back from the bytes, never from intent."""
    raw = open(path, "rb").read()
    content = pdf_content(raw)
    out = {"path": os.path.basename(path), "bytes": len(raw), "sha256": file_sha(path),
           "header": raw[:8].decode("latin-1", "replace").strip(),
           "pages": len(re.findall(rb"/Type\s*/Page\b", raw)),
           "text_show_ops": len(re.findall(rb"\bT[jJ]\b", content)),
           "fonts": sorted({f.decode("latin-1") for f in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-]+)", raw)}),
           "font_embedded": bool(re.search(rb"/FontFile[23]", raw)),
           "to_unicode": bool(re.search(rb"/ToUnicode", raw)),
           "image_xobjects": len(re.findall(rb"/Subtype\s*/Image", raw)),
           "vector": not re.search(rb"/Subtype\s*/Image", raw)}
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)
    if m:
        pt = [float(m.group(1)), float(m.group(2))]
        out["media_box_pt"] = pt
        out["media_box_mm"] = [round(pt[0] / 72 * 25.4, 1), round(pt[1] / 72 * 25.4, 1)]
        out["media_box_in"] = [round(pt[0] / 72, 2), round(pt[1] / 72, 2)]
    return out


def measure_png(path):
    """IHDR / pHYs / chunk list read straight out of the produced PNG."""
    raw = open(path, "rb").read()
    out = {"path": os.path.basename(path), "bytes": len(raw), "sha256": file_sha(path),
           "signature_ok": raw[:8] == b"\x89PNG\r\n\x1a\n", "chunks": []}
    i = 8
    while out["signature_ok"] and i + 8 <= len(raw):
        ln = int.from_bytes(raw[i:i + 4], "big")
        typ = raw[i + 4:i + 8].decode("latin-1")
        data = raw[i + 8:i + 8 + ln]
        out["chunks"].append(typ)
        if typ == "IHDR":
            out["width_px"] = int.from_bytes(data[0:4], "big")
            out["height_px"] = int.from_bytes(data[4:8], "big")
            out["bit_depth"], out["colour_type"] = data[8], data[9]
        elif typ == "pHYs":
            out["dpi_metadata"] = [round(int.from_bytes(data[0:4], "big") * 0.0254, 1),
                                   round(int.from_bytes(data[4:8], "big") * 0.0254, 1)]
        i += 12 + ln
        if typ == "IEND":
            break
    return out


def export_all(spec, lay, out_dir, dpi=300):
    """Write figure.pdf and figure.png, then measure both from their bytes."""
    pdf_path = os.path.join(out_dir, "figure.pdf")
    png_path = os.path.join(out_dir, "figure.png")
    pinfo = pdf_export(spec, lay, pdf_path)
    ninfo = png_export(spec, lay, png_path, dpi)
    pm, nm = measure_pdf(pdf_path), measure_png(png_path)
    w, h, _k = _canvas_px(lay, dpi)
    return {"svg": {"path": "figure.svg", "bytes": os.path.getsize(os.path.join(out_dir, "figure.svg")),
                    "editable": True,
                    "sha256": file_sha(os.path.join(out_dir, "figure.svg"))},
            "pdf": dict(pm, writer=pinfo, page_is_the_figure_coordinate_system=True),
            "png": dict(nm, writer=ninfo, dpi_requested=dpi, pixels_expected=[w, h]),
            "raster": {"produced": True, "backend": ninfo.get("engine"),
                       "why": "PDF and PNG are written at run time from the same primitive list as "
                              "the SVG, then re-read and measured (MediaBox / Tj count / image "
                              "xobjects / IHDR + pHYs); no binary ships inside the Skill package"},
            "checks": {"pdf_is_vector": pm.get("vector") is True,
                       "pdf_page_matches_canvas": [round(x, 2) for x in pm.get("media_box_pt", [])]
                       == [round(lay["cv"]["w"], 2), round(lay["cv"]["h"], 2)],
                       "pdf_has_selectable_text": pm.get("text_show_ops", 0) > 0,
                       "pdf_fonts_embedded": bool(pm.get("font_embedded")),
                       "png_size_matches_dpi": abs((nm.get("width_px") or 0) - w) <= 1 and
                       abs((nm.get("height_px") or 0) - h) <= 1,
                       "png_dpi_metadata_matches": nm.get("dpi_metadata") == [round(dpi, 1)] * 2}}


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


if __name__ == "__main__":
    sys.exit(main())
