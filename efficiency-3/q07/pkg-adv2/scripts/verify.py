import argparse, hashlib, io, json, os, re, sys, zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import talkplan as T  # noqa: E402

RANK = {"weak": 0, "moderate": 1, "strong": 2}
# slide_plan vocabulary (schemas/slide_plan.schema.json: evidence_strength)
STRENGTH_ORDER = {"background": 0, "mechanistic": 1, "comparative": 2, "direct": 3}

# ---------------------------------------------------------------- reference integrity
# "every reference resolves to a real file" used to be asserted by an out-of-package build
# helper and was therefore unverifiable for a reader of this package. It is checked here,
# over the shipped docs *and* over path/script literals inside the shipped code.
DIRS = ("scripts", "references", "schemas", "examples")
RUNTIME_OK = {"slide_plan.json", "deck.pptx", "outline.json", "speaker-notes.md", "result.json",
              "verification.json", "benchmark.json", "gain-cases.json", "render-record.json",
              "preview.pdf", "preview-1.png", "resolved-paths.json"}
TOKEN = re.compile(r"((?:%s)/[A-Za-z0-9._\u4e00-\u9fff/-]*[A-Za-z0-9._\u4e00-\u9fff])" % "|".join(DIRS))
BARE_PY = re.compile(r"[\"']([A-Za-z0-9_]+\.py)[\"']")


def _prefix_hit(pkg, ref):
    """`references/04` (a section pointer without extension) resolves when a single file
    in that directory starts with the last segment. Extension-bearing refs must match exactly."""
    last = ref.rsplit("/", 1)[-1]
    if "." in last:
        return False
    d = os.path.join(pkg, *ref.split("/")[:-1])
    if not os.path.isdir(d):
        return False
    return len([f for f in os.listdir(d) if f.startswith(last)]) == 1


def refcheck(pkg_root=None):
    """Every `dir/path` token in the shipped .md/.json/.py files must exist inside the package."""
    pkg = pkg_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dangling, checked = [], 0
    for dp, _d, fs in os.walk(pkg):
        for f in fs:
            if not f.endswith((".md", ".json", ".py")):
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, pkg).replace("\\", "/")
            text = io.open(full, encoding="utf-8", errors="replace").read()
            for i, line in enumerate(text.split("\n"), 1):
                for m in TOKEN.finditer(line):
                    ref = m.group(1).rstrip(".,;:)`\u3002\uff09\uff0c")
                    if ref.endswith("/"):
                        continue
                    checked += 1
                    if not os.path.exists(os.path.join(pkg, ref.replace("/", os.sep))) and \
                       not _prefix_hit(pkg, ref):
                        dangling.append({"file": rel, "line": i, "ref": ref, "kind": "path"})
                if f.endswith(".py"):
                    for m in BARE_PY.finditer(line):
                        name = m.group(1)
                        if name in RUNTIME_OK:
                            continue
                        checked += 1
                        if not [p for _dp, _dd, ff in os.walk(pkg) for p in ff if p == name]:
                            dangling.append({"file": rel, "line": i, "ref": name, "kind": "script-literal"})
    return {"checked": checked, "dangling": dangling,
            "rule": "documents and code may only name files that ship in the package; runtime outputs "
                    "written to --out/--work are exempt"}


