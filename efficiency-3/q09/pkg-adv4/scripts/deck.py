"""deck.py — minimal academic deck kit (one file, one command)"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, time, zipfile
sys.dont_write_bytecode = True
try:
    from pptx import Presentation
    from pptx.util import Emu, Pt
    from pptx.enum.text import PP_ALIGN
except Exception:
    Presentation = None
NUM = re.compile(r"(?<![\d.])[-+]?\d+(?:\.\d+)?\s?(?:%|ms|s|h|GB|M|K|B|F1)?")
PH = {1: "title", 2: "body", 3: "ctitle", 4: "subtitle", 7: "object", 15: "footer",
      13: "slideno", 16: "date"}
TT = {"question": "研究问题与缺口", "method": "方法", "results": "结果",
      "limits": "限制与不确定性", "conclusion": "结论与下一步", "backup": "备用页"}
ROLES = ("question", "method", "results", "results", "limits", "conclusion")

def jd(p, o):
    if os.path.dirname(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def cl(t):
    t = re.sub(r"_x[0-9A-Fa-f]{4}_|[\ue000-\uf8ff\x00-\x08\x0b-\x1f\x7f]", " ", t or "")
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", " ", t)).strip()

LIG = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
       "\ufb04": "ffl", "\u00ad": ""}
def _norm(t):
    t = t or ""
    for k, v in LIG.items():
        t = t.replace(k, v)
    for k, v in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2010", "-"), ("\u2011", "-"), ("\u2012", "-"), ("\u2013", "-"),
                 ("\u2014", "-"), ("\u2212", "-")):
        t = t.replace(k, v)
    return re.sub(r"\s+", " ", t).strip()

def _flat(t):
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", _norm(t).lower())

def mtext(src):
    """normalised material text used to decide verbatim / 改写 in the notes."""
    if not src:
        return {"norm": "", "flat": ""}
    joined = _norm(" ".join((b.get("text") or "") for b in src.get("blocks") or []))
    return {"norm": joined, "flat": _flat(joined)}

def verbatim(t, mat):
    """True when t can be found verbatim in the material (hyphenation tolerated)."""
    if not t or not mat.get("norm"):
        return False
    if _norm(t) in mat["norm"]:
        return True
    f = _flat(t)
    return bool(f) and f in mat.get("flat", "")

def fp(p):
    if not p or not os.path.isfile(p) or Presentation is None:
        return {}
    prs = Presentation(p)
    d = {"size": [int(prs.slide_width), int(prs.slide_height)], "layouts": []}
    for lo in prs.slide_layouts:
        d["layouts"].append([lo.name] + sorted(
            [int(x.placeholder_format.idx), int(x.left or 0), int(x.top or 0),
             int(x.width or 0), int(x.height or 0)] for x in lo.placeholders))
    try:
        d["fonts"] = sorted(set(re.findall(r'typeface="([^"]+)"', zipfile.ZipFile(p)
                            .read("ppt/theme/theme1.xml").decode("utf-8", "replace"))))
    except Exception:
        d["fonts"] = []
    return d

def cfields(case):
    for k in ("output_contract", "outputContract", "contract", "outputs"):
        n = case.get(k)
        if isinstance(n, dict) and isinstance(n.get("properties"), dict):
            return list(n["properties"])
        if isinstance(n, dict):
            n = n.get("fields", n)
            if isinstance(n, dict) and n:
                return [x for x in n if not str(x).startswith("_")]
        if isinstance(n, list) and n and isinstance(n[0], dict):
            return [x for x in n[0] if not str(x).startswith("_")]
    for v in case.values():
        if isinstance(v, dict):
            got = cfields(v)
            if got:
                return got
    return []

def cget(case, *names):
    for src in [case] + [v for v in case.values() if isinstance(v, dict)]:
        for k, v in src.items():
            if str(k).lower() in names and isinstance(v, (int, float, str)):
                return v
    return None

def iscase(p):
    try:
        h = open(p, "rb").read(20000).decode("utf-8", "replace").lower()
    except Exception:
        return False
    return "{" in h and ("case_id" in h or "output_contract" in h)

ENV_JSON_PAT = re.compile(r"(^|[._\-])(example|sample|rubric|template|expected|golden|"
                          r"answer)([._\-]|$)")

def deny_json_by_name(p):
    """the same anchored policy for the page-plan / edit-instruction JSON files: a
    plan called 'case-plan.json' is still a plan, so 'case' alone must not veto it."""
    low = os.path.basename(p or "").lower()
    if low == "case.json":
        return True, "the file is a case descriptor, not a page plan"
    if ENV_JSON_PAT.search(low):
        return True, ("the file name marks it as an example/template document (not a "
                      "page plan or an edit script)")
    return False, ""

def usable_spec(p):
    """(ok, obj|why) — a page plan is only accepted if it really is one."""
    if not p:
        return False, "unset"
    denied, why = deny_json_by_name(p)
    if denied:
        return False, why + ": a stray JSON in /input must not become the page plan"
    if iscase(p):
        return False, "the file is a case descriptor, not a page plan"
    try:
        obj = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return False, "not readable JSON: %s" % str(e)[:60]
    if not isinstance(obj, dict):
        return False, "a page plan must be a JSON object"
    slides = obj.get("slides")
    if not isinstance(slides, list) or not slides or \
            not all(isinstance(x, dict) and ("role" in x or "title" in x) for x in slides):
        return False, ("a page plan must carry a non-empty slides[] list of objects "
                       "with role/title: the file does not look like one")
    return True, obj

def usable_ops(p):
    """(ok, ops|why) — edit instructions must be a list of op objects."""
    if not p:
        return False, "unset"
    denied, why = deny_json_by_name(p)
    if denied:
        return False, why
    try:
        obj = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return False, "not readable JSON: %s" % str(e)[:60]
    ops = obj.get("ops") if isinstance(obj, dict) else obj
    if not isinstance(ops, list) or not ops or \
            not all(isinstance(x, dict) and x.get("op") for x in ops):
        return False, ("edit instructions must be a list of objects carrying an 'op' "
                       "key: the file does not look like one")
    return True, ops

def usable_pptx(p):
    if not p:
        return False, "unset"
    if Presentation is None:
        return False, "python-pptx is unavailable"
    try:
        Presentation(p)
        return True, os.path.basename(p)
    except Exception as e:
        return False, "not a readable .pptx: %s" % str(e)[:60]

def resolve(v, base, cwd):
    if not isinstance(v, str) or not v:
        return None, "unset"
    if os.path.isabs(v):
        return (v, "absolute") if os.path.isfile(v) else (None, "absolute-missing")
    for tag, root in (("case_dir", base), ("cwd", cwd or "."), ("/input", "/input")):
        p = os.path.join(root, v)
        if os.path.isfile(p):
            return p, tag
    return None, "missing"

# --- evidence policy -------------------------------------------------------------
# Only research material may become the citation corpus.  The task sheet, the case
# file, the package docs, templates, plans and edit instructions are NOT evidence:
# if one of them entered the corpus, every quote/number check would be certifying
# the assignment text against itself (structural false green).
#
# The name rule is deliberately ANCHORED, not substring: a real paper called
# case-study-routing.md / case_report.md / task_notes.md IS material (we do not know
# what the organizer will name the fixed-case material, and rejecting real material is
# worse than letting a suspicious name through — the content sniff below still catches
# an actual task sheet).  Only an exact work-order basename or an explicit
# example/template/schema suffix is refused by name.
EVIDENCE_EXT = (".pdf", ".md", ".markdown", ".txt", ".text")
DENY_EXACT = {"case.json", "case.md", "case.txt", "task.md", "task.json", "task.txt",
              "readme.md", "readme.txt", "rubric.md", "rubric.json", "skill.md",
              "method.md", "notes.md", "benchmark.md", "benchmark.json",
              "deck-rules.md", "prompt.md", "instructions.md"}
DENY_SUFFIX = (".example.json", ".example.md", ".example.txt", ".template.json",
               ".template.md", ".template.txt", ".schema.json", ".schema.md")
DENY_NAME_RE = re.compile(r"^template[-_](spec|plan|deck)[^.]*\.(json|md|txt)$")

def deny_by_name(n):
    """(denied?, why) — anchored matching only, never a bare substring."""
    low = (n or "").lower()
    if low in DENY_EXACT:
        return True, "the file is the task sheet or a package document, not material"
    for s in DENY_SUFFIX:
        if low.endswith(s):
            return True, ("the file name marks it as an example/template/schema file "
                          "(%s)" % s)
    if DENY_NAME_RE.match(low):
        return True, "the file name marks it as a template spec/plan"
    return False, ""

# --- content sniff -----------------------------------------------------------------
# The name rule is only a hint; the CONTENT decides whether a file is a work order.
# Only CONTRACT-EXCLUSIVE words are decisive: they describe a submission contract
# (deliver this, submit that), which a paper does not talk about.  Grading vocabulary
# (评分维度 / 评分点 / 评分细则 / grader / rubric / prepared answer / case_id / task_id)
# is corroborating evidence and is REPORTED, but never decisive on its own: a Chinese
# evaluation paper describing its own annotation scheme, or an NLP paper about
# prepared answers, must still be read.  Refusing real material zeroes the case, which
# is far worse than missing a work order.
SNIFF_CONTRACT = ("output_contract", "runtime contract", "submission_contract",
                  "deliverable_contract", "提交材料", "收到材料", "提交目录", "交付要求",
                  "交付标准", "提交要求", "提交清单")
SNIFF_DECISIVE = ("do not submit prepared answers", "do not submit prepared answer",
                  "不得提交预制答案", "禁止提交预制答案")
SNIFF_CORROBORATING = ("评分维度", "评分点", "评分细则", "预置答案", "prepared answer",
                       "case_id", "task_id")
SNIFF_WEAK = ("grader", "rubric", "rubrics", "whiteboard", "llm-as-a-judge",
              "judge model")      # reported only, never decisive
SNIFF_MIN_CONTRACT = 2
SNIFF_SCAN_CHARS = 20000

def evidence_sniff(p):
    """(ok, why, detail) — is this file's CONTENT a work order rather than a paper?"""
    n = os.path.basename(p or "").lower()
    ext = os.path.splitext(n)[1]
    detail = {"chars_scanned": 0, "contract_markers": [], "corroborating_markers": [],
              "weak_markers": [], "decisive_phrase": None,
              "threshold": SNIFF_MIN_CONTRACT,
              "rule": ">=%d distinct contract-exclusive markers, or one unambiguous "
                      "submission warning; grading vocabulary (评分维度/评分点/评分细则/"
                      "grader/rubric/prepared answer/case_id/task_id) is corroborating "
                      "only and never decides by itself" % SNIFF_MIN_CONTRACT}
    if ext not in (".md", ".markdown", ".txt", ".text"):
        detail["verdict"] = "not scanned (not a text material)"
        return True, "", detail
    try:
        head = open(p, encoding="utf-8", errors="replace").read(SNIFF_SCAN_CHARS).lower()
    except Exception:
        detail["verdict"] = "not scanned (unreadable)"
        return True, "", detail
    detail["chars_scanned"] = len(head)
    contract = [m for m in SNIFF_CONTRACT if m in head]
    corroborating = [m for m in SNIFF_CORROBORATING if m in head]
    weak = [m for m in SNIFF_WEAK if m in head]
    dec = next((m for m in SNIFF_DECISIVE if m in head), None)
    detail.update({"contract_markers": contract, "corroborating_markers": corroborating,
                   "weak_markers": weak, "decisive_phrase": dec,
                   # legacy keys kept so older report readers still line up
                   "strong_markers": contract,
                   "generic_markers": corroborating + weak})
    if dec:
        detail["verdict"] = "refused (unambiguous submission-warning phrase)"
        return False, ("the file carries the submission warning %r, which a paper does "
                       "not contain" % dec), detail
    if len(contract) >= SNIFF_MIN_CONTRACT:
        detail["verdict"] = "refused (%d contract-exclusive markers)" % len(contract)
        return False, ("the file reads like a work order: %d contract-exclusive markers "
                       "(%s)" % (len(contract), ", ".join(contract[:6]))), detail
    detail["verdict"] = ("accepted (%d/%d contract-exclusive markers; %d grading "
                         "word(s) recorded but not decisive)"
                         % (len(contract), SNIFF_MIN_CONTRACT,
                            len(corroborating) + len(weak)))
    return True, "", detail

