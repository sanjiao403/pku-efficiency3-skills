import argparse, hashlib, io, json, os, re, sys, zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import talkplan as T  # noqa: E402

RANK = {"weak": 0, "moderate": 1, "strong": 2}


GAIN_CASES = {"_purpose":"带标签的增益案例：用同一套运行期回查代码，证明本 Skill 能区分『真推导』与『编造/跑题』。","_how_to_run":"python3 scripts/verify.py --gain-cases tests/gain_cases.json","_labels":{"grounded":"页面内容逐字来自材料 → 期望 locator 全命中、数字全可定位、判定 accept","fabricated_number":"页面断言里的数字在材料中不存在 → 期望数字可定位率 <100%、判定 reject","fabricated_quote":"引用片段不在所标注的那一行（行号造假）→ 期望逐字回查失败、判定 reject","off_topic":"论断与材料无关（材料里没有该内容）→ 期望无锚点/回查失败、判定 reject"},"material":"# 1 Problem\nHowever, freezing attention layers under scarce labels remains brittle across sensors.\n# 2 Method\nWe propose AttnFreeze-2: freeze the first 3 stages and fine-tune the last 2 stages (lr 1e-4).\n# 3 Results\nMacro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).\n# 4 Limitations\nLimitation: only one sensor and one region were covered, so external validity is unverified.\n","cases":[{"id":"case-grounded-ok","label":"grounded","expect":"accept","why":"claim/quote/bullets 全部逐字取自材料第 6 行，数字 0.87/0.83/0.03 都在材料里","pages":[{"index":1,"role":"result-1","title":"冻结前 3 个 stage 提升 +4.2%","claim":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","claim_strength":"strong","bullets":["Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds)."],"figures":[],"speaker_notes":"point at the F1 line and the p value; do not push past strong","evidence":[{"material":"paper.md","line":6,"quote":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","numbers":["0.87","0.83","0.03","3"]}]}]},{"id":"case-fabricated-number","label":"fabricated_number","expect":"reject","why":"同一页但把结论改成 +12.4%（材料里没有 12.4）","pages":[{"index":1,"role":"result-1","title":"冻结前 3 个 stage 提升 +12.4%","claim":"AttnFreeze-2 improves macro F1 by +12.4% over full fine-tuning.","claim_strength":"strong","bullets":["macro F1 0.87±0.01 vs 0.83±0.02"],"figures":[],"speaker_notes":"claim the improvement out loud","evidence":[{"material":"paper.md","line":6,"quote":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","numbers":["12.4"]}]}]},{"id":"case-fabricated-quote","label":"fabricated_quote","expect":"reject","why":"引用的句子真实存在，但被标在了错误的行号（L2 而非 L6）——行号造假","pages":[{"index":1,"role":"result-1","title":"颤抖的结论","claim":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","claim_strength":"strong","bullets":[],"figures":[],"speaker_notes":"quote it as if it were on the method line","evidence":[{"material":"paper.md","line":2,"quote":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","numbers":[]}]}]},{"id":"case-off-topic","label":"off_topic","expect":"reject","why":"材料讲冻结注意力层，页面断言讲蛋白质折叠——既无锚点也对不上任何一行","pages":[{"index":1,"role":"result-1","title":"蛋白质折叠预测精度达到 0.94","claim":"Our folding model reaches 0.94 GDT-TS on the CASP15 target set.","claim_strength":"strong","bullets":["0.94 GDT-TS, n=41 targets"],"figures":["Figure 3"],"speaker_notes":"claim state of the art on proteins","evidence":[{"material":"paper.md","line":4,"quote":"Our folding model reaches 0.94 GDT-TS on the CASP15 target set.","numbers":["0.94","41"]}]}]}]}


def gain_cases(path, out_dir=None):
    """Run the labelled gain cases through the pipeline's own re-check code.

    Each case declares a label (grounded / fabricated_number / fabricated_quote / off_topic),
    the material text, and the pages to judge. Verdicts come from:
      * talkplan.runtime_recheck  -> locator resolvable + quote verbatim on the cited line
      * number traceability       -> every number on the page must exist in the material
      * caption consistency       -> referenced figure ids must exist in the material captions
    A case passes when its machine verdict matches its declared expectation.
    """
    import tempfile as _tf
    key = str(path).lower()
    if key in ("builtin", "embedded", ""):
        data = dict(GAIN_CASES)
    else:
        if not os.path.exists(path):
            raise SystemExit("gain-cases: file not found: %s\n"
                             "use `--gain-cases builtin` for the cases embedded in this script, "
                             "or a path that exists." % path)
        data = T.jl(path, None)
        if not isinstance(data, dict) or not (data.get("cases") or []):
            raise SystemExit("gain-cases: %s contains no cases (refusing to report a pass)" % path)
    results = []
    for case in data.get("cases", []):
        work = _tf.mkdtemp(prefix="gain-case-")
        mpath = os.path.join(work, "paper.md")
        io.open(mpath, "w", encoding="utf-8", newline="\n").write(data.get("material", ""))
        mats = [T.rd(mpath)]
        pages = case.get("pages") or []
        re_ = T.runtime_recheck(mats, pages, [])
        blob = " ".join(" ".join(m["lines"]) for m in mats if m["readable"])
        nums_t = nums_ok = 0
        for pg in pages:
            for x in T.NUMs(" ".join([str(pg.get("claim") or "")] + list(pg.get("bullets") or []))):
                if len(x) > 1:
                    nums_t += 1
                    nums_ok += 1 if x in blob else 0
        caps = set()
        for m in mats:
            for f in m.get("figures", []):
                caps.add(T.nz(f["id"]).lower())
        caps_t = caps_bad = 0
        for pg in pages:
            for f in pg.get("figures", []):
                caps_t += 1
                caps_bad += 0 if T.nz(f).lower() in caps else 1
        verdict = "accept" if (re_["summary"]["fail"] == 0 and nums_ok == nums_t and caps_bad == 0
                               and re_["summary"]["locators_verified"] > 0) else "reject"
        results.append({
            "id": case.get("id"), "label": case.get("label"), "why": case.get("why"),
            "expected": case.get("expect"), "verdict": verdict,
            "ok": verdict == case.get("expect"),
            "evidence": {
                "locators_verified": re_["summary"]["locators_verified"],
                "verbatim_failures": re_["summary"]["fail"],
                "number_traceability": "%s/%s" % (nums_ok, nums_t),
                "caption_mismatches": caps_bad,
                "first_failure": next((c for c in re_["items"] if not c.get("ok")), None),
            },
        })
    rep = {"file": "builtin" if key in ("builtin", "embedded", "") else os.path.basename(path),
           "cases": results, "passed": sum(1 for r in results if r["ok"]), "total": len(results),
           "rule": "accept = locator verified AND every number traceable AND captions real; otherwise reject"}
    if out_dir:
        T.jd(rep, os.path.join(out_dir, "gain-cases.json"))
    return rep


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

    need = ["deck.pptx", "outline.json", "result.json", "speaker-notes.md"]
    gone = [n for n in need if not os.path.exists(os.path.join(out, n))]
    ck("required files exist", not gone, "missing=%s" % gone)
    deck_p = os.path.join(out, "deck.pptx")
    hollow = []
    if os.path.exists(deck_p):
        try:
            with zipfile.ZipFile(deck_p) as z:
                for n in z.namelist():
                    if re.match(r"ppt/slides/slide\d+\.xml$", n) and \
                       z.read(n).decode("utf-8", "replace").count("<p:sp>") == 0:
                        hollow.append(n)
        except Exception as exc:
            fails.append("deck.pptx unreadable: %s" % exc)
    ck("no hollow slide (every slide carries >=1 shape)", not hollow, "hollow=%s" % hollow[:3])
    eg = (res.get("empty_artifact_guard") or {}).get("passed")
    ck("runtime empty-artifact guard passed", eg is not False,
       "guard=%s reasons=%s" % (eg, str((res.get("empty_artifact_guard") or {}).get("reasons") or [])[:100]))
    rsum = (res.get("audit") or {}).get("summary") or {}
    ck("runtime verbatim re-check ran by the pipeline", bool(rsum.get("locators_verified")),
       "locators_verified=%s fails=%s numbers=%s/%s captions=%s" % (
           rsum.get("locators_verified"), rsum.get("fail"), rsum.get("numbers_locatable"),
           rsum.get("numbers_total"), rsum.get("captions_matched")))

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
    ap.add_argument("--gain-cases", default="", help="run the labelled gain cases in this JSON and print verdicts")
    ap.add_argument("--out-dir", default="", help="where to drop gain-cases.json (optional)")
    a = ap.parse_args(av)
    if a.gain_cases:
        rep = gain_cases(a.gain_cases, a.out_dir or None)
        for r in rep["cases"]:
            print("  %-26s label=%-18s expected=%-6s verdict=%-6s %s  %s"
                  % (r["id"], r["label"], r["expected"], r["verdict"], "OK" if r["ok"] else "MISMATCH",
                     r["evidence"]))
        ok = rep["total"] > 0 and rep["passed"] == rep["total"]
        print("gain cases: %d/%d matched their label -> %s"
              % (rep["passed"], rep["total"], "PASS" if ok else "FAIL"))
        return 0 if ok else 1
    return verify(a.case, a.out, a.input or None)

if __name__ == "__main__":
    sys.exit(main())