GAIN_CASES = {"_purpose":"带标签的增益案例：用同一套运行期回查代码，证明本 Skill 能区分『真推导』与『编造/跑题』。","_how_to_run":"python3 scripts/verify.py --gain-cases builtin   (add --out-dir <dir> to also write gain-cases.json)","_labels":{"grounded":"页面内容逐字来自材料 → 期望 locator 全命中、数字全可定位、判定 accept","fabricated_number":"页面断言里的数字在材料中不存在 → 期望数字可定位率 <100%、判定 reject","fabricated_quote":"引用片段不在所标注的那一行（行号造假）→ 期望逐字回查失败、判定 reject","off_topic":"论断与材料无关（材料里没有该内容）→ 期望无锚点/回查失败、判定 reject"},"material":"# 1 Problem\nHowever, freezing attention layers under scarce labels remains brittle across sensors.\n# 2 Method\nWe propose AttnFreeze-2: freeze the first 3 stages and fine-tune the last 2 stages (lr 1e-4).\n# 3 Results\nMacro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).\n# 4 Limitations\nLimitation: only one sensor and one region were covered, so external validity is unverified.\n","cases":[{"id":"case-grounded-ok","label":"grounded","expect":"accept","why":"claim/quote/bullets 全部逐字取自材料第 6 行，数字 0.87/0.83/0.03 都在材料里","pages":[{"index":1,"role":"result-1","title":"冻结前 3 个 stage 提升 +4.2%","claim":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","claim_strength":"strong","bullets":["Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds)."],"figures":[],"speaker_notes":"point at the F1 line and the p value; do not push past strong","evidence":[{"material":"paper.md","line":6,"quote":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","numbers":["0.87","0.83","0.03","3"]}]}]},{"id":"case-fabricated-number","label":"fabricated_number","expect":"reject","why":"同一页但把结论改成 +12.4%（材料里没有 12.4）","pages":[{"index":1,"role":"result-1","title":"冻结前 3 个 stage 提升 +12.4%","claim":"AttnFreeze-2 improves macro F1 by +12.4% over full fine-tuning.","claim_strength":"strong","bullets":["macro F1 0.87±0.01 vs 0.83±0.02"],"figures":[],"speaker_notes":"claim the improvement out loud","evidence":[{"material":"paper.md","line":6,"quote":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","numbers":["12.4"]}]}]},{"id":"case-fabricated-quote","label":"fabricated_quote","expect":"reject","why":"引用的句子真实存在，但被标在了错误的行号（L2 而非 L6）——行号造假","pages":[{"index":1,"role":"result-1","title":"颤抖的结论","claim":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","claim_strength":"strong","bullets":[],"figures":[],"speaker_notes":"quote it as if it were on the method line","evidence":[{"material":"paper.md","line":2,"quote":"Macro F1 reaches 0.87±0.01 versus 0.83±0.02 for full fine-tuning (p=0.03, n=3 seeds).","numbers":[]}]}]},{"id":"case-off-topic","label":"off_topic","expect":"reject","why":"材料讲冻结注意力层，页面断言讲蛋白质折叠——既无锚点也对不上任何一行","pages":[{"index":1,"role":"result-1","title":"蛋白质折叠预测精度达到 0.94","claim":"Our folding model reaches 0.94 GDT-TS on the CASP15 target set.","claim_strength":"strong","bullets":["0.94 GDT-TS, n=41 targets"],"figures":["Figure 3"],"speaker_notes":"claim state of the art on proteins","evidence":[{"material":"paper.md","line":4,"quote":"Our folding model reaches 0.94 GDT-TS on the CASP15 target set.","numbers":["0.94","41"]}]}]}]}


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