def evidence_ok(p):
    """(ok, why) — may this file be used as the citation corpus?"""
    n = os.path.basename(p or "").lower()
    ext = os.path.splitext(n)[1]
    if ext not in EVIDENCE_EXT:
        return False, ("not a paper/text material (extension %s): a .json/.pptx/.png "
                       "input is an instruction or an artifact, never evidence"
                       % (ext or "none"))
    denied, why = deny_by_name(n)
    if denied:
        return False, why
    ok, why, _ = evidence_sniff(p)
    return ok, why

def find(d, case, cwd="."):
    f = {"material": None, "template": None, "deck": None, "ops": None, "spec": None,
         "resolved_from": {}, "missing": [], "rejected": [], "candidates": [],
         "sniff": {}}
    mats, tags = [], {}

    def take(p, where, seen_as):
        ok, why = evidence_ok(p)
        ok2, why2, det = evidence_sniff(p)
        if det:
            f["sniff"][os.path.basename(p)] = dict(det, accepted=bool(ok))
        if ok:
            mats.append((p, where))
        else:
            f["rejected"].append({"file": os.path.basename(p), "why": why,
                                  "seen_as": seen_as})

    for n in sorted(os.listdir(d)):
        p, low = os.path.join(d, n), n.lower()
        if os.path.isdir(p):
            continue
        if low.endswith(".json") and low != "case.json" and not iscase(p):
            f["spec" if "plan" in low or "spec" in low else "ops"] = p
            tags["spec" if "plan" in low or "spec" in low else "ops"] = "case_dir"
        elif low.endswith(".pptx"):
            k = "deck" if "start" in low or "existing" in low else "template"
            f[k], tags[k] = p, "case_dir"
        elif low.endswith((".pdf", ".md", ".markdown", ".txt", ".text")):
            take(p, "case_dir", "file in the input directory")
    for k, s in (("template", "template"), ("starting_deck", "deck"), ("deck", "deck"),
                 ("ops", "ops"), ("edits", "ops"), ("deck_plan", "spec")):
        v = case.get(k)
        if isinstance(v, str):
            p, where = resolve(v, d, cwd)
            if p:
                f[s], tags[s] = p, where
            else:
                f["missing"].append({"key": k, "value": v, "where": where})
    m = case.get("materials")
    for x in ([m] if isinstance(m, str) else (m or [])):
        p, where = resolve(str(x), d, cwd)
        if p:
            take(p, where, "named in case.json materials")
        else:
            f["missing"].append({"key": "materials", "value": str(x), "where": where})
    # a full paper is bigger than a task sheet, so size sorts descending inside the
    # same class; PDFs always come first
    mats = sorted(set(mats), key=lambda t: (not t[0].lower().endswith(".pdf"),
                                            -os.path.getsize(t[0]), t[0]))
    f["candidates"] = [os.path.basename(p) for p, _ in mats]
    if mats:
        f["material"], tags["material"] = mats[0][0], mats[0][1]

    # a stray JSON / pptx in the input directory must not silently become the page
    # plan, the edit script or the template: validate, then reject with a reason
    for key, check in (("spec", usable_spec), ("ops", usable_ops),
                       ("template", usable_pptx), ("deck", usable_pptx)):
        if not f[key]:
            continue
        ok, res = check(f[key])
        if ok:
            if key in ("spec", "ops"):
                f[key + "_obj"] = res
            continue
        f["rejected"].append({"file": os.path.basename(f[key]),
                              "why": "seen as %s but %s" % (key, res),
                              "seen_as": key})
        tags.pop(key, None)
        f[key] = None
    f["resolved_from"] = tags
    return f

