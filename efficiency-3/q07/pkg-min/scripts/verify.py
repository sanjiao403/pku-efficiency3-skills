import argparse, hashlib, io, json, os, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import talkplan as T  # noqa: E402

RANK = {"weak": 0, "moderate": 1, "strong": 2}

def verify(case_path, out, input_dir=None, quiet=False):
    ind = input_dir or os.path.dirname(os.path.abspath(case_path)) or "."
    case = T.jl(case_path, {}) or {}
    res = T.jl(os.path.join(out, "result.json"), {}) or {}
    outl = T.jl(os.path.join(out, "outline.json"), {}) or {}
    plan = T.jl(os.path.join(out, "page-plan.json"), {}) or {}
    fails, warns, checks = [], [], []

    def ck(name, ok, detail, warn=False):
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       "level": "pass" if ok else ("warn" if warn else "fail")})
        if not ok:
            (warns if warn else fails).append("%s: %s" % (name, detail))

    con, src = T.con_of(case)
    unres = {u.get("key") for u in (res.get("contract_unresolved_fields") or [])}
    bad = [k for k in con if k not in res or (res[k] is None and k not in unres) or res[k] == "" or res[k] == []]
    ck("contract fields present (null only if declared unresolved)", not bad,
       "source=%s missing/silent-null=%s" % (src, bad))

    ofail = []
    for o in res.get("outputs") or []:
        p = os.path.join(out, str(o.get("path") or ""))
        if not os.path.exists(p):
            ofail.append("%s missing" % o.get("path"))
            continue
        if int(o.get("bytes") or -1) != os.path.getsize(p):
            ofail.append("%s bytes mismatch" % o.get("path"))
        if o.get("sha256") and o["sha256"] != hashlib.sha256(open(p, "rb").read()).hexdigest():
            ofail.append("%s sha256 mismatch" % o.get("path"))
    ck("outputs[] entries exist with matching bytes+sha256", not ofail, "; ".join(ofail))

    tb = outl.get("time_budget") or {}
    pages, backups = outl.get("pages") or [], outl.get("backup_slides") or []
    total, want = len(pages) + len(backups), tb.get("slide_count")
    ck("slides == slide_count", (not want) or total == want,
       "want=%s got=%s (%s+%s)" % (want, total, len(pages), len(backups)),
       warn=True)

    sp = sum(int(p.get("seconds") or 0) for p in pages)
    talk = int(tb.get("talk_seconds") or 0)
    dev = abs(sp - talk) / float(talk) * 100 if talk else 100.0
    if not pages and res.get("status") == "unsupported":
        ck("sum(page seconds) within 5% of talk budget", True,
           "skipped: nothing was produced and the run declares unsupported", warn=True)
    else:
        ck("sum(page seconds) within 5% of talk budget", dev <= 5.0 + 1e-6,
           "sum=%ss talk=%ss dev=%.1f%%" % (sp, talk, dev))

    thin = [p["index"] for p in pages
            if not p.get("claim") or not p.get("claim_strength") or not p.get("evidence_refs")]
    ck("every content page has claim + strength + anchor", not thin,
       "pages=%s" % thin if pages else "no pages produced", warn=not pages)

    paths, _miss = T.mp(case, ind)
    mrec = {}
    for p in paths:
        r = T.rd(p)
        mrec[r["file"]] = r
    bad_anchor, checked = [], 0
    for pg in pages:
        for ev in pg.get("evidence_refs") or (pg.get("evidence") or []):
            checked += 1
            r = mrec.get(ev.get("material"))
            if r is None or not r["readable"]:
                bad_anchor.append({"page": pg["index"], "why": "material not readable"})
                continue
            line = ev.get("line")
            if not line or line > len(r["lines"]):
                bad_anchor.append({"page": pg["index"], "why": "line out of range: %s" % line})
                continue
            src_line = T.nz(r["lines"][line - 1])
            if not src_line:
                bad_anchor.append({"page": pg["index"], "why": "line %s is blank" % line})
    ck("evidence line numbers resolve in the real materials", not bad_anchor,
       "%d anchors checked, %d bad" % (checked, len(bad_anchor)))

    mat_text = T.sq(" ".join(" ".join(r["lines"]) for r in mrec.values() if r["readable"]))
    fab = []
    for pg in pages + backups:
        txt = " ".join([str(pg.get("title") or ""), str(pg.get("claim") or "")] + list(pg.get("bullets") or []))
        for n in T.NUMs(txt):
            k = T.sq(n)
            if len(k) > 1 and k not in mat_text:
                fab.append({"page": pg.get("index"), "number": n})
    ck("no number appears on a page that is absent from the materials", not fab,
       "fabricated=%s" % fab[:6])

    figs = set()
    for r in mrec.values():
        for f in r.get("figures", []):
            figs.add(T.sq(f["id"]))
    badfig = [{"page": p["index"], "fig": f} for p in pages for f in (p.get("figures") or []) if T.sq(f) not in figs]
    ck("figure references match material caption ids", not badfig, "mismatched=%s" % badfig[:6])

    dup = []
    for p in pages:
        n = p.get("notes") or ""
        body = " ".join([str(p.get("claim") or "")] + list(p.get("bullets") or []))
        if n and body:
            a = set(re.findall(r"[0-9a-z\u4e00-\u9fff]+", n.lower()))
            bb = set(re.findall(r"[0-9a-z\u4e00-\u9fff]+", body.lower()))
            if a and bb and len(a & bb) / float(len(a | bb)) > 0.8:
                dup.append(p["index"])
    ck("speaker notes are complementary, not a copy of the page", not dup, "pages=%s" % dup, warn=True)

    st = res.get("status")
    ck("status is one of success/partial/unsupported", st in ("success", "partial", "unsupported"), "status=%s" % st)
    if st in ("partial", "unsupported"):
        ck("partial/unsupported carries uncertainty entries", bool(res.get("uncertainty")), "uncertainty empty")
    ck("change_log present", bool(res.get("change_log")), "change_log missing")

    leak = []
    blob = json.dumps(res, ensure_ascii=False) + json.dumps(outl, ensure_ascii=False)
    for m in re.finditer(r"(?:[A-Za-z]:\\|/home/|/Users/|/app/|/skills/)", blob):
        leak.append(blob[max(0, m.start() - 20):m.start() + 30])
    ck("no host absolute paths in result/outline", not leak, "leaks=%s" % leak[:3])

    verdict = "PASS" if not fails else "FAIL"
    report = {"verdict": verdict, "checks": checks, "fails": fails, "warns": warns,
              "summary": {"total": len(checks), "pass": sum(1 for c in checks if c["ok"]),
                          "warn": len(warns), "fail": len(fails)},
              "note": "materials are re-read here, so anchor/number checks do not trust the planner's output"}
    T.jd(report, os.path.join(out, "verification.json"))
    if not quiet:
        print("verify: %s (%d checks, %d warn, %d fail)" % (verdict, len(checks), len(warns), len(fails)))
        for f in fails:
            print("  FAIL %s" % f)
        for w in warns:
            print("  WARN %s" % w)
    return 0 if not fails and not warns else (2 if not fails else 1)

def main(av=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--input", default="")
    a = ap.parse_args(av)
    return verify(a.case, a.out, a.input or None)

if __name__ == "__main__":
    sys.exit(main())