def source_policy_probe():
    """Negative control for the q01-class defect: in one directory holding the work order, the task
    statement, a template spec, an example json, the pipeline's own output and the real paper,
    auto-discovery must take the paper and refuse everything else."""
    import tempfile as _tf
    root = _tf.mkdtemp(prefix="source-policy-")
    outd = os.path.join(root, "out")
    os.makedirs(outd)
    for name, txt in (("case.json", '{"case_id":"x","materials":[],"output_contract":{"a":"b"}}'),
                      ("task.md", "# task statement"), ("template.template.json", '{"theme":{}}'),
                      ("case.example.json", '{"_example":true}'), ("paper.md", "# paper\nResult 0.87.\n"),
                      (os.path.join("out", "resolved-paths.json"), '{"x":1}')):
        full = os.path.join(root, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        io.open(full, "w", encoding="utf-8", newline="\n").write(txt)
    case = {"case_id": "x", "_case_path": os.path.join(root, "case.json")}
    got, _miss, skipped = T.mp(case, root, outd, None)
    used = sorted(os.path.basename(p) for p in got)
    refused = sorted(s["file"] for s in skipped)
    must_refuse = ["case.example.json", "case.json", "resolved-paths.json", "task.md", "template.template.json"]
    return {"ok": used == ["paper.md"] and all(m in refused for m in must_refuse),
            "expected_used": ["paper.md"], "actual_used": used, "must_refuse": must_refuse,
            "refused_with_reason": {s["file"]: s["reason"] for s in skipped}}


def verify(case_path, out, input_dir=None, quiet=False):
    ind = input_dir or os.path.dirname(os.path.abspath(case_path)) or "."
    case = T.jl(case_path, {}) or {}
    res = T.jl(os.path.join(out, "result.json"), {}) or {}
    outl = T.jl(os.path.join(out, "outline.json"), {}) or {}
    spath = os.path.join(out, "slide_plan.json")
    spdoc = T.jl(spath, None)
    st = res.get("status")
    unsup = st == "unsupported"          # honest "nothing could be produced": expected empty plan, no deck
    fails, warns, checks = [], [], []

    def ck(name, ok, detail, warn=False):
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       "level": "pass" if ok else ("warn" if warn else "fail")})
        if not ok:
            (warns if warn else fails).append("%s: %s" % (name, detail))

    con, src = T.con_of(case)
    unres = {u.get("key") for u in (res.get("contract_unresolved_fields") or [])}
    echo = res.get("contract_echo") or {}
    bad = [k for k in con if (k not in res and k not in echo)
           or (k in res and (res[k] is None or res[k] == "" or res[k] == []) and k not in unres)]
    ck("contract fields present (null only if declared unresolved)", not bad,
       "source=%s missing/silent-null=%s" % (src, bad))
    coll = res.get("contract_key_collisions") or []
    ck("declared keys that collide with reserved result fields are echoed, not dropped",
       all(c.get("key") in echo for c in coll),
       "collisions=%s echoed=%s" % ([c.get("key") for c in coll][:4], sorted(echo)[:4]))

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

    # ---- first-class intermediate artifact: recomputed here, not taken from result.json ----
    ck("slide_plan.json exists (declared first-class artifact)", isinstance(spdoc, dict),
       "path=%s" % spath)
    spdoc = spdoc if isinstance(spdoc, dict) else {}
    serrs = T.validate_slide_plan(spdoc) if spdoc else ["slide_plan.json missing or unreadable"]
    # an honest "unsupported" run produces a 0-slide plan; only the two emptiness rules may fire then
    EMPTY_ERRS = ("needs >=1 items, got 0", "talk_slides: below minimum 1")
    empty_plan_ok = bool(unsup and serrs) and all(any(s in e for s in EMPTY_ERRS) for e in serrs)
    ck("slide_plan.json validates against the shipped schema (recomputed)", (not serrs) or empty_plan_ok,
       "schema=%s errors=%s%s" % (os.path.basename(T.SCHEMA_PATH), serrs[:4],
                                  " | expected on an unsupported run: the honest plan has 0 slides" if empty_plan_ok else ""),
       warn=bool(empty_plan_ok))
    claimed = res.get("slide_plan") or {}
    ck("result.json.slide_plan claim agrees with the recomputed verdict",
       bool(claimed.get("schema_ok")) == (not serrs) and claimed.get("written_before_deck") is True,
       "claimed_ok=%s recomputed_ok=%s written_before_deck=%s"
       % (claimed.get("schema_ok"), not serrs, claimed.get("written_before_deck")))
    mut = json.loads(json.dumps(spdoc)) if spdoc else {"probe": True}
    if not (mut.get("slides") or []):        # an honest empty plan still must not crash the guard
        mut["slides"] = [{}]
    mut["slides"][0]["role"] = "definitely-not-a-role"
    mut["slides"][0]["notes"] = ""
    mut.pop("spine", None)
    mut_errs = T.jschk(mut, T.load_schema() or {}, "$")
    ck("schema validator rejects a deliberately broken plan (rubber-stamp guard)",
       len(mut_errs) >= 3, "%d error(s) on a plan broken in 3 places: %s" % (len(mut_errs), mut_errs[:3]))

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

    # the evidence corpus is rebuilt with the same policy the planner used: the case file and any
    # input the planner refused as non-evidence are excluded, so numbers cannot become "traceable"
    # just because they appear in the work order.
    case = dict(case)
    case["_case_path"] = os.path.abspath(case_path)
    refused = {str(x.get("path") or x.get("file")) for x in (res.get("non_material_inputs") or [])}
    excl = tuple(os.path.join(ind, r) for r in refused if r and ind)
    paths, _miss, skipped_here = T.mp(case, ind, out, None, exclude=excl)
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

    # ---- source policy: evidence may only come from scientific material -------------------
    refused_names = {os.path.basename(str(x.get("path") or x.get("file"))).lower()
                     for x in (res.get("non_material_inputs") or [])}
    cited = set()
    for pg in pages + backups:
        for ev in (pg.get("evidence_refs") or pg.get("evidence") or []):
            cited.add(str(ev.get("material")))
    for s in (spdoc.get("slides") or []):
        for ev in (s.get("evidence") or []):
            cited.add(str(ev.get("id")))
    unknown = sorted(c for c in cited if c and c not in mrec)
    ck("every cited source is part of the evidence corpus", not unknown,
       "cited_but_not_in_corpus=%s corpus=%s" % (unknown, sorted(mrec)))
    reserved_cites = []
    for c in cited:
        p = os.path.join(ind, c) if c else ""
        if p and os.path.exists(p):
            why = T.reserved_input(p, os.path.abspath(case_path), out, None, True)
            if why:
                reserved_cites.append({"material": c, "why": why})
    ck("no cited source is a work-order/template/example shape", not reserved_cites,
       "reserved_citations=%s" % reserved_cites[:3])
    bad_cite = sorted(c for c in cited if c and c.lower() in refused_names)
    ck("no page cites a work order / template / example / own output as evidence", not bad_cite,
       "refused_inputs=%s cited_as_evidence=%s" % (sorted(refused_names)[:5], bad_cite))
    probe = source_policy_probe()
    ck("source policy negative control (work order, task, template, example, own output are refused)",
       probe["ok"], "expected_used=%s actual_used=%s refused=%s" % (
           probe["expected_used"], probe["actual_used"], sorted(probe["refused_with_reason"])))
    # ---- result.sources[] / source_policy must be audited too, not just the page citations ----
    # (pkg-adv1 built `cited` from page evidence only, so "task.md" could be appended to sources[]
    # and verify still returned 41/41 PASS)
    spol = res.get("source_policy") or {}
    listed = [str(s.get("material") or "") for s in (res.get("sources") or [])]
    bad_listed = []
    for name in listed:
        p = os.path.join(ind, name)
        why = T.reserved_input(p, os.path.abspath(case_path), out, None, True) if os.path.exists(p) else \
            ("listed source does not exist in the input dir")
        if why:
            bad_listed.append({"material": name, "why": why})
    ck("every entry of result.sources[] is a scientific material (not work order/template/example/own output)",
       not bad_listed, "sources=%s violations=%s" % (listed, bad_listed[:3]))
    not_read = [n for n in listed if n not in mrec]
    ck("every entry of result.sources[] was actually read by this verifier run", not not_read,
       "unread_listed=%s corpus=%s" % (not_read, sorted(mrec)))
    claimed_used = sorted(spol.get("used_as_evidence") or [])
    recomputed_used = sorted({e.get("id") for s in (spdoc.get("slides") or [])
                              for e in (s.get("evidence") or []) if e.get("id")})
    ck("source_policy.used_as_evidence equals the set of materials actually cited",
       claimed_used == recomputed_used, "claimed=%s recomputed=%s" % (claimed_used, recomputed_used))
    unused_claim = sorted(spol.get("read_but_unused") or [])
    unused_calc = sorted(set(listed) - set(recomputed_used))
    ck("source_policy.read_but_unused is honest (read but never cited)",
       unused_claim == unused_calc, "claimed=%s recomputed=%s" % (unused_claim, unused_calc))
    echo_vals = {T.sq(str(case.get(k) or "")) for k in ("task", "audience", "goal", "presentation_type")
                 if case.get(k)}
    copied = [{"page": p.get("index"), "field": k} for p in pages for k in ("title", "claim", "notes")
              if T.sq(str(p.get(k) or "")) in echo_vals and T.sq(str(p.get(k) or ""))]
    copied += [{"page": p.get("index"), "field": "bullets"} for p in pages for b in (p.get("bullets") or [])
               if T.sq(str(b)) in echo_vals and T.sq(str(b))]
    copied += [{"slide": s.get("slide_no"), "field": "claim"} for s in (spdoc.get("slides") or [])
               if T.sq(str(s.get("claim") or "")) in echo_vals and T.sq(str(s.get("claim") or ""))]
    ck("no page copies the case descriptor verbatim (a work order is not slide content)", not copied,
       "copied=%s echo_fields=%s" % (copied[:3], (res.get("input_echo") or {}).get("field_paths")))
    # Lead's ruling on the q01-class defect: re-echoing a declared contract / input-identifier field is
    # NOT contamination. The ban covers citations, evidence, page content and figures. This check makes
    # that boundary machine-visible: every verbatim case-field echo in result.json must sit inside one of
    # the declared echo fields; anything else is stray and fails.
    echo_q = {T.sq(str(case.get(k) or "")) for k in ("task", "audience", "goal", "presentation_type")
              if T.sq(str(case.get(k) or ""))}
    echo_q |= {T.sq(str(v)) for v in con.values() if isinstance(v, str) and len(T.sq(str(v))) >= 8}
    found = []

    def _walk_echo(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                _walk_echo(v, path + [str(k)])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk_echo(v, path + [str(i)])
        elif isinstance(node, str) and T.sq(node) in echo_q and T.sq(node):
            found.append(".".join(p for p in path if not p.isdigit()))

    _walk_echo(res, [])
    ECHO_PREFIX = ("input_echo", "audience_model", "slide_plan", "contract_echo",
                   "contract_key_collisions")     # every surface that legitimately echoes an input field
    stray = sorted({f for f in found if not f.startswith(ECHO_PREFIX)})
    ck("verbatim case-field echoes stay inside the declared echo fields (contract echo != contamination)",
       bool(found) == bool(echo_q and (case.get("task") or case.get("audience") or case.get("goal"))) and not stray,
       "echo_locations=%s stray=%s allowed_prefix=%s contract_echo_keys=%s" % (
           sorted(set(found))[:5], stray[:3], list(ECHO_PREFIX), sorted((res.get("contract_echo") or {}).keys())[:4]))
    # ---- template provenance must match what was actually used (pkg-adv1 claimed "case-provided"
    #      while the deck was built from the package's built-in DEFAULT_SPEC) ----
    ts = res.get("template_spec") or {}
    declared_ts = case.get("template_spec")
    spec_file = None
    if declared_ts:
        for cand in (os.path.join(ind, os.path.basename(str(declared_ts))), str(declared_ts)):
            if os.path.exists(cand):
                spec_file = cand
                break
    said_default = "default_spec" in str(ts.get("resolved") or "").lower()
    expect_default = (declared_ts is None) or (spec_file is None)
    ck("template_spec.resolved/degraded tells the truth about the spec actually used",
       said_default == expect_default and bool(ts.get("degraded")) == expect_default,
       "declared=%s spec_file_found=%s expect_default=%s resolved=%r degraded=%s theme_used=%s" % (
           declared_ts, bool(spec_file), expect_default, ts.get("resolved"), ts.get("degraded"),
           (ts.get("theme_used") or {}).get("major_font")))
    ck("a defaulted template is registered in uncertainty, not silently used",
       (not str(ts.get("resolved") or "").lower().startswith("package default")) or
       any("template" in str(u.get("kind") or "").lower() or "template_spec" in str(u.get("item") or "")
           for u in (res.get("uncertainty") or [])),
       "resolved=%s uncertainty_kinds=%s" % (ts.get("resolved"),
                                             [u.get("kind") for u in (res.get("uncertainty") or [])][:4]))
    o_anch = {p.get("index"): sorted((e.get("material"), e.get("line")) for e in (p.get("evidence_refs") or []))
              for p in pages}                       # content pages; outline.backup_slides carry no anchors
    s_anch = {s.get("slide_no"): sorted((e.get("id"), e.get("page")) for e in (s.get("evidence") or []))
              for s in (spdoc.get("slides") or []) if not s.get("backup")}
    drift = [k for k in sorted(set(o_anch) | set(s_anch), key=lambda x: (x is None, x))
             if o_anch.get(k) != s_anch.get(k)]
    ck("outline and slide_plan agree on every content page's anchors", not drift,
       "pages_with_differing_anchors=%s" % [{"slide_no": k, "outline": o_anch.get(k),
                                             "slide_plan": s_anch.get(k)} for k in drift[:3]])

    below = [{"page": p.get("index"), "role": p.get("role"),
              "anchors": len(p.get("evidence_refs") or []), "floor": T.EVID.get(p.get("role"), 0)}
             for p in pages if len(p.get("evidence_refs") or []) < T.EVID.get(p.get("role"), 0)]
    recorded = len((res.get("evidence_floor") or {}).get("below_floor") or [])
    ck("anchor floor per page type is met, or the gap is recorded honestly",
       recorded == len(below), "recomputed_below_floor=%s recorded=%s" % (below[:3], recorded))

    # ---- independent verbatim re-check of the plan's own quotes (does not trust result.json.audit) ----
    verbad, vchecked = [], 0
    for s in (spdoc.get("slides") or []):
        for ev in (s.get("evidence") or []):
            r = mrec.get(ev.get("id"))
            ln, q = ev.get("page"), T.nz(str(ev.get("quote") or ""))[:40]
            vchecked += 1
            if not r or not r["readable"] or not ln or ln > len(r["lines"]) or not q \
               or q not in T.nz(r["lines"][ln - 1]):
                verbad.append({"slide": s.get("slide_no"), "material": ev.get("id"), "line": ln})
    ck("slide_plan quotes are verbatim on the cited line (independent re-read)", not verbad,
       "%d quotes checked, %d not verbatim: %s" % (vchecked, len(verbad), verbad[:3]))

    nos = {s.get("slide_no") for s in (spdoc.get("slides") or [])}
    qa = spdoc.get("qa_prep") or []
    qa_bad = [q.get("backup_slide_no") for q in qa
              if q.get("backup_slide_no") is not None and q.get("backup_slide_no") not in nos]
    ck("qa_prep page pointers reference real slides", not qa_bad, "dangling=%s slides=%s" % (qa_bad[:4], sorted(nos)[:6]))
    ck("qa_prep has a reachable page pointer (question -> slide)", bool([q for q in qa if q.get("backup_slide_no")]),
       "%d qa items, %d linked" % (len(qa), len([q for q in qa if q.get("backup_slide_no")])), warn=True)
    smap = {s.get("slide_no"): s.get("evidence_strength") for s in (spdoc.get("slides") or [])}
    over = [{"q": i, "answer": q.get("answer_strength"), "slide": smap.get(q.get("backup_slide_no"))}
            for i, q in enumerate(qa)
            if q.get("backup_slide_no") in smap and q.get("answer_strength") not in (None, "") and
            STRENGTH_ORDER.get(q.get("answer_strength"), 9) > STRENGTH_ORDER.get(smap.get(q["backup_slide_no"]), -1)]
    ck("qa_prep answer strength does not exceed the cited slide", not over, "over_claimed=%s" % over[:3])
    ck("slide_plan slides == outline pages + backups",
       len(spdoc.get("slides") or []) == len(pages) + len(backups),
       "plan=%s outline=%s" % (len(spdoc.get("slides") or []), len(pages) + len(backups)))

    mat_text = T.sq(" ".join(" ".join(r["lines"]) for r in mrec.values() if r["readable"]))
    fab = []
    for pg in pages + backups:
        txt = " ".join([str(pg.get("claim") or "")] + list(pg.get("bullets") or []))   # same scope as runtime_recheck
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

    need = ["deck.pptx", "outline.json", "result.json", "speaker-notes.md", "slide_plan.json",
            "render-record.json"]
    gone = [n for n in need if not os.path.exists(os.path.join(out, n))]
    # an honest "unsupported" run has no deck by design: flag it as a warn with the reason, not as
    # a verifier failure (the run must still be visibly non-success via result.json.status).
    ck("required files exist", not gone,
       ("missing=%s (status=unsupported: no deck was expected)" % gone) if unsup else "missing=%s" % gone,
       warn=unsup)
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

    # ---- the delivered deck is read back through its own OOXML relationship graph ----------
    # (pkg-adv1 shipped a deck whose first sldId resolved to the slide master, with duplicate rIds
    # and an unreachable last slide; counting slideN.xml files could never see that)
    import minipptx as _mpt
    drec = (_mpt.inspect(deck_p) if os.path.exists(deck_p) else
            {"ok": False, "errors": ["deck.pptx missing"], "slides": [], "count": 0,
             "duplicate_rel_ids": [], "unreachable_slide_parts": [], "unresolved_sld_ids": [],
             "missing_targets": []})
    soft = not (len(pages) + len(backups))     # 0 slides -> nothing to open, by design
    ck("deck.pptx is structurally readable (sldIdLst resolves, no duplicate/dangling rIds)",
       bool(drec.get("ok")) or soft,
       "slides_reachable=%s dup_rids=%s unreachable=%s unresolved_sldIds=%s missing_targets=%s errors=%s" % (
           drec.get("count"), drec.get("duplicate_rel_ids"), drec.get("unreachable_slide_parts"),
           (drec.get("unresolved_sld_ids") or [])[:2], (drec.get("missing_targets") or [])[:2],
           (drec.get("errors") or [])[:2]), warn=soft)
    ck("every slide part is reachable from sldIdLst", bool(soft) or not drec.get("unreachable_slide_parts"),
       "unreachable=%s" % drec.get("unreachable_slide_parts"), warn=soft)
    dclaimed = (res.get("deck") or {}).get("read_back") or {}
    ck("result.json.deck.read_back agrees with the recomputed deck audit",
       bool(dclaimed.get("ok")) == bool(drec.get("ok"))
       and int(dclaimed.get("slides_reachable") or -1) == int(drec.get("count") or -2)
       and (dclaimed.get("duplicate_rel_ids") or []) == (drec.get("duplicate_rel_ids") or [])
       and (dclaimed.get("unreachable_slide_parts") or []) == (drec.get("unreachable_slide_parts") or []),
       "claimed_ok=%s recomputed_ok=%s claimed_slides=%s file_slides=%s" % (
           dclaimed.get("ok"), drec.get("ok"), dclaimed.get("slides_reachable"), drec.get("count")), warn=soft)
    plan_titles = [T.sq(p.get("title") or "") for p in pages] + [T.sq(x.get("title") or "") for x in backups]
    deck_titles = [T.sq(s.get("title") or "") for s in (drec.get("slides") or [])]
    ck("deck slide titles match the plan, in order",
       bool(soft) or plan_titles == deck_titles,
       "plan=%s deck=%s" % (plan_titles[:3], deck_titles[:3]), warn=soft)
    hidden = [s["part"] for s in (drec.get("slides") or []) if s.get("hidden")]
    ck("backup/Q&A slides are hidden from the show", bool(soft) or len(hidden) == len(backups),
       "hidden=%s backups=%s" % (len(hidden), len(backups)), warn=soft)
    try:
        from pptx import Presentation as _Prs
        _prs = _Prs(deck_p)
        _n = 0
        for _s in _prs.slides:
            _ = _s.shapes.title
            _n += 1
        pp = {"ok": _n == drec.get("count"), "slides": _n}
    except Exception as exc:
        pp = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    _opt = str(pp.get("error") or "").startswith(("ModuleNotFoundError", "ImportError"))
    ck("python-pptx opens the deck and iterates every slide",
       bool(pp.get("ok")) or bool(soft) or _opt,
       "slides=%s error=%s (python-pptx is optional in the runtime; the structural read-back always runs)" % (
           pp.get("slides"), pp.get("error")), warn=bool(soft) or _opt)
    eg = (res.get("empty_artifact_guard") or {}).get("passed")
    ck("runtime empty-artifact guard passed", eg is not False,
       "guard=%s reasons=%s" % (eg, str((res.get("empty_artifact_guard") or {}).get("reasons") or [])[:100]),
       warn=unsup)
    rsum = (res.get("audit") or {}).get("summary") or {}
    ck("runtime verbatim re-check ran by the pipeline", bool(rsum.get("locators_verified")),
       "locators_verified=%s fails=%s numbers=%s/%s captions=%s" % (
           rsum.get("locators_verified"), rsum.get("fail"), rsum.get("numbers_locatable"),
           rsum.get("numbers_total"), rsum.get("captions_matched")),
       warn=unsup)

    rc = refcheck()
    ck("every in-package reference resolves to a shipped file", not rc["dangling"],
       "%d references checked, %d dangling: %s" % (rc["checked"], len(rc["dangling"]), rc["dangling"][:3]))

    # ---- rendered export: measured from the file's own bytes, never from a note ----------
    import minipdf
    pdf = os.path.join(out, "preview.pdf")
    recp = os.path.join(out, "render-record.json")
    rec = T.jl(recp, {}) or {}
    want_pages = len(pages) + len(backups)
    pdf_ok = os.path.exists(pdf) and open(pdf, "rb").read(5) == b"%PDF-"
    expect_render = want_pages > 0          # 0 slides -> there is nothing to render, by design
    opted_out = str(rec.get("skipped") or "").startswith("--no-render")
    if not pdf_ok:
        why = ("no slides were produced, so no preview exists by design" if not expect_render
               else "--no-render: the preview was skipped on purpose and recorded as such" if opted_out
               else "preview.pdf missing/unreadable (status=%s)" % st)
        soft_pdf = (not expect_render) or opted_out
        for nm in ("preview.pdf exists and is a real PDF", "preview.pdf page count matches the plan",
                   "preview.pdf geometry (16:9) and extractable text layer",
                   "render-record.json matches the bytes on disk"):
            ck(nm, soft_pdf, why, warn=soft_pdf)
    else:
        blob = open(pdf, "rb").read()
        ck("preview.pdf exists and is a real PDF", True,
           "%d bytes, header=%s" % (len(blob), blob[:8].decode("latin-1")))
        npages = minipdf.page_count(pdf)
        ck("preview.pdf page count matches the plan", npages == want_pages,
           "file=%s plan=%s(%s+%s)" % (npages, want_pages, len(pages), len(backups)))
        boxes = minipdf.media_boxes(pdf)
        size = boxes[0] if boxes else []
        ratio_ok = bool(size) and abs((size[2] / size[3]) - (16.0 / 9.0)) < 0.02
        txt = minipdf.extract_text(pdf)
        probe = T.sq((pages[0]["claim"] if pages else "")[:16])
        ck("preview.pdf geometry (16:9) and extractable text layer", bool(size) and ratio_ok and bool(txt),
           "mediabox=%s ratio_16_9=%s extracted_chars=%d first_probe=%s" % (
               size, ratio_ok, len(txt), (probe in T.sq(txt)) if probe else "n/a"))
        ck("preview.pdf text layer matches page 1 (claims survive the export)",
           bool(probe) and probe in T.sq(txt), "probe=%r found=%s" % (
               probe[:24], (probe in T.sq(txt)) if probe else "n/a"))
        fonts = re.findall(rb"/BaseFont\s*/([A-Za-z0-9\-+]+)", blob)
        embedded = bool(re.search(rb"/FontFile[23]?\b", blob))
        ck("render-record.json matches the bytes on disk",
           bool(rec) and rec.get("bytes") == len(blob) and rec.get("sha256") == hashlib.sha256(blob).hexdigest()
           and int(rec.get("pages") or rec.get("pages_in_file") or -1) == want_pages,
           "record bytes=%s file=%s | record pages=%s file=%s | fonts=%s embedded=%s" % (
               rec.get("bytes"), len(blob), rec.get("pages") or rec.get("pages_in_file"), want_pages,
               sorted({f.decode() for f in fonts})[:4], embedded))
        ck("render record tells the truth about font embedding / Office rendering",
           bool(rec) and bool(rec.get("font_embedded")) == embedded,
           "record.font_embedded=%s bytes_have_FontFile=%s engine=%s real_office=%s" % (
               rec.get("font_embedded"), embedded, rec.get("engine"), rec.get("real_office_render")))
        # the preview must be a render OF THE DECK, not of the plan: its text has to match the
        # strings that are actually inside deck.pptx
        src = str(rec.get("source") or (res.get("render") or {}).get("source") or "")
        titles = [T.sq(s.get("title") or "") for s in (drec.get("slides") or [])]
        # compare prefixes: minipdf wraps long titles, so the extracted line is the same characters
        # but not necessarily one contiguous run of the plan's full title
        in_pdf = [t for t in titles if len(t) >= 8 and t[:12] in T.sq(txt)]
        ck("preview.pdf is rendered from deck.pptx (source + slide text agree with the deck)",
           "deck" in src.lower() and (not titles or len(in_pdf) >= max(1, len(titles) - 1)),
           "source=%r slide_title_prefixes_found_in_pdf=%d/%d missing=%s" % (
               src, len(in_pdf), len(titles), [t[:16] for t in titles if t not in in_pdf][:2]))

    verdict = "PASS" if not fails else "FAIL"
    report = {"verdict": verdict, "checks": checks, "fails": fails, "warns": warns,
              "summary": {"total": len(checks), "pass": sum(1 for c in checks if c["ok"]),
                          "warn": len(warns), "fail": len(fails)},
              "refcheck": rc,
              "note": "materials and the shipped schema are re-read here, so anchor/number/quote checks and the "
                      "schema verdict do not trust result.json"}
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
    ap.add_argument("--refcheck", action="store_true",
                    help="only check that every path/script reference inside the package exists (no run needed)")
    a = ap.parse_args(av)
    if a.refcheck:
        rc = refcheck()
        print("refcheck: %d references checked, %d dangling" % (rc["checked"], len(rc["dangling"])))
        for d in rc["dangling"]:
            print("  DANGLING %(file)s:%(line)s -> %(ref)s (%(kind)s)" % d)
        return 0 if not rc["dangling"] else 1
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