def ingest(path, work):
    ok, why = evidence_ok(path)
    s = {"kind": os.path.splitext(path)[1].lstrip(".").lower(), "parser": "text",
         "pages": 1, "path": os.path.basename(path), "blocks": [], "numbers": [],
         "limits": [], "notes": [],
         "corpus": {"trusted": bool(ok), "policy": "only paper/text material may be "
                                                   "the citation corpus", "why": why},
         "sha256_16": hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]}
    if not ok:
        s["limits"].append("refused as an evidence corpus: %s" % why)
        jd(os.path.join(work, "source.json"), s)
        return s
    if s["kind"] == "pdf":
        try:
            import fitz
            doc = fitz.open(path)
            s["parser"], s["pages"] = "pymupdf", doc.page_count
            for i in range(doc.page_count):
                ln = [cl("".join(x.get("text", "") for x in l.get("spans", [])))
                      for b in doc[i].get_text("dict").get("blocks", [])
                      if b.get("type") == 0 for l in b.get("lines", [])]
                ln = [x for x in ln if x]
                if ln:
                    s["blocks"].append({"id": "p%d.b%d" % (i + 1, len(s["blocks"])),
                                        "page": i + 1, "text": cl(" ".join(ln))})
            doc.close()
        except Exception as e:
            s["limits"].append("PDF text unavailable (PyMuPDF missing or unreadable): %s"
                               % str(e)[:70])
        if not any(b["text"] for b in s["blocks"]):
            s["limits"].append("no extractable text layer (scanned PDF?): the plan keeps "
                               "only its skeleton and says so")
    else:
        s["kind"] = "markdown" if s["kind"] in ("md", "markdown") else "text"
        for i, para in enumerate(x for x in re.split(
                r"\n\s*\n", open(path, encoding="utf-8", errors="replace").read())
                if x.strip()):
            s["blocks"].append({"id": "p1.b%d" % i, "page": 1, "text": cl(para)})
        s["notes"].append("text material: no page geometry; anchors carry block ids "
                          "instead of page numbers")
    s["numbers"] = [{"value": m.group(0).strip().replace(" ", ""), "page": b["page"],
                     "block_id": b["id"]} for b in s["blocks"]
                    for m in NUM.finditer(b["text"]) if re.search(r"\d", m.group(0))]
    jd(os.path.join(work, "source.json"), s)
    return s

def plan(src, c):
    zh = not str(c.get("lang") or "zh").lower().startswith("en")
    bud, mins = int(c.get("count") or 10), float(c.get("minutes") or 12)
    roles = list(ROLES)
    while len(roles) + 2 > bud and len(roles) > 1:      # honor a small slide_count
        for r in ("results", "limits", "conclusion", "question"):
            if roles.count(r) > 1:
                roles.remove(r)
                break
        else:
            roles.pop()
    for _ in range(max(0, bud - 2 - len(roles))):
        roles.insert(-2, "results") if roles.count("results") < 4 else roles.append("backup")
    title = c.get("title") or os.path.splitext(src["path"])[0]
    sl = [{"index": 1, "role": "title", "title": title, "bullets": [], "claim": "",
           "subtitle": "%s · %g min" % (c.get("audience") or "-", mins),
           "notes": "开场 30 秒：题目 + 一句话结论。"},
          {"index": 2, "role": "outline", "title": "讲解路线" if zh else "Outline",
           "claim": "先问题、再方法、后证据，最后交代边界。", "notes": "",
           "bullets": [{"text": TT[r], "anchor": {"source": "plan"}}
                       for r in dict.fromkeys(roles)]}]
    cands = [{"text": x.strip(), "anchor": {"source": src["path"], "page": b["page"],
                                            "block_id": b["id"], "quote": x.strip()}}
             for b in src["blocks"]
             for x in re.split(r"(?<=[.!?。！？])\s+", b["text"])
             if 30 <= len(x.strip()) <= 260]
    if not cands:
        cands = [{"text": b["text"][:260], "anchor": {"source": src["path"],
                                                      "page": b["page"],
                                                      "block_id": b["id"],
                                                      "quote": b["text"][:260]}}
                 for b in src["blocks"] if len(b["text"].strip()) >= 20]
    cands.sort(key=lambda b: (0 if re.search(r"[.。!?！？)]$", b["text"]) else 1,
                            0 if re.search(r"\d", b["text"]) else 1, -len(b["text"])))
    pool, seen = [], set()
    for b in cands:
        if b["anchor"]["block_id"] + b["text"][:12] not in seen:
            seen.add(b["anchor"]["block_id"] + b["text"][:12])
            pool.append(b)
    # spread the pool across the content pages instead of filling the early ones and
    # leaving the tail empty (QA-round-20261124 P1-1: pages 6-8 came out as blank
    # bodies).  Round-robin: every role gets one sentence before any role gets two, so
    # the conclusion never ends up empty while an early page holds four quotes.
    n_content = max(1, len(roles))
    cap = max(1, min(4, -(-len(pool) // n_content))) if pool else 1
    buckets = [[] for _ in roles]
    chars = [0] * len(roles)
    idx = 0
    for _ in range(cap):
        for j in range(len(roles)):
            if idx >= len(pool):
                break
            if chars[j] + len(pool[idx]["text"]) > 420 and buckets[j]:
                continue        # keep the page inside its text box (see build())
            buckets[j].append(pool[idx])
            chars[j] += len(pool[idx]["text"])
            idx += 1
    unfilled = []
    for j, role in enumerate(roles):
        k, n, got = roles[:j].count(role), roles.count(role), buckets[j]
        rec_role = role
        if not got:
            rec_role = "backup"                 # declared, not silent: see below
            unfilled.append(len(sl) + 1)
        sl.append({"index": len(sl) + 1, "role": rec_role,
                   "title": TT[rec_role] + ("" if (n == 1 or rec_role == "backup")
                                            else " (%d/%d)" % (k + 1, n)),
                   "claim": ("" if got else
                             "材料中已无更多可逐字引用的整句，本页声明为答疑/备用页"),
                   "bullets": got,
                   "notes": ("" if got else
                             "材料中已无更多可逐字引用的整句；本页不作任何主张。")})
    left = len(pool) - idx
    rep = {"_comment": "auto plan; text may be rewritten, anchors/numbers must stay "
                       "traceable", "title": title, "audience": c.get("audience"),
           "language": c.get("lang") or "zh", "source": {"path": src["path"]},
           "slide_budget": bud, "plan_warnings": list(src["limits"][:4]),
           "unfilled_pages": unfilled,
           "per_page_bullet_cap": cap, "pool_size": len(pool),
           "bullets_left_unused": max(0, left),
           "slides": sl}
    if unfilled:
        rep["plan_warnings"].append(
            "the material holds %d citable sentence(s) for %d content page(s): page(s) "
            "%s are declared backup pages ([备份] in the notes), not silent blanks"
            % (len(pool), n_content, ", ".join(str(x) for x in unfilled)))
    return rep

def probe(p):
    t = {"source": os.path.basename(p) if p else None, "layouts": [],
         "safe": {"x": 48, "y": 120, "w": 864, "h": 340}}
    if p and os.path.isfile(p) and Presentation is not None:
        prs = Presentation(p)
        for i, lo in enumerate(prs.slide_layouts):
            sl = {}
            for x in lo.placeholders:
                sl.setdefault(PH.get(int(x.placeholder_format.type), "other"),
                              [float(x.left or 0) / 12700, float(x.top or 0) / 12700,
                               float(x.width or 0) / 12700, float(x.height or 0) / 12700])
            t["layouts"].append({"index": i, "name": lo.name or "", "slots": sl})
        for lo in t["layouts"]:
            if "title" in lo["slots"] and ({"body", "object"} & set(lo["slots"])):
                b = lo["slots"].get("body") or lo["slots"].get("object")
                t["safe"] = {"x": lo["slots"]["title"][0], "y": b[1],
                             "w": lo["slots"]["title"][2], "h": max(60.0, 500.0 - b[1])}
                break
    return t

def master(out):
    import pptx
    shutil.copy2(os.path.join(os.path.dirname(pptx.__file__), "templates",
                              "default.pptx"), out)
    prs = Presentation(out)
    prs.slide_width, prs.slide_height = 12192000, 6858000
    prs.save(out)
    return out

def lay(t, role):
    for w in (("title slide", "title") if role == "title"
              else ("title and content", "content")):
        for lo in t["layouts"]:
            if w in lo["name"].lower():
                return lo["index"]
    return 0

ROLE_SCRIPT = {
    "question": "先交代问题与缺口，再说明为什么值得投入注意力",
    "method": "按材料顺序讲设计选择，每个选择都指向它解决了什么",
    "results": "先给证据句，再给读者怎么读这张表/这组数字",
    "limits": "主动交代边界与不确定性，避免被听众反问",
    "conclusion": "收束成一句可复述的结论，并给出下一步",
    "backup": "预留为答疑页，不主动讲",
}

def auto_script(role, bullets, claim):
    """a speaking scaffold that refers to the quoted sentences and invents nothing."""
    if not bullets:
        return ""
    head = ROLE_SCRIPT.get(role, "按要点顺序讲")
    picks = []
    for b in bullets[:3]:
        t = re.sub(r"\s+", " ", b["text"]).strip()
        picks.append(t if len(t) <= 60 else t[:58] + "…")
    body = "；".join("「%s」" % x for x in picks)
    tail = ("落点：%s。" % claim) if claim else "落点：把这几句原文串成一条判断。"
    return "%s：%s。%s" % (head, body, tail)

def build(spec, tpl, out, work, mat=None):
    prs, t, safe, total = Presentation(tpl), probe(tpl), None, len(spec["slides"])
    t, safe = t, t["safe"]
    mat = mat or {"norm": "", "flat": ""}
    rep = {"slides": [], "warnings": []}
    for s in spec["slides"]:
        role = s.get("role") or "results"
        slide = prs.slides.add_slide(prs.slide_layouts[lay(t, role)])
        p = {}
        notelines = []
        for x in slide.placeholders:
            p.setdefault(PH.get(int(x.placeholder_format.type), "other"), x)
        rec = {"index": s["index"], "role": role}
        if role == "backup" and not (s.get("bullets") or []):
            notelines.append("[备份] 本页无材料整句可引用，声明为备用/答疑页")
        elif s.get("claim"):
            notelines.append("[主张] %s" % s["claim"])
        ti = p.get("title") or p.get("ctitle")
        if ti is not None:
            ti.text_frame.text = s.get("title") or ""
            if role == "title":
                ti.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        if role == "title":
            if p.get("subtitle") is not None:
                p["subtitle"].text_frame.text = s.get("subtitle") or ""
            for k in ("body", "object"):
                if k in p:
                    p[k]._element.getparent().remove(p[k]._element)
        else:
            bl = [b for b in (s.get("bullets") or []) if b.get("text")]
            if bl:
                body = p.get("body") or p.get("object")
                box = body if body is not None else slide.shapes.add_textbox(
                    Emu(int(safe["x"] * 12700)), Emu(int(safe["y"] * 12700)),
                    Emu(int(safe["w"] * 12700)), Emu(int(safe["h"] * 12700)))
                if body is None:
                    box.name = "BodyText"
                h = float(body.height or 0) / 12700 if body is not None else safe["h"]
                need = sum(1 + len(b["text"]) // 22 for b in bl) * 22.0
                # if the page cannot hold these bullets even at the 12 pt floor, DROP
                # bullets from the end instead of clipping text in the export
                # (C14 caught clipped text as a 0.32 text-survival rate)
                dropped = []
                while len(bl) > 1 and need > h - 10:
                    dropped.insert(0, bl.pop())
                    need = sum(1 + len(b["text"]) // 22 for b in bl) * 22.0
                size = round(17.0 if need <= h - 10 else max(12.0, 17.0 * (h - 10) / need), 1)
                box.text_frame.word_wrap = True
                for j, b in enumerate(bl):
                    para = box.text_frame.paragraphs[0] if j == 0 else \
                        box.text_frame.add_paragraph()
                    para.text = b["text"]
                    for r in para.runs:
                        r.font.size = Pt(size)
                rec.update({"bullets": len(bl), "font_pt": size, "fits": need <= h - 10})
                if dropped:
                    rec["dropped_for_fit"] = [x["text"][:40] for x in dropped]
                    rep["warnings"].append({"level": "warn", "slide": s["index"],
                                            "what": "bullets dropped so the page fits "
                                                    "its box instead of clipping",
                                            "dropped": len(dropped),
                                            "kept": len(bl)})
                if need > h - 10:
                    rep["warnings"].append({"level": "error", "slide": s["index"],
                                            "what": "text overflows at the floor size",
                                            "needed_pt": round(need), "box_pt": round(h)})
            keep = ("title", "ctitle", "subtitle", "date", "footer", "slideno")
            if bl:
                keep += ("body", "object")      # the filled body must survive pruning
            for x in list(slide.placeholders):
                if PH.get(int(x.placeholder_format.type), "other") not in keep:
                    x._element.getparent().remove(x._element)
        foot = slide.shapes.add_textbox(Emu(int(safe["x"] * 12700)), Emu(500 * 12700),
                                        Emu(int(safe["w"] * 12700)), Emu(22 * 12700))
        foot.name = "SourceFooter"
        pgs = [q for q in sorted({(b.get("anchor") or {}).get("page")
                                  for b in (s.get("bullets") or [])} - {None})
               if isinstance(q, int)]
        foot.text_frame.text = "来源 %s%s   %d/%d" % (
            spec["source"]["path"], " · p." + ", ".join(str(q) for q in pgs) if pgs
            else "", s["index"], total)
        for para in foot.text_frame.paragraphs:
            for r in para.runs:
                r.font.size = Pt(9)
        tf = slide.notes_slide.notes_text_frame
        for b in (s.get("bullets") or []):
            a = b.get("anchor") or {}
            bt = b["text"]
            if a.get("source") == "plan":
                notelines.append("- %s  [路线]" % bt)
                continue
            pg = a.get("page")
            notelines.append("- %s  [来源 %s p.%s %s]" % (
                bt, a.get("source") or "material",
                pg if isinstance(pg, int) else "-", a.get("block_id") or ""))
            q = (a.get("quote") or "").strip()
            if q and not verbatim(bt, mat):
                # the sentence is a rewrite: keep the original sentence next to it so
                # the citation can still be verified against the material
                notelines.append("  改写自原句：%s" % q)
        notelines.append("[讲稿] " + (s.get("notes") or
                                      auto_script(role, s.get("bullets") or [],
                                                  s.get("claim"))))
        tf.text = "\n".join(notelines)
        for para in tf.paragraphs:
            for r in para.runs:
                r.font.size = Pt(11)
        rep["slides"].append(rec)
    try:
        prs.core_properties.title = spec.get("title") or "Academic slides"
        prs.core_properties.author = ""
        prs.core_properties.comments = "page evidence anchors are in the speaker notes"
    except Exception:
        pass
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    prs.save(out)
    rep.update({"output": out, "bytes": os.path.getsize(out), "slides_written": total})
    jd(os.path.join(work, "build_report.json"), rep)
    return rep

def tgt(slide, name):
    if name in (None, "", "*"):
        return [x for x in slide.shapes if x.has_text_frame and x.text_frame.text.strip()]
    if str(name).startswith("ph:"):
        return [x for x in slide.placeholders
                if PH.get(int(x.placeholder_format.type)) == str(name).split(":")[1]]
    return [x for x in slide.shapes if x.name == name]

def ops_apply(prs, ops):
    log = []
    for op in ops:
        kind, sn, sl = op.get("op"), int(op.get("slide") or 0), list(prs.slides)
        if kind not in ("set_title", "set_text", "replace_text", "compress_bullets",
                        "set_notes", "delete_slide"):
            log.append({"op": kind, "status": "unsupported"})
        elif not 1 <= sn <= len(sl):
            log.append({"op": kind, "slide": sn, "status": "skipped",
                        "why": "slide out of range"})
        elif kind == "delete_slide":
            ids = list(prs.slides._sldIdLst)
            prs.part.drop_rel(ids[sn - 1].rId)
            prs.slides._sldIdLst.remove(ids[sn - 1])
            log.append({"op": kind, "slide": sn, "status": "ok"})
        elif kind == "set_title":
            ti = sl[sn - 1].shapes.title
            if ti is None:
                log.append({"op": kind, "slide": sn, "status": "failed",
                            "why": "no title placeholder"})
            else:
                was = ti.text_frame.text
                ti.text_frame.text = op.get("text", "")
                log.append({"op": kind, "slide": sn, "status": "ok", "before": was,
                            "after": op.get("text", "")})
        elif kind == "set_notes":
            tf = sl[sn - 1].notes_slide.notes_text_frame
            n0 = len(tf.text)
            tf.text = op.get("text", "")
            log.append({"op": kind, "slide": sn, "status": "ok", "before_len": n0,
                        "after_len": len(tf.text)})
        else:
            hits, extra = 0, {}
            for sh in tgt(sl[sn - 1], op.get("shape")):
                tf = sh.text_frame
                if kind == "set_text":
                    for j, text in enumerate(op.get("paragraphs") or []):
                        para = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                        para.text = text
                    hits += 1
                    if not op.get("all"):
                        break
                elif kind == "replace_text":
                    find, repl = op.get("find", ""), op.get("replace", "")
                    for para in tf.paragraphs:
                        if not find or find not in para.text or not para.runs:
                            continue
                        if len(para.runs) > 1 and not any(find in r.text
                                                          for r in para.runs):
                            para.runs[0].text = para.text.replace(find, repl)
                            for r in para.runs[1:]:
                                r._r.getparent().remove(r._r)
                            hits += 1
                        else:
                            for r in para.runs:
                                if find in r.text:
                                    r.text = r.text.replace(find, repl)
                                    hits += 1
                else:
                    lim = int(op.get("max") or 3)
                    ps = [para.text for para in tf.paragraphs if para.text.strip()]
                    if len(ps) <= lim:
                        continue
                    for j, text in enumerate(ps[:lim]):
                        para = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                        para.text = text
                    while len(tf.paragraphs) > max(1, lim):
                        e = tf.paragraphs[-1]._p
                        e.getparent().remove(e)
                    extra = {"kept": lim, "dropped": ps[lim:], "why": op.get("why")}
                    hits += 1
                    break
            log.append({"op": kind, "slide": sn,
                        "status": "ok" if hits else
                        ("no-match" if kind == "replace_text" else "failed"),
                        "hits": hits, **extra})
    return log

ANCHOR_LINE = re.compile(r"\[来源\s+.+?\s+p\.(-|\d+)")

def scan_anchor_pages(pptx):
    """what the supplied deck already carries (input side, read-only).

    Returns the number of pages with a material anchor, their numbers, and a
    compact set of (slide, sha1-of-bullet-text) keys so the verifier can tell an
    inherited citation problem from one this run introduced.
    """
    empty = {"anchors": 0, "pages": [], "format_known": False, "keys": []}
    if not pptx or not os.path.isfile(pptx) or Presentation is None:
        return empty
    try:
        prs = Presentation(pptx)
    except Exception:
        return empty
    pages, keys = [], []
    for i, s in enumerate(prs.slides, 1):
        t = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
        if not ANCHOR_LINE.search(t or ""):
            continue
        pages.append(i)
        for raw in (t or "").splitlines():
            m = re.match(r"^-\s+(?P<text>.+?)\s+\[来源\s+(?P<src>[^\]]+?)\s+"
                         r"p\.(?P<page>-|\d+)\s*(?P<bid>[^\]]*)\]\s*$", raw.strip())
            if not m or m.group("src").strip().lower() == "plan":
                continue
            keys.append([i, hashlib.sha1(_norm(m.group("text")).encode("utf-8"))
                         .hexdigest()[:16]])
    return {"anchors": len(pages), "pages": pages,
            "format_known": bool(pages), "keys": keys}

def edit(deck_in, ops, out, work, target=None):
    prs = Presentation(deck_in)
    f0, n0 = fp(deck_in), len(prs.slides)
    anchors_before = scan_anchor_pages(deck_in)
    log = ops_apply(prs, ops)
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    prs.save(out)
    v = os.path.join(work, "versions")
    os.makedirs(v, exist_ok=True)
    b = os.path.splitext(os.path.basename(deck_in))[0]
    shutil.copy2(deck_in, os.path.join(v, b + "-v0-original.pptx"))
    shutil.copy2(out, os.path.join(v, b + "-v1-edited.pptx"))
    f1, n1 = fp(out), len(Presentation(out).slides)
    rep = {"mode": "edit", "input": os.path.basename(deck_in), "ops": log,
           "slides_before": n0, "slides_after": n1, "template_preserved": f0 == f1,
           "anchors_found_before": anchors_before["anchors"],
           "anchor_pages_before": anchors_before["pages"],
           "input_anchor_keys": anchors_before["keys"],
           "availability_note": (
               "" if anchors_before["format_known"] else
               "the supplied starting deck carries no [来源 p.N] anchor notes: page "
               "evidence checks report n/a for this input instead of passing silently"),
           "fingerprint_differences": [] if f0 == f1 else {"before": f0, "after": f1},
           "changed_slides": [o.get("slide") for o in log
                              if o.get("status") in ("ok", "no-match")],
           "versions": [os.path.join(v, b + "-v0-original.pptx"),
                        os.path.join(v, b + "-v1-edited.pptx")],
           "target_slide_count": target,
           "meets_target": (n1 == int(target)) if target else None,
           "bytes": os.path.getsize(out)}
    jd(os.path.join(work, "edit_report.json"), rep)
    return rep

def render(pptx, out_dir):
    r = {"renderer": None, "render_status": "unavailable", "pdf": None, "png": [],
         "notes": []}
    os.makedirs(out_dir, exist_ok=True)
    pdf = os.path.join(out_dir, "deck.pdf")
    # never let a preview from an earlier run pass as this run's render: a stale
    # deck.pdf made C14 compare the new deck with an old PDF (text survival 0.35)
    for stale in [pdf] + [os.path.join(out_dir, n) for n in os.listdir(out_dir)
                          if re.match(r"slide-\d+\.png$", n)]:
        try:
            if os.path.isfile(stale):
                os.remove(stale)
        except Exception as e:
            r["notes"].append("could not remove a stale preview %s: %s"
                              % (os.path.basename(stale), str(e)[:50]))
    so = shutil.which("soffice") or shutil.which("libreoffice") or next(
        (p for p in ("/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                     r"C:\Program Files\LibreOffice\program\soffice.exe")
         if os.path.isfile(p)), None)
    if so:
        try:
            subprocess.run([so, "--headless", "--norestore", "--convert-to", "pdf",
                            "--outdir", out_dir, pptx], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=180)
            r["renderer"] = "soffice"
        except Exception as e:
            r["notes"].append("soffice failed: %s" % str(e)[:80])
    if not os.path.isfile(pdf) and os.name == "nt":
        import tempfile
        exe = shutil.which("pwsh") or shutil.which("powershell")
        sc = os.path.join(tempfile.mkdtemp(prefix="deckpdf"), "c.ps1")
        open(sc, "w", encoding="utf-8-sig").write(
            "$ErrorActionPreference='Stop';$a=New-Object -ComObject PowerPoint."
            "Application;try{$p=$a.Presentations.Open('%s',$true,$false,$false);"
            "$p.SaveAs('%s',32);$p.Close()}finally{$a.Quit()}"
            % (os.path.abspath(pptx), os.path.abspath(pdf)))
        for i in range(3):
            try:
                subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                sc], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=240)
                if os.path.isfile(pdf) and os.path.getsize(pdf) > 0:
                    r["renderer"] = "powerpoint-com(attempt %d)" % (i + 1)
                    break
            except Exception as e:
                r["notes"].append("COM attempt %d: %s" % (i + 1, str(e)[:60]))
            time.sleep(2)
    if os.path.isfile(pdf) and os.path.getsize(pdf) > 0:
        r.update({"pdf": pdf, "render_status": "ok", "renderer": r["renderer"] or "convert"})
        try:
            import fitz
            doc = fitz.open(pdf)
            for i in range(doc.page_count):
                p = os.path.join(out_dir, "slide-%02d.png" % (i + 1))
                doc[i].get_pixmap(dpi=110).save(p)
                r["png"].append(p)
            doc.close()
        except Exception:
            pass
    else:
        r["notes"].append("no LibreOffice/PowerPoint: PDF preview unavailable (no PNG "
                          "is produced rather than faked)")
    return r

def main(argv=None):
    ap = argparse.ArgumentParser(description="minimal academic deck kit")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="")
    a = ap.parse_args(argv)
    t0, case, indir = time.time(), {}, None
    if os.path.isdir(a.case):
        indir = os.path.abspath(a.case)
        for n in sorted(os.listdir(indir)):
            if n.endswith(".json") and (n == "case.json" or iscase(
                    os.path.join(indir, n))):
                case = json.load(open(os.path.join(indir, n), encoding="utf-8"))
                break
    elif os.path.isfile(a.case):
        indir = os.path.dirname(os.path.abspath(a.case))
        case = json.load(open(a.case, encoding="utf-8"))
    indir = indir or ("/input" if os.path.isdir("/input") else ".")
    os.makedirs(a.out, exist_ok=True)
    work = a.work or os.path.join(a.out, "_work")
    os.makedirs(work, exist_ok=True)
    stages, warns, unc, chlog = [], [], [], []
    st = lambda n, s, d=None: stages.append({"stage": n, "status": s, "detail": d or {}})
    fields = cfields(case)
    cid = case.get("case_id") or case.get("caseId") or case.get("id") or ""
    st("contract", "ok" if fields else "degraded", {"case_id": cid, "fields": fields})
    f = find(indir, case, os.getcwd())
    st("discover", "ok" if (f["material"] or f["deck"]) else "degraded",
       {k: (os.path.basename(v) if isinstance(v, str) else None)
        for k, v in f.items() if k in ("material", "template", "deck", "ops", "spec")}
       | {"resolved_from": f["resolved_from"], "missing": f["missing"],
          "evidence_candidates": f["candidates"],
          "evidence_sniff": f["sniff"],
          "refused_as_evidence": f["rejected"]})
    if f["missing"]:
        unc.append("case.json points at files that do not exist: %s"
                   % json.dumps(f["missing"], ensure_ascii=False))
    if f["rejected"]:
        note = ("refused %d input file(s) as evidence (the citation corpus must be "
                "research material): %s" % (len(f["rejected"]), json.dumps(
                    f["rejected"], ensure_ascii=False)))
        (warns if f["material"] else unc).append(note)
    if not f["material"] and not f["deck"]:
        unc.append("no material and no starting deck in the input directory")
    tpl = f["template"]
    if not tpl and not f["deck"]:
        try:
            tpl = master(os.path.join(work, "neutral-master.pptx"))
            warns.append("no template supplied: built a neutral 16:9 master")
        except Exception as e:
            unc.append("no template and the neutral master could not be built: %s"
                       % str(e)[:60])
    st("template", "ok" if tpl else "not-needed",
       {"source": os.path.basename(tpl) if tpl else None,
        "why": None if tpl else "editing a supplied deck: its own master is the "
                                "invariance baseline, so no template is built"})
    jd(os.path.join(work, "template.json"), probe(tpl) if tpl else
       {"source": None, "note": "not applicable in edit mode"})
    src = None
    if f["material"]:
        try:
            src = ingest(f["material"], work)
            st("ingest", "ok", {"parser": src["parser"], "blocks": len(src["blocks"]),
                                "numbers": len(src["numbers"]),
                                "limitations": src["limits"]})
            unc += src["limits"]
            warns += src.get("notes") or []
        except Exception as e:
            st("ingest", "failed", {"error": str(e)[:100]})
            unc.append("material could not be read: %s" % str(e)[:80])
    if src and not (src.get("corpus") or {}).get("trusted", True):
        st("ingest", "refused", {"why": (src.get("corpus") or {}).get("why"),
                                 "path": src.get("path")})
        unc.append("the candidate material %s was refused as an evidence corpus "
                   "(%s); no deck is generated from it"
                   % (src.get("path"), (src.get("corpus") or {}).get("why")))
        src = None
    deck = os.path.join(a.out, "deck.pptx")
    spec = build_rep = edit_rep = rrep = checks = None
    baseline, tpl_role = tpl, ("template" if tpl else None)
    g = lambda *n: cget(case, *n)  # noqa: E731
    mat = mtext(src)
    # interruption safety: an honest partial result.json exists from here on, so a
    # killed run still leaves a valid, truthful file (the final one overwrites it)
    partial = {k: "" for k in fields}
    partial["contract_echo"] = {k: "" for k in fields}
    partial.update({
        "case_id": cid, "status": "partial", "_partial": True,
        "_partial_at_stage": "after discovery/ingest, before build",
        "contract_fields_detected": fields,
        "contract_missing_fields": list(fields),
        "stages": list(stages), "uncertainty": list(unc),
        "deliverable": {"pptx": "deck.pptx", "slides": 0, "editable": None,
                        "note": "placeholder written before build; the final "
                                "result.json replaces this file"},
        "evidence_map": [], "outputs": [],
        "sources": [{"kind": "material",
                     "path": (src or {}).get("path") or
                     (os.path.basename(f["deck"]) if f["deck"] else None),
                     "sha256_16": (src or {}).get("sha256_16")}],
        "resolved_from": f["resolved_from"]})
    jd(os.path.join(a.out, "result.json"), partial)
    st("partial_result", "ok", {"written": os.path.join(a.out, "result.json"),
                                "status": "partial", "why": "interruption safety"})
    if f["deck"]:
        ops = f.get("ops_obj") or []
        if not ops and isinstance(case.get("ops"), list):
            ops = case["ops"]
        if ops:
            edit_rep = edit(f["deck"], ops, deck, work, g("slide_count", "num_slides"))
            st("edit", "ok" if edit_rep["template_preserved"] else "failed",
               {"slides": [edit_rep["slides_before"], edit_rep["slides_after"]],
                "template_preserved": edit_rep["template_preserved"],
                "meets_target": edit_rep["meets_target"]})
            chlog += [{"what": o.get("op"), "slide": o.get("slide"),
                       "why": o.get("why") or "explicit edit op",
                       "status": o.get("status")} for o in edit_rep["ops"]]
            if not edit_rep["template_preserved"]:
                unc.append("design fingerprint changed while editing")
        else:
            shutil.copy2(f["deck"], deck)
            st("edit", "degraded", {"why": "starting deck without ops: copied"})
            warns.append("starting deck copied through (no edit instructions found)")
    elif src and tpl:
        if f.get("spec_obj") is not None:
            spec = f["spec_obj"]
            st("plan", "ok", {"source": os.path.basename(f["spec"]),
                              "slides": len(spec.get("slides") or [])})
        else:
            spec = plan(src, {"lang": g("language", "lang"),
                              "count": g("slide_count", "num_slides", "max_slides"),
                              "minutes": g("minutes", "duration_min"),
                              "audience": g("audience"), "title": g("deck_title")})
            jd(os.path.join(work, "deck_plan.json"), spec)
            st("plan", "ok", {"slides": len(spec["slides"]),
                              "warnings": spec["plan_warnings"]})
            warns += spec["plan_warnings"]
        build_rep = build(spec, tpl, deck, work, mat)
        st("build", "ok", {"slides": build_rep["slides_written"],
                           "bytes": build_rep["bytes"],
                           "warnings": len(build_rep["warnings"])})
        chlog.append({"what": "generate deck from plan",
                      "why": "%s slides" % len(spec["slides"]), "status": "ok"})
        warns += ["slide %s: %s" % (w.get("slide"), w.get("what"))
                  for w in build_rep["warnings"]]
    else:
        st("build", "skipped", {"why": "no material or no template"})
    if os.path.isfile(deck):
        rrep = render(deck, os.path.join(a.out, "preview"))
        jd(os.path.join(work, "render_report.json"), rrep)
        st("render", "ok" if rrep["render_status"] == "ok" else "degraded",
           {"renderer": rrep["renderer"], "png": len(rrep["png"]),
            "notes": rrep["notes"][:2]})
        if rrep["render_status"] != "ok":
            unc.append("no renderer available: PDF preview missing")
    # the invariance baseline is the file whose design must survive: the supplied
    # template when there is one, otherwise the starting deck being edited,
    # otherwise the neutral master this run itself built
    baseline, tpl_role = (f["template"] or f["deck"] or tpl,
                          "supplied template" if f["template"] else
                          "starting deck (edit invariance)" if f["deck"] else
                          "neutral master built by this run")
    # if the material ran out, say so instead of shipping silent blank pages
    if spec and (spec.get("unfilled_pages") or []):
        unc.append("the material had no further citable sentence for page(s) %s: they "
                   "are declared backup pages (notes carry [备份]) and no claim is made "
                   "on them" % ", ".join(str(x) for x in spec["unfilled_pages"]))
        warns.append("plan warned about %d unfilled page(s)"
                     % len(spec["unfilled_pages"]))
    ev = [{"slide": s["index"], "role": s.get("role"), "claim": s.get("claim"),
           "text": b.get("text"), "anchor": b["anchor"]}
          for s in ((spec or {}).get("slides") or [])
          for b in (s.get("bullets") or []) if (b.get("anchor") or {}).get("page")
          or (b.get("anchor") or {}).get("block_id")]
    if not ev and os.path.isfile(deck):
        from pptx import Presentation as _P
        for i, s in enumerate(_P(deck).slides, 1):
            t = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
            cur = None
            for raw in (t or "").splitlines():
                m = re.match(r"^-\s+(?P<text>.+?)\s+\[来源\s+(?P<src>[^\]]+?)\s+"
                             r"p\.(?P<page>-|\d+)\s*(?P<bid>[^\]]*)\]\s*$", raw.strip())
                if m:
                    cur = {"slide": i, "role": "edited", "claim": "",
                           "text": m.group("text").strip(),
                           "anchor": {"source": m.group("src").strip(),
                                      "page": (None if m.group("page") == "-"
                                               else int(m.group("page"))),
                                      "block_id": (m.group("bid") or "").strip() or None,
                                      "quote": m.group("text").strip()}}
                    ev.append(cur)
                    continue
                mm = re.match(r"^改写自原句[：:]\s*(?P<q>.+?)\s*$", raw.strip())
                if mm and cur is not None:
                    cur["anchor"]["quote"] = mm.group("q").strip()
                    cur["anchor"]["rewritten"] = True
    with open(os.path.join(a.out, "evidence_map.jsonl"), "w", encoding="utf-8") as fh:
        for row in ev:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if spec:
        jd(os.path.join(a.out, "slide_plan.json"), spec)
    n = len((spec or {}).get("slides") or []) or (edit_rep or {}).get("slides_after") or 0
    real = 0
    if os.path.isfile(deck):
        try:
            real = len(Presentation(deck).slides)
        except Exception as exc:
            unc.append("deck.pptx cannot be opened: %s" % str(exc)[:60])
        if real == 0:
            unc.append("empty-artifact guard: the produced deck has 0 slides "
                       "(input discovery or build produced nothing)")
        n = real or n
    outs = []
    for p in [deck, (rrep or {}).get("pdf")] + list((rrep or {}).get("png") or []) + [
            os.path.join(a.out, "evidence_map.jsonl"),
            os.path.join(a.out, "slide_plan.json") if spec else None]:
        if p and os.path.isfile(p):
            outs.append({"path": os.path.relpath(p, a.out),
                         "bytes": os.path.getsize(p),
                         "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]})
    dv = {"pptx": "deck.pptx",
          "pptx_bytes": os.path.getsize(deck) if os.path.isfile(deck) else 0,
          "slides": n, "editable": True, "pdf_preview": (rrep or {}).get("pdf"),
          "png_previews": (rrep or {}).get("png") or [], "notes_included": True}
    if spec and spec.get("unfilled_pages"):
        dv["declared_backup_pages"] = spec["unfilled_pages"]
    # the notes contract field is read back FROM THE ARTIFACT: QA-round-20261124 P1-2
    # found result.json.notes empty for pages 2..8 while the pptx notes held 99-580
    # characters, i.e. the contract field described the plan, not what was delivered
    notes_list, notes_origin = [], "plan (deck.pptx unreadable)"
    if os.path.isfile(deck):
        try:
            from pptx import Presentation as _P2
            _deck = _P2(deck)
            for i, s in enumerate(_deck.slides, 1):
                t = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
                sp = next((x for x in ((spec or {}).get("slides") or [])
                           if x.get("index") == i), {})
                # `notes` = exactly what the deck carries (contract == artifact);
                # `script` = just the 讲稿 part, for readers who want the narration
                script = t.split("[讲稿] ", 1)[-1].strip() if "[讲稿] " in t else ""
                notes_list.append({"index": i, "role": sp.get("role"),
                                   "claim": sp.get("claim"),
                                   "notes": t, "notes_full": t, "script": script})
            notes_origin = "read back from deck.pptx"
        except Exception as e:
            unc.append("the speaker notes could not be read back from the deck: %s"
                       % str(e)[:60])
    if not notes_list:
        notes_list = [{"index": s["index"], "role": s.get("role"),
                       "claim": s.get("claim"), "notes": s.get("notes") or "",
                       "notes_full": ""} for s in ((spec or {}).get("slides") or [])]
    sources_list = [{"kind": "material",
                     "path": (src or {}).get("path") or
                     (os.path.basename(f["deck"]) if f["deck"] else None),
                     "sha256_16": (src or {}).get("sha256_16"),
                     "kind_detail": (src or {}).get("kind"),
                     "siblings": f["candidates"],
                     "evidence_policy": (src or {}).get("corpus", {}).get("why"),
                     "anchors": "page/block ids in evidence_map"}]
    # run the mechanical checks on the artifacts, handing them the contract fields so
    # C16 can prove contract and deliverable agree
    pre = {"case_id": cid, "deliverable": dv, "sources": sources_list,
           "notes": notes_list, "outputs": outs}
    if os.path.isfile(deck):
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import verify as vm
            checks = vm.check(deck, case=case, source=src, spec=spec, template=baseline,
                              render=rrep, edit=edit_rep, template_role=tpl_role,
                              result=pre)
        except Exception as e:
            checks = {"passed": None, "error": str(e)[:160]}
            unc.append("the built-in verifier could not run (%s): this run is NOT "
                       "self-verified" % str(e)[:80])
        jd(os.path.join(work, "checks.json"), checks)
        summ = checks.get("summary") or {}
        st("verify", "ok" if checks.get("passed") else "degraded",
           {"passed": checks.get("passed"), "error": checks.get("error"),
            "failed": summ.get("failed_ids") or
            [x.get("id") or x.get("check") for x in checks.get("checks", [])
             if x.get("status") == "fail" or x.get("ok") is False],
            "not_applicable": summ.get("not_applicable")})
        if checks.get("passed") is None:
            unc.append("verification did not run to completion, so no check result is "
                       "claimed for this deck")
        elif checks.get("passed") is False:
            unc.append("mechanical checks failed: %s" % ", ".join(
                (summ.get("failed_ids") or ["?"])))
        # NOTE: never reuse `cid` here — it is the case id used for the contract below,
        # and a loop variable would overwrite it (QA-round-20261124 P0-1:
        # result.json.case_id came out as the last n/a check id, e.g. "C07")
        for na_id in (summ.get("not_applicable") or []):
            warns.append("check %s is not applicable to this deck (%s)" % (
                na_id, next((c.get("detail", {}).get("why")
                             for c in checks.get("checks", [])
                             if c.get("id") == na_id), "")))
    c12 = next((c.get("detail") or {} for c in (checks or {}).get("checks") or []
                if c.get("id") == "C12"), {})
    claim_support = {"paraphrased_bullets": c12.get("paraphrases_declared"),
                     "paraphrases_without_shared_token":
                         len(c12.get("paraphrases_without_shared_token") or []),
                     "entailment": "not machine-checked: C12 proves the declared "
                                   "original sentence is verbatim in the material, it "
                                   "does not prove the sentence supports the bullet"}
    if claim_support["paraphrases_without_shared_token"]:
        warns.append("%d rewritten bullet(s) share no token with their declared "
                     "original sentence (translation or loose rewrite): their "
                     "entailment was not machine-checked, which is why this run "
                     "reports it instead of claiming support"
                     % claim_support["paraphrases_without_shared_token"])
    biz = {"deliverable": dv, "deck": dv, "evidence_map": ev,
           "outputs": outs, "changes": chlog, "claim_support": claim_support,
           "notes": notes_list, "notes_origin": notes_origin,
           "slide_plan": [{"index": s["index"], "role": s.get("role"),
                           "title": s.get("title"), "claim": s.get("claim")}
                          for s in ((spec or {}).get("slides") or [])],
           "render_and_versions": {
               "renderer": (rrep or {}).get("renderer"),
               "render_status": (rrep or {}).get("render_status"),
               "pdf": (rrep or {}).get("pdf"),
               "png_count": len((rrep or {}).get("png") or []),
               "template": os.path.basename(baseline) if baseline else None,
               "template_role": tpl_role,
               "template_preserved": (edit_rep or {}).get("template_preserved",
                                                          True if build_rep else None),
               "versions": (edit_rep or {}).get("versions") or []},
           "checks": checks, "change_log": chlog, "stages": stages,
           "summary": "%s slides; preview %s" % (n, os.path.basename(
               dv["pdf_preview"] or "") or "none"),
           "limitations": (unc + warns)[:10], "runtime_s": round(time.time() - t0, 2)}
    status = "failed"
    if os.path.isfile(deck):
        status = "partial" if (unc or (checks or {}).get("passed") is False or
                               (edit_rep and not edit_rep["template_preserved"])) \
            else "success"
    res = {"case_id": cid, "status": status, "contract_fields_detected": fields}
    echo = {}
    for k in fields:
        res[k] = echo[k] = biz.get(k, "")
    for k, v in biz.items():
        res.setdefault(k, v)
    res.update({"contract_echo": echo,
                "resolved_from": f["resolved_from"],
                "sources": sources_list,
                "uncertainty": unc, "change_log": chlog,
                "contract_missing_fields": [k for k in fields
                                            if res.get(k) in ("", None, [], {})]})
    res["contract_selfcheck"] = {
        "case_id_matches_input": res.get("case_id") == cid,
        "notes_origin": notes_origin,
        "notes_pages_nonempty": sum(1 for x in notes_list if (x.get("notes") or "").strip()),
        "declared_backup_pages": (spec or {}).get("unfilled_pages") or []}
    if not res["contract_selfcheck"]["case_id_matches_input"]:
        # structurally impossible after the rename above; kept as a tripwire so a
        # future edit cannot silently ship a polluted case_id again
        res["status"] = "partial"
        res["uncertainty"] = unc + ["case_id in this report does not match the input "
                                    "case: contract field integrity guard triggered"]
    jd(os.path.join(a.out, "result.json"), res)
    print(json.dumps({"result": os.path.join(a.out, "result.json"), "status": status,
                      "slides": n, "render": (rrep or {}).get("render_status"),
                      "checks_passed": (checks or {}).get("passed"),
                      "stages": [(s["stage"], s["status"]) for s in stages]},
                     ensure_ascii=False))
    return 0 if status != "failed" else 1

if __name__ == "__main__":
    sys.exit(main())
